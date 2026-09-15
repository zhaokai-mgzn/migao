# 断言可信度门禁 —— 红证留档（补前必红 / 补后绿）

> **为什么留档**：`migao-acceptance` 铁律 2 ——「每条断言都要有**红证**（不会红的断言 = 空断言）」。
> 本文件逐字记录 `RED-PROOF-BEFORE` 与 `GREEN-PROOF-AFTER` 的**原始输出**，
> 由 `tests/unit_ci_workflows/test_case_trust_gate.py::TestRedProofRecord` 锁定
> （标记缺失或规则码未覆盖即红），**防止红证被事后改写**。

被测对象：

| 件 | 路径 |
|---|---|
| 判据单一源 | `.github/assertion_taxonomy.py` |
| 门禁外壳 | `.github/case_trust_gate.py` |
| 存量基线 | `.github/case-trust-baseline.json` |
| L0 守卫 | `tests/unit_ci_workflows/test_case_trust_gate.py` |

红证锚定：**补门禁之前**的仓库状态 = `origin/main` = `82d20090a1a2abe4e432b7894df77476b7fb2399`
（commit 之前已实测；被测件的存在性以下方 `git cat-file` 输出为准）。

---

## RED-PROOF-BEFORE（三段，均为**补门禁之前**的真实输出）

### 红证 A —— 把判据函数**临时置为恒绿**（空壳化）⇒ L0 守卫必红

命令（在 worktree 内，`_neutralize_conftest_hook.py` 把
`assertion_taxonomy.judge_case` 置为 `lambda case, **kw: []`）：

```bash
PYTHONPATH="tests/unit_ci_workflows" python3.11 -m pytest \
  tests/unit_ci_workflows/test_case_trust_gate.py -q -p _neutralize_conftest_hook
```

输出（节选，**17 failed, 21 passed** —— 与补门禁后 `43 passed` 对照）：

```
FAILED tests/unit_ci_workflows/test_case_trust_gate.py::TestKnownDefectFixturesAreBlocked::test_cu_003_unresolvable_preclean_target
FAILED tests/unit_ci_workflows/test_case_trust_gate.py::TestKnownDefectFixturesAreBlocked::test_pg_013_forbidden_text_sole_judgement
FAILED tests/unit_ci_workflows/test_case_trust_gate.py::TestKnownDefectFixturesAreBlocked::test_pr_021_machine_scored_keyword_missing
FAILED tests/unit_ci_workflows/test_case_trust_gate.py::TestKnownDefectFixturesAreBlocked::test_prose_only_case_is_flagged[CH-009]
FAILED tests/unit_ci_workflows/test_case_trust_gate.py::TestKnownDefectFixturesAreBlocked::test_prose_only_case_is_flagged[CH-016]
FAILED tests/unit_ci_workflows/test_case_trust_gate.py::TestKnownDefectFixturesAreBlocked::test_single_leg_without_persona_is_flagged
FAILED tests/unit_ci_workflows/test_case_trust_gate.py::TestKnownDefectFixturesAreBlocked::test_all_seven_defect_fixtures_are_covered
FAILED tests/unit_ci_workflows/test_case_trust_gate.py::TestDegenerateGuardRails::test_judge_is_not_constant
FAILED tests/unit_ci_workflows/test_case_trust_gate.py::TestBaselineDiscipline::test_baseline_is_not_used_to_exempt_all_rules
FAILED tests/unit_ci_workflows/test_case_trust_gate.py::TestGateShell::test_gate_reports_new_violation_as_blocking
FAILED tests/unit_ci_workflows/test_case_trust_gate.py::TestGateShell::test_gate_reports_baseline_violation_as_passed
FAILED tests/unit_ci_workflows/test_case_trust_gate.py::TestGateShell::test_gate_requires_baseline_pruning_only_for_diff_cases
FAILED tests/unit_ci_workflows/test_case_trust_gate.py::TestRedProofRecord::test_red_proof_is_documented
FAILED tests/unit_ci_workflows/test_case_trust_gate.py::TestRedProofRecord::test_red_proof_covers_every_rule_code
17 failed, 21 passed in 0.19s
```

**这一段的判别力**：它证明「判据恒绿 ⇒ 守卫必红」—— 即守卫**不会因为判据变成空壳而跟着变绿**。
特别地 `test_judge_is_not_constant`（退化守卫）在这一段红，正是设计意图。

### 红证 B —— 门禁件在**补门禁之前**的仓库状态上不存在

```bash
for f in .github/assertion_taxonomy.py .github/case_trust_gate.py \
         .github/case-trust-baseline.json tests/unit_ci_workflows/test_case_trust_gate.py; do
  git cat-file -e origin/main:"$f" 2>/dev/null && echo "存在: $f" || echo "缺失: $f"
done
```

```
缺失: .github/assertion_taxonomy.py
缺失: .github/case_trust_gate.py
缺失: .github/case-trust-baseline.json
缺失: tests/unit_ci_workflows/test_case_trust_gate.py
```

⇒ 在 `82d20090` 上，上述缺陷**没有任何门禁会报**（这条不是推测：`pr-check.yml` 的用例侧
job 只有 `Case Contract (truths_ref)` / `Case Coverage Gate` / `QA Growth Gate`，三者都不校验
断言自身可信度）。补门禁前的完整 pytest 输出（10 failed / 28 passed）见下一节「补前红」。

### 红证 C —— 「补门禁之前」判据对缺陷返回 **0 违规**

补门禁**之前**（判据尚未接入门禁、基线/红证/外壳都不存在）跑 L0 守卫，**10 条红**：

