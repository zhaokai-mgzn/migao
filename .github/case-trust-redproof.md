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
| `CASE-TRUST-VOLATILE-LOCATOR` | `fixture_cu_003` | `pre_clean[].customer_index: 0`（按列表位置定位客户） |
| `CASE-TRUST-NO-PRECONDITION-ASSERTION` | `fixture_pg_013` | 多轮写用例无 `precondition` / 机器计分型前置断言 |
| `CASE-TRUST-STALE-LINE-REF` | `TestReferenceFreshness` 的 3 个注入夹具 | 行号越界 / 文件不存在 / 符号在文件里完全找不到 |
| `CASE-TRUST-SINGLE-LEG-NO-PERSONA` | `fixture_single_leg_unmarked` | `{curtain_calc}` ⊆ 小布工具集但无 `persona` |

### 绿证 C —— 门禁对**正确形态**保持沉默（防假红）

`TestNoFalsePositivesOnCorrectShapes` 10 条全绿：读 action（`customer_manage(action=query)`
及 15 个工具的 `read_only_actions`）不被当写；写 + `must_succeed` + 可解析 `pre_clean` 全绿；
`namespaces` 放行但证据等级降级为「弱」；`forbidden_text` **配行为断言**或**已轮次作用域**
或**显式声明禁令即主判据**时放行。

### 绿证 F —— E / F / G 三条规则的注入式红证（2026-09-15 主会话追加）

**规则 e（不可变对象引用）** —— `TestVolatileLocator`：

- 红：`fixture_cu_003`（`pre_clean[].customer_index: 0`）⇒ 报
  `CASE-TRUST-VOLATILE-LOCATOR`，失败信息点名 `customer_index` 并给「换成手机号/order_no/id」的改法；
- 绿（防误伤）：手机号 `customer_keyword: "13800138000"` 定位 ⇒ 全绿；
- **关键口径**：序号出现在 `user_inputs`（`auto_select: True` / 「第一个」）**不算违规**
  —— 那是被测行为的一部分。若判据扫 `user_inputs`，全库 8+ 条序数用例会被误伤。
- 名字子串（`product_keyword` 等 20 条）⇒ **警告级**（`name_key_positions` 识别但不阻塞），
  避免一次把 20 条存量全判红挡住所有人。

**规则 f（前置自断言）** —— `TestPreconditionAssertion`：

- 红：`fixture_pg_013`（多轮写用例无前置声明）⇒ 报 `CASE-TRUST-NO-PRECONDITION-ASSERTION`；
- **防虚增红证**：只加 `must_succeed` + `db_verify` 仍判违规 ——
  本模块初版把效果层当「弱形式」接受，实测把「已声明」从 **1 条虚增到 37 条**，
  那 36 条**根本没说前置是什么**（虚增 = 判据失去判别力 = 空壳）；移除后判据恢复判别力；
- 红：**纯散文** `data_checks: ["前置：库里应有…"]` 不算声明（不计分 ⇒ 前置不成立时不会红，#3559 同族）；
- 绿：`precondition` 字段 或 **机器计分型**前置 data_checks ⇒ 放行；
- 绿（防摩擦）：单轮只读用例**不强制**（读不改变世界）。

**规则 g（引用新鲜度）** —— `TestReferenceFreshness`：

- 红：`tests/agent_eval/local_runner.py:999999`（行号越界 ⇒ 该行**不存在**）⇒ 阻塞；
- 红：`no/such/file.py:10`（文件在 `origin/main` 上不存在）⇒ 阻塞；
- 红：引用 `a/b.py:5` 的 `totally_absent_symbol`（符号在该文件里**完全找不到**）⇒ 阻塞；
- **红证夹具取自 `#3787` 的过期指引形态**：`test_known_stale_refs_from_3787_are_flagged`
  用同形态（引用了某文件里根本不存在的锚点）证明判据会红；
- 警告（不阻塞）：行号漂移（符号在文件别处）⇒ 报「建议改用符号锚点」；
- 绿（防误伤）：合法裸行号（无符号、行号在范围内）⇒ 不报 —— 仓库里大量正当
  `path:NNN`（如 `aftersales.yml` 引 `local_runner.py:2000`）不能被误判；
