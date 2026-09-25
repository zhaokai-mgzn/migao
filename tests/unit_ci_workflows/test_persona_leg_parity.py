# case_ids: CH-008, CH-010, CH-015, OR-013, OR-016, PR-018, ST-008
"""评测 runner 的**跨腿完整性**判据（issue #5504）。

## 缺口（改前的实测形态）

「禁止静默少跑」原先只有一层：`--case-ids` 里的 ID **能不能在用例库里解析出来**
（`local_runner.filter_cases_by_ids` 的 `_missing` ⇒ 直接 `sys.exit(1)`）。它把两件
**不同**的事混成一件：

  · 「库里真没有这个 ID」（写错 / 抄错）—— 该红；
  · 「这个 ID 属于**另一条腿**」（`persona: xiaobu` 的用例被派发到米宝腿）—— **不该红**，
    该做的是**点名**「未覆盖该 ID + 两边去向」。改前实测（本机实跑，`--cases` 指向注入语料）：

      $ PERSONA=mibao python tests/agent_eval/local_runner.py full \\
            --cases <注入语料> --case-ids LEGX-1        # LEGX-1 声明 persona: xiaobu
      🧪 Persona=mibao：用例集过滤后 2/3 条（排除 1 条另一端专属/超出本端工具能力）
      ❌ --case-ids 里有无法解析的用例 ID: ['LEGX-1']（禁止静默少跑）

  ⇒ 库里**明明有** LEGX-1 且写着 `persona: xiaobu`，却被报成「无法解析」= **归因错**
    （误导性红，并把读者引向「用例库坏了」这个错误方向）。

## 改后的机械判据（本文件；零 LLM，全部结构化读声明对象）

`tests/agent_eval/eval_case_filter.audit_case_ids_leg_parity`：对每条请求 ID **按 persona
现取它应落的那条腿**（`persona` 字段 ⇒ 两侧去向），与「它实际声明/登记的去向」比对：

  | 形态 | 判定 |
  |---|---|
  | 归属本腿（或双端）且真的被收集 | `ok`（会执行） |
  | 归属**另一条腿** | `cross_leg` ⇒ **点名「未覆盖该 ID」+ 两边去向，不判整腿红** |
  | 归属本腿却**未被收集**（档位/分片/skip/工具集/语义丢掉） | `not_covered` ⇒ **违规（红）** |
  | 库里真没有这个 ID（含 legacy_id 口径） | `unresolved` ⇒ **违规（红）** |
  | `persona` 值不属于任何一条腿（现取不到去向） | `unjudged` ⇒ **显式登记**，不静默跳过 |

`audit_library_leg_parity` 把同一条判据铺到**全库 × 两条腿**：声明本腿却未被收集、且
**无任何显式登记**（`skip_reason` 为空）⇒ 违规；`skip_reason` 非空 = **显式登记的少跑**
（合法，进未命中清单）；声明另一条腿 ⇒ **正常跨腿**（不判红，防判据退化成「凡跨腿皆红」）。

结构化纪律（#5003 同口径）：判定只读 `persona` / `skip_reason` **字段**，不做文本子串匹配；
runner 的接线用 **AST 调用点**判定（不是 grep 源码文本）。
"""
import ast
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

from eval_case_filter import (  # noqa: E402
    LEGS,
    audit_case_ids_leg_parity,
    audit_library_leg_parity,
    declared_leg,
    judge_case_ids_leg_parity,
    leg_label,
    leg_parity_violations,
)
from render_cases import load_case_dicts  # noqa: E402

CASES_DIR = REPO_ROOT / ".github" / "cases"
RUNNER = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"
UNIMPLEMENTED_JSON = REPO_ROOT / ".github" / "case-trust-unimplemented.json"
TAXONOMY = REPO_ROOT / ".github" / "assertion_taxonomy.py"
WITHDRAWN_CODE = "CASE-TRUST-CROSS-LEG-NARROW-RUN"

#: 红证①的注入语料：**声明落小布腿**的用例（无 skip_reason ⇒ 无显式登记）
INJ_XIAOBU = {"id": "INJ-X1", "persona": "xiaobu", "tier": "smoke",
              "user_inputs": [{"text": "我的订单到哪了"}],
              "expectations": [{"tool": "customer_order_query"}]}
#: 红证②的注入语料：**声明落米宝腿**、`persona` 值合法但被某个过滤器悄悄丢掉
INJ_MIBAO = {"id": "INJ-M1", "persona": "mibao", "tier": "normal",
             "user_inputs": [{"text": "看看经营概览"}],
             "expectations": [{"tool": "dashboard_stats"}]}


