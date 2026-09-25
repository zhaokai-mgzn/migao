# case_ids: OR-019, OR-018, OR-014
"""确认卡值 ↔ 落库值的**一致性守护判据**（issue #4025 台账 F22 的判据层收口）。

## 缺陷（台账原文）
「确认卡 ↔ 落库一致性无守护：用户点卡确认 **¥498**（10 米/2.8 米/3 加工项），
落库 **¥133.80**（1 米/3.2 米/2 项 + 优惠 ¥5），**全系统无一处校验两者一致**」。

## 本单**不重写**已落地的那一半（判据交叉验证它仍在，改动它必红）
`#4072`（issue #4037）已落下**运行时**护栏：确认那一刻把订单事实快照进
`confirmed_order_facts`，`order_create` 真正执行之前重算比对
（判据 = `app.tools.order_create.order_confirmation_mismatch`，拦截点
`backend/ai-agent-service/app/graph/skills/execution/react_turn.py`）；
`confirm_card_fields` 亦已让卡面带上数量/单价/小计/合计。

## 本单补的是**判据层**的两处残留（「全系统无一处校验」的下一格）
**① 「没法比对」与「对得上」不可区分。** `order_confirmation_mismatch` 对
「一致 / 没有卡 / 没有落库值」**一律返回空串**。运行时无所谓（三者都放行），
审计面却必须分开 —— 空串让「结构上无从核对」静默算作绿
（§migao-acceptance 的"空跑"：绿了但没跑）。
⇒ 新增三态判据源 `order_create.order_confirmation_verdict`：
一致 / 不一致 / **不可判定**，且 `reason` 恒非空（红绿都得可归因）。

**② 无覆盖面台账。** 判据本体在，但**没有任何东西**保证下一条新的落库路径会被登记进
这套比对 ⇒ 新写路径默默落地、零信号。
⇒ `app.tools.confirm_value.CARD_DB_CONSISTENCY_LEDGER`：每条落库写路径要么登记
比对载体（`amount_guarded` / `value_guarded`），要么**显式登记为不可判定**
（必带 `reason` + `issue` + `owner`）。**未登记即红、陈旧条目即红、声明与源码不符即红**。

## 现取（**不写死条数**）
写路径名册 = `app/tools/*.py` 里 `read_only = False` **且有类属性 `name`** 的文件
（与 `tests/test_write_audit_action_semantics.py` 的源码面口径同源；`registry.py` 命中
该字面量但不是工具 ⇒ 靠 `name` 排除）。复算：

    python -m pytest tests/test_card_db_consistency_guard.py -q -s -k census

## 结构上判不了的（显式登记，**不静默跳过**；清单由 `-k census` 打印）
`order_manage` / `aftersale_create` 的退款金额、加工单域三条、已退场的 `human_handoff`
—— 逐条理由见台账条目。另有一条**口径级**不可判定由实现侧自陈：
`order_create._entry_processing_fee` 的「声明加工费**没有接地**」（服务端 `ProcessingFeeCalculator`
重算，见 `#4390` 缺口③）⇒ 卡上的加工费与服务端真正会收的那笔**可以是两个数**，
本守护证明不了后者（要证明得消费 `POST /api/admin/orders/fee-preview`，代价见该函数注释）。

## 不属本判据（如实登记）
真实 LLM 是否**真的**把卡值与落库值写成一致 ⇒ 属真实评测（`migao-dev-flow` §13
默认不跑；本文件零 LLM、零外部依赖）。
"""
import ast
import json
import re
from pathlib import Path

import pytest

from app.graph.skills.base_skill import confirmed_order_facts_of
from app.tools.confirm_value import (
    AMOUNT_GUARDED,
    CARD_DB_CONSISTENCY_LEDGER,
    CARD_ONLY_VALUE_FIELDS,
    UNDECIDABLE,
    VALUE_GUARDED,
    VERDICT_UNENROLLED,
    card_db_verdict,
    write_value_facts,
)
from app.tools.order_create import (
    ORDER_VERDICT_MATCH,
    ORDER_VERDICT_MISMATCH,
    ORDER_VERDICT_UNDECIDABLE,
    order_confirmation_mismatch,
    order_confirmation_verdict,
    order_facts_of,
)