- 只扫**本次新增/改动行**（`test_gate_scans_only_new_or_changed_lines`）⇒
  不把存量过期引用算到无关 PR 头上。

**规则 g 打在真实文件内容上的四态读数**（`tests/agent_eval/local_runner.py` `@origin/main`，7422 行）：

```
[行号越界]   blocking=1  | 行号越界：`tests/agent_eval/local_runner.py` 在 origin/main 上只有 7422 行，引用第 999999 行
[符号不存在] blocking=1  | 引用指向的符号 ['totally_absent_symbol_xyz'] 在 `tests/agent_eval/local_runner.py` 里**完全找不到**
[行号漂移]   blocking=0  warnings=1 | 行号漂移：符号 ['_pre_clean_for_case'] 不在第 10 行附近（该文件里能找到）—— 建议改用符号锚点
[合法裸行号] blocking=0  warnings=0
```

**降噪三条纪律（缺任一条都会误报，本包实测）**：
① 只扫本次新增/改动行；② 豁免门禁自身的实现/测试/红证留档（那里的「不存在路径」是夹具）；
③ **先解析路径再判定**（裸文件名按 basename 唯一匹配；`git ls-files` 解析不到的占位符直接丢弃）。

> ⚠️ **一个被自己抓到的假红**：`_resolve_repo_path`（路径解析）与 `origin_main_lines`（文件内容）
> 初版**共用一个 cache dict**，两者值类型不同（str vs list[str]）⇒ 互相污染 ⇒
> 报出「`local_runner.py` 在 origin/main 上只有 **32 行**」（真实 7422 行）这类**自相矛盾的假读数**，
> 把合法引用误判成「行号越界」。修复 = **两个独立缓存** + 注释写明为什么必须分开。
> 这正是本包要治的形态（读数不可信 ⇒ 结论不可信），故留档。

### 绿证 D —— 退化守卫

`TestDegenerateGuardRails` 全绿：写工具集合非空（≥5）、效果层集合非空（≥3）且每项带理由、
判据不恒真/不恒假、机器计分口径与 `local_runner.py` **同源**（直接读其源码锚点比对）、
小布工具集**转发**单一源而非复制、未实装项带理由与缺口、`RULES` 内无恒真规则。

---

## 读数（锚定 SHA）

| 项 | 读数 |
|---|---|
| 锚定 SHA | `origin/main` = `5300dae0fafd645c27d749b5a39a9017cf312b5c` |
| 用例总数 | 289 |
| 存量含违规用例 | 143（见 `.github/case-trust-baseline.json`） |
| 逐规则存量计数 | `NO-PRECONDITION-ASSERTION` 106 / `NO-SELF-CLEAN` 42 / `NO-EFFECT-ASSERTION` 34 / `EMPTY-ASSERTION` 28 / `SINGLE-LEG-NO-PERSONA` 18 / `FORBIDDEN-TEXT-SOLE` 7 / `PRECLEAN-TARGET-UNRESOLVABLE` 3 / `VOLATILE-LOCATOR` 1 / `STALE-LINE-REF` 0 |
| L0 守卫（本包文件） | `62 passed`（`python3.11 -m pytest tests/unit_ci_workflows/test_case_trust_gate.py -q`） |

> ⚠️ 锚定 SHA 已由 `82d20090` 前进到 `5300dae0`：期间**并发包合并了 `CU-003`/`PG-013` 的修复**
> （issue #3832 / #3833）。本表是**重生成后**的读数，与修复前对比可见：
> `PRECLEAN-TARGET-UNRESOLVABLE` 4 → **3**（`CU-003` 修好）、`NO-SELF-CLEAN` 43 → **42**、
> 且 `CU-003` 的 `customer_index` 已换成手机号（`VOLATILE-LOCATOR` 存量降到 1）。
> **`PG-013` 的修后形态已被回归用例锁定**（`test_concurrent_fix_shapes_pass`）：
> 新增 `pre_clean: [{type: processing_order_reset, order_no: …}]` + `forbidden_text` 部分条目
> 改为**轮次作用域**（`{round: 2, any_of: [...]}`）⇒ 判据**放行**（不挡住他们的 PR）。
