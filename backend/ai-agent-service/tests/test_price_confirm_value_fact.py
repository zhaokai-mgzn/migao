# case_ids: PR-009, PR-010, PR-021
"""改价确认记录**按值**记（issue #5414）—— 点过「价 A」的卡不得放行「价 B」的改动。

## 病灶（一句话）
`confirmed_write_tool` 记的是**工具名**，不是**值**：

    轮 N：模型发卡，商家点了「确认」（价 A）→ 记 confirmed_write_tool = product_update
    轮 N：写失败 / 未提交（**没有清除**）
    轮 N+1：模型改价 B（≠ A）⇒ 因「该工具已被确认过」⇒ **放行**

⇒ 商家点的是价 A 的卡，被放行的是价 B 的改动。这与 #5317 自己引用的那条诊断同源：
「门禁只证明『确认过』，不证明『看过什么』」—— #5317 在**卡 vs 文本**这一维治好了它，
**「看过哪个价」**这一维当时只做到"确认过某个价"。

## 本文件的判据（每条都能单独变红，见 `TestRedProofs`）
- **判据 1（值面）** 记录里存"被确认的值"，放行时与本次 args **逐值核对**：
  点过价 A 的卡 ⇒ 价 B 仍需**新卡**；同一个价 ⇒ 照旧放行（阳性对照，防"门禁恒拦"）。
- **判据 2（跨轮残留窗口）** **点过卡但写未成功**期间换价 ⇒ 仍需新卡
  （这正是 #5317 主动登记的 ③ 条；写**成功**即清除 ⇒ 有断言钉住清除后的读数）。
- **判据 3（机械判据）** 「逐值核对」不是"某处代码记得核"：写入该键**只此两处**
  （record / clear）、按工具名比较该键**只此一处**（release）—— 静态不变式。
- **判据 4（跨语言同口径）** Python 侧的按值比较与 Java `AgentWriteValues.sameValue`
  **共用同一份语料**（`backend/admin-api/src/test/resources/agent-write-values-corpus.json`），
  两侧各自的测试都跑它 ⇒ 口径漂移必红。
- **判据 5（不回退）** 非涉钱面（改名 / 上下架 / 下单）的既有「按名放行」语义**一字不动**。

## 不属本判据（如实登记）
- **同轮无 pending 的形态**：价面确认卡由 `interact` 发出（模型自带 fields），系统**无从**
  机器判定"卡上那个价"与本次调用参数是否同源 ⇒ 点卡轮内「卡值 A / 调用价 B」这一形态
  仍不可判（记录取自本次调用参数）。判据 1/2 覆盖的是**跨轮**放行（本单的病灶形态）。
- 真实 LLM 是否**真的**先查再改、商家是否**真的**点了卡 ⇒ 属真实评测（`migao-dev-flow` §13
  默认不跑）。
"""

import asyncio
import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from app.graph.skills import base_skill
from app.graph.skills.base_skill import execute_skill
from app.tools.confirm_value import confirm_card_fields, confirm_value_for_fields
from app.tools.product_update import ProductUpdateTool
from app.tools.registry import get_tool_registry

REPO = Path(__file__).resolve().parents[3]

#: 改价的典型参数（#5303 的预览契约：改后价 + 改前价成对）
PRICE_A = {"product_id": "遮光窗帘", "price": 199, "before_price": 168}
#: 同一张卡被点过之后，模型改成的**另一个价**（≠ A）
PRICE_B = {"product_id": "遮光窗帘", "price": 299, "before_price": 168}
#: 非涉钱面（改名）：**不得**被本单的值核对误伤
RENAME = {"product_id": "遮光窗帘", "name": "遮光窗帘（加厚）"}


def _new_api():
    """本单新增的 API —— **函数内取**（不是模块顶层）。

    为什么：Red 阶段必须"判据失败"可读，而不是整个文件收集期就 ImportError
    （那样连"阳性对照是否绿"都看不见）。也让 `TestRedProofs` 的注入能直接打到模块属性上。
    """
    from app.graph.skills.base_skill import (
        CONFIRMED_WRITE_VALUES_KEY,
        clear_confirmed_write,
        confirmed_write_release,
        record_confirmed_write,
    )
    from app.tools.confirm_value import (
        CARD_ONLY_VALUE_FIELDS,
        same_value,
        values_match,
        write_value_facts,
    )
    return {
        "KEY": CONFIRMED_WRITE_VALUES_KEY,
        "record": record_confirmed_write,
        "clear": clear_confirmed_write,
        "release": confirmed_write_release,
        "fields": CARD_ONLY_VALUE_FIELDS,
        "same_value": same_value,
        "values_match": values_match,
        "facts": write_value_facts,
    }


