"""
内部 API 路由（Service Token 认证）

提供内部服务之间的调用接口：
- Tool 执行接口（供 admin-api 反向调用）
- 会话知识提炼（LLM WIKI 板块 P5b，issue #3051：客服会话 → 知识卡片候选）
- 健康检查
"""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from loguru import logger

from app.utils.auth import verify_service_token
from app.tools import ToolContext, get_tool_registry
from app.api.response_models import make_response
from app.knowledge.distill import distill
from app.briefing.generator import generate_briefing
from app.production.routing import qty_and_source
from app.tools import curtain_calc

router = APIRouter()


class ToolExecuteRequest(BaseModel):
    """Tool 执行请求"""
    tool_name: str = Field(..., description="Tool 名称")
    params: Dict[str, Any] = Field(default_factory=dict, description="Tool 参数")
    tenant_id: int = Field(..., description="租户 ID")
    user_id: str = Field(..., description="用户 ID")
    session_id: Optional[str] = Field(None, description="会话 ID")


class KnowledgeDistillRequest(BaseModel):
    """会话知识提炼请求"""
    tenant_id: int = Field(..., description="租户 ID")
    conversation_text: str = Field(..., description="待提炼文本（客服会话 或 店铺资料文档）")
    max_candidates: int = Field(5, ge=1, le=10, description="最多提炼候选数")
    mode: str = Field("conversation", description="提炼模式：conversation（客服问答对）/ document（文档→FAQ 条目）")


class BriefingGenerateRequest(BaseModel):
    """智能每日经营简报生成请求（issue #3468）

    数据安全红线：snapshot 只含聚合指标与脱敏事实（无客户 PII），
    LLM 只允许引用快照中的数字（metrics 引用由 admin-api 校验层对账）。
    """
    tenant_id: int = Field(..., description="租户 ID")
    snapshot: Dict[str, Any] = Field(..., description="聚合指标快照 {metrics: {key: value}, facts: [...]}")


class OperationQtyPosition(BaseModel):
    """待算应做数量的单个部位（issue #4208）

    请求可带 `curtain_type` / `craft`（契约形状，同 admin-api 侧），但**本端点不需要**：
    工序清单由调用方给出（真相源 = DB 工序库 #4193），数量只取决于 `operations` + `calc_info`。
    """
    position_name: str = Field(..., description="部位名（原样回传，不参与计算）")
    operations: List[str] = Field(default_factory=list, description="该部位的工序名列表")
    calc_info: Dict[str, Any] = Field(default_factory=dict, description="算料引擎输出（fabric_meters/pleat_count 等）")


class OperationQtyRequest(BaseModel):
    """工序应做数量请求（issue #4208）"""
    positions: List[OperationQtyPosition] = Field(default_factory=list, description="待算部位列表")


# 算料试算的引擎入参（issue #4421）：
#   · 门幅 —— 褶数法（定高买宽）**不消费**门幅，它只决定「成品高 + 卷边 > 门幅」时是否
#     转定宽买高；取 3.2m（宽幅定高布，与 issue #4118 ⑤-B 实测的同一扇窗 6.6m/2.6m 同口径）
#     ⇒ 常规层高走褶数法本式 `0.25×褶数+余量`，正是本单要交付的那个数。
#     门幅**不入参**：商家手工下单页当前没有门幅字段，加了就是一个没有消费者的契约字段
#     （后续按面料真实门幅接线的口径待裁定）。
#   · 窗高缺省 2.5m（常见层高口径；**不传 ≠ 0**）。
_FABRIC_WIDTH = 3.2
_DEFAULT_HEIGHT = 2.5