def _call_name(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _calls(tree, name: str) -> list:
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and _call_name(n.func) == name]


def _legacy_missing_ids(requested, universe) -> list:
    """**改前口径的复算**（判据判别力的对照臂）：只判「ID 能不能解析」，不看 persona。

    这就是 origin/main 的 `filter_cases_by_ids` + `_missing` 分支做的事 ——
    把它写在这里，是为了让「同一份输入：旧口径放行 / 新判据报违规」这件事**可执行**，
    而不是只在 PR 正文里贴读数。
    """
    known = set()
    for c in universe:
        for k in ("id", "legacy_id"):
            v = c.get(k) if isinstance(c, dict) else getattr(c, k, "")
            if str(v or "").strip():
                known.add(str(v))
    want = [x.strip() for x in str(requested or "").split(",") if x.strip()]
    return [x for x in want if x not in known]


class TestCaseIdsCrossLegParity:
    """运行期判据：`--case-ids` 的跨腿完整性（#5504 的验收标准）。"""

    def test_cross_leg_id_is_named_and_not_graded_red(self):
        """跨腿 ID ⇒ **显式点名**「未覆盖该 ID」+ 两边去向，且**不判整腿红**（反向红证）。"""
        report = audit_case_ids_leg_parity("INJ-X1", [INJ_XIAOBU], [], "mibao", suite="full")
        assert leg_parity_violations(report) == [], (
            f"跨腿登记被判成了违规 —— 判据退化成「凡跨腿皆红」：{report}")
        named = report["cross_leg"]
        assert len(named) == 1, f"跨腿 ID 没有被点名（这就是「静默少跑」）：{report}"
        entry = named[0]
        assert entry["id"] == "INJ-X1"
        assert entry["declared"] == "xiaobu"
        assert entry["declared_leg"] == leg_label("xiaobu")
        assert entry["run_leg"] == leg_label("mibao")
        # 本腿仍有 1 条可跑 ⇒ 裁决不 fatal（「不判整腿红」的可执行形态）
        fatal, code, msg = judge_case_ids_leg_parity(report, will_run=1)
        assert (fatal, code) == (False, 0), f"跨腿登记把整腿判红了：{msg}"

    def test_declared_here_but_not_collected_is_a_violation(self):
        """红证②：声明本腿 + 无显式登记 + 未被收集 ⇒ 违规并点名（ID + persona + 两边去向）。"""
        report = audit_case_ids_leg_parity("INJ-M1", [INJ_MIBAO], [], "mibao", suite="smoke")
        bad = leg_parity_violations(report)
        assert len(bad) == 1, f"「登记在本腿却没被收集」没有报违规：{report}"
        entry = bad[0]
        assert (entry["id"], entry["declared"], entry["run"]) == ("INJ-M1", "mibao", "mibao")
        assert "未被本腿收集" in entry["why"]
        fatal, code, msg = judge_case_ids_leg_parity(report, will_run=0)
        assert (fatal, code) == (True, 1)
        assert "INJ-M1" in msg, f"判红没有点名用例 ID：{msg}"

    def test_unresolved_id_keeps_the_red(self):
        """真不存在的 ID 仍要红（归因换成「库中没有」，不是「跨腿」）。"""
        report = audit_case_ids_leg_parity("NOPE-999", [INJ_MIBAO], [], "mibao")
        assert [e["id"] for e in report["unresolved"]] == ["NOPE-999"]
        assert report["cross_leg"] == []
        fatal, code, _ = judge_case_ids_leg_parity(report, will_run=0)
        assert (fatal, code) == (True, 1)

    def test_all_cross_leg_is_fatal_but_attributed_to_uncovered(self):
        """全被跨腿覆盖 ⇒ 仍**非零退出**（空跑禁假绿），但归因 = 「未覆盖」而非「无法解析」。"""
        report = audit_case_ids_leg_parity("INJ-X1", [INJ_XIAOBU], [], "mibao")
        fatal, code, msg = judge_case_ids_leg_parity(report, will_run=0)
        assert (fatal, code) == (True, 1)
        assert "未覆盖" in msg
        assert "无法解析" not in msg, f"空跑仍按「ID 无法解析」归因（#5504 修的正是这条）：{msg}"

    def test_discrimination_self_proof_legacy_rule_stays_blind(self):
        """判别力自证：同一份「少跑一条」输入 —— 旧口径放行，本判据报违规。"""
        requested, universe, collected = "INJ-M1", [INJ_MIBAO], []
        assert _legacy_missing_ids(requested, universe) == [], (
            "对照臂自身写错了：旧口径在库中有该 ID 时不会报任何东西（= 静默少跑）")
        report = audit_case_ids_leg_parity(requested, universe, collected, "mibao")
        assert [e["id"] for e in leg_parity_violations(report)] == ["INJ-M1"]

    def test_unjudged_persona_value_is_registered_not_skipped(self):
        """无法判定的形态（persona 值不属任何一条腿）⇒ 显式登记，不静默跳过。"""
        weird = dict(INJ_MIBAO, id="INJ-W1", persona="bothish")
        report = audit_case_ids_leg_parity("INJ-W1", [weird], [], "mibao")
        assert [e["id"] for e in report["unjudged"]] == ["INJ-W1"]
        assert report["cross_leg"] == [] and report["ok"] == []
        assert leg_parity_violations(report) == [], "无法判定不该按违规读（它是显式登记）"


