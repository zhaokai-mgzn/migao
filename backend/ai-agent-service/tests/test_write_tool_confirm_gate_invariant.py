"""写工具确认门禁「显式表态」不变式 — L0 静态防线（零 LLM，秒级）

背景（issue #3594，用户原则 2026-09-14）：
    「我的要求是写操作应该是安全的，我们在 admin-api 层面做了限制，
      我希望交互形态是统一的。」

缺陷形态：`base_skill._requires_confirmation` 只在
`destructive=True` 或 `requires_confirmation=True` 时要求确认 —— 于是
`read_only=False` 但两项均 False 的写工具**完全不经代码层门禁**，
只靠 prompt 文本铁律（间接提示注入面，审计 07 P0-L1）。
实测踩到两处：`processing_order_generate`（批量建加工单 + 订单 confirmed→producing）
与 `human_handoff`（非幂等：建工单 + 通知管理员 + 建人工会话）。

本文件的不变式（本 issue 的核心防线，§16.1 L0）：
    **每个 `read_only=False` 的工具必须显式表态** ——
      ① 要么 `destructive=True` / `requires_confirmation=True`（走确认门禁）；
      ② 要么**显式登记**在 `CONFIRM_GATE_EXEMPT_WRITE_TOOLS` 且**带理由**。
    未表态即红。这样下一个新写工具落地时会被**强制表态**，
    而不是默认落进「无门禁」的静默状态（这正是 human_handoff 的成因）。

判定原则（按用户要求推导）：
    凡产生不可忽略业务副作用（创建工单/订单/加工单、发送通知、改状态、动资金）
    → 必须有确认门禁；纯查询不算；由**已确认流程派生**的内部动作可豁免，
    但豁免必须写明理由（不得靠"恰好没被枚举到"）。
"""
# case_ids: CH-015, CH-019, DF-008, PG-013

import re

from app.tools.registry import get_tool_registry

# ──────────────────────────────────────────────────────────────────────────────
# 显式豁免清单：read_only=False 但豁免「工具层确认门禁」的写工具。
#
# 契约（由本文件的测试强制）：
#   1. 每条 key 之后必须带**非空理由**，且理由需**引用证据锚点**
#      （issue 号 `#NNNN` 或用例 ID `XX-999`）—— 防豁免清单退化成垃圾场；
#   2. key 必须是注册表里真实存在的 `read_only=False` 工具（防陈旧/拼写错误）；
#   3. 被豁免的工具**不得**同时标记 `destructive`/`requires_confirmation`
#      （自相矛盾 = 该删豁免项，红）。
# ──────────────────────────────────────────────────────────────────────────────
CONFIRM_GATE_EXEMPT_WRITE_TOOLS: dict[str, str] = {
    "human_handoff": (
        "确认发生在**上游流程**，不在工具层：C 端「转人工」有三条入口，"
        "其中两条由用户自己的消息构成确认（D1 显式请求词命中 → intent_router 短路直转 "
        "complaint；D2 商家 autoHandoffKeywords 命中 → 直转），第三条 D3（AI 主动建议）"
        "由 handoff_offer 节点**先发建议卡、用户点卡确认后**才进入本工具 —— "
        "三条路径都不存在「未确认即转人工」。在工具层再加一道确认 = 对已经确认过的动作"
        "重复确认，且直接破坏用例锁定的语义：CH-008（转人工创建人工会话）/ CH-015"
        "（显式『转人工』不经建议卡片直接转）/ UI-010 / ST-008。"
        "该豁免是既有产品决策而非本次新开：docs/design/xiaobu-ai-handoff-guidance.md"
        "（第 25/64/244/264 行）明文记载「D1/D2 直转是产品共识…再加确认是负体验」"
        "并将 `requires_confirmation=True` 列为「会改变 CH-008 语义，须单独评审」。"
        "残留风险（已登记，见 #3594）：本工具 idempotent=False，重复调用会产生重复"
        "投诉工单 + 重复管理员通知 —— 该风险的正确收敛点在幂等/去重（admin-api 或"
        "会话级一次性守卫），不能靠工具层确认门禁（那会牺牲 CH-008/CH-015 语义）。"
    ),
}

# 理由必须引用的证据锚点：issue 号（#3594）或用例 ID（CH-015 / PG-013）
_EVIDENCE_ANCHOR_RE = re.compile(r"#\d+|[A-Z]{2}-\d{3}")
_MIN_REASON_LEN = 30


def _write_tools():
    """注册表中所有写工具（read_only=False）。"""
    return [
        tool
        for tool in get_tool_registry().get_all_tools()
        if not getattr(tool, "read_only", True)
    ]


def _is_gated(tool) -> bool:
    """工具是否自带确认门禁标记（`_requires_confirmation` 的判据）。"""
    return bool(
        getattr(tool, "destructive", False)
        or getattr(tool, "requires_confirmation", False)
    )