def _make_state(**overrides):
    state = {
        "messages": [HumanMessage(content="改价")],
        "tenant_id": 1,
        "user_id": 100,
        "session_id": "sess_5414",
        "role": "admin",
        "intent_result": None,
        "route_decision": None,
        "entities": {},
        "intent_chain": [],
        "stage": "initial",
        "cached_answer": None,
        "final_answer": "",
        "skill_used": "",
        "suggestions": [],
    }
    state.update(overrides)
    return state


class _TurnHarness:
    """跨轮驱动 `execute_skill`（product / product_update），会话状态**真持久化**。

    与 `test_graph_skills.TestWriteConfirmedLifecycle._run` 的唯一差异（关键）：
    `commit` 会**写回**会话状态（那边只 append 到 commits）—— 本单的核心场景是
    「点过卡但写未成功 ⇒ 下一轮换价」，两轮必须看同一份状态，否则判据测不到残留窗口。
    """

    def __init__(self, store_state=None):
        self.store = dict(store_state or {})
        self.commits = []
        self.executed = []

    @property
    def executed_names(self):
        return [name for name, _ in self.executed]

    def turn(self, user_msg, tool_calls, tool_ok=True):
        from langchain_core.messages import AIMessage

        start = len(self.executed)

        async def fake_execute(tool, args, ctx, state):
            self.executed.append((tool.name, dict(args)))
            res = {"success": bool(tool_ok), "data": {}}
            return (json.dumps(res, ensure_ascii=False), res)

        with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
             patch("app.memory.session_state_store.SessionStateStore") as store_cls:
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = (
                lambda n: ProductUpdateTool() if n == "product_update" else None)
            create_reg.return_value = registry

            breaker = MagicMock()

            async def _passthrough(fn):
                return await fn()

            breaker.call = _passthrough
            get_breaker.return_value = breaker

            def make_call(name, args):
                m = MagicMock(spec=AIMessage)
                m.content = ""
                m.tool_calls = [{"name": name, "args": args, "id": "t1"}]
                return m

            final = MagicMock(spec=AIMessage)
            final.content = "好的"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[make_call(*tc) for tc in tool_calls] + [final])
            get_llm.return_value = llm
            mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)

            inst = MagicMock()
            inst.load = AsyncMock(side_effect=lambda sid: dict(self.store))

            def _commit(sid, full):
                self.commits.append(dict(full))
                self.store.clear()
                self.store.update(full)

            inst.commit = AsyncMock(side_effect=_commit)
            store_cls.return_value = inst

            asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content=user_msg)]),
                skill_name="product",
                tool_names=["product_update"],
                system_prompt="你是米宝",
            ))
        # 只报**本轮**执行了什么（累计列表会把上一轮的读数混进来 ⇒ 断言指向错误的轮次）
        return [name for name, _ in self.executed[start:]]


def _clicked_card_on_price_a() -> dict:
    """「商家点过价 A 的卡、该写**还没成功**」的会话状态（本单的核心残留窗口）。"""
    api = _new_api()
    st = {}
    api["record"](st, "product_update", dict(PRICE_A))
    return st


#: 确认记录的「写」形态（赋值 / pop）；允许的落点只有 record / clear 两处。
_WRITE_KEY_SITE = re.compile(r"""\[["']confirmed_write_tool["']\]\s*="""
                             r"""|\.pop\(\s*["']confirmed_write_tool["']""")
#: 确认记录的「按工具名判」形态：下标取值 / `.get(...)` 取值，其后 40 字符内出现 `==` / `!=`
#: （允许中间夹 `str(...)` / `or ""` 之类的包装 —— 旁路正是藏在包装里）；允许的落点只有
#: release 一处。**射程如实登记**：`state.update({...})` / `setdefault` / 变量中转不在面内。
_JUDGE_KEY_SITE = re.compile(
    r"""(?:\[["']confirmed_write_tool["']\]|\.get\(\s*["']confirmed_write_tool["']\s*\))"""
    r"""[^\n;]{0,40}?(?:==|!=)""")