class TestLibraryLegParity:
    """全库判据：**按 persona 现取**的腿 vs 实际声明/登记的腿（现取，不写死数字）。"""

    def test_real_library_has_no_silent_under_run(self):
        cases = load_case_dicts(str(CASES_DIR))
        report = audit_library_leg_parity(cases)
        assert report["violations"] == [], (
            "出现「静默少跑」：声明归属某腿、却未被该腿收集且无显式登记 ——\n"
            + "\n".join(f"  · {e['id']}：{e['why']}" for e in report["violations"]))
        # 判据不许空跑：两条腿都要有收集量、库里必须有单腿声明（否则「通过」没有意义）
        for leg in LEGS:
            bucket = report["counts"][leg]
            assert bucket["collected"] > 0, f"{leg} 腿收集集为空 ⇒ 本判据在该腿上空跑"
            assert set(bucket) == {"collected", "other_leg", "registered_skip",
                                   "silent", "dual_leg_narrowed", "unjudged"}
        assert sum(1 for c in cases if declared_leg(c) in LEGS) > 0

    def test_registered_skip_is_explicit_not_silent(self):
        """合法少跑必须**带显式登记**：进清单的每一条都读得到 `skip_reason`（结构化字段）。"""
        cases = load_case_dicts(str(CASES_DIR))
        report = audit_library_leg_parity(cases)
        by_id = {str(c.get("id")): c for c in cases}
        seen = 0
        for leg in LEGS:
            for e in report["legs"][leg]["registered_skip"]:
                assert str(by_id[e["id"]].get("skip_reason") or "").strip(), (
                    f"{e['id']} 被记成「显式登记的少跑」但 skip_reason 为空 ⇒ 登记是假的")
                seen += 1
        assert seen > 0, "没有任何「显式登记的少跑」被记账 —— 该分支可能从未被执行"

    def test_declared_but_not_collected_injection_is_red(self):
        """红证①：注入一条**声明落小布腿**、却被本腿收集集漏掉的用例 ⇒ 判红并点名。"""
        report = audit_library_leg_parity([INJ_XIAOBU], selected={"xiaobu": [], "mibao": []})
        assert len(report["violations"]) == 1, f"注入的少跑形态没有被判红：{report['counts']}"
        entry = report["violations"][0]
        assert (entry["id"], entry["declared"], entry["run"]) == ("INJ-X1", "xiaobu", "xiaobu")
        assert entry["declared_leg"] == leg_label("xiaobu")
        assert "静默少跑" in entry["why"]

    def test_normal_cross_leg_declaration_is_not_red(self):
        """反向红证：正常跨腿声明（单腿用例只跑自己那条腿）**不得**判红。"""
        cases = load_case_dicts(str(CASES_DIR))
        report = audit_library_leg_parity(cases)
        collected = {leg: {e["id"] for e in report["legs"][leg]["collected"]} for leg in LEGS}
        single_mibao = {str(c.get("id")) for c in cases if declared_leg(c) == "mibao"}
        single_xiaobu = {str(c.get("id")) for c in cases if declared_leg(c) == "xiaobu"}
        assert single_mibao and single_xiaobu, "库里没有单腿声明的用例 ⇒ 反向判据空跑"
        # 米宝单腿用例出现在小布腿的「正常跨腿」桶里（而不是违规桶）才算判据没写歪
        other_leg_xiaobu = {e["id"] for e in report["legs"]["xiaobu"]["other_leg"]}
        assert single_mibao - collected["mibao"] - other_leg_xiaobu == set(), (
            "有米宝单腿用例既没进米宝腿收集集、也没被记成「正常跨腿」")
        assert not (single_mibao & {e["id"] for e in report["violations"]})
        assert not (single_xiaobu & {e["id"] for e in report["legs"]["xiaobu"]["silent"]})
        # 双端用例未命中本腿必须能归因（工具集/语义收口），不许凭空消失
        dual = {str(c.get("id")) for c in cases if declared_leg(c) == "both"}
        bucketed = (collected["xiaobu"]
                    | {e["id"] for e in report["legs"]["xiaobu"]["dual_leg_narrowed"]}
                    | {e["id"] for e in report["legs"]["xiaobu"]["registered_skip"]})
        assert dual - bucketed == set(), "有双端用例在小布腿上既没跑、也没被显式记账"


