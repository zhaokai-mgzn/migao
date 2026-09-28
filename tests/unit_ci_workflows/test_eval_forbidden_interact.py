# case_ids: OR-014
"""负向**按轮**卡片约束（`forbidden_interact`）：把「红色形态」钉进用例（issue #3789）。

## 病灶（判定跑实证：同一个用例，红/绿由"agent 当轮是否抽卡"决定）

| | 红（run 34856561459） | 绿（run 34864608826） |
|---|---|---|
| R2 agent 问加工项 | **纯文本**（无 `interact`） | 发了 `interact(choice, multiSelect)` 卡 |
| R3 输入 | fallback「不需要其他加工项」 | harness `auto_respond` **答了那张卡** |
| R3 路由 | **非答卡轮** ⇒ L1 域逃逸清锁（#3784 窗口）⇒ `product` skill（无 `order_create`） | **答卡轮** ⇒ #3718 卡型豁免 ⇒ 留在订单流程 |
| 结果 | 自称落不了单、`order_create` 从未发生 | 正常落单 |

⇒ 该用例**永远可能**走 #3718 的安全路径（绿），于是「修复 #3785 的行为侧判别性验证」
**无法稳定复现**；反过来，一次绿也**不能**证明修法有效（issue #3789 原文）。

## 修法（runner 的最小扩展）

新增家族 `forbidden_interact`：声明**某一轮不得出现 `interact` 卡**（可限定卡型）。
它与既有家族**不重叠**：
`forbidden_card_text` 管**卡里的字**（卡存在才判）、`forbidden_tools` 管**全程**不得调用某工具、
`forbidden_text` 管**回复文本**（纯文本提问恰恰是期望形态）；本断言管「**本轮不得出现卡**」——
它是**用例形状的前提**（红路径的形状），故命中即判红、与 `forbidden_*` 家族同权
（进 `case_issues` → `score=0` + 进 summary 的 `failures`）。

## 红证（三条，全部零 LLM、零栈）

① **`TestGreenFormIsNowRed`**：把**绿形态**的逐轮结果喂给判据 ⇒ 必须判红；
   同一份轨迹喂给**既有全部家族** ⇒ 全部返回空（= 改前 runner **没有任何能力**判出它）
   ⇒ 这条红证同时证明"旧判据对该形态是**盲的**"（不是"我新写的判据恒红"）。
② **`TestTheFixIsWhatMakesItRed`**：把约束**忽略/误评**（注入式退化）⇒ 绿形态重新变成"全绿"
   ⇒ 前者那条红证会失败（判据不是恒真）。
③ **`TestConstraintIsWiredEndToEnd`**：`.github/cases/order.yml` → CI 的 YAML 装载路径
   （`load_cases_from_yaml`）→ 用例对象；漏映射即红（否则又是"声明了没人消费"的假绿）。
"""
import re
import sys
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

import local_runner as lr  # noqa: E402


# ─────────────────────── OR-014 的两种分流形态（判定跑逐轮实证的复刻）───────────────────────

def _card(component: str = "choice", title: str = "是否需要加工项？") -> dict:
    return {"type": component, "component": component, "title": title,
            "options": [{"label": "打孔 · ¥9.5/米", "value": "打孔"}],
            "multiSelect": True, "multiSelectSkipLabel": "不需要加工项"}


def _round(n: int, *, text: str = "", cards: list = None, tools: list = None,
           args: dict = None) -> dict:
    return {"__round": n, "final_text": text, "interactive": list(cards or []),
            "tool_calls": [{"name": t, "args": dict(args or {}) if t == "order_create" else {}}
                           for t in (tools or [])]}


#: 一次**合法**下单的入参（`processing_info` 嵌套层是 issue #3789 的字段级证据面）
ORDER_ARGS = {"items": [{"product_name": "遮光窗帘", "quantity": 3, "unit_price": 168,
                         "processing_info": {"colorName": "米白",
                                             "processingItems": [{"id": "pi_punch",
                                                                  "name": "打孔",
                                                                  "quantity": 3,
                                                                  "unit": "米"}]}}]}

# ⚠️ 轮次是**位置**语义（`idx = round - 1`，与 `forbidden_text` / `want_text` 同口径）
# ⇒ 夹具必须从 R1 起逐轮给全，不能只给被判的那两轮（否则"越界"分支会顶掉被测分支）。
GREEN_FORM = [
    _round(1, text="帮我下单，遮光窗帘 3 米，要打孔加工", tools=["product_detail"]),
    # R2 **发了卡**（= 绿形态：harness 会答这张卡 ⇒ 答卡轮豁免 ⇒ 留在 order）
    _round(2, text="请选择需要的加工项", cards=[_card()], tools=["product_detail"]),
    _round(3, text="✅ 已为您下单成功（订单号 EVAL-ORD-0001）",
           cards=[_card("confirm", "确认下单？")], tools=["order_create"], args=ORDER_ARGS),
]
RED_FORM = [
    _round(1, text="帮我下单，遮光窗帘 3 米，要打孔加工", tools=["product_detail"]),
    # R2 **纯文本**（= 判别性红形态：R3 的文本答复不是答卡轮 ⇒ L1 域逃逸清锁）
    _round(2, text="还需要其他加工项吗？不需要的话回复「不需要其他加工项」",
           tools=["product_detail"]),
    _round(3, text="我这条线负责商品，落单请回「转人工」"),
]