_WRITE_OWNERS = {"record_confirmed_write", "clear_confirmed_write"}
#: 「按工具名判」的合法落点：**放行**（release）与**清除**（clear，写成功后的收尾）。
#: 两者都只判"这条记录是不是这个工具的"，**不据此放行**；其余任何地方按工具名判 = 旁路。
_JUDGE_OWNERS = {"confirmed_write_release", "clear_confirmed_write"}


def _key_sites(pattern: re.Pattern) -> list:
    """全 `app/**` 里命中 pattern 的 `(文件, 行号, 所属函数, 代码行)`（**去掉注释**后匹配）。

    抽成模块级纯函数是为了让红证能直接喂负例：注入一处旁路 ⇒ **它必须变红**
    （否则"静态判据"只是没扫到东西的绿）。
    """
    app_dir = REPO / "backend/ai-agent-service/app"
    out = []
    for path in sorted(app_dir.rglob("*.py")):
        owner = ""
        for no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if raw.startswith(("def ", "async def ")):
                owner = raw.split("(", 1)[0].replace("async ", "").replace("def ", "").strip()
            line = raw.split("#", 1)[0]
            if pattern.search(line):
                out.append((str(path.relative_to(REPO)), no, owner, line.strip()))
    return out


class TestConfirmRecordIsAValueFact:
    """判据 1 + 2：记录按值记 ⇒ 价 A 的卡不放过价 B 的改动。"""

    def test_price_b_needs_a_new_card_after_card_a_clicked(self):
        """🔴 本单的判据：点过价 A 的卡后，改价 B **必须**仍需新卡。"""
        h = _TurnHarness(_clicked_card_on_price_a())
        executed = h.turn("改成 299 吧", [("product_update", dict(PRICE_B))])
        assert executed == [], (
            "点过价 A 的卡却放行了价 B 的改动 —— 确认记录又退回「只证明确认过某工具」"
            f"（executed={executed}）")

    def test_same_price_a_is_still_released(self):
        """阳性对照：同一张卡的**同一个价** ⇒ 照旧放行（证明上一条不是"门禁恒拦"）。"""
        h = _TurnHarness(_clicked_card_on_price_a())
        executed = h.turn("就按这个价", [("product_update", dict(PRICE_A))])
        assert executed == ["product_update"], (
            f"同一个价也被拦 ⇒ 判据 1 的红无从区分真假（executed={executed}）")

    def test_cross_turn_residual_window_after_failed_write(self):
        """🔴 判据 2（#5317 登记的 ③ 条）：点卡轮**写失败** ⇒ 下一轮换价仍需新卡。"""
        card = confirm_value_for_fields(confirm_card_fields(PRICE_A))
        h = _TurnHarness({"last_confirm_value": card})
        clicked = h.turn(card, [("product_update", dict(PRICE_A))], tool_ok=False)
        assert clicked == ["product_update"], (
            f"点卡轮就没放行 ⇒ 前置不成立（executed={clicked}）")
        assert h.store.get("confirmed_write_tool") == "product_update", (
            "写失败后记录已不在 ⇒ 残留窗口的前置不成立（本判据失去对象）")

        executed = h.turn("还是改 299", [("product_update", dict(PRICE_B))])
        assert executed == [], (
            "写失败期间换价被放行 —— 商家点的是价 A 的卡，落库的却是价 B"
            f"（executed={executed}）")

    def test_cross_turn_same_price_is_still_released(self):
        """阳性对照：写失败后**同一个价**重试 ⇒ 不该被拦（否则正常流程要多点一次卡）。"""
        card = confirm_value_for_fields(confirm_card_fields(PRICE_A))
        h = _TurnHarness({"last_confirm_value": card})
        h.turn(card, [("product_update", dict(PRICE_A))], tool_ok=False)
        executed = h.turn("再试一次", [("product_update", dict(PRICE_A))])
        assert executed == ["product_update"], (
            f"同一个价的重试被拦（把正常流程当攻击拦）executed={executed}")

    def test_successful_write_clears_both_the_name_and_the_values(self):
        """写成功 ⇒ 记录（**含值事实**）整体清除 —— 留痕不等于发生过，这里看落库读数。"""
        api = _new_api()
        card = confirm_value_for_fields(confirm_card_fields(PRICE_A))
        h = _TurnHarness({"last_confirm_value": card})
        h.turn(card, [("product_update", dict(PRICE_A))], tool_ok=True)
        assert "confirmed_write_tool" not in h.store, (
            f"写成功后工具名记录残留：{sorted(h.store)}")
        assert api["KEY"] not in h.store, (
            f"写成功后值事实残留 ⇒ 下一轮同价调用会被旧记录放行：{sorted(h.store)}")