class CraftCalcRequest(BaseModel):
    """算料试算请求（issue #4421，商家手工下单页）

    用料口径 = 用户 2026-09-19 裁定的**褶数法（标准档）**：
    `宽 × 倍数 → 褶数（按开数取整）→ 每折吃布 × 褶数 + 余量`。
    **每折吃布随款式/拼次变化**（同一次裁定，纸质速查表表头）：
    单色 0.25 / 拼色·拼1次 0.65 / 拼色·拼2次 1.2 米每折；余量不随拼色变化（单开 0.2 / 多开 0.3）。
    """
    width: float = Field(..., gt=0, description="窗宽（米）")
    height: Optional[float] = Field(None, gt=0, description="窗高（米）；不传按 2.5m 常见层高处理")
    open_count: int = Field(1, ge=1, description="打开方式开数（1 单开 / 2 双开 / 4 四开）")
    mounting: str = Field("s_hook", description="悬挂方式（s_hook 韩褶才走褶数法）")
    craft_tier: str = Field("standard", description="工艺档位（standard 2.0 / economy 1.8）")
    style: Optional[str] = Field(None, description="款式（单色 / 拼色）；拼色**必须**同时给拼次特殊选项才用料系数")
    special_options: List[str] = Field(
        default_factory=list,
        description="部位级特殊选项（逐字名，见 routing.SPECIAL_OPTION_ROUTINGS）；拼色用料系数由 拼1次/拼2次 决定",
    )
    has_pattern: bool = Field(
        False,
        description=(
            "是否对花（issue #4571）。**只在定宽买高时影响用料**：每幅长 +1 个花距 "
            "（`curtain_calc.calculate_fabric_meters` 的 `if has_pattern: panel_length += pattern_repeat`）。"
            "定高买宽下它**不改变**用料。缺省 false = 不按对花算。"
        ),
    )
    pattern_repeat: float = Field(
        0.0,
        ge=0,
        description="花距（米），仅 `has_pattern=true` 时有意义；行业常见 0.3~0.6",
    )
    formula: Optional[str] = Field(
        None,
        description=(
            "用料计算方法（issue #4527，用户 2026-09-19 裁定）：pleat 韩褶公式（褶数法，**默认**）/ "
            "fullness 褶倍数公式（倍数法）。缺省由算料引擎的配置默认值给（本端点**不补默认值**，"
            "补默认值 = 第二份口径）；未知取值 ⇒ 400。"
        ),
    )
    craft: Optional[str] = Field(
        None,
        description=(
            "安装工艺（用户 2026-09-19 追加裁定「**韩褶用韩褶公式算布料，打孔按倍数法算布料**」）："
            "韩褶/打孔/四爪钩/穿杆/平幔。**公式由工艺推导**（唯一口径在算料引擎 `curtain_calc.resolve_craft_rule` + `CRAFT_S_HOOK`/`CRAFT_EYELET` 枚举常量）："
            "韩褶 ⇒ 韩褶公式、打孔 ⇒ 褶倍数公式（默认 2 倍）；本端点只透传，不复制推导表。"
        ),
    )
    config: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "算料公式参数（issue #4528 = 包 E）：**租户级**配置，键集 = 算料引擎 "
            "`curtain_calc.DEFAULT_CRAFT_CALC_CONFIG`（per_fold_single / per_fold_mixed_times / "
            "margin_single / margin_multi / min_fullness / tiers / default_formula / "
            "hem_margin / meters_rounding_step）。**缺省/None ⇒ 引擎默认值**（未配置租户的既有口径一字不变）。"
            "非法值 ⇒ 400（**不静默回退默认值** —— 静默 = 算错钱且无人知道）。"
            "⚠️ 本端点只做**键类型归一**（JSON 对象键恒为字符串 ⇒ 拼次键转回 int），不复制校验规则。"
        ),
    )
    fabric_width: Optional[float] = Field(
        None,
        gt=0,
        description=(
            "**该商品/SKU 的门幅**（米，issue #4976 包 1a）：由 admin-api 按订单行的 SKU 门幅传入。"
            "缺省 ⇒ 本端点既有常量 `_FABRIC_WIDTH`（**回归不变量**：未接线的调用方口径一字不变）。"
            "⚠️ 门幅的权威是 **SKU/商品门幅**（商品可配、**没有缺省门幅**，issue #4877）——"
            "本字段就是把它接进来的入口；不接 = 服务端按一个不是这张单的值判「超宽/超高」（分叉 #4652 / #4746）。"
        ),
    )
    cutting_mode: Optional[str] = Field(
        None,
        description=(
            "加工类型（`定高买宽` / `定宽买高`，issue #4976 包 1a）：决定**哪个方向受门幅约束** ——"
            "`定高买宽` ⇒ 只判超高；`定宽买高` ⇒ 超宽（分幅）+ 倒幅。"
            "缺省 / 表外取值 ⇒ **都不判**（保守：不猜朝向，与下单页同款）。"
            "用户 2026-09-20 裁定：「定高买宽的话就不用算超宽，定宽买高就不用算超高」。"
        ),
    )
    splice_times: Optional[int] = Field(
        None,
        description=(
            "**人工覆盖**拼次（0~3，issue #5201 = 母单 #5200 子单 A，契约 R7）：给 ⇒ `plan.auto=false`、"
            "**逐字采用**、不再自动改判。⚠️ 契约判据 8（回归不变量）：不传 `splice_times` / "
            "`join_height_m` / `join_width_m` 这三个键时，本端点口径与改动前**逐值一致** —— "
            "三项输入的自动推导只在至少传了其中一个时才启用（`fabric_width` 单独传**不**启用）。"
            "取值表外（≥4 / 负数）⇒ 422（**不发明「拼4次」**，R5）。"
        ),
    )
    join_height_m: Optional[float] = Field(
        None,
        description=(
            "**人工加接高**（米，`0 < x ≤ 0.1`，issue #5201 / 裁定 5）：超 0.1 米 ⇒ 422 fail-closed。"
            "⚠️ **不参与算料**（R2）：不另买布、不改米数。只适用于「定高买宽」（倒幅高方向无缺口）。"
        ),
    )
    join_width_m: Optional[float] = Field(
        None,
        description=(
            "**人工加接宽**（米，`0 < x ≤ 0.1`，issue #5201 / 裁定 5）：超 0.1 米 ⇒ 422 fail-closed。"
            "⚠️ **不参与算料**（R2）：接宽那条 ≤0.1 米的布条来自边角料、不另买布 ⇒ 用料只算 `P−1` 幅。"
            "只适用于「定宽买高」（倒幅）。"
        ),
    )


@router.post("/tools/execute")
async def execute_tool(
    request: ToolExecuteRequest,
    authorized: bool = Depends(verify_service_token),
):
    """
    执行 Tool（内部服务调用）
    
    由 admin-api 通过 Service Token 调用，用于反向触发 Agent Tool 执行。
    例如：admin-api 需要 AI 服务执行某个 Tool 获取结果。
    """
    registry = get_tool_registry()
    tool = registry.get_tool(request.tool_name)

    # 检查 Tool 是否存在
    if tool is None:
        raise HTTPException(
            status_code=404,
            detail={
                "success": False,
                "error": {
                    "code": "TOOL_NOT_FOUND",
                    "message": f"Tool '{request.tool_name}' not found",
                }
            }
        )

    # 安全加固：内部反向调用仅允许只读工具。写操作必须走用户侧对话流程
    # （LLM 决策 + interact confirm 卡片），防止 SERVICE_TOKEN 泄露后被用于
    # 对任意租户执行破坏性写操作。
    if not getattr(tool, "read_only", True):
        raise HTTPException(
            status_code=403,
            detail={
                "success": False,
                "error": {
                    "code": "WRITE_TOOL_FORBIDDEN",
                    "message": f"Tool '{request.tool_name}' 是写操作，禁止通过内部接口执行",
                }
            }
        )

    # 构建上下文
    context = ToolContext(
        tenant_id=request.tenant_id,
        user_id=request.user_id,
        session_id=request.session_id,
        role="admin",  # 内部调用使用 admin 角色
        permissions=["*"],  # admin 拥有全部细粒度权限（与后端 admin 角色口径一致）
    )
    
    # 执行 Tool
    try:
        result = await registry.execute_tool(
            request.tool_name,
            context,
            **request.params,
        )
        
        return {
            "success": result.success,
            "data": result.data,
            "error": result.error,
            "message": result.message,
        }
    except Exception as e:
        logger.error(f"Internal tool execution error: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": f"Tool execution failed: {str(e)}",
                }
            }
        )


