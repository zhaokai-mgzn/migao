"""order_create 写操作前置校验 — L2 单测（issue #3029 复盘回归防线）

背景：_VALIDATION_RULES["order_create"] 曾为平铺结构（{required, ...}），
而 execute 按 tool_rules.get(target_action) 分层读取（取 ["create"]）→ 恒为 None
→ 永远走「无需校验（该操作无预定义规则）」跳过，手机号/必填报错全空转
（线上会话 sess_7f27137647e14b1e A5 轮实证）。
修复为 {create: {...}} 分层（与 product_manage/aftersale_create 对齐）后，
以下用例必须全部通过。
"""
# case_ids: OR-015, CH-010
import pytest
from app.tools.validate_input import ValidateInputTool


@pytest.fixture
def tool():
    return ValidateInputTool()


class TestOrderCreateValidation:
    async def test_valid_params_passes(self, tool, admin_tool_context):
        """合法参数（客户/11位手机号/商品明细）→ 校验通过"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="order_create",
            target_action="create",
            params={
                "customer_name": "张三",
                "customer_phone": "13800138000",
                "items": [{"product_id": "p1", "quantity": 3}],
            },
        )
        assert result.success is True
        assert result.data["validated"] is True

    async def test_missing_required_fails(self, tool, admin_tool_context):
        """缺 customer_name → 校验失败并列出缺失字段（不允许跳过）"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="order_create",
            target_action="create",
            params={
                "customer_phone": "13800138000",
                "items": [{"product_id": "p1", "quantity": 3}],
            },
        )
        assert result.success is False
        assert "客户姓名" in result.message
        assert "缺少必填字段" in result.message

    async def test_missing_items_fails(self, tool, admin_tool_context):
        """缺 items → 校验失败"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="order_create",
            target_action="create",
            params={
                "customer_name": "张三",
                "customer_phone": "13800138000",
            },
        )
        assert result.success is False
        assert "商品明细" in result.message

    async def test_invalid_phone_fails(self, tool, admin_tool_context):
        """手机号非 11 位 → 校验失败并提示格式（防 LLM 编造号码）"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="order_create",
            target_action="create",
            params={
                "customer_name": "张三",
                "customer_phone": "12345",
                "items": [{"product_id": "p1", "quantity": 3}],
            },
        )
        assert result.success is False
        assert "11 位" in result.message

    async def test_missing_phone_fails(self, tool, admin_tool_context):
        """缺 customer_phone → 必填报错"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="order_create",
            target_action="create",
            params={
                "customer_name": "张三",
                "items": [{"product_id": "p1", "quantity": 3}],
            },
        )
        assert result.success is False

    async def test_never_skips_validation(self, tool, admin_tool_context):
        """回归防线：order_create/create 绝不返回「无需校验」跳过分支"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="order_create",
            target_action="create",
            params={
                "customer_name": "张三",
                "customer_phone": "13800138000",
                "items": [{"product_id": "p1", "quantity": 3}],
            },
        )
        assert result.data.get("skipped") is not True

class TestOrderCreateProcessingFeeConsistency:
    """加工费必须与明细自洽 —— 确定性闸门（issue #3521）。

    为什么必须拦在**发确认卡之前**：确认卡上的金额由模型按自己声明的
    `processingFee` 渲染，而落库金额由服务端按 `Σ processingItems.unitPrice × quantity`
    重算（`OrderService.sumProcessingFee()`，`processingFee` 字段不参与）。两者不一致时
    顾客看到的总额 ≠ 实际收款金额 —— 这是钱的问题，且 prompt 写了规则也会被 LLM 方差漏掉
    （与 #3052 建品兜底同一理由：**validate_input 必须是确定性闸门**）。

    实证（CH-010 首跑签名）：
        amount_verify[order_create](R8): 总额 311.4 ≠ Σ小计71.4+加工费252.0=323.4
      落库 311.4 = 71.4（3×23.8）+ 240（明细 30×8）；
      而声明的 processingFee = 252（把按面积的项另算成 30×8.4）→ 差 12 元。
    """

    def _params(self, fee, items):
        return {
            "customer_name": "张三",
            "customer_phone": "13800138000",
            "items": [{
                "product_name": "北欧风窗帘", "quantity": 3, "unit_price": 128.0,
                "subtotal": 384.0,
                "processing_info": {"processingFee": fee, "processingItems": items},
            }],
        }

    async def test_inconsistent_fee_is_blocked(self, tool, admin_tool_context):
        """#3521 实况：明细 30×8=240，却声明 252 → 必须拦下并告知应改成 240"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="order_create",
            target_action="create",
            params=self._params(252.0, [{"name": "刺绣工艺", "unitPrice": 30, "quantity": 8}]),
        )
        assert result.success is False, "声明 252 而明细 240（差 12 元）必须拦住"
        msg = result.message or ""
        assert "252" in msg and "240" in msg, f"必须点明两个数字与应改的值: {msg}"
        assert "processingFee" in msg, f"必须点名出问题的字段: {msg}"

    async def test_consistent_fee_passes(self, tool, admin_tool_context):
        """声明值与明细一致（24 = 8×3）→ 通过"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="order_create",
            target_action="create",
            params=self._params(24.0, [{"name": "纳米圈打孔", "unitPrice": 8, "quantity": 3}]),
        )
        assert result.success is True, result.message

    async def test_multi_item_fee_sum_passes(self, tool, admin_tool_context):
        """多项明细：合计 == Σ 各项 → 通过（不因多项误判）"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="order_create",
            target_action="create",
            params=self._params(54.0, [
                {"name": "打孔", "unitPrice": 8, "quantity": 3},
                {"name": "定型", "unitPrice": 10, "quantity": 3},
            ]),
        )
        assert result.success is True, result.message

    async def test_no_items_detail_is_not_blocked(self, tool, admin_tool_context):
        """老形态（只写 processingFee、无 processingItems 明细）不拦 —— 避免误伤"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="order_create",
            target_action="create",
            params=self._params(24.0, []),
        )
        assert result.success is True, result.message

    async def test_plain_order_without_processing_passes(self, tool, admin_tool_context):
        """无加工项的普通订单不受影响"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="order_create",
            target_action="create",
            params={
                "customer_name": "张三",
                "customer_phone": "13800138000",
                "items": [{"product_name": "北欧风窗帘", "quantity": 3, "unit_price": 128.0}],
            },
        )
        assert result.success is True, result.message
