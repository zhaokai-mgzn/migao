# case_ids: PR-010, PR-014, PR-021, PR-108
"""点卡确认轮必须给模型一条「**顾客点了卡**」的上下文事实（issue #6985，A 档涉钱写路径）。

## 病（实测，issue #6985 的两条 A 档路径；读数见 PR body）

| 路径 | 工具/动作 | 实测（修前） |
|---|---|---|
| 商品级统一定价 | `product_update` | ❌ `PR-010`：7 轮**零次写调用**、零闸门事件、价格恒 ¥168 |
| 批量库存调整 | `product_batch_update(action=execute, batch_type=inventory_stock)` | ❌ `PR-014`：只到 `preview` |
| SKU 调价 | `sku_update` | ✅ `PR-021`（对照实现） |
| 批量改价 | `product_batch_update` preview→execute | ✅ `PR-108`（对照实现） |

**断点不在闸门**（同轮另一会话有 `确认卡 confirmValue 精确匹配 → 放行写操作 product_batch_update`）——
断点在**模型侧**：模型收到「逐字等于自己刚发出的卡值」的用户消息后，把它读成**普通文本**，
对照 4 处 prompt 的绝对措辞「**商家打字「确认」不算**」（issue #5317）自造第二条判据
⇒ 判「这不是点卡」⇒ 反复重发新卡（`confirmValue` 每轮还在变）⇒ **永远走不到"点卡后再次调用写工具"**。

判据基准（`base_skill._is_card_confirm_value`）本来就是「用户消息**逐字等于**系统自产的卡值」，
而模型**看不到这个判定**：它看到的只是一条长得像文本的用户消息。本包把
「系统已判定：这是点卡回传」这条**上下文事实**在点卡轮注入给模型（修法①），
把门禁话术改成有条件（修法②），并把绝对措辞改成与判据同源的相对措辞（修法③）。

## 本文件的判据（每条都有能单独变红的红证，见 `TestRedProofs`）

- **判据 1**：点卡轮（消息逐字等于 `last_confirm_value`）⇒ 注入文本出现且**明说这是点卡**、
  给出「本轮应当调用写工具执行」与「**不得再发确认卡**」；
- **判据 2**：非点卡轮（普通文本 / 空消息 / 无卡 / 无 session / 读库异常）⇒ **一字不注入**；
- **判据 3**：注入判据与门禁**同源**（逐字匹配才注入；前缀相同不注入）；
- **判据 4**：目标工具只由**卡字段**反推（改价卡 → `product_update`；库存卡 →
  `product_batch_update`），认不出则只给事实、不猜工具名；
- **判据 5**（静态契约）：4 处涉钱口径**不得**再出现「打字『确认』不算」这类**绝对否定**措辞
  —— 它正是模型自造第二条判据的诱因；
- **判据 6**（门禁话术）：被拦话术不得再有无条件的「不要再次调用 X」，且必须写明真正判据。

## 不属本判据（如实登记）

- 「模型**真的**因此调用了写工具、价格**真的**变了」⇒ 属真实 LLM 评测
  （`migao-dev-flow` §13：默认不跑；本包在 PR body 给出四条用例的重放读数）。
- 本文件**不**测「点卡后写工具被放行」—— 那条放行链是既有机制（`confirmed_write_release`），
  既有判据在 `tests/test_price_card_only_confirm.py` / `tests/test_price_confirm_value_fact.py`。
"""

import ast
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.graph.skills.base_skill import (
    _card_click_target_tool,
    _inject_card_click_signal,
    _is_card_confirm_value,
)

REPO = Path(__file__).resolve().parents[3]
AI_AGENT = REPO / "backend/ai-agent-service"