@router.get("/tools")
async def list_tools(
    authorized: bool = Depends(verify_service_token),
):
    """
    获取所有可用 Tool 列表（内部接口）
    """
    registry = get_tool_registry()
    
    tools = []
    for tool in registry.get_all_tools():
        tools.append({
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        })
    
    return {
        "success": True,
        "data": {
            "tools": tools,
            "count": len(tools),
        }
    }


@router.post("/knowledge/distill")
async def distill_knowledge(
    request: KnowledgeDistillRequest,
    authorized: bool = Depends(verify_service_token),
):
    """
    会话知识提炼（LLM WIKI 板块 P5b，issue #3051）

    admin-api 把人工客服会话文本传来，AI 提炼为「顾客问题 → 标准回答」知识卡片候选，
    返回候选列表由 admin-api 写入待确认队列（knowledge_candidates），商家采纳后生效。
    提炼失败降级返回空候选（不阻断 admin-api 流程）。
    """
    logger.info(
        f"Knowledge distill triggered: tenant_id={request.tenant_id}, "
        f"text_len={len(request.conversation_text or '')}, max_candidates={request.max_candidates}"
    )
    candidates = await distill(request.conversation_text, max_candidates=request.max_candidates, mode=request.mode)
    return make_response(True, data={"candidates": candidates})


@router.post("/briefing/generate")
async def generate_daily_briefing(
    request: BriefingGenerateRequest,
    authorized: bool = Depends(verify_service_token),
):
    """
    智能每日经营简报生成（issue #3468）

    admin-api 定时任务/手动触发时把聚合指标快照传来（纯数字 + 脱敏事实，无客户 PII），
    LLM 组织成四区块简报（昨日回顾/今日必办/风险预警/优化建议）。
    生成失败返回 data.briefing=None（不编造数据，admin-api 落 failed 状态）。
    """
    logger.info(
        f"Briefing generate triggered: tenant_id={request.tenant_id}, "
        f"snapshot_keys={len(request.snapshot or {})}"
    )
    briefing = await generate_briefing(request.snapshot)
    return make_response(True, data={"briefing": briefing})


@router.post("/production/operation-qty")
async def operation_qty(
    request: OperationQtyRequest,
    authorized: bool = Depends(verify_service_token),
):
    """工序应做数量 = 算料引擎输出（issue #4208 方案 A，`POST /api/internal/production/operation-qty`）

    admin-api 生成加工单时逐工序问数量。真值源 = `app/production/routing.py::_qty_for`
    （本仓此前的**零运行时消费者**，商家后台「应做数量」因此退化成订单数量，如「韩褶-布」显示 3 折）。

    本端点**只答数量**：路线 / 单价 / 开始标记的真相源是 DB 工序库（#4193），不在此返回。
    （`is_must_finish` / 必完标记自 #4961 起已退场，更不在本端点返回。）
    兜底口径（不把加工单生成打成硬失败）：缺键 / 引擎不认识的工序或单位 ⇒ qty=1（**绝不落 0**，
    应做 0 会让 `done_qty ≥ qty` 恒真 ⇒ 假完工）+ `qty_source="fallback"`，HTTP 仍 200。

    `qty_source_by_operation` 三态（供页面/排查区分值的来路，Java 侧照此落 `qty_source` 列）：
    ① 键名（`fabric_meters` / `pleat_count` / `holes`）= 该键直接供数；
    ② `<键名>_x6` = 「孔」类无 holes 时按每米 6 孔的行业口径估算（12.3 米 → 73.8 孔）；
    ③ `"fallback"` = 真兜底 1（无键可读 / 未知工序或单位 / panels・set_count 引擎待补键）。
    """
    positions = []
    for position in request.positions:
        qty_by_operation: Dict[str, float] = {}
        qty_source_by_operation: Dict[str, str] = {}
        for operation in position.operations:
            qty, source = qty_and_source(operation, position.calc_info)
            qty_by_operation[operation] = qty
            qty_source_by_operation[operation] = source
        positions.append({
            "position_name": position.position_name,
            "qty_by_operation": qty_by_operation,
            "qty_source_by_operation": qty_source_by_operation,
        })
    logger.info(
        f"Operation qty resolved: positions={len(positions)}, "
        f"operations={sum(len(p['qty_by_operation']) for p in positions)}"
    )
    return make_response(True, data={"positions": positions})