class TestRunnerWiring:
    """runner 侧的接线（**AST 调用点**判定；不做源码文本匹配）。"""

    def _tree(self):
        return ast.parse(RUNNER.read_text(encoding="utf-8"))

    def test_guard_is_called_before_dispatch_and_consumed(self):
        tree = self._tree()
        guard = _calls(tree, "audit_case_ids_leg_parity")
        judge = _calls(tree, "judge_case_ids_leg_parity")
        dispatch = _calls(tree, "run_suite")
        assert guard, "runner 没有接线跨腿完整性判据（--case-ids 仍按旧口径判）"
        assert judge, "判据只被打印、没有被**消费**（裁决结果没人用 ⇒ 等于没判）"
        assert dispatch, "找不到 run_suite 调用点 —— 本判据的坐标前提失效"
        assert min(c.lineno for c in guard) < min(d.lineno for d in dispatch), (
            "跨腿完整性判据被放在派发之后 —— 违反「零 LLM 先判」"
            "（跑完才判 = 已经烧了 LLM 成本）")

    def test_no_bare_missing_ids_exit_anymore(self):
        """改前的 `if _missing: … sys.exit(1)` 裸红必须消失（归因改由判据给出）。"""
        tree = self._tree()
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
            if "_missing" not in names:
                continue
            if any(_call_name(n.func) == "exit" for n in ast.walk(node)
                   if isinstance(n, ast.Call)):
                offenders.append(node.lineno)
        assert offenders == [], (
            f"runner 仍在按 `_missing` 直接判红（归因错 ⇒ 误导性红/误导评论）：第 {offenders} 行")


class TestRegistrationWithdrawn:
    """#5504 实装 ⇒ 必须**撤**未实装登记（留着就是与实现相反的假真值）。"""

    def test_unimplemented_registration_is_withdrawn(self):
        data = json.loads(UNIMPLEMENTED_JSON.read_text(encoding="utf-8"))
        codes = [str(i.get("code")) for i in (data.get("unimplemented") or [])]
        assert WITHDRAWN_CODE not in codes, (
            f"`{WITHDRAWN_CODE}` 已实装（runner 侧按 persona 校验跨腿完整性）"
            f"⇒ 必须从 {UNIMPLEMENTED_JSON.name} 撤登记；留着会被读成「还没做」")
        # 同一份清单的另一半在 assertion_taxonomy.UNIMPLEMENTED（结构化读 AST 常量，不 grep）
        tree = ast.parse(TAXONOMY.read_text(encoding="utf-8"))
        assigned = set()
        for node in ast.walk(tree):
            # `UNIMPLEMENTED: tuple[dict, ...] = (…)` 是 **AnnAssign**（带注解），
            # 只认 `ast.Assign` 会让本判据静默空跑成绿（取空集 ⇒ 断言恒真）。
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if not any(isinstance(t, ast.Name) and t.id == "UNIMPLEMENTED" for t in targets):
                    continue
                value = node.value
                if value is None:
                    continue
                assigned |= {n.value for n in ast.walk(value)
                             if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        assert assigned, "`assertion_taxonomy.UNIMPLEMENTED` 取空 ⇒ 本判据会静默空跑成绿"
        assert WITHDRAWN_CODE not in assigned, (
            f"`assertion_taxonomy.UNIMPLEMENTED` 里仍留着 {WITHDRAWN_CODE}（两份清单必须一致）")


def test_pytest_collects_this_module():
    """防「文件路径/命名不合法 ⇒ 一条都没收集」被读成通过（RC=4 是用法错误，不是判据红）。"""
    assert Path(__file__).name.startswith("test_")
    assert RUNNER.exists() and CASES_DIR.is_dir()


if __name__ == "__main__":       # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))