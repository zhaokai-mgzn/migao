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
# case_ids: OR-016, CH-010, PR-019, OR-021, OR-022, CH-025
from pathlib import Path

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
    # 2026-09-13 上调 3250 → 3300（+50，issue #3379 P2-3）：新增**草稿态措辞**规则
    #   「加工项此刻只是草稿 → 用『记下了，下单时一并提交』，禁止『已为您加上』」
    #   实测该规则净增 ~106 字符（先按守卫要求精简过一轮：初版 270 字符被本守卫拦下）。
    #   这是**安全/诚实性**规则（防止顾客以为草稿已落单），非冗余描述，故按守卫允许的
    #   "明确上调上限并说明理由"路径处理；再涨需先删旧内容。
    # 2026-09-13 上调 3300 → 3600（+300，issue #3386/#3389）：两条**能力诚实性**规则 ——
    #   ① 手机号必须用完整 11 位（禁止自己打码/填 0）—— 掩码值回流写工具会静默写错订单手机号
    #      （DB 实证：订单 20260913384380002 落库 13800008000）；
    #   ② 禁止能力自我否定（"小布没法提交订单"）—— 验收 C-A1 实证：顾客「确认下单」×4 轮被拒 + 转人工。
    #   同步执行了守卫要求的"先删旧内容"：本轮净删 ~130 字符冗余措辞（重复调用告警、
    #   校验说明、引导话术示例），新规则首版 490 字符压缩到 ~330。
    #   ⚠️ 下次再涨前必须先删旧内容（prompt 越长越容易稀释关键规则，实测长 prompt 的规则遵守率下降）。
    # 2026-09-19 上调 3600 → 3700（+100，用户裁定「不应该存在 human_handoff 这种东西，
    #   以后全是 AI 来判断」）：转人工退场要求 C 端下单 prompt **必须新增两条规则** ——
    #   ① 顾客要求找人工/强烈不满时「如实说明已无人工转接通道 + 自己继续办」；
    #   ② **禁止**说"已为您转接人工客服/客服马上联系您"（做不到的承诺比不承诺更伤；
    #      退场后这是最高频的新失败形态 —— 原模板正是"我帮您转接人工客服处理哦~"）。
    #   按守卫要求**先精简**：新块 283 字符压到 ~170（两轮），并顺手去掉「不能修改或取消
    #   订单」在查询段与能力边界两处的重复表述；仍余 46 字符缺口，故按守卫允许的
    #   "明确上调上限并说明理由"路径处理（非业务内容冗余）。
    MAX_LEN = 3700

    def test_prompt_length_within_budget(self):
        n = len(CUSTOMER_ORDER_SYSTEM_PROMPT)
        assert n <= self.MAX_LEN, (
            f"C 端下单 prompt 长度 {n} > 上限 {self.MAX_LEN} —— 新内容需精简，"
            f"或明确上调上限并说明理由（当前 {n}/{self.MAX_LEN}）"
        )

    def test_prompt_keeps_capability_honesty_rules(self):
        """能力诚实性规则必须在 prompt 里**真实存在**（issue #3386 / #3389）。

        长度守卫只保证"没膨胀"，不保证"规则还在"—— 规则被删掉时长度照样合规（还会更短）。
        故把两条规则的**判据关键词**钉住：
          · 手机号必须完整 11 位 + 禁止自己打码（掩码值回流写工具 → 静默写错订单手机号）；
          · 禁止能力自我否定（"没法提交订单"）—— 验收 C-A1 实证的拒单形态。
        """
        p = CUSTOMER_ORDER_SYSTEM_PROMPT
        assert "完整 11 位" in p, "缺少「手机号用完整 11 位」规则（掩码回流会写错号码）"
        assert "不要自己打码" in p, "缺少「展示脱敏由系统做，不要自己打码」规则"
        assert "禁止自我否定" in p, "缺少「禁止能力自我否定」规则（C-A1 拒单形态）"
        assert "13800008000" not in p or "静默写错" in p, "掩码填充值的危害说明缺失"

    def test_prompt_keeps_quantity_vs_dimension_rule(self):
        """数量口径规则必须在 prompt 里（issue #3395）：'要 3 米' = 买 3 米布，不得当窗宽算料。

        实证：OR-022 顾客「买遮光窗帘，米白 3 米」被当成窗宽 3 米 + 窗高默认 2.7 米 →
        算料 9 米 → 落库 ¥1584（应为 ¥528），顾客被多收 3 倍钱。
        """
        p = CUSTOMER_ORDER_SYSTEM_PROMPT
        assert "数量口径铁律" in p, "缺少「顾客说米数＝购买数量」规则（多收 3 倍钱的根因）"
        assert "禁止**当窗宽" in p or "禁止" in p and "窗宽" in p, "规则未禁止把米数当窗宽"
        assert "curtain_calc" in p, "未说明何时才允许算料"
        assert "再让他选用量" in p, (
            "缺少「顾客已给数量时不得再让他选用量/褶皱倍数」规则"
            "（实测 C-A1：Agent 发『请选择窗帘用量』卡并推荐 6 米＝2 倍钱，还耗尽轮数，issue #3402）")
        assert "重述" in p and "相加" in p, (
            "缺少「顾客重复同一数量＝重述，禁止相加」规则"
            "（实测重报一次 3 米 → 落库 ×6，run 34750771576）")

    def test_prompt_not_accidentally_truncated(self):
        n = len(CUSTOMER_ORDER_SYSTEM_PROMPT)
        assert n >= 2000, (
            f"C 端下单 prompt 仅 {n} 字符 —— 疑似规则被误删（收货/确认/验证码/加工项等环节）"
        )