def _formula_text(
    width: float, fullness: float, pleat_count: int, open_count: int,
    meters: float, per_fold: float, margin: float,
) -> str:
    """可读公式串（**褶数法/韩褶公式**）—— **后端产出**，与数值同源（issue #4421 交付物 1）。

    形态：`韩褶公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米`；
    拼色时系数如实换（`0.65×52+0.3 = 34.1米`）。

    数字全部取自**同一次算料**：倍数/褶数/每折吃布/余量来自引擎（`build_quote` 的
    `fullness` / `pleat_count` / `per_fold` / `margin`）⇒ 公式串不可能与米数不一致；
    前端**不得**自拼（前端自拼 = 第二份算料逻辑）。

    ⚠️ issue #4527 起公式串由**算料引擎** `curtain_calc` 产出（`quote["formula_text"]`）——
    因为「公式名 + 逐片表达式」两种公式各不相同，端点自拼就是**第二份算料逻辑**。
    本函数保留为**褶数法**的兼容形态（本仓 `test_formula_text_is_derived_from_same_numbers`
    等既有断言仍可直调它），端点实际返回的是引擎那一份。
    """
    return (
        f"韩褶公式：({width:g}+{margin:g})×{fullness:g} → {pleat_count:g}折 → "
        f"{per_fold:g}×{pleat_count:g}+{margin:g} = {meters:g}米"
    )


