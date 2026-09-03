"""
AI 智能客服系统 - 窗帘算料报价 Tool

面向小布（C 端客服）的窗帘用布量计算与报价工具。
纯计算（确定性公式），不调用 admin-api。

真值来源：docs/curtain-fabric-quote-rules.md（行业标准值 + 经验默认值）。

核心公式：
- 定高布（买宽）：M = (W + 0.3) × N    （W=窗宽, N=褶皱倍数, 0.3=左右各15cm覆盖余量）
- 定宽布（买高）：P = ceil((W+0.3)×N/G)，M = P × (H + 0.3)   （G=门幅, H=窗高, 0.3=上下卷边）
- 罗马帘：M = (W + 0.2) × (H + 0.3)
- 对花：定宽布每幅长加 1 个花距

工程陷阱：成品高 H + 0.3 > 门幅 G 时定高布超限，须改用定宽布并返回告警。
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult


# ── 悬挂方式 → 褶皱倍数默认值（【标】行业标准）──
DEFAULT_FULLNESS: Dict[str, float] = {
    "eyelet": 2.0,   # 打孔帘（罗马圈/眼环）1.8~2 倍，默认 2
    "s_hook": 2.0,   # 韩式褶（S 钩/调节钩）2~2.5 倍，默认 2
    "hook": 2.0,     # 四爪钩/普通挂钩 1.5~2 倍，默认 2
    "roman": 1.0,    # 罗马帘/卷帘/百叶帘 1 倍（无褶皱）
}

# ── 悬挂方式 → 加工费默认单价（【默】经验默认，元/米）──
DEFAULT_PROCESSING_PRICE: Dict[str, float] = {
    "eyelet": 8.0,   # 打孔式
    "s_hook": 10.0,  # 韩式褶
    "hook": 5.0,     # 四爪钩/挂钩式
    "roman": 0.0,    # 硬质折叠无加工费
}

# ── 损耗/余量常量（【标】行业标准）──
SIDE_MARGIN = 0.3       # 定高布：左右覆盖余量合计（各 15cm）
HEM_MARGIN = 0.3        # 定宽布：上下卷边合计（脚位+止口）
ROMAN_SIDE = 0.2        # 罗马帘：包边余量
ROD_EXTENSION = 0.4     # 罗马杆两端各伸出 15~20cm，合计 0.3~0.4

# ── 辅料/安装默认单价（【默】经验默认，商家可配置）──
ROMAN_RING_PRICE = 1.5        # 罗马圈 元/个（每米布约 6 个）
ROMAN_RING_PER_METER = 6      # 每米布罗马圈个数
EYELET_TAPE_PRICE = 8.0       # 孔带 元/米
ROD_PRICE = 25.0              # 罗马杆 元/米
TIEBACK_PRICE = 15.0          # 绑带 元/对
INSTALL_PRICE = 18.0          # 安装 元/米（按杆长）


def calculate_fabric_meters(
    window_width: float,
    window_height: float,
    fullness: float,
    fabric_width: float,
    mounting: str = "eyelet",
    has_pattern: bool = False,
    pattern_repeat: float = 0.0,
) -> tuple[float, str, str]:
    """计算窗帘面料用量（米）。

    Args:
        window_width: 窗宽（米）
        window_height: 窗高（米，成品窗帘高度）
        fullness: 褶皱倍数
        fabric_width: 面料门幅（米）
        mounting: 悬挂方式（eyelet/s_hook/hook/roman）
        has_pattern: 是否需要对花
        pattern_repeat: 花距（米），对花时有效

    Returns:
        (meters, formula_used, warning)
        formula_used: fixed_height（定高买宽）/ fixed_width（定宽买高）/ roman_panel（罗马帘）
        warning: 非空字符串表示存在工程告警（如窗高超定高上限）
    """
    # 罗马帘：无褶皱倍率，按包边计算
    if mounting == "roman":
        meters = (window_width + ROMAN_SIDE) * (window_height + HEM_MARGIN)
        return meters, "roman_panel", ""

    # 定高布可用条件：成品高 + 卷边 ≤ 门幅（2.8m 定高上限成品高约 2.5m）
    if window_height + HEM_MARGIN <= fabric_width:
        # 定高买宽：M = (W + 0.3) × N
        meters = (window_width + SIDE_MARGIN) * fullness
        return meters, "fixed_height", ""

    # 定宽买高：幅数向上取整，每幅长 = 窗高 + 卷边（+ 对花花距）
    panels = math.ceil((window_width + SIDE_MARGIN) * fullness / fabric_width)
    panel_length = window_height + HEM_MARGIN
    if has_pattern:
        panel_length += pattern_repeat
    meters = panels * panel_length
    warning = (
        f"成品高 {window_height:.2f}m 超过门幅 {fabric_width:.2f}m 的定高上限，"
        f"已按定宽布（买高）计算，幅数 {panels} 幅。"
    )
    return meters, "fixed_width", warning


def build_quote(
    window_width: float,
    window_height: float,
    mounting: str = "eyelet",
    fullness: Optional[float] = None,
    fabric_width: float = 2.8,
    fabric_price: float = 30.0,
    has_pattern: bool = False,
    pattern_repeat: float = 0.0,
) -> Dict[str, Any]:
    """构建完整报价单。

    Args:
        window_width: 窗宽（米）
        window_height: 窗高（米）
        mounting: 悬挂方式（默认 eyelet）
        fullness: 褶皱倍数（None 时按悬挂方式默认值）
        fabric_width: 面料门幅（默认 2.8 米）
        fabric_price: 面料单价（元/米）
        has_pattern: 是否对花
        pattern_repeat: 花距（米）

    Returns:
        报价字典：fabric_meters / fabric_cost / processing_cost / accessory_cost /
        install_cost / total / breakdown / formula_used / warning / fullness
    """
    # 褶皱倍数默认值
    N = fullness if fullness is not None else DEFAULT_FULLNESS.get(mounting, 2.0)

    meters, formula_used, warning = calculate_fabric_meters(
        window_width=window_width,
        window_height=window_height,
        fullness=N,
        fabric_width=fabric_width,
        mounting=mounting,
        has_pattern=has_pattern,
        pattern_repeat=pattern_repeat,
    )

    # 面料费
    fabric_cost = meters * fabric_price

    # 加工费（按款式单价 × 面料米数）
    processing_price = DEFAULT_PROCESSING_PRICE.get(mounting, 0.0)
    processing_cost = meters * processing_price

    # 辅料费（打孔帘：罗马圈 + 孔带 + 罗马杆 + 绑带）
    rod_length = window_width + ROD_EXTENSION
    accessory_breakdown = []
    accessory_cost = 0.0

    if mounting == "eyelet":
        ring_count = round(meters * ROMAN_RING_PER_METER)
        ring_cost = ring_count * ROMAN_RING_PRICE
        tape_cost = meters * EYELET_TAPE_PRICE
        rod_cost = rod_length * ROD_PRICE
        tieback_cost = TIEBACK_PRICE
        accessory_breakdown = [
            {"name": "罗马圈", "detail": f"{ring_count}个 × ¥{ROMAN_RING_PRICE}/个", "cost": round(ring_cost, 2)},
            {"name": "孔带", "detail": f"{meters:.2f}米 × ¥{EYELET_TAPE_PRICE}/米", "cost": round(tape_cost, 2)},
            {"name": "罗马杆", "detail": f"{rod_length:.2f}米 × ¥{ROD_PRICE}/米", "cost": round(rod_cost, 2)},
            {"name": "绑带", "detail": "1对", "cost": tieback_cost},
        ]
        accessory_cost = ring_cost + tape_cost + rod_cost + tieback_cost

    # 安装费（按杆长）
    install_cost = rod_length * INSTALL_PRICE

    total = fabric_cost + processing_cost + accessory_cost + install_cost

    breakdown = [
        {"name": "面料", "detail": f"{meters:.2f}米 × ¥{fabric_price}/米", "cost": round(fabric_cost, 2)},
        {"name": "加工费", "detail": f"{meters:.2f}米 × ¥{processing_price}/米", "cost": round(processing_cost, 2)},
        *accessory_breakdown,
        {"name": "安装费", "detail": f"{rod_length:.2f}米 × ¥{INSTALL_PRICE}/米", "cost": round(install_cost, 2)},
    ]

    return {
        "fabric_meters": round(meters, 2),
        "fabric_cost": round(fabric_cost, 2),
        "processing_cost": round(processing_cost, 2),
        "accessory_cost": round(accessory_cost, 2),
        "install_cost": round(install_cost, 2),
        "total": round(total, 2),
        "breakdown": breakdown,
        "formula_used": formula_used,
        "fullness": N,
        "warning": warning,
    }


class CurtainCalcTool(BaseTool):
    """窗帘算料报价 Tool

    根据窗户尺寸 + 悬挂方式 + 面料信息，计算用布量与报价。
    纯计算（read_only），不修改任何数据。
    """

    name = "curtain_calc"
    description = (
        "计算窗帘用布量与报价。用户询问窗帘需要多少布、多少钱、怎么算料时调用。"
        "【前置】需要窗宽(米)、窗高(米)；面料单价可通过 product_detail 查询得到。"
        "【反例】查面料价格/库存用 product_detail，不要用它算料；下单用 order_create。"
        "READONLY"
    )
    read_only = True
    destructive = False
    idempotent = True
    allowed_roles = ["customer", "admin", "agent", "tenant_admin"]

    parameters = {
        "type": "object",
        "properties": {
            "window_width": {
                "type": "number",
                "description": "窗宽（米），必填。如 3 米宽窗传 3.0",
            },
            "window_height": {
                "type": "number",
                "description": "窗高（米，成品窗帘高度），必填。如 2.7 米高窗传 2.7",
            },
            "mounting": {
                "type": "string",
                "description": "悬挂方式：eyelet(打孔帘)/s_hook(韩式褶)/hook(四爪钩)/roman(罗马帘)。默认 eyelet",
                "enum": ["eyelet", "s_hook", "hook", "roman"],
            },
            "fullness": {
                "type": "number",
                "description": "褶皱倍数（可选，不传则按悬挂方式默认：打孔/韩式褶/四爪钩=2，罗马帘=1）",
            },
            "fabric_width": {
                "type": "number",
                "description": "面料门幅（米），默认 2.8。窄幅布为 1.4",
            },
            "fabric_price": {
                "type": "number",
                "description": "面料单价（元/米），必填。可从 product_detail 查询得到",
            },
            "has_pattern": {
                "type": "boolean",
                "description": "是否需要对花（大花型面料），默认 false",
            },
            "pattern_repeat": {
                "type": "number",
                "description": "花距（米），对花时有效，常见 0.3~0.6",
            },
        },
        "required": ["window_width", "window_height"],
    }

    async def execute(
        self,
        context: ToolContext,
        window_width: float,
        window_height: float,
        mounting: str = "eyelet",
        fullness: Optional[float] = None,
        fabric_width: float = 2.8,
        fabric_price: Optional[float] = None,
        has_pattern: bool = False,
        pattern_repeat: float = 0.0,
    ) -> ToolResult:
        """执行算料报价"""
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限使用算料功能",
                suggestion="请联系管理员",
            )

        # 参数校验
        if not window_width or window_width <= 0:
            return ToolResult(
                success=False,
                error="缺少窗宽",
                message="请提供窗户宽度（米）",
                suggestion="请告诉客户窗户的宽度，例如「窗宽3米」",
            )
        if not window_height or window_height <= 0:
            return ToolResult(
                success=False,
                error="缺少窗高",
                message="请提供窗户高度（米）",
                suggestion="请告诉客户窗户的高度，例如「窗高2.7米」",
            )
        if mounting not in DEFAULT_FULLNESS:
            return ToolResult(
                success=False,
                error="不支持的悬挂方式",
                message=f"悬挂方式 {mounting} 不支持",
                suggestion="悬挂方式仅支持：打孔(eyelet)/韩式褶(s_hook)/四爪钩(hook)/罗马帘(roman)",
            )

        # GB/T 47746-2026 承诺边界：面料单价缺失时禁止按默认 30 元/米兜底报价
        # （默认价可能与真实售价不符，属编造报价承诺）。必须先查商品拿到真实单价再报价。
        if fabric_price is None:
            return ToolResult(
                success=False,
                error="缺少面料单价",
                message="缺少面料单价，请先查商品信息再报价",
                suggestion="请先调用 product_detail 或 product_search 查询该商品的面料单价（元/米），拿到真实单价后再重新计算报价",
            )

        try:
            quote = build_quote(
                window_width=float(window_width),
                window_height=float(window_height),
                mounting=mounting,
                fullness=fullness,
                fabric_width=float(fabric_width),
                fabric_price=float(fabric_price),
                has_pattern=has_pattern,
                pattern_repeat=pattern_repeat,
            )

            logger.info(
                f"[curtain-calc] quote: W={window_width} H={window_height} "
                f"mounting={mounting} fullness={quote['fullness']} "
                f"meters={quote['fabric_meters']} total={quote['total']} "
                f"formula={quote['formula_used']} | tenant={context.tenant_id}"
            )

            return ToolResult(
                success=True,
                data=quote,
                summary=(
                    f"算料结果：{quote['fabric_meters']}米，总价¥{quote['total']} "
                    f"（面料¥{quote['fabric_cost']}+加工¥{quote['processing_cost']}"
                    f"+辅料¥{quote['accessory_cost']}+安装¥{quote['install_cost']}）"
                ),
                message=(
                    f"算料完成：共需面料 {quote['fabric_meters']} 米，总价 ¥{quote['total']}"
                    "（以上为 AI 按您提供尺寸的预估报价，最终以实际测量/确认为准）"
                ),
            )
        except Exception as e:
            logger.error(f"[curtain-calc] Failed: {type(e).__name__}: {e}")
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="算料失败，请稍后重试",
                suggestion="请检查窗宽窗高是否正确，确认后重试",
            )