CONSTRAINT = [{"round": 2}]


class TestGreenFormIsNowRed:
    """**红证①**：绿形态（R2 抽卡）必须判红；同一轨迹对既有家族**全部不可见**。"""

    def test_green_form_is_judged_red_by_the_new_family(self):
        issues = lr.check_forbidden_interact(GREEN_FORM, CONSTRAINT)
        assert len(issues) == 1, f"绿形态没有被判红（判据空转）：{issues}"
        assert "R2 出现了 interact 卡" in issues[0], issues[0]
        assert "choice" in issues[0], f"卡型没有进归因原文：{issues[0]}"

    def test_red_form_stays_clean(self):
        """反向：判别性红形态（R2 纯文本）**不得**被本断言判红 —— 否则它是恒红的空断言。"""
        assert lr.check_forbidden_interact(RED_FORM, CONSTRAINT) == []

    def test_no_preexisting_family_can_see_the_green_form(self):
        """**改前的盲区就是本单的病灶**：把**用例真会写**的那套既有断言（OR-014 的声明）
        套到绿形态轨迹上 ⇒ **全部返回空** ⇒ 该 run 计分 100%（判绿）。

        这条同时证明上面那条红证不是"我新写的判据恒红"：**同一个输入**，既有家族全空、
        新家族命中。⚠️ 前提自证：同一套既有断言套到**红形态**上，必须由 `must_succeed`
        那类断言之一下沉（这里用 `check_want_text` 的缺失形态做代表）—— 否则说明我拿了一组
        本来就"什么都不查"的空 spec 在凑红证。
        """
        for name, got in (
            ("forbidden_text", lr.check_forbidden_text(GREEN_FORM, ["落不了单"])),
            ("forbidden_card_text", lr.check_forbidden_card_text(GREEN_FORM, ["用量"])),
            ("forbidden_tools", lr.check_forbidden_tools(GREEN_FORM, ["refund_apply"])),
            ("order_before（confirm 先行）", lr.check_order_before(
                GREEN_FORM, ["interact[confirm] before order_create"])),
            ("forbidden_args", lr.check_forbidden_args(GREEN_FORM, [])),
            ("required_args（四键存在性）", lr.check_required_args(GREEN_FORM, [
                {"tool": "order_create",
                 "fields": ["items[].processing_info.processingItems[].quantity"]}])),
            ("want_text（下单成功话术）", lr.check_want_text(GREEN_FORM, ["下单成功"])),
        ):
            assert got == [], f"{name} 竟然对绿形态有输出（本红证的前提不成立）：{got}"
        # 前提自证：同一组断言**能**在别的形态上出声（不是"什么都不查的空 spec"）
        assert lr.check_want_text(RED_FORM, ["已为您下单成功"]), (
            "既有正/反向断言在红形态上也不出声 —— 本红证退化成了空断言")

    def test_family_is_not_satisfiable_by_saying_the_right_words(self):
        """**措辞不能顶替形状**：R2 用最礼貌的纯文本 + R3 说对话术 ⇒ 只要 R2 抽了卡就判红。

        与 `forbidden_text`（管措辞）刻意分开：这条约束管的是**用例形状**（红路径的形状），
        措辞正确不构成豁免。
        """
        shape = [
            _round(1, text="帮我下单，遮光窗帘 3 米", tools=["product_detail"]),
            _round(2, text="请问还需要其他加工项吗？不需要的话请回复「不需要其他加工项」",
                   cards=[_card("choice")]),
            _round(3, text="✅ 已按面料米数 3 米登记「打孔」加工，正在为您落单",
                   tools=["order_create"], args=ORDER_ARGS),
        ]
        assert len(lr.check_forbidden_interact(shape, CONSTRAINT)) == 1


class TestTheFixIsWhatMakesItRed:
    """**红证②（注入式）**：把约束忽略/误评 ⇒ 绿形态重新"全绿" ⇒ 判据不是恒真。"""

    def test_ignoring_the_constraint_makes_the_green_form_pass(self, monkeypatch):
        monkeypatch.setattr(lr, "check_forbidden_interact", lambda results, spec: [])
        assert lr.check_forbidden_interact(GREEN_FORM, CONSTRAINT) == [], (
            "注入式退化没有生效 —— 下面的结论不可信（红证前提必须先自证）")

    def test_wrong_round_scope_makes_the_green_form_pass(self):
        """**错评**形态：约束声明在**没有卡的那一轮**（卡实际在 R2）⇒ 判据必须放行。

        证明命中是**按轮**的（不是"整场有卡就红"）—— 否则 OR-014 后面的
        `interact[confirm]` 明细卡会把用例打成恒红。
        """
        assert lr.check_forbidden_interact(GREEN_FORM, [{"round": 1}]) == []
        assert len(lr.check_forbidden_interact(GREEN_FORM, [{"round": 2}])) == 1

    def test_card_type_scope_is_honored(self):
        """限定卡型时只对该卡型生效（`confirm` 卡不在 `choice` 的射程内）。"""
        confirm_round = [
            _round(1, text="帮我下单", tools=["product_detail"]),
            _round(2, cards=[_card("confirm", "确认下单？")]),
        ]
        assert lr.check_forbidden_interact(confirm_round, [{"round": 2, "type": "choice"}]) == []
        assert len(lr.check_forbidden_interact(confirm_round, [{"round": 2, "type": "confirm"}])) == 1
        assert len(lr.check_forbidden_interact(confirm_round, [{"round": 2}])) == 1