def _normalize_craft_calc_config(config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """线上配置（JSON）→ 算料引擎入参：**只做键类型归一**，不复制任何校验/默认值。

    ⚠️ 为什么必须归一：JSON 对象键**恒为字符串**（`{"1": 0.65}`），而引擎的
    `per_fold_mixed_times` 键是**正整数拼次**（`{1: 0.65}`；`resolve_craft_calc_config` 逐键
    校验 `isinstance(int)`）⇒ 不转就整份配置被拒（400），商家改了系数却算不出料。

    **不静默丢档**：键转不成 int ⇒ 显式 `ValueError`（丢一档 = 拼色退回单色系数 = 少算用料）。
    其余键**原样透传** —— 校验与默认值都在引擎（`resolve_craft_calc_config`），
    这里再抄一份就是第二份口径。
    """
    if not config:
        return None
    out = dict(config)
    mixed = out.get("per_fold_mixed_times")
    if mixed is not None:
        if not isinstance(mixed, dict):
            raise ValueError(f"算料配置 per_fold_mixed_times 必须是映射（收到 {mixed!r}）")
        normalized: Dict[int, Any] = {}
        for times, per_fold in mixed.items():
            try:
                normalized[int(times)] = per_fold
            except (TypeError, ValueError):
                raise ValueError(
                    f"算料配置 per_fold_mixed_times 的拼次必须是正整数（收到 {times!r}）"
                ) from None
        out["per_fold_mixed_times"] = normalized
    return out


@router.get("/production/craft-calc-config")
async def craft_calc_config_defaults(
    authorized: bool = Depends(verify_service_token),
):
    """算料公式配置的**引擎默认值**（issue #4528 = 包 E，内部端点）。

    为什么有这个端点（而不是 Java 侧写一份默认常量）：默认值**就是**算料口径的一部分，
    唯一实现在 `curtain_calc.DEFAULT_CRAFT_CALC_CONFIG`。admin-api 的
    `GET /api/admin/production/craft-calc-config` 在**本租户没有配置行**时要回默认值 +
    `source='default'`，若在 Java 侧再抄一份常量 = **第二份会漂的默认值**
    （issue #4528 明确「不做开租播种」的同一理由）⇒ 默认值的来源只能是引擎。

    返回 `data.config`：键集 == `DEFAULT_CRAFT_CALC_CONFIG`（**恰好**，不多不少）。
    """
    return make_response(True, data={"config": dict(curtain_calc.DEFAULT_CRAFT_CALC_CONFIG)})


@router.post("/production/craft-calc")
async def craft_calc(
    request: CraftCalcRequest,
    authorized: bool = Depends(verify_service_token),
):
    """算料试算（issue #4421，`POST /api/internal/production/craft-calc`）

    商家手工下单页按宽/高/开数/档位试算用料 —— 此前该页面**零算料通路**，数量/米数靠商家手填。

    **单一真值**：本端点不复制任何算料公式，只把请求转成 `curtain_calc.build_quote` 的入参
    并取回算料子集（形态照 `ProductionOperationQtyClient` 的既有先例：Java 侧不复制第二份算料逻辑）。
    `formula_text` 亦由后端按**同一份数字**产出 —— 前端不得自拼公式。

    返回 `data`：`fabric_meters` / `pleat_count` / `per_panel_pleats` / `open_count` / `margin` /
    `per_fold`（每折吃布：单色 0.25 / 拼1次 0.65 / 拼2次 1.2）/
    `fullness`（档位**理论**倍数）/ `fullness_actual`（用料÷窗宽，**实际**倍数）/
    `formula_used` / `formula_text` / `source` / `craft_tier` / `warning` /
    `auto_features`（**自动特征**：超高/超宽/倒幅，issue #4976 包 1a —— 键恒在，空列表 = 不判）。

    入参补充（issue #4976 包 1a）：`fabric_width`（**SKU 门幅**；缺省 ⇒ 本端点既有常量）与
    `cutting_mode`（加工类型：`定高买宽` ⇒ 只判超高 / `定宽买高` ⇒ 超宽 + 倒幅；缺省 ⇒ 都不判）。

    **自动推导的工艺配置 `plan`**（issue #5201 = 母单 #5200 子单 A，契约 §四）：
    三项输入（商品颜色 ⇒ SKU 门幅、净窗宽、净窗高）⇒ 全部工艺配置，规则唯一实现在
    `curtain_calc.derive_plan`（5 候选枚举 + 「用料最少 → 拼接最少 → 接高接宽最少 → 表序」选优）。

    - **开关 = 请求里真有 `fabric_width` 这个键**（缺省 ⇒ `plan` 为 `null`，且结果与改动前
      **逐值一致** —— 契约判据 8 的回归不变量）。为什么不用「引擎内 `fabric_width is not None`」：
      本端点为了「缺省 ⇒ 既有常量」会**总是**把门幅传下去，函数内分不清「真传了」与「端点补的常量」，
      拿它当开关会把存量调用方一起改掉。
    - `cutting_mode` 单独传**不**开推导（下单页今天就在传它做自动特征提示）；人工覆盖需与
      `fabric_width` 同传。
    - 人工 `join_height_m` / `join_width_m` 超 **0.1 米** ⇒ **422**（裁定 5，不截断）。
    - `splice_times` 越界（≥4 / 负数）⇒ 400（**不发明「拼4次」**，R5）。
    - ⚠️ `style=拼色` **不走**单色自动推导（拼色的每折吃布是另一套系数，塞进单色候选表 = 改已裁定的
      拼色米数 = 改钱）⇒ `plan.auto=false` + R4 冲突告知，米数逐值不变。
    - ⚠️ **单点口径**（判据 10）：`plan.meters` **就是** `fabric_meters`（同源同一变量，在引擎的
      唯一那个进位出口之后回填）—— 本端点不得再算一份。

    fail-closed（三处，均**不静默**）：
    ① `mounting` 非韩褶（褶数法不适用）⇒ 400；
    ② 档位低于行业下限 ⇒ 400；
    ③ **拼色命中纸表未登记的拼次**（如 `拼3次`）⇒ 400 `MIXED_PER_FOLD_NOT_REGISTERED`
    —— 不插值、不退回单色系数（那是发明口径）。

    `config`（issue #4528 = 包 E）：**租户级**算料公式参数，由 admin-api 从
    `craft_calc_configs` 读出后随请求传来；缺省 ⇒ 引擎默认值（未配置租户口径一字不变）。
    ⚠️ 缺口判定与算料**读同一份配置** —— 只给算料不给缺口判定，会让「商家自定义了 `拼3次`
    系数」的租户被误报「纸表未登记」（配置不生效的一种静默形态）。
    """
    try:
        config = _normalize_craft_calc_config(request.config)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": {"code": "CRAFT_CALC_INVALID_INPUT", "message": str(e)}},
        ) from e
    # ── 人工接高 / 接宽的上限（issue #5201，契约 R1 + 裁定 5）────────────────────
    # 契约判据 9：人工传 `join_height_m=0.2` ⇒ **422**（不是 400）—— 「入参非法」与
    # 「算料口径拒答」在既有端点上就是两个码（422 = pydantic 形态校验，400 = 引擎口径），
    # 本处按契约取 422。**fail-closed**：超限**不静默截断到 0.1**（截断 = 悄悄改商家的工艺配置）。
    for _label, _value in (("join_height_m", request.join_height_m), ("join_width_m", request.join_width_m)):
        if _value is not None and not (_value > 0 and _value <= curtain_calc.MAX_JOIN_GAP_M):
            raise HTTPException(
                status_code=422,
                detail={
                    "success": False,
                    "error": {
                        "code": "CRAFT_CALC_JOIN_OVER_LIMIT",
                        "message": (
                            f"{_label} = {_value} 米超出上限 {curtain_calc.MAX_JOIN_GAP_M} 米"
                            f"（用户 2026-09-22 裁定 5：接高和接宽都只能最多接 "
                            f"{curtain_calc.MAX_JOIN_GAP_M} 米，且不参与算料）—— 不截断、不静默兜底"
                        ),
                    },
                },
            )
    # 拼色缺口判定**先于**算料：纸表只有「1个折 0.65 / 2个折 1.2」两行，
    # `拼3次` 是表外项 ⇒ 不猜、不插值，显式报缺口（issue #4421 边界）。
    # ⚠️ 传 `config`（issue #4528）：已登记档位由**该租户的配置**决定，不是模块常量。
    gap = curtain_calc.mixed_per_fold_gap(request.special_options, config)
    if gap:
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": {
                    "code": "MIXED_PER_FOLD_NOT_REGISTERED",
                    "message": (
                        f"特殊选项「{gap}」的拼色用料系数纸表未登记（已登记："
                        f"{'/'.join(f'拼{n}次' for n in sorted(curtain_calc.MIXED_COLOR_PER_FOLD_BY_TIMES))}）——"
                        "不插值、不按单色系数估算，请先裁定该拼次的每折吃布（米/折）"
                    ),
                },
            },
        )
    try:
        quote = curtain_calc.build_quote(
            window_width=request.width,
            window_height=request.height if request.height is not None else _DEFAULT_HEIGHT,
            mounting=request.mounting,
            open_count=request.open_count,
            fabric_width=request.fabric_width if request.fabric_width is not None else _FABRIC_WIDTH,
            cutting_mode=request.cutting_mode,
            craft_tier=request.craft_tier,
            style=request.style,
            special_options=request.special_options,
            formula=request.formula,
            craft=request.craft,
            has_pattern=request.has_pattern,
            pattern_repeat=request.pattern_repeat,
            config=config,
            # 三项输入自动推导（issue #5201 = 母单 #5200 子单 A）：**显式开关**。
            # ⚠️ 不能用「`fabric_width is not None`」当开关：本端点为了契约 §四「缺省 ⇒ 引擎既有
            # 常量 `_FABRIC_WIDTH`」会**总是**把门幅传下来，引擎内分不清「调用方真传了」与
            # 「端点补的常量」⇒ 拿它当开关会把**存量调用方**的报价一起改掉（实测经济档
            # 11.8 → 11.2 米 = 改钱且无人知道，正是判据 8 要防的）。开关 = **请求里真有
            # `fabric_width` 这个键**；`cutting_mode` 单独传**不**开（前端今天就在传它）。
            derive_plan_config=request.fabric_width is not None,
            splice_times=request.splice_times,
            join_height_m=request.join_height_m,
            join_width_m=request.join_width_m,
        )
    except ValueError as e:  # 倍数低于行业下限（MIN_FULLNESS）/ 未知公式名 / 人工接高超 0.1 米上限等入参非法
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": {"code": "CRAFT_CALC_INVALID_INPUT", "message": str(e)}},
        ) from e

    if quote["formula"] == curtain_calc.FORMULA_PLEAT and "pleat_count" not in quote:
        # 走到这里只有一种情形：**褶数法**下 `mounting != s_hook`（引擎走了倍数法分支）
        # ⇒ 本端点答不出褶数法结果。**不静默回落**：如实报错，由调用方显式选韩褶。
        # ⚠️ `formula='fullness'`（褶倍数公式）**是**合法的另一种用料计算方法（issue #4527）——
        # 它本就不产出褶数，不得被这条守卫当成「不走褶数法」拒掉 ⇒ 只在**褶数法**下判它。
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": {
                    "code": "CRAFT_CALC_NOT_PLEAT_MODE",
                    "message": (
                        f"悬挂方式 {request.mounting} 不走褶数法（褶数法仅在 mounting=s_hook 生效），"
                        "无法给出褶数/用料，请改用 s_hook 或显式传 formula=fullness（褶倍数公式）"
                    ),
                },
            },
        )

    # 褶数类字段（`pleat_count` / `per_panel_pleats` / `margin` / `per_fold`）**只有褶数法产出**：
    # 褶倍数公式（`formula='fullness'`）本就不按折算 ⇒ 如实给 `None`（键恒在，前端判空），
    # **不发明** 0 / 1 冒充「0 折」——那是第二份口径（issue #4527 交付物 3 同族纪律）。
    data = {
        "fabric_meters": quote["fabric_meters"],
        "pleat_count": quote.get("pleat_count"),
        "per_panel_pleats": quote.get("per_panel_pleats"),
        "open_count": request.open_count,
        "margin": quote.get("margin"),
        "per_fold": quote.get("per_fold"),
        "fullness": quote["fullness"],
        "fullness_actual": quote.get("fullness_actual"),
        "formula_used": quote["formula_used"],
        # 公式串**由算料引擎产出**（issue #4527）：公式名 + 逐片表达式随公式而异，
        # 端点自拼 = 第二份算料逻辑。引擎保证它与 `fabric_meters` 同源。
        "formula_text": quote["formula_text"],
        "source": quote["source"],
        "craft_tier": quote["craft_tier"],
        "warning": quote["warning"],
        # 自动特征（issue #4976 包 1a，用户裁定 B「判定移到服务端」）：**键恒在**，
        # 空列表 = 不判（净窗宽/净窗高都未超过各自的企业阈值）。由引擎产出 ⇒ 与 `fabric_meters` 同源。
        # ⚠️ issue #5130：判定面已改为与**企业阈值参数**比（与门幅 / 褶倍 / 加工类型分流全无关）。
        "auto_features": quote["auto_features"],
        # 自动推导的工艺配置（issue #5201 = 母单 #5200 子单 A）：**键恒在**。
        # `None` = 本次调用没走三项输入通路（未接线调用方口径逐值不变）；
        # 非空 = 契约 §四 的 `plan` 对象（**原样搬运**，本端点不补默认值、不重算）。
        # ⚠️ 单一真值（契约判据 10）：`plan.meters` **就是** `fabric_meters` —— 两者同源同一变量，
        # 由引擎在**唯一那个进位出口**之后回填 ⇒ 不可能分叉。本端点不得再算一份。
        "plan": quote["plan"],
    }
    logger.info(
        f"Craft calc: width={request.width} open_count={request.open_count} "
        f"tier={request.craft_tier} formula={quote['formula']} "
        f"=> {data['fabric_meters']}m / {data['pleat_count']}折"
    )
    return make_response(True, data=data)