class TestNonPriceReleaseUnchanged:
    """判据 5：非涉钱面的既有语义一字不动（本单只收窄「值」这一维）。"""

    def test_rename_is_released_by_the_same_record(self):
        """改名（值面上什么都没有）⇒ 与既有语义一致：仍按工具名放行。"""
        api = _new_api()
        st = {}
        api["record"](st, "product_update", dict(RENAME))
        h = _TurnHarness(st)
        executed = h.turn("改名", [("product_update", dict(RENAME))])
        assert executed == ["product_update"], (
            f"非涉钱面的按名放行被误伤（executed={executed}）")

    def test_record_without_values_does_not_release_a_price_change(self):
        """老形态记录（只有工具名、没有值事实）⇒ **不可核对** ⇒ 改价仍需新卡（fail-closed）。"""
        h = _TurnHarness({"confirmed_write_tool": "product_update"})
        executed = h.turn("改成 299", [("product_update", dict(PRICE_B))])
        assert executed == [], (
            f"没有值事实的记录放行了一次改价（「没法比对」被当成「对得上」）executed={executed}")

    def test_order_facts_path_is_untouched(self):
        """下单（F22 金额事实）走的是另一条键 —— 本单的记录不改它的口径。"""
        from app.graph.skills.base_skill import (
            CONFIRMED_ORDER_FACTS_KEY,
            confirmed_order_facts_of,
            record_confirmed_write,
        )
        st = {}
        record_confirmed_write(st, "order_create",
                               {"items": [{"product_name": "遮光窗帘", "quantity": 3,
                                           "unit_price": 168}]})
        assert confirmed_order_facts_of(
            "order_create", {"items": [{"product_name": "遮光窗帘", "quantity": 3,
                                        "unit_price": 168}]}) == st.get(CONFIRMED_ORDER_FACTS_KEY), \
            "下单金额事实的落点被本单改动挤掉了（F22 口径漂移）"
        assert _new_api()["facts"]({"items": [{"unit_price": 168}]}) == {}, \
            "下单参数被误算成改价的值事实（本单的值面必须只含改价字段）"


class TestValueComparisonSemantics:
    """判据 4 的 Python 侧：按值比较（10.0 == 10.00）、非价格字面、缺失/非法 ⇒ fail-closed。"""

    def test_numeric_forms_are_the_same_price(self):
        f = _new_api()["same_value"]
        assert f("price", 199, 199.0) is True
        assert f("price", "199", "199.00") is True
        assert f("before_price", 168, "168.000") is True

    def test_different_price_is_not_the_same_price(self):
        f = _new_api()["same_value"]
        assert f("price", 199, 299) is False
        assert f("price", 168.01, "168.00") is False

    def test_missing_or_illegal_is_fail_closed(self):
        f = _new_api()["same_value"]
        assert f("price", None, 199) is False
        assert f("price", 199, None) is False
        assert f("price", "一百九十九", 199) is False
        assert f("price", "Infinity", "Infinity") is False, \
            "非有限数被当成可比对的值（Java 侧 BigDecimal 直接抛 ⇒ 口径漂移）"

    def test_batch_id_is_compared_literally(self):
        f = _new_api()["same_value"]
        assert f("batch_id", "b1", "b1") is True
        assert f("batch_id", "b1", "b2") is False

    def test_values_match_only_judges_the_values_this_call_carries(self):
        m = _new_api()["values_match"]
        assert m({"price": 199, "before_price": 168}, {"price": 199.0, "before_price": 168}) is True
        assert m({"price": 199, "before_price": 168}, {"price": 299, "before_price": 168}) is False
        assert m({"price": 199}, {"price": 199, "before_price": 168}) is False, \
            "本次调用带了记录里没有的值 ⇒ 不可核对 ⇒ 必须不放行（fail-closed）"
        assert m({"price": 199, "before_price": 168}, {}) is True, \
            "本次调用值面上什么都没有（改名）⇒ 不构成「不符」（判据 5 不回退）"

    def test_value_facts_cover_exactly_the_card_only_fields(self):
        api = _new_api()
        assert api["facts"](dict(PRICE_A)) == {"price": 199, "before_price": 168}
        assert api["facts"]({"action": "execute", "batch_id": "b1"}) == {"batch_id": "b1"}
        assert api["facts"](dict(RENAME)) == {}
        assert api["fields"] == ("price", "before_price", "batch_id"), \
            f"值面字段集变了（改它就等于改放行面）：{api['fields']}"