#: 真实派生形态（`app/tools/confirm_value.py::confirm_value_for_fields`）—— 商品级改价卡
PRICE_CARD_VALUE = "确认：改后价=198 元；改前价=168 元；商品=遮光窗帘"
STOCK_CARD_VALUE = "确认：改后库存=1200 米；改前库存=500 米；商品=遮光窗帘"
PRICE_CARD = {
    "component": "confirm",
    "confirmValue": PRICE_CARD_VALUE,
    "fields": [
        {"label": "商品", "value": "遮光窗帘"},
        {"label": "改前价", "value": "168 元"},
        {"label": "改后价", "value": "198 元"},
    ],
}
STOCK_CARD = {
    "component": "confirm",
    "confirmValue": STOCK_CARD_VALUE,
    "fields": [
        {"label": "商品", "value": "遮光窗帘"},
        {"label": "改前库存", "value": "500 米"},
        {"label": "改后库存", "value": "1200 米"},
    ],
}

PROMPT = "原提示词"


def _inject(stored, last_user_msg, system_prompt=PROMPT, session_id="s1"):
    """跑一次注入，返回 (新 prompt, 落库内容)。`stored=None` = 会话状态为空。"""
    committed = {}

    async def _run():
        with patch("app.memory.session_state_store.SessionStateStore") as store_cls:
            inst = MagicMock()
            inst.load = AsyncMock(return_value=stored or {})
            inst.commit = AsyncMock(
                side_effect=lambda sid, full: committed.update(full))
            store_cls.return_value = inst
            state = {"session_id": session_id} if session_id else {}
            return await _inject_card_click_signal(system_prompt, state, last_user_msg)

    return asyncio.run(_run()), committed


class TestSignalOnCardClickRound:
    """判据 1：点卡轮必须注入「顾客点了卡」的事实 + 执行指令。"""

    def test_price_card_click_round_injects_signal(self):
        out, _ = _inject({"last_confirm_value": PRICE_CARD_VALUE, "last_card": PRICE_CARD},
                         PRICE_CARD_VALUE)
        assert out != PROMPT, "点卡轮没有注入任何上下文事实 —— 模型仍会把卡值读成普通文本"
        assert "点击" in out, "注入文本没有说明「这是顾客点击确认卡的回传」"
        assert "product_update" in out, "注入文本没有点名本轮应当执行的写工具"

    def test_signal_tells_model_not_to_resend_the_card(self):
        """重发新卡是本单实测的死循环形态（`confirmValue` 每轮还在变）⇒ 必须明说禁止。"""
        out, _ = _inject({"last_confirm_value": PRICE_CARD_VALUE, "last_card": PRICE_CARD},
                         PRICE_CARD_VALUE)
        assert "不要" in out and "确认卡" in out, "注入文本没有禁止「再发一张确认卡」"

    def test_stock_card_click_round_points_at_batch_tool(self):
        out, _ = _inject({"last_confirm_value": STOCK_CARD_VALUE, "last_card": STOCK_CARD},
                         STOCK_CARD_VALUE)
        assert "product_batch_update" in out, (
            "批量库存卡的点卡轮没有点名 product_batch_update —— PR-014 的执行段仍无依据"
        )

    def test_prompt_is_preserved(self):
        """注入是**前置**事实，不得吞掉原 prompt（模型仍需要本域规则）。"""
        out, _ = _inject({"last_confirm_value": PRICE_CARD_VALUE, "last_card": PRICE_CARD},
                         PRICE_CARD_VALUE)
        assert PROMPT in out

    def test_does_not_write_session_state(self):
        """注入是**零副作用**的读侧动作（不得借机改放行账 —— 放行链一字不动）。"""
        _, committed = _inject({"last_confirm_value": PRICE_CARD_VALUE,
                                "last_card": PRICE_CARD}, PRICE_CARD_VALUE)
        assert committed == {}, f"注入写改了会话状态：{sorted(committed)}"