SERVICE_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = SERVICE_DIR / "app" / "tools"

#: 写工具在源码面的**唯一**依据（与 registry 的执行分支同一字段）。
_WRITE_MARKER = "read_only = False"

#: 台账要求的字段（按 stance 取）：不可判定条目必须给出**去向**，缺口不许匿名。
_UNDECIDABLE_FIELDS = ("reason", "issue", "owner")


# ══════════════════════════════════════════════════════════════════════════════
# 现取：源码面写路径名册（判据的输入，条数由它决定，**不写死**）
# ══════════════════════════════════════════════════════════════════════════════


def _declared_name(src: str):
    """类属性 `name = "xxx"` —— 工具名（非工具模块如 `registry.py` 无此声明 ⇒ 返回 None）。"""
    for node in ast.parse(src).body:
        if not isinstance(node, ast.ClassDef):
            continue
        for sub in node.body:
            if not isinstance(sub, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == "name" for t in sub.targets):
                continue
            if isinstance(sub.value, ast.Constant) and isinstance(sub.value.value, str):
                return sub.value.value
    return None


def _param_keys(src: str) -> set:
    """工具 `parameters.properties` 的键集（判"该工具的参数面有没有可比的金额字段"）。"""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "parameters" for t in node.targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            seg = ast.get_source_segment(src, node.value) or ""
            m = re.search(r'"properties"\s*:\s*\{(.*)', seg, re.S)
            return set(re.findall(r'"([a-z_]+)"\s*:', m.group(1))) if m else set()
        return set(((value or {}).get("properties") or {}).keys())
    return set()


