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
#   · 门幅 —— 折数法（定高买宽）**不消费**门幅，它只决定「成品高 + 卷边 > 门幅」时是否
#     转定宽买高；取 3.2m（宽幅定高布，与 issue #4118 ⑤-B 实测的同一扇窗 6.6m/2.6m 同口径）
#     ⇒ 常规层高走折数法本式 `0.25×折数+余量`，正是本单要交付的那个数。
#     门幅**不入参**：商家手工下单页当前没有门幅字段，加了就是一个没有消费者的契约字段
#     （后续按面料真实门幅接线的口径待裁定）。
#   · 窗高缺省 2.5m（常见层高口径；**不传 ≠ 0**）。
_FABRIC_WIDTH = 3.2
_DEFAULT_HEIGHT = 2.5


class CraftCalcRequest(BaseModel):
    """算料试算请求（issue #4421，商家手工下单页）

    用料口径 = 用户 2026-09-19 裁定的**折数法（标准档）**：
    `宽 × 倍数 → 折数（按开数取整）→ 每折吃布 × 折数 + 余量`。
    **每折吃布随款式/拼次变化**（同一次裁定，纸质速查表表头）：
    单色 0.25 / 拼色·拼1次 0.65 / 拼色·拼2次 1.2 米每折；余量不随拼色变化（单开 0.2 / 多开 0.3）。
    """
    width: float = Field(..., gt=0, description="窗宽（米）")
    height: Optional[float] = Field(None, gt=0, description="窗高（米）；不传按 2.5m 常见层高处理")
    open_count: int = Field(1, ge=1, description="打开方式开数（1 单开 / 2 双开 / 4 四开）")
    mounting: str = Field("s_hook", description="悬挂方式（s_hook 韩褶才走折数法）")
    craft_tier: str = Field("standard", description="工艺档位（standard 2.0 / economy 1.8）")
    style: Optional[str] = Field(None, description="款式（单色 / 拼色）；拼色**必须**同时给拼次特殊选项才用料系数")
    special_options: List[str] = Field(
        default_factory=list,
        description="部位级特殊选项（逐字名，见 routing.SPECIAL_OPTION_ROUTINGS）；拼色用料系数由 拼1次/拼2次 决定",
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

    本端点**只答数量**：路线 / 单价 / 必完标记的真相源是 DB 工序库（#4193），不在此返回。
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
    meters: float, per_fold: float,
) -> str:
    """可读公式串 —— **后端产出**，与数值同源（issue #4421 交付物 1）。

    形态：`(6.6+0.3)×2.0 → 52折 → 0.25×52+0.3 = 13.3米`；
    拼色时系数如实换（`0.65×52+0.3 = 34.1米`）。

    四个数字全部取自**同一次算料**：倍数/折数/每折吃布来自引擎（`build_quote` 的
    `fullness` / `pleat_count` / `per_fold`），余量走 `curtain_calc.margin_for_open_count`
    （与算料同一个函数）⇒ 公式串不可能与米数不一致；
    前端**不得**自拼（前端自拼 = 第二份算料逻辑）。
    """
    margin = curtain_calc.margin_for_open_count(open_count)
    return (
        f"({width:g}+{margin:g})×{fullness:g} → {pleat_count:g}折 → "
        f"{per_fold:g}×{pleat_count:g}+{margin:g} = {meters:g}米"
    )


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
    `formula_used` / `formula_text` / `source` / `craft_tier` / `warning`。

    fail-closed（三处，均**不静默**）：
    ① `mounting` 非韩褶（折数法不适用）⇒ 400；
    ② 档位低于行业下限 ⇒ 400；
    ③ **拼色命中纸表未登记的拼次**（如 `拼3次`）⇒ 400 `MIXED_PER_FOLD_NOT_REGISTERED`
    —— 不插值、不退回单色系数（那是发明口径）。
    """
    # 拼色缺口判定**先于**算料：纸表只有「1个折 0.65 / 2个折 1.2」两行，
    # `拼3次` 是表外项 ⇒ 不猜、不插值，显式报缺口（issue #4421 边界）。
    gap = curtain_calc.mixed_per_fold_gap(request.special_options)
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
            fabric_width=_FABRIC_WIDTH,
            craft_tier=request.craft_tier,
            style=request.style,
            special_options=request.special_options,
        )
    except ValueError as e:  # 倍数低于行业下限（MIN_FULLNESS）等入参非法
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": {"code": "CRAFT_CALC_INVALID_INPUT", "message": str(e)}},
        ) from e

    if "pleat_count" not in quote:
        # `mounting != s_hook` ⇒ 引擎走倍数法，本端点答不出折数法结果。
        # **不静默回落**：如实报错，由调用方显式选韩褶。
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": {
                    "code": "CRAFT_CALC_NOT_PLEAT_MODE",
                    "message": (
                        f"悬挂方式 {request.mounting} 不走折数法（折数法仅在 mounting=s_hook 生效），"
                        "无法给出折数/用料，请改用 s_hook"
                    ),
                },
            },
        )

    data = {
        "fabric_meters": quote["fabric_meters"],
        "pleat_count": quote["pleat_count"],
        "per_panel_pleats": quote["per_panel_pleats"],
        "open_count": quote["open_count"],
        "margin": quote["margin"],
        "per_fold": quote["per_fold"],
        "fullness": quote["fullness"],
        "fullness_actual": quote.get("fullness_actual"),
        "formula_used": quote["formula_used"],
        "formula_text": _formula_text(
            request.width, quote["fullness"], quote["pleat_count"],
            request.open_count, quote["fabric_meters"], quote["per_fold"],
        ),
        "source": quote["source"],
        "craft_tier": quote["craft_tier"],
        "warning": quote["warning"],
    }
    logger.info(
        f"Craft calc: width={request.width} open_count={request.open_count} "
        f"tier={request.craft_tier} => {data['fabric_meters']}m / {data['pleat_count']}折"
    )
    return make_response(True, data=data)