class TestCrossLanguageValueParity:
    """判据 4：Python 侧按值比较与 `AgentWriteValues.sameValue` **语义一致**（共用同一份语料）。"""

    CORPUS = REPO / "backend/admin-api/src/test/resources/agent-write-values-corpus.json"
    JAVA_TEST = (REPO / "backend/admin-api/src/test/java/com/migao/admin/service"
                 / "AgentWriteValuesTest.java")

    def _corpus(self) -> dict:
        data = json.loads(self.CORPUS.read_text(encoding="utf-8"))
        assert isinstance(data.get("cases"), list) and data["cases"], \
            f"跨语言语料缺失或为空 ⇒ 判据空转：{self.CORPUS}"
        return data

    def test_python_verdicts_match_the_shared_corpus(self):
        f = _new_api()["same_value"]
        for c in self._corpus()["cases"]:
            assert f(c["field"], c["given"], c["current"]) is c["expect"], \
                f"Python 侧与语料不符（跨语言口径漂移）：{c}"

    def test_python_arg_vocabulary_behaves_like_the_java_field_word(self):
        """工具参数用的是 `price` / `before_price`，Java 用 `basePrice` —— 词不同、**语义同**。"""
        f = _new_api()["same_value"]
        data = self._corpus()
        aliases = data["python_alias_fields"]
        assert aliases, "别名映射为空 ⇒ 这条判据是空跑"
        checked = 0
        for c in data["cases"]:
            for alias, java_field in aliases.items():
                if java_field != c["field"]:
                    continue
                checked += 1
                assert f(alias, c["given"], c["current"]) is c["expect"], \
                    f"参数词 {alias} 与 Java 字段词 {java_field} 判定不一致：{c}"
        assert checked >= len(aliases), f"没有一条语料被别名口径覆盖（checked={checked}）"

    def test_corpus_covers_the_load_bearing_forms(self):
        cases = self._corpus()["cases"]
        eq = [c for c in cases if c["expect"] is True]
        ne = [c for c in cases if c["expect"] is False]
        assert eq and ne, "语料只有单向判决 ⇒ 恒真的那种写法照样能过"
        assert any(c["given"] is None or c["current"] is None for c in cases) or \
            any(c["given"] is None for c in cases), "语料没有「一侧缺失」的用例（fail-closed 没被钉）"
        assert any(not str(c["given"]).replace(".", "").lstrip("-").isdigit()
                   for c in cases if c["given"] is not None), \
            "语料没有「非法数字」的用例"

    def test_the_java_side_consumes_the_same_corpus(self):
        src = self.JAVA_TEST.read_text(encoding="utf-8")
        assert "agent-write-values-corpus.json" in src, (
            "Java 侧没有读这份语料 ⇒ 「跨语言同口径」名不副实（两侧各跑各的）")