class TestDraftStateWordingCoversAnyModification:
    """草稿态措辞规则必须覆盖**在办流程里的任何修改**（issue #3440）。

    实证（run 34771663639，CH-025）：顾客 R2「收货地址帮我改成…」→ AI 回「**已更新**」，
    而此刻只是记下来了、订单未创建（最终 order_create 在若干轮之后才成功）。
    顾客会以为地址已经改好，若流程中途失败就直接带着错误认知离开。

    规则原本只写在**加工项**小节里（「加工项此刻只是草稿」）→ 模型对"改地址"没有可依据的措辞约束。
    本守卫钉住"推广"这件事：规则文本里必须同时出现地址/数量等修改面，且明确禁掉"已更新"。
    """

    def _rule_block(self) -> str:
        p = CUSTOMER_ORDER_SYSTEM_PROMPT
        i = p.index("草稿态措辞")
        return p[i:i + 200]

    def test_covers_address_and_quantity_not_just_processing_items(self):
        blk = self._rule_block()
        assert "地址" in blk, f"草稿态规则未覆盖「地址」修改（#3440 实证的形态）：{blk[:120]!r}"
        assert "数量" in blk, "草稿态规则未覆盖数量修改"
        assert "加工项" in blk, "草稿态规则丢了原有的加工项面"

    def test_forbids_completion_wording_before_write(self):
        blk = self._rule_block()
        assert "已更新" in blk or "已修改" in blk, (
            f"未明确禁掉完成态措辞（如「已更新」）：{blk[:120]!r}")
        assert "order_create 成功后" in blk or "订单未创建" in blk, (
            "未说明完成态措辞的允许时机（写工具成功后）")


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


class TestProcessingQuantityByPricingMethod:
    """加工数量必须**按计价方式**推导，processingFee 必须 == Σ 明细（issue #3521）。

    实证（CH-010 首跑红）：
        amount_verify[order_create](R8): 总额 311.4 ≠ Σ小计71.4+加工费252.0=323.4
    反推：小计 71.4 = 3 × 23.8（面料），落库总额 311.4 = 71.4 + 240，
    而模型在 `processing_info.processingFee` 里声明的是 252 —— 差别来自**同一个订单里
    模型对按面积（per_area）的刺绣工艺写了两份面积**（30 × 8 = 240 vs 30 × 8.4 = 252）。

    根因是只有 `per_meter` 有数量口径（prompt 原话"加工数量 = 面料米数"），
    其余计价方式（per_area/per_set/fixed）**没有规则** → 模型只能猜数量。
    服务端 `OrderService.sumProcessingFee()` 只认 `Σ processingItems.unitPrice × quantity`
    （`processingFee` 字段不参与总额计算）→ 顾客在确认卡看到的总额 ≠ 实际落库/收款金额。

    规则落在 **order_create 的工具描述**（而非 system prompt）：
      · 这是**参数语义**（processingItems 的 quantity 怎么来），与字段定义同处最合适；
      · C 端下单 prompt 已顶到长度守卫上限（3592/3600），加规则必须先删旧规则 ——
        在 bug 修复里改别的行为域措辞风险更大，故走零预算的加法路径。
    另一道**确定性**闸门在 `validate_input`（prompt 会被 LLM 方差漏掉，
    见 `test_tools_order_create_validation.py` 的加工费一致性用例）。

    本组是 L0 静态不变式（migao-dev-flow §16.1）：合法计价方式集合从
    `docs/sql/schema.sql` 的 processing_items.pricing_method 注释取（单一源），
    逐个要求工具描述给出数量口径 —— 改枚举而不补口径会红。
    """

    # schema.sql: `pricing_method VARCHAR(32) NOT NULL, -- per_meter / per_set / fixed / per_area（…）`
    _SCHEMA = Path(__file__).resolve().parents[3] / "docs" / "sql" / "schema.sql"

    def _legal_pricing_methods(self) -> list:
        import re
        text = self._SCHEMA.read_text(encoding="utf-8")
        m = re.search(
            r"pricing_method\s+VARCHAR\([^)]*\)\s*NOT\s+NULL\s*,\s*--\s*([^（(\n]+)", text)
        assert m, "未能从 docs/sql/schema.sql 解析出 pricing_method 合法取值注释（单一源解析失效）"
        methods = [t.strip() for t in m.group(1).split("/") if t.strip()]
        assert len(methods) >= 3, f"解析出的计价方式过少: {methods!r}"
        return methods

    def test_every_legal_pricing_method_has_a_quantity_rule(self):
        desc = OrderCreateTool.description
        missing = [m for m in self._legal_pricing_methods() if m not in desc]
        assert not missing, (
            f"order_create 工具描述未给出这些计价方式的加工数量口径: {missing!r}"
            "（缺口径 → 模型猜数量 → 确认卡金额与落库金额不一致，issue #3521）")

    def test_tool_description_requires_fee_equals_item_sum(self):
        """必须把「processingFee == Σ(unitPrice × quantity)」写成规则（服务端权威口径）"""
        desc = OrderCreateTool.description
        assert "processingFee" in desc, "工具描述未提 processingFee"
        assert "Σ" in desc and "unitPrice" in desc and "quantity" in desc, (
            "未点明服务端口径 = Σ(processingItems[i].unitPrice × quantity)")