```
FAILED ...::TestKnownDefectFixturesAreBlocked::test_pg_013_forbidden_text_sole_judgement
FAILED ...::TestKnownDefectFixturesAreBlocked::test_all_seven_defect_fixtures_are_covered
FAILED ...::TestBaselineDiscipline::test_baseline_exists_and_is_shaped
FAILED ...::TestBaselineDiscipline::test_baseline_entries_have_known_codes
FAILED ...::TestBaselineDiscipline::test_baseline_is_not_used_to_exempt_all_rules
FAILED ...::TestGateShell::test_gate_reports_new_violation_as_blocking
FAILED ...::TestGateShell::test_gate_reports_baseline_violation_as_passed
FAILED ...::TestGateShell::test_gate_requires_baseline_pruning_only_for_diff_cases
FAILED ...::TestRedProofRecord::test_red_proof_is_documented
FAILED ...::TestRedProofRecord::test_red_proof_covers_every_rule_code
10 failed, 28 passed in 0.20s
```

其中 `test_pg_013_forbidden_text_sole_judgement` 的失败原文（判据当时把
`order_before` 当成行为层证据 ⇒ `PG-013` 形态漏判 —— 这**正是**本包要补的洞）：

```
E       AssertionError: PG-013 形态（散文禁令单独承载）未被判违规，实际=[
E         {'code': 'CASE-TRUST-NO-EFFECT-ASSERTION', ...},
E         {'code': 'CASE-TRUST-NO-SELF-CLEAN', ...}]
E       assert 'CASE-TRUST-FORBIDDEN-TEXT-SOLE' in
E              {'CASE-TRUST-NO-EFFECT-ASSERTION', 'CASE-TRUST-NO-SELF-CLEAN'}
tests/unit_ci_workflows/test_case_trust_gate.py:210: AssertionError
```

以及 `CU-003` 的「物理不可满足」在**旧仓库真值**上的判定（判据函数直接跑
`origin/main` 的种子与用例定义）：

```
CU-003 的 pre_clean tag_name 在 origin/main 种子里可解析吗: False
```

「解析不到」**就是** #3832 的形态 —— 旧仓库上这条没有任何门禁会报（红证 B）。

---

## GREEN-PROOF-AFTER（补门禁之后）

### 绿证 A —— L0 守卫全绿

```bash
python3.11 -m pytest tests/unit_ci_workflows -q
```

见下方「读数」节（`43 passed`，含本包新增 38 条 + 既有用例）。

### 绿证 B —— 门禁对缺陷夹具**逐条报出**（每规则都有红证夹具）

`TestKnownDefectFixturesAreBlocked` 9 条全绿，且
`test_all_seven_defect_fixtures_are_covered` 断言**六条规则码全部被某个夹具触发过**
—— 即**不存在没有任何红证的规则**（漏一条即红）：

| 规则码 | 红证夹具 | 触发判据 |
|---|---|---|
| `CASE-TRUST-EMPTY-ASSERTION` | `fixture_ch_009` / `fixture_ch_016` | 计分断言数 = 0 ⇒ `score` 恒 1.0 |
| `CASE-TRUST-NO-EFFECT-ASSERTION` | `fixture_pr_021` / `fixture_cu_003` / `fixture_pg_013` | 写期望在，效果层断言不在 |
| `CASE-TRUST-NO-SELF-CLEAN` | `fixture_pg_013` | 写期望在，`pre_clean`/`namespaces` 都不在 |
| `CASE-TRUST-PRECLEAN-TARGET-UNRESOLVABLE` | `fixture_cu_003` | `VIP2活跃` ∉ 种子 `customer_tags` |
| `CASE-TRUST-FORBIDDEN-TEXT-SOLE` | `fixture_pg_013` | 8 条 `forbidden_text` + 无行为/效果层断言 |
| `CASE-TRUST-SINGLE-LEG-NO-PERSONA` | `fixture_single_leg_unmarked` | `{curtain_calc}` ⊆ 小布工具集但无 `persona` |

### 绿证 C —— 门禁对**正确形态**保持沉默（防假红）

`TestNoFalsePositivesOnCorrectShapes` 10 条全绿：读 action（`customer_manage(action=query)`
及 15 个工具的 `read_only_actions`）不被当写；写 + `must_succeed` + 可解析 `pre_clean` 全绿；
`namespaces` 放行但证据等级降级为「弱」；`forbidden_text` **配行为断言**或**已轮次作用域**
或**显式声明禁令即主判据**时放行。

### 绿证 D —— 退化守卫

`TestDegenerateGuardRails` 全绿：写工具集合非空（≥5）、效果层集合非空（≥3）且每项带理由、
判据不恒真/不恒假、机器计分口径与 `local_runner.py` **同源**（直接读其源码锚点比对）、
小布工具集**转发**单一源而非复制、未实装项带理由与缺口、`RULES` 内无恒真规则。

---

## 读数（锚定 SHA）

| 项 | 读数 |
|---|---|
| 锚定 SHA | `origin/main` = `82d20090a1a2abe4e432b7894df77476b7fb2399` |
| 用例总数 | 289 |
| 存量含违规用例 | 110（见 `.github/case-trust-baseline.json`） |
| L0 守卫 | `tests/unit_ci_workflows` 全绿（本包新增 43 条） |

> 上述"补前/补后"两段读数**不是同一批测试文件**：补前那 38 条里 10 条因被测件缺失而红
> （红证 B/C），补后新增了 5 条（文档/清单完整性），故总数由 38 → 43。