class TestNoSignalOffCardClickRound:
    """判据 2：非点卡轮一字不注入（零回归面）。"""

    def test_plain_text_is_untouched(self):
        out, _ = _inject({"last_confirm_value": PRICE_CARD_VALUE, "last_card": PRICE_CARD},
                         "确认")
        assert out == PROMPT, "普通文本轮被注入 —— 会诱导模型凭打字执行涉钱写"

    def test_empty_message_is_untouched(self):
        out, _ = _inject({"last_confirm_value": PRICE_CARD_VALUE, "last_card": PRICE_CARD}, "")
        assert out == PROMPT

    def test_no_stored_card_value_is_untouched(self):
        out, _ = _inject({"last_card": PRICE_CARD}, PRICE_CARD_VALUE)
        assert out == PROMPT, "没有已发出的确认卡却注入了点卡事实"

    def test_no_session_is_untouched(self):
        out, _ = _inject({"last_confirm_value": PRICE_CARD_VALUE, "last_card": PRICE_CARD},
                         PRICE_CARD_VALUE, session_id="")
        assert out == PROMPT

    def test_store_failure_is_non_fatal(self):
        """会话存储读失败不得破坏主流程（与既有 `_inject_*` 同口径）。"""
        async def _run():
            with patch("app.memory.session_state_store.SessionStateStore") as store_cls:
                inst = MagicMock()
                inst.load = AsyncMock(side_effect=RuntimeError("boom"))
                store_cls.return_value = inst
                return await _inject_card_click_signal(
                    PROMPT, {"session_id": "s1"}, PRICE_CARD_VALUE)

        assert asyncio.run(_run()) == PROMPT


class TestJudgementIsSharedWithGate:
    """判据 3：注入判据与门禁判据**同源**（不许另立第二份「算不算点卡」的口径）。"""

    def test_prefix_is_not_a_card_click(self):
        """前缀相同 ≠ 点卡：卡值逐字相等才算（`_is_card_confirm_value` 的口径）。"""
        msg = PRICE_CARD_VALUE + "，另外再便宜点"
        out, _ = _inject({"last_confirm_value": PRICE_CARD_VALUE, "last_card": PRICE_CARD}, msg)
        assert out == PROMPT, "前缀匹配就注入了点卡事实 —— 与门禁判据不同源（门禁只放行逐字相等）"
        assert not _is_card_confirm_value(msg, PRICE_CARD_VALUE)

    def test_trailing_whitespace_is_a_card_click(self):
        """两侧 strip 后相等即点卡（与门禁逐字同源：`_is_card_confirm_value` 也 strip）。"""
        out, _ = _inject({"last_confirm_value": PRICE_CARD_VALUE, "last_card": PRICE_CARD},
                         f"  {PRICE_CARD_VALUE}  ")
        assert out != PROMPT
        assert _is_card_confirm_value(f"  {PRICE_CARD_VALUE}  ", PRICE_CARD_VALUE)


class TestTargetToolComesFromCardContent:
    """判据 4：目标工具只由**卡字段**反推；工具名不得脱离卡内容凭空出现。"""

    def test_price_card_fields(self):
        assert _card_click_target_tool(PRICE_CARD) == "product_update"

    def test_stock_card_fields(self):
        assert _card_click_target_tool(STOCK_CARD) == "product_batch_update"

    def test_unknown_card_degrades_to_no_tool_name(self):
        """认不出目标时**只**给事实、不猜工具名（否则会诱导模型调用错工具）。"""
        unknown = {"component": "confirm", "confirmValue": "确认：商品=遮光窗帘",
                   "fields": [{"label": "商品", "value": "遮光窗帘"}]}
        assert _card_click_target_tool(unknown) == ""
        out, _ = _inject({"last_confirm_value": "确认：商品=遮光窗帘", "last_card": unknown},
                         "确认：商品=遮光窗帘")
        assert out != PROMPT, "认不出目标就不注入事实 —— 点卡轮仍需知道「卡被点了」"
        assert "product_update" not in out and "product_batch_update" not in out

    def test_empty_card_is_safe(self):
        assert _card_click_target_tool(None) == ""
        assert _card_click_target_tool({}) == ""

    def test_falls_back_to_recorded_target_tool(self):
        """卡字段认不出时退到点卡轮落账的 `confirmed_write_tool`（同一份事实，不另立口径）。"""
        unknown = {"component": "confirm", "confirmValue": "确认：商品=遮光窗帘",
                   "fields": [{"label": "商品", "value": "遮光窗帘"}]}
        out, _ = _inject({"last_confirm_value": "确认：商品=遮光窗帘", "last_card": unknown,
                          "confirmed_write_tool": "sku_update"}, "确认：商品=遮光窗帘")
        assert "sku_update" in out