class TestMechanicalJudgments:
    """判据 3：逐值核对有**机械判据**（写入/比较该键的位置只此几处）。"""

    def test_only_record_and_clear_write_the_key(self):
        offenders = [f"{p}:{n} ({o}): {l}" for p, n, o, l in _key_sites(_WRITE_KEY_SITE)
                     if o not in _WRITE_OWNERS]
        assert offenders == [], (
            "有旁路在直接写「已确认」记录 ⇒ 值事实可能不落（本单的类级风险）："
            + "；".join(offenders))

    def test_only_the_release_judgment_compares_the_key_to_a_tool_name(self):
        offenders = [f"{p}:{n} ({o}): {l}" for p, n, o, l in _key_sites(_JUDGE_KEY_SITE)
                     if o not in _JUDGE_OWNERS]
        assert offenders == [], (
            "有第二处按工具名放行（不核值）—— 这就是本单要根除的形态："
            + "；".join(offenders))

    def test_the_judgments_are_not_vacuous(self):
        """防空转：守卫必须真的扫到「写」与「判」两处合法命中（否则它只是没扫到东西）。"""
        writes = [s for s in _key_sites(_WRITE_KEY_SITE) if s[2] in _WRITE_OWNERS]
        judges = [s for s in _key_sites(_JUDGE_KEY_SITE) if s[2] == "confirmed_write_release"]
        assert writes and judges, (
            f"守卫没扫到合法命中（写={writes} / 判={judges}）⇒ 判据空转，宁可红")

    def test_the_whitelist_points_at_functions_that_still_exist(self):
        """台账「条目须活着」：白名单指向的函数必须仍在源码里（改名 ⇒ 守卫静默失效）。"""
        src = (REPO / "backend/ai-agent-service/app/graph/skills/base_skill.py").read_text(
            encoding="utf-8")
        for name in sorted(_WRITE_OWNERS | _JUDGE_OWNERS):
            assert f"def {name}(" in src, f"白名单指向的函数不存在（守卫已成空转）：{name}"

    def test_release_also_reads_the_values_key(self):
        """放行判据必须**真的读值事实**（不是只比工具名再补一句注释）。"""
        src = (REPO / "backend/ai-agent-service/app/graph/skills/base_skill.py").read_text(
            encoding="utf-8")
        body = src.split("def confirmed_write_release(", 1)[1].split("\ndef ", 1)[0]
        assert "CONFIRMED_WRITE_VALUES_KEY" in body, \
            "放行判据没读值事实键 ⇒ 又退回按工具名放行"


class TestClassLevelMetaGuard:
    """§23 G1/G2 类级元守卫：让「某工具的确认记录一律按值」这一类**进不来**。

    射程 = **现取**注册表（不硬编码清单）：任何落在涉钱面（声明 `before_price`，
    或声明 `card_only_actions`）的写工具，都必须算得出非空的值事实 ——
    新改价工具落地即自动进面，**不需要有人记得改清单**。
    """

    def _card_only_surface(self, tool) -> bool:
        props = ((getattr(tool, "parameters", None) or {}).get("properties") or {})
        return "before_price" in props or bool(getattr(tool, "card_only_actions", None))

    def _probe(self, tool) -> dict:
        props = ((getattr(tool, "parameters", None) or {}).get("properties") or {})
        if "before_price" in props:
            probe = {"price": 199, "before_price": 168}
            if "batch_id" in props:
                probe["batch_id"] = "b1"
            return probe
        actions = list(getattr(tool, "card_only_actions", None) or [])
        return {"action": actions[0] if actions else "", "batch_id": "b1"}

    def test_every_card_only_tool_records_a_value_fact(self):
        facts = _new_api()["facts"]
        covered, offenders = set(), []
        for tool in get_tool_registry().get_all_tools():
            if getattr(tool, "read_only", True) or not self._card_only_surface(tool):
                continue
            covered.add(tool.name)
            if not facts(self._probe(tool)):
                offenders.append(tool.name)
        assert offenders == [], (
            f"涉钱面工具算不出值事实 ⇒ 它的确认记录会退化成「按工具名记」：{offenders}")
        # 防空转 + 实例锚定：注册表里必须真有这几个改价工具被扫到
        assert {"product_update", "sku_update", "product_batch_update"} <= covered, \
            f"实例改价工具不在射程内（元守卫空转）：{sorted(covered)}"

    def test_meta_guard_can_go_red(self, monkeypatch):
        """注入：抽掉某工具的 `before_price` 声明 ⇒ 它脱离射程（判据形态可见）。"""
        tool = get_tool_registry().get_tool("product_update")
        props = dict(tool.parameters["properties"])
        props.pop("before_price")
        monkeypatch.setattr(tool, "parameters", {"type": "object", "properties": props})
        assert self._card_only_surface(tool) is False, "注入没生效：射程判据无从变红"


