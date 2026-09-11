"""
C 端小布下单「加工项」环节契约（issue #3270 / #3266 实测缺口）。

背景（2026-09-11 实测）：
- `order_create` 工具**已支持** `processing_info.processingItems` / `processingFee`
  （app/tools/order_create.py:125-150），B 端 `EXAMPLES-order.md` 有 7 处加工项规则；
- 但 C 端 `customer_order_skill.py` 的 `CUSTOMER_ORDER_SYSTEM_PROMPT`
  **`grep 加工项` 零命中** → 小布下单链路没有「询问加工项 / 计加工费」环节。

用户可见后果：顾客买需要加工的商品（打孔/高温定型等）时，
- 加工项从不被询问（顾客不知道能选，也不知道要加钱）；
- 若顾客主动提「要打孔加工」，加工费不进订单金额 → 报价与实际应付款不符。

B 端同款缺陷曾在 2026-09-08 被复盘（issue #3033，case OR-016：
"A5 confirm 卡在加工项询问前弹出、金额 ¥238 不含加工费"），修复方式是
**order.md 加工项段从被动式改主动式 + EXAMPLES 例 2 补加工项环节**。
C 端一直没跟。

本测试锁定 C 端 prompt 的加工项契约——删规则即 fail，防重构回退。
"""
# case_ids: OR-016, CH-010, PR-019
import pytest

from app.graph.skills.customer_order_skill import CUSTOMER_ORDER_SYSTEM_PROMPT
from app.tools.order_create import OrderCreateTool


class TestCustomerOrderProcessingItemRule:
    """小布下单 prompt 必须含主动询问加工项 + 加工费计入的规则"""

    def test_prompt_mentions_processing_item(self):
        """prompt 必须出现「加工项」——这是缺失能力的直接信号"""
        assert "加工项" in CUSTOMER_ORDER_SYSTEM_PROMPT, (
            "C 端下单 prompt 完全未提加工项 —— 小布无法引导顾客选加工项"
        )

    def test_rule_is_proactive_before_confirm(self):
        """必须要求「confirm 之前主动询问」，而非被动等顾客提（B 端 #3033 同款修复）"""
        p = CUSTOMER_ORDER_SYSTEM_PROMPT
        assert "confirm" in p.lower(), "未提及 confirm 环节"
        # 主动式：明确顺序约束
        assert ("之前" in p or "前" in p), "未声明加工项询问与 confirm 的先后关系"
        assert ("主动" in p or "必须" in p), "未强调主动询问（防退回被动式）"

    def test_rule_covers_interact_choice_multi_select(self):
        """询问方式须用交互卡（小布 C 端点选友好），与 B 端一致"""
        p = CUSTOMER_ORDER_SYSTEM_PROMPT
        assert "interact" in p, "未要求用 interact 组件询问加工项"
        assert "choice" in p, "加工项询问未指定 choice 组件"
        assert "multiSelect" in p or "multi" in p.lower(), (
            "未要求多选（加工项可多选，如打孔+高温定型）"
        )

    def test_rule_carries_processing_items_and_fee_to_order_create(self):
        """须声明把选定加工项与加工费传入 order_create（否则金额不含加工费）"""
        p = CUSTOMER_ORDER_SYSTEM_PROMPT
        assert "processingItems" in p, "未声明 processingItems 落参"
        assert "processingFee" in p, "未声明 processingFee 落参"

    def test_rule_handles_empty_processing_items(self):
        """商品无加工项时须如实告知后继续（不卡死流程）"""
        p = CUSTOMER_ORDER_SYSTEM_PROMPT
        assert ("无可用加工项" in p or "无加工项" in p or "没有加工项" in p), (
            "未定义「商品无加工项」分支 —— 会导致流程卡住或编造加工项"
        )

    def test_rule_handles_skip(self):
        """顾客说不需要时须可跳过（不强制加购）"""
        p = CUSTOMER_ORDER_SYSTEM_PROMPT
        assert ("不需要" in p or "跳过" in p), "未定义「顾客不需要加工项」分支"

    def test_processing_fee_counted_into_subtotal(self):
        """加工费必须计入金额（防报价与应付款不符）"""
        p = CUSTOMER_ORDER_SYSTEM_PROMPT
        assert ("计入" in p or "合计" in p or "subtotal" in p), (
            "未声明加工费计入订单金额"
        )