class AutoFeaturesRequest(BaseModel):
    """自动特征判定请求（issue #4976 包 2 —— 「判定移到服务端」的**读面**）。

    ⚠️ **与算料试算分开是有意的**：本端点只判「超高 / 超宽 / 倒幅」，**不算用料、不取价**。
    理由（读源事实）：下单页的 `CALC_CRAFTS` 只含 `韩褶 / 打孔 / 空` ⇒ **四爪钩 / 穿杆 / 平幔
    不发试算请求**，而自动特征是**每一行**都要判的 —— 把判定挂在试算响应上，那些行会**丢特征**
    ⇒ 组合键少一项 ⇒ **加工费匹配不到组合价**（P1 钱风险）。
    """

    width: Optional[float] = Field(
        None, gt=0, description="**净窗宽**（米）；缺 ⇒ 不判超宽")
    height: Optional[float] = Field(
        None, gt=0, description="**净窗高**（米）；缺 ⇒ 不判超高")
    fabric_width: Optional[float] = Field(
        None,
        gt=0,
        description=(
            "**该商品/SKU 的门幅**（米）。⚠️ **判定面已不读它**（issue #5130：判据改为与**企业阈值参数**比）"
            "—— 它只剩两个用途：① 几何矛盾提示（`notices` 的 `cutting-mode-conflict`）；"
            "② 回显（`door_width`）。**没有缺省门幅**（issue #4877）：缺 ⇒ **不回落**任何默认值、"
            "也不产判定面提示（回落 = 拿一个不是这张单的值判）。"
        ),
    )
    cutting_mode: Optional[str] = Field(
        None,
        description=(
            "加工类型（`定高买宽` / `定宽买高`）：**只决定要不要推导 `倒幅`**"
            "（`超高` / `超宽` 与它无关 —— issue #5130 已退役 #4661 的分流）。"
            "缺省 / 表外 ⇒ 无 `倒幅`，其余照判。"
        ),
    )
    config: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "算料公式参数（**租户级**）：判定用到两个**企业阈值**"
            "（`oversize_width_threshold` / `oversize_height_threshold`），"
            "提示用到 `hem_margin`。缺省 ⇒ 引擎默认值（`6 / 4`，未配置租户口径一字不变）。"
        ),
    )