class TestWordingContractIsRelativeNotAbsolute:
    """判据 5（静态契约）：涉钱口径**不得**再写「打字『确认』不算」这类绝对否定。

    实测（issue #6985）：模型正是拿这句绝对措辞自造第二条判据 ——
    「用户消息是文本 ⇒ 打字 ⇒ 不算确认 ⇒ 拒答并重发卡」。真正判据是
    「消息是否**逐字等于**卡值」（`_is_card_confirm_value`），措辞必须与它同源。
    """

    #: 本单修复的**四处**涉钱口径（issue #6985 的定位面）——「同源」是硬要求，逐处核。
    FILES = (
        AI_AGENT / "app/graph/skills/references/prompts/product.md",
        AI_AGENT / "app/graph/skills/product_skill.py",
        AI_AGENT / "app/tools/product_update.py",
        AI_AGENT / "app/tools/sku_update.py",
    )

    #: 类级元守卫的扫描面 = **整个 agent 面**（prompt / 工具描述 / 技能话术），
    #: 不是上面那四处的硬编码清单：新增第五处写同样的绝对措辞 ⇒ 同样会被本判据抓到
    #: （`migao-dev-flow` §23「修一处 = 没修」：措辞面必须让同类进不来）。
    SCAN_ROOTS = (AI_AGENT / "app",)

    #: 绝对否定措辞（模型据它自造第二条判据）——**逐字等于 `_is_card_confirm_value` 的反面**。
    ABSOLUTE_MARKERS = ("打字「确认」不算", "打字「确认」**不算**", "打字确认不算",
                        "文字回复不算", "打字回复不算")

    def test_no_absolute_wording_anywhere_in_the_agent_surface(self):
        """**类级元守卫（全仓现取）**：任何一处再写绝对否定措辞都判红，不靠人记得改清单。

        射程 = **会进模型上下文的那部分文本**：`.py` 只扫**字符串字面量**（AST，
        注释与 docstring 是给维护者看的、不进 prompt ⇒ 不误伤「复盘时引用旧措辞」），
        `.md` 是 prompt 载体本身，整篇扫。
        """
        offenders = _absolute_wording_offenders(AI_AGENT / "app", self.ABSOLUTE_MARKERS)
        assert not offenders, (
            "涉钱口径又出现了「打字「确认」不算」类**绝对否定**措辞（模型据此自造"
            f"「文本都不算」的第二条判据）：{offenders}"
        )

    def test_shared_criterion_is_named(self):
        """四处口径都必须落到与判据同源的**可机械复算**口径上（逐字等于卡值）。"""
        for path in self.FILES:
            text = path.read_text(encoding="utf-8")
            assert "逐字" in text and "confirmValue" in text, (
                f"{path.relative_to(REPO)} 没有写明真正判据"
                "（商家消息逐字等于确认卡 confirmValue = 点卡回传）"
            )

    def test_execute_after_click_is_stated(self):
        """「点卡之后**必须**调用」这一半必须写出来（本单的断点就在这一半）。"""
        for path in self.FILES:
            text = path.read_text(encoding="utf-8")
            assert "点卡之后" in text, f"{path.relative_to(REPO)} 缺少「点卡之后必须执行」"

    def test_meta_guard_has_discriminating_power(self, tmp_path):
        """判别力自证（三种坏形态）：假 `.md` / 假 `.py` 字面量 ⇒ 必被抓到；**注释里的引用 ⇒ 不抓**。"""
        root = tmp_path / "app"
        (root / "graph").mkdir(parents=True)
        (root / "graph" / "fake_domain.md").write_text(
            "改价只认点卡：商家打字「确认」不算。", encoding="utf-8")
        (root / "fake_tool.py").write_text(
            'DESC = "改价只认点卡：商家打字「确认」不算。"\n'
            "# 复盘：旧措辞「打字「确认」不算」已废除\n",
            encoding="utf-8")
        offenders = _absolute_wording_offenders(root, self.ABSOLUTE_MARKERS)
        names = sorted(o.split("::")[0] for o in offenders)
        assert names == ["fake_tool.py", "graph/fake_domain.md"], (
            f"判别力自证失败（坏形态没被抓全 / 误伤注释）：{offenders}"
        )
        # 反向对照：注释里的**引用**不算（否则复盘材料会把守卫喂红）
        (root / "fake_tool.py").write_text(
            "# 复盘：旧措辞「打字「确认」不算」已废除\nX = 1\n", encoding="utf-8")
        assert _absolute_wording_offenders(root, self.ABSOLUTE_MARKERS) == [
            "graph/fake_domain.md::打字「确认」不算"], "注释被当成 prompt 文本（误伤）"