class TestEveryWriteToolDeclaresStance:
    """核心不变式：写工具必须显式表态（门禁 or 带理由的豁免），未表态即红。"""

    def test_registry_has_write_tools(self):
        """防空转：注册表里必须有写工具，否则后续断言失去判别力。"""
        write_tools = _write_tools()
        assert write_tools, "注册表中没有任何 read_only=False 的工具 —— 不变式会空转假绿"

    def test_every_write_tool_declares_confirm_gate_stance(self):
        """每个写工具要么带门禁标记，要么在豁免清单里，否则红。

        红时的报错就是**待表态任务书**：新写工具落地未表态 → 本用例列出它，
        迫使作者在「加门禁」与「登记豁免理由」之间二选一（而非默认无门禁）。
        """
        undeclared = [
            f"{tool.name}(idempotent={getattr(tool, 'idempotent', None)}, "
            f"destructive={getattr(tool, 'destructive', None)}, "
            f"requires_confirmation={getattr(tool, 'requires_confirmation', None)})"
            for tool in _write_tools()
            if not _is_gated(tool)
            and tool.name not in CONFIRM_GATE_EXEMPT_WRITE_TOOLS
        ]
        assert not undeclared, (
            "以下 write 工具（read_only=False）**未对确认门禁表态** —— "
            "既没标 destructive/requires_confirmation，也不在 CONFIRM_GATE_EXEMPT_WRITE_TOOLS：\n  "
            + "\n  ".join(undeclared)
            + "\n处置（二选一，禁止默认无门禁）：\n"
            "  ① 有不可忽略业务副作用（创建工单/订单/加工单、发通知、改状态、动资金）"
            "→ 标 destructive=True 或 requires_confirmation=True；\n"
            "  ② 确认已在上游流程完成（如用户显式请求 / 已点确认卡）→ 在 "
            "CONFIRM_GATE_EXEMPT_WRITE_TOOLS 登记并写明理由 + 证据锚点（issue/用例 ID）。"
        )

    def test_declared_stance_reaches_the_confirm_guard(self):
        """表态必须真的生效：门禁实测结果 == 声明的表态（防"标了却没接上"）。

        等价断言：`_requires_confirmation(tool, {}, 非确认消息)` 当且仅当工具带门禁标记
        时为 True。既证明门禁真的读这两个字段，也让豁免项的**行为含义**被锁死
        （豁免 = 该工具在未确认时不会被拦）。
        """
        from app.graph.skills.base_skill import _requires_confirmation

        mismatches = []
        for tool in _write_tools():
            expected = _is_gated(tool)
            actual = _requires_confirmation(tool, {}, "帮我处理一下这个订单")
            if actual != expected:
                mismatches.append(
                    f"{tool.name}: 声明需确认={expected}，门禁实测={actual}"
                )
        assert not mismatches, (
            "写工具的确认表态与代码层门禁不一致（元数据没接上守卫）：\n  "
            + "\n  ".join(mismatches)
        )


class TestExemptionListHygiene:
    """豁免清单卫生：每条带理由 + 引用证据，且不陈旧、不自相矛盾。"""

    def test_every_exemption_has_reason_with_evidence_anchor(self):
        problems = []
        for name, reason in CONFIRM_GATE_EXEMPT_WRITE_TOOLS.items():
            text = (reason or "").strip()
            if not text:
                problems.append(f"{name}: 缺 reason（豁免必须写明理由，禁止裸登记）")
            elif len(text) < _MIN_REASON_LEN:
                problems.append(
                    f"{name}: reason 过短（{len(text)} < {_MIN_REASON_LEN} 字），"
                    f"不足以说明豁免依据"
                )
            elif not _EVIDENCE_ANCHOR_RE.search(text):
                problems.append(
                    f"{name}: reason 未引用证据锚点（issue #NNNN 或用例 ID XX-999）—— "
                    f"豁免理由必须可追溯"
                )
        assert not problems, "豁免清单不达标：\n  " + "\n  ".join(problems)

    def test_every_exemption_is_a_live_ungated_write_tool(self):
        """豁免项必须真实存在、是写工具、且确实未带门禁（防陈旧/自相矛盾）。"""
        registry = get_tool_registry()
        problems = []
        for name in CONFIRM_GATE_EXEMPT_WRITE_TOOLS:
            tool = registry.get_tool(name)
            if tool is None:
                problems.append(f"{name}: 不在注册表中（陈旧条目或拼写错误）")
                continue
            if getattr(tool, "read_only", True):
                problems.append(f"{name}: 是只读工具，豁免无意义（应删除该条）")
                continue
            if _is_gated(tool):
                problems.append(
                    f"{name}: 已带确认门禁（destructive/requires_confirmation=True），"
                    f"豁免条目应删除"
                )
        assert not problems, (
            "豁免清单存在陈旧/自相矛盾条目：\n  " + "\n  ".join(problems)
        )
