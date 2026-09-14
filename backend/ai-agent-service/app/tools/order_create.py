"""
AI 智能客服系统 - 订单创建 Tool

创建新订单，调用 admin-api 的 POST /api/admin/orders 接口。

安全（#518）:
- 客户创建订单前必须通过手机号 SMS 验证码验证身份
- 管理员/客服帮客户下单无需 SMS 验证
"""
from __future__ import annotations

import json
import math
import os
import re
from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client
from app.utils.redis_client import RedisClient


# SMS 验证码 Redis key 前缀
_OTP_KEY_PREFIX = "sms:otp:"
_OTP_TTL_SECONDS = 300  # 5分钟有效期
_OTP_VALID_PATTERN = re.compile(r"^\d{4,6}$")  # 4-6位数字验证码
_PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")  # 中国大陆手机号

# 数值参数解析（issue #3586）：允许货币符号前缀 + 单位后缀（"¥168.00" / "3米" / "2.8 米"）。
# 用户口语里的"3米"就是数量 3 —— 带单位的合法输入不得被当成非法值拦掉。
_NUMERIC_PREFIX_PATTERN = re.compile(r"^[¥￥$]?\s*(?P<num>[+-]?\d+(?:\.\d+)?)")

# 枚举合法值（issue #3622）。单一事实源在 admin-api 侧，工具侧照抄，别名归一化刻意不做：
# - sellingMethod: `product_skus.selling_method` = bulk_cut(散剪) / full_roll(整卷)；
#   `OrderService:1435` 回退匹配时按**字面** eq 比较 → 拼写变体静默匹配不到
#   → 库存校验/销量统计静默丢失（#3621 同源）。
# - pricingMethod: `ProcessingItemService:298` 只认 per_meter/per_set/fixed/per_area
#   （per_piece 按个不支持，issue #3005）。
_SELLING_METHODS = ("bulk_cut", "full_roll")
_PRICING_METHODS = ("per_meter", "per_set", "fixed", "per_area")

# 万能验证码 bypass（POC/测试阶段，对齐 admin-api 的 sms.bypass-code 机制）。
# 空字符串 = 禁用 bypass（生产安全默认）。POC 部署时设置 SMS_BYPASS_CODE=123456 与 admin-api 对齐。
SMS_BYPASS_CODE = os.getenv("SMS_BYPASS_CODE", "")