class TestGateWordingIsConditional:
    """判据 6：门禁话术不得无条件说「不要再次调用 X」（它留在历史里=给模型的强指令）。"""

    REACT = AI_AGENT / "app/graph/skills/execution/react_turn.py"

    def test_gate_message_has_conditional_ban(self):
        text = self.REACT.read_text(encoding="utf-8")
        assert "**不要再次调用 {tool_name}**" not in text, (
            "门禁话术仍是无条件禁止句 —— 模型会把「不要再次调用 X」当成本会话通用规则"
            "（本单实测：即便顾客点了卡也不敢调用）"
        )
        assert "在顾客点击确认卡之前，不要再次调用" in text, (
            "门禁话术没有把禁止句限定在「点卡之前」"
        )

    def test_gate_message_states_the_true_criterion(self):
        text = self.REACT.read_text(encoding="utf-8")
        assert "逐字等于" in text and "confirmValue" in text, (
            "门禁话术没有把真正判据（消息逐字等于 confirmValue）说给模型"
        )


def _absolute_wording_offenders(root: Path, markers) -> list:
    """全仓现取：`root` 下**会进模型上下文**的文本里出现的绝对否定措辞（具名返回）。

    `.py` 只取**非 docstring** 的字符串字面量（AST；注释是维护者文本、docstring 是模块说明，
    两者都不进 prompt ⇒ 复盘里引用旧措辞不误伤；而 prompt / 工具描述正是字面量）；
    `.md` 整篇（prompt 载体）。返回 `"<相对路径>::<命中标记>"` 列表（空 = 通过）。
    """
    offenders = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in (".py", ".md"):
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(root)
        if path.suffix == ".md":
            texts = [raw]
        else:
            try:
                tree = ast.parse(raw)
            except SyntaxError:
                continue
            docs = set()
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                         ast.AsyncFunctionDef)):
                    continue
                body = getattr(node, "body", None) or []
                if body and isinstance(body[0], ast.Expr) \
                        and isinstance(body[0].value, ast.Constant) \
                        and isinstance(body[0].value.value, str):
                    docs.add(id(body[0].value.value))
            texts = [n.value for n in ast.walk(tree)
                     if isinstance(n, ast.Constant) and isinstance(n.value, str)
                     and id(n.value) not in docs]
        for marker in markers:
            if any(marker in t for t in texts):
                offenders.append(f"{rel}::{marker}")
    return offenders


# ════════════════════════════════════════════════════════════════════════════
# 接线判据：注入必须真的出现在**运行时传给 LLM 的 system prompt** 里
# （形态照抄 `tests/test_permission_scope_injection.py::TestWiredIntoTheRealPromptAssembly`）
# ════════════════════════════════════════════════════════════════════════════

def _make_state(**overrides):
    state = {
        "messages": [HumanMessage(content="确认")],
        "tenant_id": 1,
        "user_id": "u_100",
        "session_id": "sess_6985",
        "role": "operator",
        "agent_type": "mibao",
        "permissions": [],
        "intent_result": None,
        "route_decision": None,
        "entities": {},
        "intent_chain": [],
        "stage": "initial",
        "cached_answer": None,
        "final_answer": "",
        "skill_used": "",
    }
    state.update(overrides)
    return state