class TestFailClosedConfigAndScope:
    """失败关闭：不会红的断言 = 空断言（与 `forbidden_text` 的轮次作用域同口径）。"""

    def test_missing_round_is_a_violation_not_a_silent_skip(self):
        issues = lr.check_forbidden_interact(GREEN_FORM, [{"type": "choice"}])
        assert len(issues) == 1 and "round" in issues[0], issues

    def test_round_out_of_range_is_a_violation(self):
        """用例提前结束（该轮压根不存在）⇒ 约束永不成立 ⇒ 判红，不静默放过。"""
        issues = lr.check_forbidden_interact(GREEN_FORM, [{"round": 9}])
        assert len(issues) == 1 and "超出实际轮数" in issues[0], issues

    def test_empty_or_bogus_config_is_a_violation(self):
        assert len(lr.check_forbidden_interact(GREEN_FORM, [{}])) == 1
        assert len(lr.check_forbidden_interact(GREEN_FORM, ["not-a-dict"])) == 1

    def test_failure_atom_is_stable_and_round_scoped(self):
        """指纹：同一违反点两次尝试必须折成**同一个**原子（否则误判 unstable）；
        不同轮次则是**不同的违反点**（不得洗成一个）。"""
        atom_r2 = lr._failure_atom(
            "forbidden_interact: R2 出现了 interact 卡（type=choice「是否需要加工项？」）",
            lr._CASE_LEVEL_DETAIL)
        assert atom_r2 == "forbidden_interact(R2)", atom_r2
        atom_r3 = lr._failure_atom(
            "forbidden_interact: R3 出现了 interact 卡（type=form「收货信息」）",
            lr._CASE_LEVEL_DETAIL)
        assert atom_r3 == "forbidden_interact(R3)", atom_r3
        cfg = lr._failure_atom(
            "forbidden_interact: 配置缺/非法 round（None）", lr._CASE_LEVEL_DETAIL)
        assert cfg == "config_error(forbidden_interact)", cfg


class TestConstraintIsWiredEndToEnd:
    """**红证③**：用例声明 → CI 装载路径 → 运行时消费点，三段都要真的接上。"""

    def test_or014_declares_the_constraint_on_the_card_emission_round(self):
        cases = {c.id: c for c in lr.load_cases_from_yaml(str(REPO_ROOT / ".github" / "cases"))}
        or014 = cases.get("OR-014")
        if or014 is None:
            pytest.fail("OR-014 不在用例库（本判据的前提不成立）")
        assert or014.forbidden_interact == [{"round": 2}], (
            f"OR-014 的按轮禁卡约束被改掉/丢了：{or014.forbidden_interact!r} —— "
            f"它钉的是 R2「加工项提问」必须纯文本（本用例判别性红路径的形状）")

    def test_loader_maps_the_field_from_yaml(self, tmp_path):
        """**CI 走的是 YAML 装载路径**（不是生成物 `eval_cases.py`）：漏映射 = 静默不检查。"""
        d = tmp_path / "cases"
        d.mkdir()
        (d / "x.yml").write_text(
            "cases:\n"
            "  - id: TMP-1\n"
            "    title: t\n"
            "    tier: normal\n"
            "    persona: xiaobu\n"
            "    user_inputs:\n"
            "      - \"你好\"\n"
            "    forbidden_interact:\n"
            "      - round: 2\n",
            encoding="utf-8")
        case = {c.id: c for c in lr.load_cases_from_yaml(str(d))}["TMP-1"]
        assert case.forbidden_interact == [{"round": 2}], (
            f"装载器没把 forbidden_interact 送到用例对象：{case.forbidden_interact!r}")

    def test_the_runtime_consumes_the_whole_forbidden_family(self):
        """消费点必须**逐家族**接线（#3417 的形态：生成物有字段、但跑批路径不读它）。

        装配点在 `run_case`（不是 `_run_one_case`：那是 `run_suite` 里的嵌套函数）。
        """
        src = Path(lr.__file__).read_text(encoding="utf-8")
        body = src.split("async def run_case", 1)[1].split("\nasync def ", 1)[0]
        for family in ("check_forbidden_text", "check_forbidden_tools",
                       "check_forbidden_interact", "check_forbidden_card_text"):
            assert re.search(rf"case_issues \+= {family}\(", body), (
                f"`{family}` 没有出现在 case-level 断言装配处 ⇒ 声明了也不会被判（假绿）")