class OrderCreateTool(BaseTool):
    """订单创建 Tool

    通过调用 admin-api 创建新订单。

    使用场景：
    - 客服帮客户下单
    - 客户通过聊天直接创建订单

    安全规则（#518）:
    - customer 角色：必须提供 sms_code，且通过手机号验证
    - admin/agent/tenant_admin 角色：无需 SMS 验证（帮客户下单）
    """

    name = "order_create"
    description = (
        "【触发】创建订单。用户说'创建订单''下单'时调用。"
        "【前置】必须先调 product_detail 查 SKU，多 SKU 必须让用户选规格（颜色/售卖方式/门幅）。单 SKU 直接用。"
        "必填: customer_name + customer_phone + items(product_name+quantity+unit_price+subtotal)。"
        "售卖方式/门幅/颜色等规格信息放入 items[i].processing_info（字段：sellingMethod/doorWidth/colorName），"
        "不要平铺在 items 顶层（平铺会被丢弃）。"
        "【铁律·加工项】product_detail 返回的加工项（processing_items）非空时，**必须先调用 "
        "interact(component=choice, multiSelect=true) 主动询问顾客要不要加工项**（列出名称与单价），"
        "把所选写入 items[i].processing_info.processingItems、合计写入 processingFee 并计入金额；"
        "顾客说不需要可跳过；加工项为空才可告知无可用加工项。"
        "**未询问就直接建单 = 漏收加工费 = 订单金额错误**，属禁止行为。"
        # 口径规则放工具描述而非 system prompt（issue #3521）：
        #   ① 这是**参数语义**（processingItems 的 quantity 怎么来），与字段定义同处最合适；
        #   ② C 端下单 prompt 已顶到长度守卫上限（3592/3600），加规则必须先删旧规则——
        #      在 bug 修复里改别人行为域的措辞风险更大，故走零预算的加法路径。
        # 实证：CH-010 首跑 `总额 311.4 ≠ Σ小计71.4+加工费252.0=323.4` —— 小计 71.4=3×23.8，
        #   落库总额 311.4=71.4+240（服务端按 processingItems 的 unitPrice×quantity 重算），
        #   而模型声明的 processingFee=252（把按面积的刺绣工艺算成 30×8.4）。同一个订单两份数字。
        "【铁律·加工数量口径】processingItems[i].quantity 必须按 pricingMethod 推导，不许凭感觉："
        "per_meter(按米)=面料米数；per_area(按面积)=门幅(米)×面料米数；per_set(按套)=套数；"
        "fixed(一口价)=1（单价即该项总价）。"
        "**processingFee 必须等于 Σ(processingItems[i].unitPrice × quantity)**（容差 0.01）——"
        "服务端只按这个明细口径计总额，两处不一致时顾客在确认卡上看到的总额 ≠ 实际落库/收款金额。"
        "【反例】跳过 SKU 选择直接下单；把 sellingMethod/doorWidth 平铺进 items；"
        "凭 product_search 列表断言'该商品无加工项'（列表本就查不到，必须查详情）。修改订单用 order_manage。WRITE"
    )
    allowed_roles = ["admin", "agent", "tenant_admin", "customer"]

    read_only = False
    destructive = False
    # GB/T 47746-2026 承诺边界：下单即与顾客达成交易合同（金额/履约承诺），
    # 含 B 端客服代顾客下单——必须先向用户展示订单确认卡并取得明确确认后才能执行。
    requires_confirmation = True
    idempotent = False  # 每次调用创建新订单

    # 关联校验工具
    related_tools = ["validate_input"]

    parameters = {
        "type": "object",
        "properties": {
            "customer_name": {
                "type": "string",
                "description": "客户姓名（必填）",
            },
            "customer_phone": {
                "type": "string",
                "description": "客户电话（必填）",
            },
            "sms_code": {
                "type": "string",
                "description": "短信验证码，4-6位数字。customer角色必填，admin/agent不需要",
            },
            "customer_address": {
                "type": "string",
                "description": "客户收货地址（可选）",
            },
            "remark": {
                "type": "string",
                "description": "订单备注（可选）",
            },
            "items": {
                "type": "array",
                "description": "商品明细列表（必填，至少一项）",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_name": {
                            "type": "string",
                            "minLength": 1,
                            "description": "商品名称（必填，不得为空；与 product_detail 返回一致）",
                        },
                        "quantity": {
                            "type": "integer",
                            "exclusiveMinimum": 0,
                            "description": "数量（必填，必须为正整数；负数/0 会被本地拒绝）",
                        },
                        "unit_price": {
                            "type": "number",
                            "exclusiveMinimum": 0,
                            "description": "单价（必填，必须大于 0 元）",
                        },
                        "subtotal": {
                            "type": "number",
                            "minimum": 0,
                            "description": "小计 = 数量 × 单价 + 加工费（必填，不得为负）",
                        },
                        "product_id": {
                            "type": "string",
                            "description": "商品 32 位 UUID（可选）。当用户明确指定商品时传入。不传时服务端通过 product_name 自动匹配",
                        },
                        "width": {
                            "type": "number",
                            "minimum": 0,
                            "description": "宽度（米，可选，不得为负；可传 2.8 或「2.8米」）",
                        },
                        "height": {
                            "type": "number",
                            "minimum": 0,
                            "description": "高度（米，可选，不得为负；可传 2.0 或「2.0米」）",
                        },
                        "processing_info": {
                            "type": "object",
                            "description": "商品销售信息（选了颜色/门幅后必填）：colorId(颜色ID，字符串，来自商品详情)、colorName(颜色名称)、sellingMethod(售卖方式: bulk_cut散剪/full_roll整卷)、doorWidth(门幅如2.8米)、skuCode(SKU编码)、processingItems(加工项列表)、processingFee(加工费合计)",
                            "properties": {
                                "colorId": {"type": "string", "description": "颜色ID（字符串，来自商品详情）"},
                                "colorName": {"type": "string", "description": "颜色名称"},
                                "sellingMethod": {
                                    "type": "string",
                                    "enum": ["bulk_cut", "full_roll"],
                                    "description": "售卖方式，取 product_detail skus[].selling_method 原值：bulk_cut(散剪) / full_roll(整卷)。拼写变体（散剪/bulkCut）会被本地拒绝",
                                },
                                "doorWidth": {"type": "string", "description": "门幅"},
                                "skuCode": {"type": "string", "description": "SKU编码"},
                                "processingFee": {
                                    "type": "number",
                                    "minimum": 0,
                                    "description": "加工费合计（不得为负）= Σ(processingItems[i].unitPrice × quantity)",
                                },
                                "processingItems": {
                                    "type": "array",
                                    "description": "加工项列表",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "name": {"type": "string"},
                                            "unitPrice": {"type": "number", "minimum": 0},
                                            "quantity": {"type": "integer", "minimum": 0},
                                            "unit": {"type": "string"},
                                            "pricingMethod": {
                                                "type": "string",
                                                "enum": ["per_meter", "per_set", "fixed", "per_area"],
                                                "description": "计价方式，取 product_detail processing_items[].pricing_method 原值：per_meter(按米)/per_set(按套)/fixed(一口价)/per_area(按面积)；per_piece(按个)不支持",
                                            },
                                            "subtotal": {"type": "number", "minimum": 0},
                                        },
                                    },
                                },
                            },
                        },
                    },
                    "required": ["product_name", "quantity", "unit_price", "subtotal"],
                },
            },
        },
        "required": ["customer_name", "customer_phone", "items"],
    }

    @staticmethod
    def _parse_positive_number(raw: Any) -> Optional[float]:
        """解析数值参数（数量/单价/小计），容忍 LLM 常见形态并**拒绝非正数**。

        契约（issue #3586）：
        - 数值型直接取用；字符串数字（"3"）与**带单位**的合法输入（"3米"、"¥168.00"、
          "2.8 米"）按前导数字解析——用户口语里的"3米"就是数量 3，不能因为带单位拦掉；
        - 布尔值（True/False）不算数字（Python 里 bool 是 int 子类，必须显式排除）；
        - NaN / Infinity、空值、非数字文本 → None（交由调用方给出可行动提示）。

        Returns: float 值；无法解析返回 None。
        """
        if isinstance(raw, bool) or raw is None:
            return None
        if isinstance(raw, (int, float)):
            value = float(raw)
            return value if math.isfinite(value) else None
        if isinstance(raw, str):
            m = _NUMERIC_PREFIX_PATTERN.match(raw.strip())
            if not m:
                return None
            value = float(m.group("num"))
            return value if math.isfinite(value) else None
        return None

    @staticmethod
    def _reject_quantity(i: int, raw: Any) -> Optional[ToolResult]:
        """数量校验（issue #3586）：必须是正整数（拒绝 0 / 负数 / 非整数小数）。

        为什么在工具层 fail-fast：`order_items.quantity` 是**金额与库存的乘数**——
        负数量会算出**负金额**落库（下游 `createOrder` 不做正负判断），
        0 数量产出 0 元明细；且 Agent 路径的 admin-api 入参（AgentOrderItem）
        **未做 Bean Validation**，等 HTTP 回来才拒绝等于白跑一轮且提示不可行动。
        """
        value = OrderCreateTool._parse_positive_number(raw)
        if value is None:
            return ToolResult(
                success=False,
                error=f"商品明细第 {i + 1} 项数量无效",
                message=(
                    f"商品明细第 {i + 1} 项的数量「{raw}」不是有效数字。"
                    f"数量必须是**正整数**（如 3、10），不要带单位或写成文字。"
                ),
                suggestion=(
                    "请把 quantity 改成正整数（按米数/件数取整，如 3 米 → 3）；"
                    "若同一商品有多个规格，请拆成多行而不是把数量写在一行里"
                ),
            )
        if value <= 0:
            return ToolResult(
                success=False,
                error=f"商品明细第 {i + 1} 项数量必须大于 0",
                message=(
                    f"商品明细第 {i + 1} 项的数量是 {raw}，但下单数量必须是**正数**。"
                    f"数量为负会让订单金额变成负数（{raw} × 单价），导致金额/库存/对账全部出错，"
                    f"因此系统在调用服务端**之前**就拒绝。"
                ),
                suggestion=(
                    f"请把 quantity 改成正整数：顾客想要 {abs(value):g} 米就填 {abs(value):g}，"
                    "不要用 -1 之类的占位值表示退款或扣减（退款请用 order_manage 的 refund）"
                ),
            )
        if value != int(value):
            return ToolResult(
                success=False,
                error=f"商品明细第 {i + 1} 项数量必须为整数",
                message=(
                    f"商品明细第 {i + 1} 项的数量是 {raw}，但订单数量只支持**整数**（最小 1）。"
                    f"小数会被服务端截断（{raw} → {int(value)}），造成少收钱/少发货。"
                ),
                suggestion=(
                    f"请把数量取整为整数（例如 {value:g} → {max(1, round(value))}）；"
                    "不足 1 米的零头请与顾客确认后按整数计"
                ),
            )
        return None

    @staticmethod
    def _reject_non_positive_amount(i: int, field: str, raw: Any) -> Optional[ToolResult]:
        """金额类字段校验（issue #3586）：单价/小计必须是 ≥ 0 的数，单价必须 > 0。

        admin-api `OrderCreateRequest.OrderItemRequest` 对 unitPrice/subtotal 标了
        `@Positive`（必须 > 0）；工具侧提前对齐，避免"注定被拒的调用白跑一轮"。
        """
        label = "单价" if field == "unit_price" else "小计"
        value = OrderCreateTool._parse_positive_number(raw)
        if value is None:
            return ToolResult(
                success=False,
                error=f"商品明细第 {i + 1} 项{label}无效",
                message=f"商品明细第 {i + 1} 项的{label}「{raw}」不是有效数字。",
                suggestion=f"请填写数字型{label}（元），如 168 或 168.00",
            )
        if value < 0:
            return ToolResult(
                success=False,
                error=f"商品明细第 {i + 1} 项{label}不能为负数",
                message=(
                    f"商品明细第 {i + 1} 项的{label}是 {raw}，订单{label}不能为负数"
                    f"（负金额会污染订单总额与财务对账）。"
                ),
                suggestion=(
                    f"请把 {field} 改成 ≥ 0 的数；折扣请走优惠金额，不要在明细里写负数"
                ),
            )
        if field == "unit_price" and value == 0:
            return ToolResult(
                success=False,
                error=f"商品明细第 {i + 1} 项单价必须大于 0",
                message=(
                    f"商品明细第 {i + 1} 项的单价是 0，服务端要求单价必须大于 0 元"
                    f"（免费的加工项应计 0 元加工费，但面料单价必须 > 0）。"
                ),
                suggestion="请向顾客确认单价后填写大于 0 的金额（如 168）；赠品请用 0 元加工项表达，不要整行 0 元",
            )
        return None

    @staticmethod
    def _reject_subtotal_below_product(i: int, quantity: float, unit_price: float,
                                       raw: Any) -> Optional[ToolResult]:
        """小计自洽校验（issue #3586）：subtotal 不得小于「数量 × 单价」。

        口径说明（不误伤）：**不要求严格相等**——本行业 subtotal = 面料金额 + 加工费
        （先例：OR-014 的 288 = 168×? 面料 + 打孔加工费），因此只拦"比面料金额还小"的
        自相矛盾值（少收钱 + 金额对不上账）。容差 0.01 吸浮点误差。
        """
        value = OrderCreateTool._parse_positive_number(raw)
        if value is None:
            return None  # 无法解析已在 _reject_non_positive_amount 覆盖
        expected = quantity * unit_price
        if value < expected - 0.01:
            return ToolResult(
                success=False,
                error=f"商品明细第 {i + 1} 项小计与数量×单价不符",
                message=(
                    f"商品明细第 {i + 1} 项：小计 {raw} < 数量 {quantity:g} × 单价 {unit_price:g} "
                    f"= {expected:.2f}，订单金额自相矛盾（会少收钱）。"
                ),
                suggestion=(
                    f"请把 subtotal 改为「数量 × 单价 + 加工费」= {expected:.2f} 起"
                    "（含加工费时应大于该值）；顾客打折请走优惠金额字段"
                ),
            )
        return None

    @staticmethod
    def _reject_invalid_amount(where: str, field_label: str, field_key: str, raw: Any,
                               impact: str) -> Optional[ToolResult]:
        """非负数值闸门（issue #3622）：负数/不可解析 → 本地拒绝（HTTP 之前 fail-fast）。

        覆盖面：`items[].width/height`（尺寸）、`processing_info.processingFee`、
        `processing_info.processingItems[].quantity/unitPrice/subtotal`。

        为什么在工具层拦：这些值直接进入金额/面积数学 —— 服务端
        `OrderService.sumProcessingFee()`（:824-829）就是 Σ `unitPrice × quantity`
        （`extractProcessingItems` :807-811 即这两字段相乘），**任一为负 → 负加工费**
        直接加进 `totalAmount` 落库（:417）；负尺寸则让 per_area 计价算出负面积。
        Agent 路径 DTO（`AgentOrderItem`）原先零约束注解、Controller 无 `@Valid` → 后端不拦。
        """
        value = OrderCreateTool._parse_positive_number(raw)
        if value is None:
            return ToolResult(
                success=False,
                error=f"{where}{field_label}无效",
                message=f"{where}的{field_label}「{raw}」不是有效数字。",
                suggestion=(
                    f"请把 {field_key} 改成数值型{field_label}（如 2.8 / 8 / 24.00），"
                    "不要写文字或「宽2.8」这类带前后缀的文本"
                ),
            )
        if value < 0:
            return ToolResult(
                success=False,
                error=f"{where}{field_label}不能为负数",
                message=(
                    f"{where}的{field_label}是 {raw}，不能为负数 —— {impact}。"
                ),
                suggestion=(
                    f"请把 {field_key} 改成 ≥ 0 的数值；顾客要减钱请走优惠金额字段，"
                    "不要用负数代表扣减"
                ),
            )
        return None

    @staticmethod
    def _reject_invalid_enum(where: str, field_label: str, field_key: str, raw: Any,
                             legal: tuple) -> Optional[ToolResult]:
        """枚举闸门（issue #3622）：售卖方式/计价方式必须是**后端字面认得的**枚举值。

        刻意不做别名归一化（"散剪"→bulk_cut）：后端 `OrderService:1435` 是**按字面**
        eq 匹配 SKU 的，归一化会把"这个字段到底该传什么"的契约藏进工具层；而静默接受
        变体的代价是**静默不匹配**（SKU 匹配不到 → 库存校验/销量统计静默丢失）。
        所以拒绝 + 点名合法值，让 LLM 下一轮自愈。
        """
        if raw is None:
            return None  # 可选字段（单 SKU 商品不一定有售卖方式）
        if isinstance(raw, str) and raw in legal:
            return None
        return ToolResult(
            success=False,
            error=f"{where}{field_label}无效",
            message=(
                f"{where}的{field_label}是「{raw}」，不是后端认得的合法值。"
                "拼写变体会被**静默**当成另一个规格：SKU 匹配按字面比较 → 匹配不到 → "
                "库存校验与销量统计静默丢失。"
            ),
            suggestion=(
                f"请改用 product_detail 返回的**原值**：{' / '.join(legal)}"
                + ("（散剪=bulk_cut、整卷=full_roll）" if field_key.endswith("sellingMethod")
                   else "（per_piece 按个不支持，issue #3005）")
            ),
        )

    @staticmethod
    def _validate_processing_info(i: int, pinfo: Any) -> Optional[ToolResult]:
        """`processing_info` 内的范围/枚举闸门（issue #3622）。

        只在 pinfo 是 dict 时校验：JSON 字符串形态是老契约（服务端 `extractProcessingItems`
        自己解析），工具侧不臆断其内容，避免误报。
        """
        if not isinstance(pinfo, dict):
            return None
        where = f"商品明细第 {i + 1} 项"
        rejected = OrderCreateTool._reject_invalid_enum(
            where, "售卖方式", "processing_info.sellingMethod",
            pinfo.get("sellingMethod"), _SELLING_METHODS)
        if rejected is not None:
            return rejected
        if pinfo.get("processingFee") is not None:
            rejected = OrderCreateTool._reject_invalid_amount(
                where, "加工费", "processing_info.processingFee", pinfo.get("processingFee"),
                "负加工费会把订单总额拉低（顾客少付钱、财务对账对不上）")
            if rejected is not None:
                return rejected
        raw_items = pinfo.get("processingItems")
        if raw_items is None:
            return None
        if not isinstance(raw_items, list):
            return ToolResult(
                success=False,
                error=f"{where}加工项格式错误",
                message=(
                    f"{where}的 processing_info.processingItems 不是列表"
                    f"（{type(raw_items).__name__}），服务端解析不出加工项与加工费。"
                ),
                suggestion="请把 processingItems 写成列表，每项为对象：{name, unitPrice, quantity, pricingMethod}",
            )
        for j, entry in enumerate(raw_items):
            entry_where = f"{where}加工项第 {j + 1} 项"
            if not isinstance(entry, dict):
                return ToolResult(
                    success=False,
                    error=f"{entry_where}格式错误",
                    message=(
                        f"{entry_where}不是对象，服务端 `extractProcessingItems` 会跳过它"
                        " → 该加工费被静默丢弃（顾客少收钱）。"
                    ),
                    suggestion="请把每个加工项写成对象：{name, unitPrice, quantity, pricingMethod}",
                )
            rejected = OrderCreateTool._reject_invalid_enum(
                entry_where, "计价方式", "processingItems[].pricingMethod",
                entry.get("pricingMethod"), _PRICING_METHODS)
            if rejected is not None:
                return rejected
            for field_key, label, impact in (
                ("quantity", "数量", "负数量的加工费是负数（服务端按 unitPrice × quantity 计费）"),
                ("unitPrice", "单价", "负单价的加工费是负数（服务端按 unitPrice × quantity 计费）"),
                ("subtotal", "小计", "负小计与加工费口径自相矛盾（确认卡金额与落库金额对不上）"),
            ):
                if entry.get(field_key) is None:
                    continue
                rejected = OrderCreateTool._reject_invalid_amount(
                    entry_where, label, f"processingItems[].{field_key}",
                    entry.get(field_key), impact)
                if rejected is not None:
                    return rejected
        return None

    @staticmethod
    def _validate_item_value_bounds(i: int, item: Dict[str, Any]) -> Optional[ToolResult]:
        """单行明细的**数值语义 + 枚举**校验：在发 HTTP 之前 fail-fast。

        覆盖面（issue #3586）：quantity（正整数）、unit_price（> 0）、subtotal（≥ 0 且 ≥ 数量×单价）。
        覆盖面（issue #3622，同族残留）：product_name 非空、width/height（≥ 0）、
        processing_info 的 sellingMethod 枚举 / processingFee（≥ 0）/
        processingItems[].pricingMethod 枚举与 quantity/unitPrice/subtotal（≥ 0）。
        只做确定性判定（无 LLM、无网络），保证"注定失败的调用"不产生 HTTP 往返，
        也保证「闸门放行的值 = 服务端能接受的值」。
        """
        # 商品名称必须非空（#3622：原先只判「字段存在 or None」→ 空串可一路下单）
        raw_name = item.get("product_name")
        if isinstance(raw_name, str) and not raw_name.strip():
            return ToolResult(
                success=False,
                error=f"商品明细第 {i + 1} 项商品名称为空",
                message=(
                    f"商品明细第 {i + 1} 项的 product_name 是空字符串 —— 空商品名的订单"
                    "无法在列表/对账里定位商品，也无法作为售后凭证。"
                ),
                suggestion=(
                    "请填写顾客所选商品的名称（与 product_detail 返回的商品名一致），"
                    "不要用空串占位"
                ),
            )
        for field, label in (("quantity", "数量"), ("unit_price", "单价"), ("subtotal", "小计")):
            if field not in item or item.get(field) is None:
                return None  # 缺字段由必填检查给出提示（此处不重复报错）
        rejected = OrderCreateTool._reject_quantity(i, item.get("quantity"))
        if rejected is not None:
            return rejected
        rejected = OrderCreateTool._reject_non_positive_amount(i, "unit_price", item.get("unit_price"))
        if rejected is not None:
            return rejected
        rejected = OrderCreateTool._reject_non_positive_amount(i, "subtotal", item.get("subtotal"))
        if rejected is not None:
            return rejected
        quantity = OrderCreateTool._parse_positive_number(item.get("quantity"))
        unit_price = OrderCreateTool._parse_positive_number(item.get("unit_price"))
        rejected = OrderCreateTool._reject_subtotal_below_product(
            i, quantity or 0.0, unit_price or 0.0, item.get("subtotal")
        )
        if rejected is not None:
            return rejected
        # 尺寸（#3622，可选）：负尺寸 → per_area 负面积
        for field, label, impact in (
            ("width", "宽度", "负宽度会让按面积（per_area）计价算出负面积"),
            ("height", "高度", "负高度会让按面积（per_area）计价算出负面积"),
        ):
            if item.get(field) is None:
                continue
            rejected = OrderCreateTool._reject_invalid_amount(
                f"商品明细第 {i + 1} 项", label, field, item.get(field), impact)
            if rejected is not None:
                return rejected
        # 加工信息（#3622）：售卖方式/加工费/加工项数量与单价
        return OrderCreateTool._validate_processing_info(i, item.get("processing_info"))

    @staticmethod
    def _otp_key(phone: str, tenant_id: int) -> str:
        """构造 SMS 验证码 Redis key"""
        return f"{_OTP_KEY_PREFIX}{tenant_id}:{phone}"

    @staticmethod
    async def _verify_sms_code(phone: str, code: str, tenant_id: int) -> bool:
        """验证短信验证码

        从 Redis 读取已存储的验证码并比对。
        验证成功后删除验证码（一次性使用）。

        Args:
            phone: 客户手机号
            code: 用户输入的验证码
            tenant_id: 租户ID

        Returns:
            bool: 验证是否通过
        """
        # 万能验证码 bypass：POC/测试阶段直接通过（不碰 Redis）。
        # 生产环境须将 SMS_BYPASS_CODE 设为空以禁用。
        if SMS_BYPASS_CODE and code and code.strip() == SMS_BYPASS_CODE:
            logger.info(f"[sms_verify] Bypass code accepted: phone={phone[:3]}****{phone[-4:]}, tenant={tenant_id}")
            return True

        if not _OTP_VALID_PATTERN.match(code or ""):
            return False

        try:
            redis_client = RedisClient()
            key = OrderCreateTool._otp_key(phone, tenant_id)
            stored_code = await redis_client.get(key)

            if stored_code and stored_code.strip() == code.strip():
                # 验证成功后删除，防止重复使用
                await redis_client.delete(key)
                logger.info(f"[sms_verify] Code verified: phone={phone[:3]}****{phone[-4:]}, tenant={tenant_id}")
                return True

            logger.warning(f"[sms_verify] Code mismatch: phone={phone[:3]}****{phone[-4:]}, tenant={tenant_id}")
            return False
        except Exception as e:
            logger.error(f"[sms_verify] Redis error: {type(e).__name__}: {e}", exc_info=True)
            return False

    @staticmethod
    async def _store_sms_code(phone: str, code: str, tenant_id: int) -> bool:
        """存储短信验证码到 Redis

        由 SMS 发送工具调用，存储生成的验证码。

        Args:
            phone: 客户手机号
            code: 生成的验证码
            tenant_id: 租户ID

        Returns:
            bool: 存储是否成功
        """
        try:
            redis_client = RedisClient()
            key = OrderCreateTool._otp_key(phone, tenant_id)
            await redis_client.set(key, code, ttl=_OTP_TTL_SECONDS)
            logger.info(f"[sms_store] Code stored: phone={phone[:3]}****{phone[-4:]}, tenant={tenant_id}")
            return True
        except Exception as e:
            logger.error(f"[sms_store] Redis error: {type(e).__name__}: {e}", exc_info=True)
            return False

    def _needs_sms_verification(self, context: ToolContext) -> bool:
        """判断是否需要 SMS 验证

        只有 customer 角色需要短信验证。
        admin/agent/tenant_admin 帮客户下单时跳过。
        """
        return context.role == "customer"

    async def execute(
        self,
        context: ToolContext,
        customer_name: str,
        customer_phone: str,
        items: List[Dict[str, Any]],
        sms_code: Optional[str] = None,
        customer_address: Optional[str] = None,
        remark: Optional[str] = None,
    ) -> ToolResult:
        """执行创建订单操作

        Args:
            context: Tool 执行上下文
            customer_name: 客户姓名
            customer_phone: 客户电话
            items: 商品明细列表
            sms_code: 短信验证码（customer角色必填）
            customer_address: 客户收货地址（可选）
            remark: 订单备注（可选）

        Returns:
            ToolResult: 创建结果
        """
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限创建订单",
                suggestion="请联系管理员获取订单创建权限",
            )

        # 参数校验
        if not customer_name:
            return ToolResult(
                success=False,
                error="缺少客户姓名",
                message="创建订单时必须提供客户姓名（customer_name）",
                suggestion="请提供客户的姓名",
            )

        if not customer_phone:
            return ToolResult(
                success=False,
                error="缺少客户电话",
                message="创建订单时必须提供客户电话（customer_phone）",
                suggestion="请提供客户的联系电话",
            )

        # 对抗编程：校验手机号格式，防止 LLM 编造号码
        if not _PHONE_PATTERN.match(customer_phone.strip()):
            return ToolResult(
                success=False,
                error="手机号格式无效",
                message=f"手机号 {customer_phone} 格式不正确，请输入 11 位中国大陆手机号",
                suggestion="请确认客户手机号是否正确",
            )

        if not items or not isinstance(items, list):
            return ToolResult(
                success=False,
                error="缺少商品明细",
                message="创建订单时必须提供商品明细列表（items）",
                suggestion="请提供至少一件商品的信息（名称、数量、单价）",
            )

        # 校验每个商品项
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                return ToolResult(
                    success=False,
                    error=f"商品明细第 {i + 1} 项格式错误",
                    message=f"商品明细第 {i + 1} 项必须是对象，包含 product_name、quantity、unit_price、subtotal",
                )
            required_fields = ["product_name", "quantity", "unit_price", "subtotal"]
            for field in required_fields:
                if field not in item or item[field] is None:
                    return ToolResult(
                        success=False,
                        error=f"商品明细第 {i + 1} 项缺少 {field}",
                        message=f"商品明细第 {i + 1} 项缺少必填字段：{field}",
                    )
            # 数值语义闸门（issue #3586）：数量/单价/小计的正负与量级 —— 在发 HTTP 之前拒绝。
            # 负数量会算出负金额落库（下游 createOrder 不做正负判断、Agent 路径 DTO 无 Bean Validation），
            # 库存校验也会被负需求绕过；0 数量则产出 0 元明细。fail-fast 且给可行动 suggestion。
            _bounds_reject = self._validate_item_value_bounds(i, item)
            if _bounds_reject is not None:
                return _bounds_reject

        # Gap-1 安全加固: SMS 验证码校验（仅 customer 角色需要）。
        # ⚠️ 顺序铁律（issue #3586）：纯本地的**确定性**校验（明细格式/数量/金额）必须排在
        # SMS 之前 —— 前者零成本零副作用，后者要读 Redis；参数本身就非法时不该先产生
        # 一次验证码往返（也不该因为「验证码错误」掩盖真正的参数错误）。
        if self._needs_sms_verification(context):
            if not sms_code:
                return ToolResult(
                    success=False,
                    error="缺少短信验证码",
                    message="为了您的账户安全，创建订单前需要验证手机号。请输入短信验证码",
                    suggestion="请先请求发送短信验证码到您的手机，然后提供收到的验证码",
                )
            if not _OTP_VALID_PATTERN.match(sms_code):
                return ToolResult(
                    success=False,
                    error="验证码格式无效",
                    message="短信验证码为4-6位数字，请检查后重新输入",
                    suggestion="请输入您收到的4-6位数字验证码",
                )
            verified = await self._verify_sms_code(
                phone=customer_phone,
                code=sms_code,
                tenant_id=context.tenant_id,
            )
            if not verified:
                return ToolResult(
                    success=False,
                    error="验证码错误或已过期",
                    message="短信验证码错误或已过期，请重新获取验证码",
                    suggestion="请重新请求发送短信验证码，并在5分钟内完成验证",
                )

        # ── 同一张单里出现**完全相同的商品行** → fail-closed（issue #3392，DB 实证）──
        # 实证（run 34747025719）：新客用例 OR-022 期望 3 米（168×3 + 打孔 8×3 = ¥528），
        # 落库却是 ¥1584（9×168 + 9×8）与 ¥1056（6×168 + 6×8）—— 数量按**确认轮次累加**
        # （3 → 6 → 9，即 3 的倍数），顾客会被多收 2~3 倍的钱，且全链路无告警。
        # 判据取"**完全相同的行**"（名称/单价/小计/规格字段逐一相等）：正常订单里同商品
        # 不同规格（颜色/门幅）会有区分字段，完全重复只可能是重复提交/累加。
        # 为什么在工具层拦：这是**钱的正确性**，不能指望模型自己发现；拦下并明确告诉它
        # "合并成一行、数量取合计"，模型下一轮即可自愈（比静默多收钱好得多）。
        _dup_key_seen: Dict[str, int] = {}
        for _i, _it in enumerate(items):
            if not isinstance(_it, dict):
                continue
            _sig = json.dumps({
                "name": str(_it.get("product_name") or ""),
                "unit_price": str(_it.get("unit_price")),
                "subtotal": str(_it.get("subtotal")),
                "product_id": str(_it.get("product_id") or ""),
                "width": str(_it.get("width") or ""),
                "height": str(_it.get("height") or ""),
                "processing_info": json.dumps(_it.get("processing_info"), ensure_ascii=False,
                                              sort_keys=True, default=str),
            }, ensure_ascii=False, sort_keys=True)
            if _sig in _dup_key_seen:
                _first = _dup_key_seen[_sig] + 1
                return ToolResult(
                    success=False,
                    error="商品明细存在重复行",
                    message=(
                        f"商品明细第 {_i + 1} 项与第 {_first} 项**完全相同**"
                        f"（{_it.get('product_name')} ×{_it.get('quantity')}，"
                        f"单价 {_it.get('unit_price')}）—— 同一张订单里不应出现完全相同的两行，"
                        f"否则顾客会被**重复计费**。"
                        f"请把数量合并成**一行**（该行 quantity = 各行数量之和）后重新提交。"
                    ),
                    suggestion=("合并重复行：同一商品/规格只保留一行，数量取合计；"
                                "例如 3 米不要写成三行各 1 米或三行各 3 米"),
                )
            _dup_key_seen[_sig] = _i

        try:
            # 构建请求体（admin-api 使用 camelCase）
            # 对抗编程：透传 LLM 提供的所有字段，避免静默丢弃 productId/width/height/processingInfo
            items_payload = []
            for item in items:
                # 数值已在上方 _validate_item_value_bounds 校验（正整数/非负金额），
                # 这里用解析值而非裸 int()/float() —— 让 "3米" 这类带单位输入落成 3，
                # 避免 int("3米") 抛 ValueError 走异常兜底（错误提示不可行动）。
                entry: Dict[str, Any] = {
                    "productName": item["product_name"],
                    "quantity": int(self._parse_positive_number(item["quantity"])),
                    "unitPrice": self._parse_positive_number(item["unit_price"]),
                    "subtotal": self._parse_positive_number(item["subtotal"]),
                }
                # 透传可选字段 — 不信任 LLM 一定传，但传了就不能丢
                for py_key, java_key in [
                    ("product_id", "productId"),
                    ("width", "width"),
                    ("height", "height"),
                    ("processing_info", "processingInfo"),
                ]:
                    value = item.get(py_key)
                    if value is None:
                        continue
                    # 尺寸已在 _validate_item_value_bounds 里按「容忍单位」的口径解析过：
                    # 这里发**数值**（"2.8米" → 2.8），否则 Java BigDecimal 解析失败 → 白跑一轮 HTTP。
                    if py_key in ("width", "height"):
                        value = self._parse_positive_number(value)
                    entry[java_key] = value
                items_payload.append(entry)

            json_data: Dict[str, Any] = {
                "customerName": customer_name,
                "customerPhone": customer_phone,
                "items": items_payload,
            }

            if customer_address:
                json_data["customerAddress"] = customer_address
            if remark:
                json_data["remark"] = remark

            logger.info(
                f"[order-create] Creating order: customer={customer_name}, "
                f"items_count={len(items)} | tenant={context.tenant_id}"
            )

            client = get_admin_api_client()
            response = await client.post(
                "/api/admin/agent/orders",
                json_data=json_data,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )

            if not response.get("success"):
                error_msg = response.get("error", {}).get("message", "创建失败")
                return ToolResult(
                    success=False,
                    error=error_msg,
                    message=f"创建订单失败：{error_msg}",
                )

            order_data = response.get("data", {})
            order_id = order_data.get("id") or order_data.get("orderNo") or ""

            logger.info(
                f"Order created: order_id={order_id}, customer={customer_name}, "
                f"items_count={len(items)} | tenant={context.tenant_id}, user={context.user_id}"
            )

            return ToolResult(
                success=True,
                data=order_data,
                message=f"订单创建成功！订单号：{order_id}，客户：{customer_name}，共 {len(items)} 件商品",
                summary=f"订单创建成功: 订单号{order_id}, 客户{customer_name}, {len(items)}件商品",
                # T2 事务终态：下单完成 → 清空订单域草稿/待确认状态（防下一轮污染）
                terminal=True,
            )

        except Exception as e:
            logger.error(
                f"[order-create] Failed: customer={customer_name}, "
                f"error={type(e).__name__}: {e}"
            )
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="创建订单失败，请稍后重试",
                suggestion="请检查商品信息和客户信息是否完整，确认后重试",
            )