class TestWiredIntoTheRealSystemPrompt:
    """**红证 A 的承载体**：摘掉 `prepare_turn` 里的接线 ⇒ 本类必红（纯函数单测察觉不到）。"""

    @staticmethod
    def _run(last_user_msg, stored):
        captured = []

        async def _capture_and_respond(messages):
            captured.extend(messages)
            resp = MagicMock(spec=AIMessage)
            resp.content = "好的。"
            resp.tool_calls = []
            return resp

        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_breaker = MagicMock()

        async def _passthrough_breaker(fn):
            return await fn()

        mock_breaker.call = _passthrough_breaker
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=_capture_and_respond)
        mock_llm.model_name = "qwen3.6-flash"

        store = MagicMock()
        store.load = AsyncMock(return_value=dict(stored or {}))
        store.commit = AsyncMock()

        async def _go():
            from app.graph.skills.base_skill import execute_skill
            with patch("app.graph.skills.base_skill.create_skill_registry",
                       return_value=mock_registry), \
                 patch("app.graph.skills.base_skill.set_tool_context"), \
                 patch("app.graph.skills.base_skill.get_breaker",
                       return_value=mock_breaker), \
                 patch("app.graph.skills.base_skill.get_skill_llm",
                       return_value=mock_llm), \
                 patch("app.memory.session_state_store.SessionStateStore",
                       return_value=store):
                await execute_skill(
                    state=_make_state(messages=[HumanMessage(content=last_user_msg)]),
                    skill_name="product",
                    tool_names=[],
                    system_prompt="你是商品助手",
                )

        asyncio.run(_go())
        return "\n".join(getattr(m, "content", "") or ""
                         for m in captured if isinstance(m, SystemMessage))

    def test_card_click_round_reaches_the_llm_prompt(self):
        text = self._run(PRICE_CARD_VALUE, {"last_confirm_value": PRICE_CARD_VALUE,
                                           "last_card": PRICE_CARD})
        assert text, "本轮没有组装出 SystemMessage —— 接线判据会变成空跑"
        assert "【系统事实" in text and "点击" in text, (
            "点卡轮的上下文事实没有进入真实 system prompt（接线断了）；"
            f"实测 prompt={text[:200]!r}"
        )
        assert "product_update" in text, (
            "真实 prompt 里的点卡事实没有点名写工具（模型仍不知道该执行什么）"
        )

    def test_plain_text_turn_does_not_reach_the_llm_prompt(self):
        text = self._run("确认", {"last_confirm_value": PRICE_CARD_VALUE,
                                 "last_card": PRICE_CARD})
        assert "【系统事实" not in text, "普通文本轮把点卡事实注入了真实 prompt（零回归面被破）"


class TestRedProofs:
    """判别力自证：把判据/反推在**内存里**摘掉 ⇒ 上面的断言形态必须落到「没注入」那一侧。"""

    def test_disabling_the_shared_criterion_kills_the_signal(self):
        with patch("app.graph.skills.base_skill._is_card_confirm_value",
                   return_value=False):
            out, _ = _inject({"last_confirm_value": PRICE_CARD_VALUE,
                              "last_card": PRICE_CARD}, PRICE_CARD_VALUE)
        assert out == PROMPT, "判据被换成恒假后仍然注入 —— 注入并非由点卡判据驱动"

    def test_removing_target_tool_leaves_no_tool_name(self):
        """摘掉目标反推 ⇒ 注入文本里不得再出现工具名（判据 4 的注入侧对照）。"""
        with patch("app.graph.skills.base_skill._card_click_target_tool",
                   return_value=""):
            out, _ = _inject({"last_confirm_value": PRICE_CARD_VALUE,
                              "last_card": PRICE_CARD}, PRICE_CARD_VALUE)
        assert out != PROMPT
        assert "product_update" not in out
