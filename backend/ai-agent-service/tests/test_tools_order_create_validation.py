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

class TestOrderCreateProcessingFeeGateRemoved:
    """加工费一致性兜底**已随 issue #4882 删除**（原 issue #3521 的确定性闸门）。

    为什么删：该闸门的判据是 `processingFee == Σ(processingItems[i].unitPrice × quantity)`，
    而 `unitPrice` 随 #4882 从加工项明细整体删除 ⇒ 明细里再没有可相乘的单价，
    判据**已无从计算**（留着只会空转成假绿：`detail_ok=False` 静默跳过 = 看着有门禁其实没有）。
    加工费与订单金额的核对改由服务端口径 + `amount_verify` 承担。

    红证：① 若有人把 `unitPrice × quantity` 算式闸门加回 validate_input，第一条必红；
    ② 若有人留着「已删字段」的校验残留（拿不存在的键判缺参），第二条必红。
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

    def test_gate_has_no_unit_price_formula_check(self):
        """validate_input 的**代码**里不得再有 Σ(processingItems[].unitPrice × quantity) 判据。

        只扫代码行（注释里保留「已删」的沿革说明是允许且必要的 —— R5：禁止静默移除）。
        """
        import inspect as _inspect

        from app.tools import validate_input as vi

        src = _inspect.getsource(vi)
        code = "\n".join(l for l in src.split("\n") if not l.lstrip().startswith("#"))
        assert "unitPrice" not in code, "已删字段 unitPrice 又出现在闸门代码里（issue #4882）"
        assert "Σ加工项" not in code, "加工费一致性（Σ 明细）判据又回来了 —— 该算式已无从计算"

    async def test_new_shape_processing_items_pass(self, tool, admin_tool_context):
        """新形态明细 `{id, name, quantity}`（数量 = 面料米数）必须放行，不得被残留校验误伤。"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="order_create",
            target_action="create",
            params=self._params(24.0, [
                {"id": "pi-punch", "name": "打孔", "quantity": 3, "unit": "米"},
            ]),
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