@router.post("/production/auto-features")
async def auto_features(
    request: AutoFeaturesRequest,
    authorized: bool = Depends(verify_service_token),
):
    """自动特征判定（`POST /api/internal/production/auto-features`）—— issue #4976 包 2。

    用户 2026-09-21 裁定 B「**判定移到服务端**」的读面：前端只**展示**本端点的结论。

    **单一真值**：判定逻辑只在 `curtain_calc.detect_auto_features` 一处 ——
    本端点只做「入参归一 + 几何矛盾提示」，**不复制任何判据**（第二份判据 = 第二套价）。

    返回 `data`：`auto_features`（`[{name, source, reason}]`，**键恒在**，空列表 = **不判**）/
    `notices`（`[{kind, reason}]`，键恒在；issue #5130 后只剩 `cutting-mode-conflict`）/
    `door_width`（回显请求里的门幅；缺 ⇒ `None`）。

    🔴 **2026-09-22 改判（issue #5130）**：判定改为与**企业阈值参数**比（净窗宽/净窗高）
    ⇒ 门幅与褶倍**都不再参与判定**。据此：
    ① 本端点**不再**因「缺加工类型」短路成 `[]`（缺省 ⇒ 超高/超宽照判、无倒幅）；
    ② 响应**删掉**两个失去消费者的字段 —— `fullness_used`（判定面不再读褶倍）与
    `notice`（它的两个取值 `missing-door-width` / `unknown-cutting-mode` 在新判据下**都是假话**）。
    三条退役裁定的完整留档见 `curtain_calc.detect_auto_features` 的 docstring。
    """
    try:
        config = _normalize_craft_calc_config(request.config)
        # fail-closed 校验（issue #5130）：两个企业阈值 / 卷边等必须是正数 ⇒ 非法值 **400**，
        # **不静默回退默认值**（静默 = 算错特征名且无人知道）。校验与默认值都在**引擎**
        # （`resolve_craft_calc_config`）—— 这里再抄一份就是第二份口径。
        # 校验一次后把**同一份**已解析配置传给判定与提示（同源，不各解析一套）。
        resolved = curtain_calc.resolve_craft_calc_config(config)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": {"code": "CRAFT_CALC_INVALID_INPUT", "message": str(e)}},
        ) from e

    # 商家可见提示（issue #5036）—— 与判定面**同配置口径**（都读 `cfg`，不新造第二份常量）。
    # #5130 后只剩「几何矛盾」一条（它说的是几何层，仍然为真）：缺门幅 / 缺褶倍两条已退役。
    notices = curtain_calc.detect_auto_feature_notices(
        window_height=request.height,
        fabric_width=request.fabric_width,
        cutting_mode=request.cutting_mode,
        config=resolved,
    )

    # 🔴 一律委派引擎（**单一真值**，端点不持第二份判据）：
    # 缺加工类型 ⇒ 超高/超宽照判、无倒幅；缺门幅 ⇒ **判定面完全不受影响**（#5130 退役 #4877 判定面）。
    features = curtain_calc.detect_auto_features(
        window_width=request.width,
        window_height=request.height,
        cutting_mode=request.cutting_mode,
        config=resolved,
    )

    return make_response(True, data={
        "auto_features": features,
        "notices": notices,
        "door_width": request.fabric_width,
    })

class DoorWidthPlanRequest(BaseModel):
    """门幅规则**只读**请求（issue #5043 包 2b —— 前端 `door-width-plan.ts` 的口径搬到服务端）。

    ⚠️ **与算料试算分开是有意的**：本端点只回答「**哪个门幅 / 单幅还是接高 / 客服所选是否最优**」，
    **不算钱、不落库**。理由（读源）：下单页的规则要在**发试算请求之前**用
    （`pickAutoSkuForColor` 靠它决定选哪个 SKU/门幅），而试算请求**本身**要带门幅 ⇒ **鸡生蛋**。

    ⚠️ **四爪钩 / 穿杆 / 平幔 照常可算**（用户 2026-09-21 裁定：「这三个工艺**不影响用料和门幅**」）
    ⇒ 本端点**不继承** `craft-calc-request.ts::CALC_CRAFTS` 的闸门，也不为这三类另立口径。
    """

    width: float = Field(..., gt=0, description="成品宽（米）")
    height: Optional[float] = Field(
        None, gt=0, description="成品高（米）；缺 ⇒ `undecidable: missing-size`（不猜朝向）"
    )
    door_widths: List[float] = Field(
        default_factory=list, description="候选门幅（米，来自该颜色的 SKU）；非法值剔除，**不回落缺省门幅**"
    )
    cutting_mode: Optional[str] = Field(
        None, description="加工类型；缺省 ⇒ **自动推导**（定高买宽可行 ⇒ 定高买宽；否则 ⇒ 定宽买高）"
    )
    selected_door_width: Optional[float] = Field(
        None, gt=0, description="**客服所选**门幅（米）；裁决用；缺 ⇒ `verdict='unknown'`（无可比对象）"
    )
    allowance: float = Field(0.0, ge=0, description="门幅**有效余量**（米：缩水/边损/对花回）")
    open_count: int = Field(1, ge=1, description="开数")
    mounting: str = Field("eyelet", description="悬挂方式（`eyelet` / `s_hook`）")
    fullness: Optional[float] = Field(None, gt=0, description="名义褶倍；缺省 ⇒ 取该租户配置的标准档")
    craft: Optional[str] = Field(None, description="工艺（如 `韩褶` / `打孔`；其余按该租户默认公式）")
    craft_tier: Optional[str] = Field(None, description="工艺档位（`standard` / `economy`）")
    pleat_count: Optional[int] = Field(None, ge=1, description="褶数（韩褶褶数法）")
    formula: Optional[str] = Field(None, description="用料公式（`pleat` / `fullness`）")
    has_pattern: bool = Field(False, description="是否对花")
    pattern_repeat: float = Field(0.0, ge=0, description="花距（米）")
    config: Optional[Dict[str, Any]] = Field(None, description="租户级算料配置（判定读它的 `hem_margin`）")