class TestRedProofs:
    """红证（`migao-acceptance`）：每条判据都要有能**单独变红**的注入。"""

    def test_release_by_tool_name_only_turns_the_criterion_red(self):
        """🔴 注入：放行改回**按工具名**（= 本单修之前的形态）⇒ 价 B 必须被放行（判据变红）。

        这正是验收判据 1 要求的红证形态；注入前后各自**自证生效**（G7）。
        """
        api = _new_api()
        st = _clicked_card_on_price_a()
        args = dict(PRICE_B)
        assert api["release"](st, "product_update", args) is False, \
            "注入前就该拦（判据没有判别力）"

        def name_only(full, tool_name, tool_args):
            return (full or {}).get("confirmed_write_tool") == str(tool_name or "")

        with patch.object(base_skill, "confirmed_write_release", name_only):
            assert base_skill.confirmed_write_release(st, "product_update", args) is True, \
                "注入没生效（按工具名的放行判据没能放行）⇒ 本红证无效"
            h = _TurnHarness(st)
            executed = h.turn("改成 299", [("product_update", args)])
        assert executed == ["product_update"], (
            f"注入后价 B 仍被拦 ⇒ 判据红的是别的东西，不是本单修的这层（executed={executed}）")

    def test_name_only_record_turns_the_positive_control_red(self):
        """注入：记录只落工具名（值事实不落）⇒ **同一个价**也被拦（记录侧确实载荷）。"""
        api = _new_api()

        def name_only(state, tool_name, tool_args):
            state["confirmed_write_tool"] = str(tool_name or "")
            return state

        with patch.object(base_skill, "record_confirmed_write", name_only):
            st = {}
            base_skill.record_confirmed_write(st, "product_update", dict(PRICE_A))
            assert api["KEY"] not in st, "注入没生效：值事实仍然落了"
            h = _TurnHarness(st)
            executed = h.turn("就按这个价", [("product_update", dict(PRICE_A))])
        assert executed == [], (
            f"记录侧不载荷（只落工具名）却仍放行 ⇒ 值事实这层没用（executed={executed}）")

    def test_no_op_clear_turns_the_clear_criterion_red(self):
        """注入：把「写成功后的清除」改成空操作 ⇒ 清除那层必须真的载荷（记录会留下）。

        与 `test_successful_write_clears_both_the_name_and_the_values` 配对：那条证明
        「清除会发生」，本条证明「不清除时记录真的会留下」—— 两层读数都指向同一层闸。
        """
        api = _new_api()
        card = confirm_value_for_fields(confirm_card_fields(PRICE_A))
        with patch.object(base_skill, "clear_confirmed_write",
                          lambda state, tool_name: state):
            h = _TurnHarness({"last_confirm_value": card})
            executed = h.turn(card, [("product_update", dict(PRICE_A))], tool_ok=True)
            assert executed == ["product_update"], (
                f"点卡轮没放行 ⇒ 前置不成立（executed={executed}）")
            # 前提自证（G7）：注入生效 ⇒ 工具名与值事实**都**留着
            assert h.store.get("confirmed_write_tool") == "product_update", \
                "注入没生效：工具名仍被清掉了 ⇒ 本红证无效"
            assert api["KEY"] in h.store, \
                "注入没生效：值事实仍被清掉了 ⇒ 本红证无效"

    def test_static_guard_can_go_red(self, monkeypatch):
        """注入：在 `app/**` 里塞一处按工具名放行 ⇒ 静态判据**必须**报出这条旁路。"""
        real = Path.read_text

        def fake_read_text(self, *a, **k):
            text = real(self, *a, **k)
            if str(self).endswith("react_turn.py"):
                text += ('\ndef _bypass(full, tool_name):\n'
                         '    return full["confirmed_write_tool"] == tool_name\n')
            return text

        monkeypatch.setattr(Path, "read_text", fake_read_text)
        src = (REPO / "backend/ai-agent-service/app/graph/skills/execution/react_turn.py") \
            .read_text(encoding="utf-8")
        assert '_bypass(full, tool_name)' in src, \
            "注入没生效（负例没有进入被测源码）⇒ 本红证无效"
        offenders = [s for s in _key_sites(_JUDGE_KEY_SITE) if s[2] not in _JUDGE_OWNERS]
        assert [o[0] for o in offenders if o[0].endswith("react_turn.py")], (
            f"注入的旁路没被判据抓到 ⇒ 静态判据是空跑（offenders={offenders}）")