class TestOrderCreateToolSupportsCustomerProcessing:
    """前提核实：order_create 工具侧确实支持 processingItems（缺口纯在 prompt）"""

    def test_tool_schema_has_processing_items(self):
        tool = OrderCreateTool()
        item_props = tool.parameters["properties"]["items"]["items"]["properties"]
        assert "processing_info" in item_props, (
            "order_create 不支持 processing_info —— 则 C 端加工项能力还缺工具侧改造"
        )
        pi = item_props["processing_info"]["properties"]
        assert "processingItems" in pi
        assert "processingFee" in pi


class TestCustomerOrderPromptGrowthGuard:
    """C 端下单 prompt 长度快照（防无限制膨胀；B 端已有同类守卫）"""

    # 本次加工项规则落地后 2382；给 +30% 余量（B 端 order prompt 上限 10000）
    MAX_LEN = 3200

    def test_prompt_length_within_budget(self):
        n = len(CUSTOMER_ORDER_SYSTEM_PROMPT)
        assert n <= self.MAX_LEN, (
            f"C 端下单 prompt 长度 {n} > 上限 {self.MAX_LEN} —— 新内容需精简，"
            f"或明确上调上限并说明理由（当前 {n}/{self.MAX_LEN}）"
        )

    def test_prompt_not_accidentally_truncated(self):
        n = len(CUSTOMER_ORDER_SYSTEM_PROMPT)
        assert n >= 2000, (
            f"C 端下单 prompt 仅 {n} 字符 —— 疑似规则被误删（收货/确认/验证码/加工项等环节）"
        )


class TestProductDetailIronRule:
    """confirm 之前必须先调 product_detail（issue #3270 实测）。

    实测（2026-09-11，本地 DEBUG 栈 + 真实 LLM）：
    顾客说「我想买夏日清风窗帘，3米，门幅2.8米散剪」时 agent 只调了 product_search
    → 直接问颜色 → 下一步就发 confirm 卡，**全程没调 product_detail**。
    product_search 的列表数据**不含** processing_items / colorId / skus，
    于是 agent 向顾客断言「这款商品暂未查询到可选加工项」（该商品实际有 2 个加工项：
    纳米圈打孔 ¥8/米、韩式波浪折边 ¥12/米）→ 顾客永远选不到加工项，加工费也进不了单。

    单独加「要问加工项」不够 —— 必须先强制拿到详情，否则规则没有数据可依据。
    """

    def test_prompt_requires_product_detail_before_confirm(self):
        p = CUSTOMER_ORDER_SYSTEM_PROMPT
        assert "product_detail" in p, "prompt 未提及 product_detail"
        assert "铁律" in p, "未把「confirm 前必调 product_detail」强调为铁律"

    def test_prompt_states_list_lacks_processing_items(self):
        """必须说明「列表数据不含加工项/颜色ID」，否则模型仍会凭列表下结论"""
        p = CUSTOMER_ORDER_SYSTEM_PROMPT
        assert "product_search" in p and "不含" in p, (
            "未说明 product_search 列表缺少 processing_info 必需字段"
        )
        assert "colorId" in p or "颜色 ID" in p or "颜色ID" in p, (
            "未点明 colorId 只在详情里"
        )

    def test_prompt_forbids_concluding_from_list(self):
        """禁止仅凭列表结果断言「无加工项」"""
        p = CUSTOMER_ORDER_SYSTEM_PROMPT
        assert "禁止" in p and "无加工项" in p, (
            "未禁止「仅凭 product_search 列表断言该商品无加工项」"
        )