@router.post("/production/door-width-plan")
async def door_width_plan(
    request: DoorWidthPlanRequest,
    authorized: bool = Depends(verify_service_token),
):
    """门幅规则（`POST /api/internal/production/door-width-plan`）—— issue #5043 包 2b。

    **单一真值**：规则解与幅数**只在引擎**（`build_quote(..., fabric_widths=...)` →
    `resolve_fabric_plan`）；裁决只在 `curtain_calc.judge_door_width_choice` 一处 ——
    本端点只做「入参归一 + 组装」，**不复制任何规则**（第二份规则 = 与引擎算料脱钩）。

    返回 `data`：`state`（`single_panel` / `needs_splice` / `undecidable`）/ `code`（undecidable 原因）/
    `effective_cutting_mode` / `door_width` / `panels` / `splice` / `verdict` / `suggestion` / `reason`。
    **不含任何金额字段**（只读规则面）。
    """
    try:
        config = _normalize_craft_calc_config(request.config)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": {"code": "CRAFT_CALC_INVALID_INPUT", "message": str(e)}},
        ) from e

    def _undecidable(code: str, reason: str) -> Any:
        return make_response(True, data={
            "state": "undecidable", "code": code, "effective_cutting_mode": None,
            "door_width": None, "panels": None, "splice": False,
            "verdict": curtain_calc.DOOR_WIDTH_VERDICT_UNKNOWN, "suggestion": None, "reason": reason,
        })

    # 候选门幅：非法值**剔除**（不默认成任何值 —— issue #4877 口径）
    candidates = sorted({
        float(g) for g in (request.door_widths or [])
        if isinstance(g, (int, float)) and not isinstance(g, bool) and float(g) > 0
    })
    if not candidates:
        return _undecidable(
            "no-door-width",
            "该规格没有可用门幅（SKU 未维护门幅）—— 不按缺省门幅推算",
        )
    if request.height is None:
        return _undecidable(
            "missing-size",
            "缺成品高 —— 判不了「定高买宽是否可行」⇒ 也推导不出加工类型（不凭空挑一个朝向）",
        )

    cfg = curtain_calc.resolve_craft_calc_config(config)
    fullness_used = (
        request.fullness if request.fullness is not None else cfg["tiers"]["standard"]["fullness"]
    )

    def _quote(door_widths: List[float]) -> Dict[str, Any]:
        """**复用 `build_quote`**（定高用料 T 的唯一实现）—— 端点**不自算 T**、不复刻公式选择。"""
        return curtain_calc.build_quote(
            window_width=request.width,
            window_height=request.height,
            mounting=request.mounting,
            fullness=fullness_used,
            fabric_width=candidates[0],
            fabric_widths=door_widths,
            open_count=request.open_count,
            pleat_count=request.pleat_count,
            craft_tier=request.craft_tier,
            craft=request.craft,
            formula=request.formula,
            has_pattern=request.has_pattern,
            pattern_repeat=request.pattern_repeat,
            cutting_mode=request.cutting_mode,
            config=config,
        )

    try:
        plan = _quote(candidates)
    except ValueError as e:
        # 加工类型表外等 ⇒ **fail-closed**（不猜朝向）
        return _undecidable("missing-cutting-mode", str(e))

    # 定宽买高裁决要比**幅数** ⇒ 用**同一份口径**把「所选门幅」也解一次（复用 `build_quote`，
    # 不另写分子 —— 前端那份「恒按倍数法」的分子正是本单要消灭的分歧）。
    selected_panels: Optional[int] = None
    selected = request.selected_door_width
    if (
        selected is not None
        and selected > 0
        and plan.get("cutting_mode") == curtain_calc.CUTTING_MODE_FIXED_WIDTH
        and plan.get("door_width") != selected
    ):
        try:
            selected_panels = _quote([float(selected)]).get("panels")
        except ValueError:
            selected_panels = None

    choice = curtain_calc.judge_door_width_choice(
        plan,
        window_height=request.height,
        selected_door_width=selected,
        selected_panels=selected_panels,
        allowance=request.allowance,
        config=config,
    )

    return make_response(True, data={
        "state": "needs_splice" if plan.get("splice") else "single_panel",
        "code": "",
        "effective_cutting_mode": plan.get("cutting_mode"),
        "door_width": plan.get("door_width"),
        "panels": plan.get("panels"),
        "splice": bool(plan.get("splice")),
        "verdict": choice["verdict"],
        "suggestion": choice["suggestion"],
        "reason": plan.get("door_width_reason", ""),
    })