def live_write_paths() -> dict:
    """现取名册 `{工具名: 参数键集}` —— 源码面 `read_only = False` 且声明了 `name`。"""
    out = {}
    for path in sorted(TOOLS_DIR.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        if _WRITE_MARKER not in src:
            continue
        name = _declared_name(src)
        if not name:
            continue
        out[name] = _param_keys(src)
    return out


def coverage_gaps(live, enrolled):
    """台账与现取名册的**双向差集**：`(未登记, 陈旧条目)`。

    抽成模块级纯函数是为了让红证能直接喂负例：注入一个未登记路径 / 一个陈旧条目
    ⇒ **它必须被点名**（否则"覆盖面判据"只是没扫到东西的绿）。
    """
    live, enrolled = set(live), set(enrolled)
    return sorted(live - enrolled), sorted(enrolled - live)


#: 金额守护的探针载荷（判"该路径是否真被订单事实守护域覆盖"）。
_PROBE_ORDER_ARGS = {
    "customer_phone": "13800138000",
    "items": [{"product_name": "遮光窗帘", "quantity": 1, "unit_price": 133.8}],
}

#: 台账里那组**真实数字**的语料（F22 原文）：卡上 ¥498（10 米 / 2.8 米）↔ 落库 ¥133.80（1 米）。
_CARD_498 = {
    "customer_phone": "13800138000",
    "items": [
        {"product_name": "遮光窗帘", "quantity": 10, "unit_price": 40.0},
        {"product_name": "纱帘", "quantity": 2.8, "unit_price": 35.0},
    ],
}
_DB_133_80 = {
    "customer_phone": "13800138000",
    "items": [{"product_name": "遮光窗帘", "quantity": 1, "unit_price": 133.8}],
}


def _facts(payload):
    return order_facts_of(payload)


# ══════════════════════════════════════════════════════════════════════════════
# 断言体（**判定与红证共用同一份** —— 谁把判据改弱，下面的机读红证同步变红）
# ══════════════════════════════════════════════════════════════════════════════


def assert_card_498_red(verdict_fn=order_confirmation_verdict):
    """核心断言体：卡上 ¥498（10 米 + 2.8 米）↔ 落库 ¥133.80（1 米）⇒ 必红且点名两边数值。"""
    v = verdict_fn(_DB_133_80, _facts(_CARD_498))
    assert v["verdict"] == ORDER_VERDICT_MISMATCH, (
        f"卡值↔落库值不一致却判成 {v['verdict']} —— F22 的守护没了："
        f"卡上 498.0（{_facts(_CARD_498)}）vs 落库 133.8（{_facts(_DB_133_80)}）；判定={v}")
    assert "498" in v["reason"] and "133.8" in v["reason"], (
        f"判红但**没有点名两边数值**（不可归因）：{v['reason']}")
    assert v["confirmed"] == _facts(_CARD_498) and v["actual"] == _facts(_DB_133_80), (
        "两侧事实串没有被原样带出 ⇒ 排查时看不到到底哪份是哪份")
    return v


def assert_no_card_undecidable(verdict_fn=order_confirmation_verdict):
    """判别力断言体：**没有卡**（无确认快照）⇒ 不可判定，而**不是**绿。"""
    v = verdict_fn(_DB_133_80, "")
    assert v["verdict"] == ORDER_VERDICT_UNDECIDABLE, (
        f"没有卡却给出 {v['verdict']} —— 「没法比对」被静默当成「对得上」"
        f"（卡上 498.0 vs 落库 133.8，只是无从核对）：{v}")
    assert v["verdict"] != ORDER_VERDICT_MATCH, "不可判定与一致必须可区分（这是本单的①）"
    return v


def _neutered(payload, confirmed_facts):
    """「守护被摘掉」的等价形态：判据源恒判 match（= 改前那种"全系统无一处校验"）。"""
    return {"verdict": ORDER_VERDICT_MATCH, "reason": "MUTATED", "confirmed": "", "actual": ""}


class TestCoverageCensus:
    """类级元守卫：**每条落库写路径都必须表态**（未登记即红、陈旧即红）。"""

    def test_census_is_not_empty(self):
        """防空转：名册扫到空集时下面几条差集会在空集上恒真（空断言）。"""
        live = live_write_paths()
        assert live, f"`{TOOLS_DIR}` 扫不到任何写路径 —— 现取口径失效，本判据会空转假绿"
        assert "order_create" in live, (
            f"名册里没有 order_create（F22 的实证域）⇒ 扫描口径已漂移：{sorted(live)}")

    def test_every_write_path_is_enrolled(self):
        """双向相等：新增落库路径未登记 ⇒ 红；工具退场而条目留着 ⇒ 也红。"""
        missing, stale = coverage_gaps(live_write_paths(), CARD_DB_CONSISTENCY_LEDGER)
        assert not missing, (
            "以下落库写路径**没有登记进卡值↔落库比对台账**（F22 类级元守卫：新写路径必须表态）"
            f"：{missing}\n"
            "出口：在 `app/tools/confirm_value.py::CARD_DB_CONSISTENCY_LEDGER` 登记"
            "`stance`（amount_guarded / value_guarded）或登记为 `undecidable` 并写明 "
            "reason + issue + owner。")
        assert not stale, (
            f"台账里有**陈旧条目**（不再是源码面写路径，或缺类属性 name）：{stale}\n"
            "出口：删掉该条目，或把源码面口径对齐（两者必须双向相等）。")

    def test_census_prints_undecidable_list(self):
        """把「结构上判不了」的清单**打印出来**（不许静默跳过）—— 用 `-s` 看清单。"""
        ledger = CARD_DB_CONSISTENCY_LEDGER
        groups = {"amount_guarded": [], "value_guarded": [], "undecidable": []}
        for name, entry in sorted(ledger.items()):
            groups.setdefault(str(entry.get("stance")), []).append(name)
        print(f"\n[census] 现取落库写路径 = {len(live_write_paths())} 条")
        print(f"[census] 已登记 = {len(ledger)} 条 "
              f"（amount_guarded={len(groups['amount_guarded'])} / "
              f"value_guarded={len(groups['value_guarded'])} / "
              f"undecidable={len(groups['undecidable'])}）")
        for name in groups["undecidable"]:
            entry = ledger[name]
            print(f"[census][不可判定] {name}：{entry.get('reason')} "
                  f"(issue={entry.get('issue')} owner={entry.get('owner')})")
        assert len(live_write_paths()) == len(ledger), (
            "现取名册与台账条数不等 ⇒ 覆盖面判据失效（见 test_every_write_path_is_enrolled）")

    def test_guarded_stances_have_a_real_carrier(self):
        """被声明的比对载体必须**真的存在**（声明与源码不符 ⇒ 红，防"登记了却没载体"）。"""
        props = live_write_paths()
        for name, entry in sorted(CARD_DB_CONSISTENCY_LEDGER.items()):
            stance = entry.get("stance")
            if stance == AMOUNT_GUARDED:
                assert confirmed_order_facts_of(name, dict(_PROBE_ORDER_ARGS)), (
                    f"{name} 声明 {AMOUNT_GUARDED} 但订单事实守护域**不覆盖**它"
                    f"（真值源：`base_skill.confirmed_order_facts_of` 对该工具返回空）")
            elif stance == VALUE_GUARDED:
                hit = set(props.get(name) or ()) & set(CARD_ONLY_VALUE_FIELDS)
                assert hit, (
                    f"{name} 声明 {VALUE_GUARDED} 但其参数面**没有任何**涉钱值字段"
                    f"（{sorted(CARD_ONLY_VALUE_FIELDS)}）⇒ 按值比对无对象，声明已陈旧")
            elif stance == UNDECIDABLE:
                for field in _UNDECIDABLE_FIELDS:
                    assert str(entry.get(field) or "").strip(), (
                        f"{name} 登记为 {UNDECIDABLE} 却缺 `{field}` ⇒ 缺口匿名（§23 G5）")
            else:
                raise AssertionError(
                    f"{name} 的 stance 不认识：{stance!r}（只允许 "
                    f"{AMOUNT_GUARDED} / {VALUE_GUARDED} / {UNDECIDABLE}）")


class TestCardValueVsDbValue:
    """实例判据：台账那组真实数字必须**红并点名两边数值**；一致不得红；无从比对报不可判定。"""

    def test_card_498_vs_db_133_80_is_mismatch_and_names_both(self):
        """🔴 本单的核心读数：卡上 ¥498（10 米 + 2.8 米）落库 ¥133.80（1 米）⇒ 必须红。"""
        assert_card_498_red()

    def test_identical_facts_are_not_red(self):
        """反向：同一份明细 ⇒ `match`，且运行时放行（不得"恒拦"）。"""
        facts = _facts(_CARD_498)
        v = order_confirmation_verdict(_CARD_498, facts)
        assert v["verdict"] == ORDER_VERDICT_MATCH, f"一致却判红（假红）：{v}"
        assert order_confirmation_mismatch(_CARD_498, facts) == "", (
            "运行时：一致必须放行（本单不改产品口径）")

    def test_no_card_is_undecidable_not_green(self):
        """判别力自证：**没有卡**（无确认快照）⇒ 不可判定，而**不是**绿。"""
        assert_no_card_undecidable()

    def test_no_db_value_is_undecidable_not_green(self):
        """判别力自证：**没有落库值**（payload 复算不出事实）⇒ 不可判定，而不是绿。"""
        v = order_confirmation_verdict({"customer_phone": "13800138000"}, _facts(_CARD_498))
        assert v["verdict"] == ORDER_VERDICT_UNDECIDABLE, (
            f"没有落库值却给出 {v['verdict']}：{v}")

    def test_unparsable_snapshot_is_undecidable_not_green(self):
        """形态读不懂（非订单事实 JSON）⇒ 不可判定，不臆断。"""
        v = order_confirmation_verdict(_DB_133_80, "手机号=13800138000")
        assert v["verdict"] == ORDER_VERDICT_UNDECIDABLE, f"快照读不懂却给 {v['verdict']}：{v}"

    def test_every_verdict_carries_a_reason(self):
        """三态都必须说得出"凭什么"（理由为空 ⇒ 红绿都不可归因）。"""
        cases = [
            (_DB_133_80, _facts(_CARD_498)),
            (_CARD_498, _facts(_CARD_498)),
            (_DB_133_80, ""),
        ]
        for payload, prior in cases:
            v = order_confirmation_verdict(payload, prior)
            assert str(v.get("reason") or "").strip(), f"{v['verdict']} 没给理由：{v}"

    def test_runtime_wrapper_is_exactly_the_mismatch_projection(self):
        """运行时护栏**一字未动**：wrapper 只在 mismatch 时给话术，其余一律放行。"""
        for payload, prior in [(_DB_133_80, _facts(_CARD_498)),
                               (_CARD_498, _facts(_CARD_498)),
                               (_DB_133_80, ""),
                               (_DB_133_80, "手机号=13800138000")]:
            v = order_confirmation_verdict(payload, prior)
            expected = v["reason"] if v["verdict"] == ORDER_VERDICT_MISMATCH else ""
            assert order_confirmation_mismatch(payload, prior) == expected, (
                f"wrapper 与三态判据源脱节（{v['verdict']}）⇒ 运行时与审计面各说各话")


class TestMoneyValuePaths:
    """涉钱**值**面（`value_guarded`）：卡上的价 ↔ 本次要落库的价。"""

    CARD_VALUES = {"price": 199.0, "before_price": 168.0}

    def test_same_values_are_not_red(self):
        v = card_db_verdict("product_update", args={"price": 199.0, "before_price": 168.0},
                            prior_values=self.CARD_VALUES)
        assert v["verdict"] == ORDER_VERDICT_MATCH, f"同一个价却判红（假红）：{v}"

    def test_changed_price_is_mismatch_and_names_both_values(self):
        """卡上价 199、本次落库 299 ⇒ 必红且点名两边数值。"""
        v = card_db_verdict("product_update", args={"price": 299.0, "before_price": 168.0},
                            prior_values=self.CARD_VALUES)
        assert v["verdict"] == ORDER_VERDICT_MISMATCH, f"换价却放行：{v}"
        assert "199" in v["reason"] and "299" in v["reason"], f"未点名两边数值：{v['reason']}"

    def test_no_card_value_is_undecidable_not_green(self):
        v = card_db_verdict("product_update", args={"price": 299.0}, prior_values={})
        assert v["verdict"] == ORDER_VERDICT_UNDECIDABLE, f"没有卡值却给 {v['verdict']}：{v}"

    def test_no_value_in_call_is_undecidable_not_green(self):
        """本次调用不带涉钱面值字段（改名/上下架）⇒ 不可判定，交回既有语义。"""
        v = card_db_verdict("product_update", args={"name": "新名字"},
                            prior_values=self.CARD_VALUES)
        assert v["verdict"] == ORDER_VERDICT_UNDECIDABLE, f"无值可比却给 {v['verdict']}：{v}"
        assert write_value_facts({"name": "新名字"}) == {}, "值清单口径变了（本判据失去对象）"

    def test_undecidable_ledger_entries_report_their_reason(self):
        """登记为不可判定的路径：判据必须**复述台账理由**（不是悄悄返回绿）。"""
        for name, entry in sorted(CARD_DB_CONSISTENCY_LEDGER.items()):
            if entry.get("stance") != UNDECIDABLE:
                continue
            v = card_db_verdict(name, args={})
            assert v["verdict"] == ORDER_VERDICT_UNDECIDABLE, (
                f"{name} 登记为不可判定，判据却给 {v['verdict']}")
            assert v["reason"] == entry["reason"], (
                f"{name} 判据理由与台账登记不一致 ⇒ 两处各说各话：{v['reason']!r}")


class TestUnenrolledIsNeverGreen:
    """未登记路径 ⇒ `unenrolled`（调用侧也拿不到绿），与判据侧的"未登记即红"两侧兜住。"""

    def test_unregistered_path_returns_unenrolled_not_match(self):
        v = card_db_verdict("brand_new_money_tool", args={"price": 1.0})
        assert v["verdict"] == VERDICT_UNENROLLED, (
            f"未登记的写路径给出了 {v['verdict']} —— 新路径默默落地即零信号：{v}")
        assert v["verdict"] != ORDER_VERDICT_MATCH
        assert "未登记" in v["reason"], f"未点明「未登记」这个可行动出口：{v['reason']}"


class TestRedProofs:
    """判据自身的红证：把负例喂进**生产用的**helper，证明它会红（不是"没扫到东西的绿"）。

    前两条是**机读红证**（每次 CI 都跑）：变异体喂进与判定**共用**的断言体，
    必须当场抛 `AssertionError` 并点名两边数值 —— 谁把判据改弱，这两条同步变红。
    """

    def test_machine_red_proof_neutered_source_is_caught(self):
        """机读红证：判据源恒判 match（= 守护被摘掉）⇒ 核心断言体**必须**抛 AssertionError。"""
        with pytest.raises(AssertionError) as ei:
            assert_card_498_red(_neutered)
        assert "498" in str(ei.value) and "133.8" in str(ei.value), (
            f"红证不点名两边数值（不可归因）：{ei.value}")

    def test_machine_red_proof_undecidable_collapse_is_caught(self):
        """机读红证：变异后「没有卡」被算成绿 ⇒ 判别力断言体**必须**抛 AssertionError。"""
        with pytest.raises(AssertionError) as ei:
            assert_no_card_undecidable(_neutered)
        assert "没有卡" in str(ei.value), f"红证未点名不可判定形态：{ei.value}"

    def test_injected_unregistered_path_is_named(self):
        live = dict(live_write_paths())
        live["injected_brand_new_write_tool"] = {"price"}
        missing, stale = coverage_gaps(live, CARD_DB_CONSISTENCY_LEDGER)
        assert missing == ["injected_brand_new_write_tool"], (
            f"注入未登记路径后 coverage_gaps 没点名它 ⇒ 覆盖面判据无判别力：{missing} / {stale}")
        assert not stale

    def test_injected_stale_entry_is_named(self):
        enrolled = dict(CARD_DB_CONSISTENCY_LEDGER)
        enrolled["injected_retired_write_tool"] = {"stance": UNDECIDABLE}
        missing, stale = coverage_gaps(live_write_paths(), enrolled)
        assert stale == ["injected_retired_write_tool"], (
            f"注入陈旧条目后 coverage_gaps 没点名它 ⇒ 「只许缩短」不可执行：{missing} / {stale}")
        assert not missing

    def test_carrier_probe_rejects_a_stale_value_claim(self):
        """把 `value_guarded` 声明挂到**没有**涉钱字段的工具上 ⇒ 载体探针必须判否。"""
        props = live_write_paths()
        stripped = dict(props)
        stripped["product_update"] = set(props["product_update"]) - set(CARD_ONLY_VALUE_FIELDS)
        assert not (set(stripped["product_update"]) & set(CARD_ONLY_VALUE_FIELDS)), (
            "注入无效（剥离后仍有涉钱字段）⇒ 本红证证明不了探针的判别力")
        assert set(props["product_update"]) & set(CARD_ONLY_VALUE_FIELDS), (
            "product_update 真实参数面里没有涉钱字段 ⇒ 台账的 value_guarded 声明已陈旧")

    def test_card_field_projection_still_carries_the_money(self):
        """交叉验证 `#4072` 的那一半仍在：卡面投影必须带数量/单价/小计/合计。

        去掉即红 —— 卡上"给用户看的值"没有机器可读的那一份时，本守护就无从比对。
        """
        from app.graph.skills.base_skill import confirm_card_fields
        fields = confirm_card_fields(json.loads(json.dumps(_CARD_498)))
        labels = [f["label"] for f in fields]
        for want in ("数量", "单价", "小计", "合计"):
            assert want in labels, f"确认卡投影缺「{want}」⇒ 卡上的钱无人可核：{labels}"