# 门禁豁免口子总账（Gate Exemption Ledger）

> **这份账治什么**：仓库里所有「能让检查变绿而不必真修」的机制 —— 豁免清单、白名单、
> 基线、跳过分支、`|| true`、`continue-on-error`、fail-open 的取证路径。
>
> **口径（用户方向性指令 2026-09-17）**：「门禁的豁免口子如果可以尽量收紧点，之前可能
> 为了绿而绿的做了很多不规范的事情」。**收紧 = 减少能免检的面** —— 不是换一个更复杂的
> 白名单、不是给豁免加更多字段、不是把阈值调高。
>
> **读法**：判定依据一律看**落码锚点**那一列，不看散文。本页是**索引 + 判据**，不复制
> 各处的第二份口径（同一口径只放一处，见 `migao-dev-flow` §19）。
>
> 盘点 SHA：`f88f8639`（本 PR 的 HEAD）／基线 `8a97c025`（当时 `origin/main`）。
> **所有数字都在 §0 给了复算命令** —— 数字会随迭代漂移，命令不会（§19.2③）。

---

## §0 复算命令（每个数字的唯一出处，别照抄数字）

```bash
cd <repo>
SHA=$(git rev-parse HEAD)          # 读数时钉住的 sha，写进引用

# C1 门禁豁免清单条数（QA Growth Gate 的数据驱动后门）
python3 -c "import sys;sys.path.insert(0,'.github');from yaml_light import load_file;print(len(load_file('.github/qa-exemptions.yml')['exemptions']))"
git show origin/main:.github/qa-exemptions.yml | grep -c '^  - pattern:'      # 基线侧对照

# C2 用例库放行面（skip_reason 是逐用例豁免；另有专路在治）
python3 -c "import sys;sys.path.insert(0,'.github');from render_cases import load_case_dicts;d=load_case_dicts('.github/cases');print('总',len(d),'非空 skip_reason',sum(1 for c in d if str(c.get('skip_reason') or '').strip()))"

# C3 断言可信度门禁的存量违规账本（另有专路在治）
python3 -c "import json,pathlib;d=json.loads(pathlib.Path('.github/case-trust-baseline.json').read_text());print('违规用例',len(d['violations']),'（用例,违规码）行',sum(len(x['codes']) for x in d['violations'].values()),'burn_down',d.get('burn_down'))"

# C4 评测覆盖体检存量豁免
python3 -c "import sys;sys.path.insert(0,'.github');from yaml_light import load_file;print(len(load_file('.github/eval-coverage-baseline.yml')['entries']))"

# C5 workflow 侧的静默面
grep -ro '|| true' .github/workflows/*.yml | wc -l
grep -rn 'continue-on-error: true' .github/workflows/*.yml | wc -l

# C6 规则源规模（缺测门禁的判据来源）
python3 -c "import sys;sys.path.insert(0,'.github');import growth_gate as G;from yaml_light import load_file;t=load_file('.github/tech-stack.yml');e=[];print('rules',len(G.compile_rules(t.get('modules') or [],t.get('test_commands') or {},e)),'编译失败',len(e))"

# C7 自动通过面（is_auto_pass 的触达率）
python3 - <<'PY'
import sys,os; sys.path.insert(0,'.github'); import growth_gate as G
f=[os.path.relpath(os.path.join(r,x),'.') for r,d,fs in os.walk('.') if not any(s in r for s in ('.git','node_modules','.venv')) for x in fs]
print('auto_pass', sum(1 for x in f if G.is_auto_pass(x)), '/ 全部', len(f))
PY

# C8 本账新增的守卫（豁免清单「活性」）
python3 -m pytest tests/unit_ci_workflows/test_qa_exemptions_liveness.py -q
```

---

## §1 总账表（按「能掩盖的问题严重度」降序）

**S1 = 能直接让 required 门禁变绿、或让安全门禁的失效方向变成「放行」**；
**S2 = 能掩盖局部问题 / 需特定条件触发**；**S3 = 诊断留痕，不需动**。

### S1

| # | 位置（文件 + 符号/字段 `@f88f8639`） | 规模（复算） | 能掩盖什么（具体缺陷形态） | 可否收紧 | 现状 / 收紧方式 |
|---|---|---|---|---|---|
| 1 | `.github/qa-exemptions.yml` → `exemptions`（消费方 `.github/growth_gate.py` 的 `is_exempt`，**先于**规则判定） | C1 → **本 PR 前 53 条 / 后 29 条** | required 的 QA Growth Gate 的**数据驱动后门**：命中 pattern 即 `kind="exempt"`，规则判定整段跳过（既非 pass 也非 block，`blocker_count` 不增）。**仓库内此前无任何守卫** —— 条目可以是死的、理由可以过期、目标文件可以早已不存在。实际形态：2 条 pattern 指向**已删文件/目录**；22 条盖住的文件走规则**本来就 pass** ⇒ 该条零作用，且配套测试被删后会**静默**把缺测门禁撑开。另有 19 条「历史分支 UI 重设计组件」的 **break-glass 从未过期**（见 §3.2）。 | ✅ 可 | **本 PR 已收紧**：删 24 条死条目（2 僵尸 + 22 冗余），53 → 29；新增守卫 `tests/unit_ci_workflows/test_qa_exemptions_liveness.py`（结构不变式 + 三向注入自证）。**19 条 break-glass 未动**（见 §3.2） |
| 2 | `.github/tech-stack.yml` → `modules`（消费方 `.github/growth_gate.py` 的 `compile_rules` / `unmatched` 分支） | C6 → rules **20**；改前对空 `modules` 只打 `::warning::` | **一条不用改代码就能关掉整条缺测门禁的路**：`modules:` 被清空（或 pattern 全非法）后 `rules == []`，每个变更文件都落进 `classify_file` 的 `unmatched` 分支 —— 而 `unmatched` **既不是 blocker 也不是 warning** ⇒ `blocker_count = 0` ⇒ CI 的 `Fail on blocking violations` 不触发、`verify-all.sh gate` 打 ✅。且 `.github/tech-stack.yml` **自身 unmatched** ⇒ 改它不需要任何测试。 | ✅ 可 | **本 PR 已收紧**：`compile_rules` 登记被丢弃的规则（空 pattern / 正则非法），`main()` 对「规则源退化」**fail-closed exit 2**。注入红证见 §2.2 |
| 3 | `.github/danger_scan.py` → `_git_name_status` / `_workflow_new_secrets`（取证路径） | 3 条扫描线（workflow / 全量 / 迁移）+ 1 条 secrets diff | **安全门禁的失效方向被写成「放行」**：旧实现裸 `except` 返回 `[]`（且不看 returncode），于是「取证失败」（BASE 配错 / 无共同祖先 / 非 git 仓库 / 超时）与「本次确实无变更」**不可区分** ⇒ 整条 danger-scan 退化成「0 变更、0 blocker、✅ danger-scan: 0 blocker / 0 warning」+ exit 0。**这与该文件 docstring 自称的 fail-closed 直接矛盾**（schema 分支早已按同一原则改过）。 | ✅ 可 | **本 PR 已收紧**：取证失败 → `None` → main() 记 blocker → exit 1。注入红证见 §2.1 |
| 4 | `.github/danger_scan.py` → workflow 扫描 scope | 改前写死 `".github/workflows/*.yml"`（现存 30 个 workflow **全是 `.yml`**，故盲区不显形） | **GitHub Actions 同样执行 `.yaml`**，而 `.yaml` 不在任何一条判定线里（workflow 变更 / 批量删除 / 部署文件三条都看不到）⇒ 新增 `.github/workflows/evil.yaml` 报「✅ 0 blocker」。安全审查该拦的东西**根本没进视野**。 | ✅ 可 | **本 PR 已收紧**：按**整目录**取全量，再按「Actions 实际会执行的后缀」过滤（这是「workflow 文件」的定义，不是白名单）。负例：目录下的 `README.md` 不参与判定 |
| 5 | `.github/workflows/pr-check.yml` 的 `DANGER_TRUSTED_ACTOR`（第 554 行 `@f88f8639`）→ `.github/danger_scan.py` 的 `analyze(trusted_actor=…)` | 1 处 env；`gh pr list --limit 15` 实测**全部** PR 作者 = `zhaokai-mgzn` | **「新增 workflow 文件 ⇒ BLOCK」这条判据对本仓库全部 PR 失效**（恒 `trusted` ⇒ 降为 WARN）。workflow 可携带任意 secrets 且可在 PR 上执行 —— 该规则本意就是拦住这类新增。 | ⚠️ **不宜由本 PR 收紧** | 单 actor 仓库：改成永远 BLOCK 会阻塞唯一贡献者并引发自动打标签/agent-poll 回路。**建议**：改由 label / 人工批准驱动，而不是 actor 身份；或至少把 WARN 落到 PR 评论里可检索的固定标记 |
| 6 | `.github/workflows/pr-check.yml` 两个收尾 job 的 `needs:`（`label-needs-changes` / `clear-needs-changes`） | 各 needs **9**，缺 **4** 个门禁 job：`case-coverage-gate` / `case-trust-gate` / `llm-sink-ledger` / `ui-regression-check` | ① 这 4 个红时**不打** `needs-changes`；② 更糟：`clear-needs-changes` 只等那 9 个 ⇒「这 4 个红 + 其余 9 个绿」时它会**把已有标签摘掉**。 | ⚠️ 可（但本 PR 禁改 workflows） | 登记 + 建议：`needs:` 补全为全部 job，或加 L0 测试锁「needs == 全部 job」。**注意**：改动前须先 `gh pr checks` 确认这 4 个当前全绿，否则收紧即红 |
| 7 | `.github/workflows/pr-check.yml` 弱断言步骤（第 291 行 `@f88f8639`）；`.github/workflows/pr-check.yml` 的 `block-env-files`（第 32 行） | 2 个 required job 各 1 处 `\| grep … \|\| true` | `NEW_TESTS=$(git diff … \| grep … \| grep … \|\| true)` —— 管道只取**最后一条**命令的退出码，而它被 `\|\| true` 兜住 ⇒ **`git diff` 失败被静默吞掉** ⇒ 集合为空 ⇒ 打印「✅ 无新增测试文件，跳过弱断言检查」并 `exit 0` ⇒ **整层 G4 弱断言检测不执行**。`block-env-files` 同形 ⇒ 上游失败时打印「✅ No forbidden .env files」。**已实测**（见 §5 实验）。 | ⚠️ 可（本 PR 禁改 workflows） | 建议：`git diff` 那一段**不加** `\|\| true`（只对 `grep` 的无命中加），失败即 step 红 |
| 8 | `.github/workflows/drift-audit.yml` 打标签步骤（第 139–141 行 `@f88f8639`） | `gh pr comment … \|\| true` + `gh pr edit --add-label block/merge \|\| true` + `exit 0` | 该 workflow 自称「fail-closed 执行闸：auto-merge 会跳过带 `block/merge` 的 PR」—— 但整条闸**只靠一次可能失败的 `gh pr edit`**。打标失败 ⇒ 步骤绿、无 `block/merge` ⇒ 漂移 PR 可被 auto-merge。 | ⚠️ 可（本 PR 禁改 workflows） | 建议：打标失败 ⇒ 非零退出 |
| 9 | `.github/growth_gate.py` 的 G2 覆盖率门禁（`--coverage-threshold` / `coverage_gate_from_report` / `parse_coverage_percent`） | 复算：`grep -rn -- '--coverage-threshold' . 2>/dev/null \| grep -v node_modules` → **仅注释与 add_argument 自身** | **双重死代码**：① 任何 workflow 与 `verify-all.sh` **都不传**该参数；② 即便接线，覆盖率结论写进 `cov_block`，而 JSON payload 在覆盖率块**之前**构建 ⇒ 结构上永远进不了 `blocker_count`，CI 读 JSON 的判据不可能因覆盖率变红；③ 零单测覆盖。⇒ 文档里「G2 已实现」是**假真值**。 | ✅ 可（低风险） | 建议：要么接线（并把结论并入 payload），要么删掉整段 + 在 `docs/audit-2026-08` 那份报告上标「已撤回」。**删比留好**：留着会让人以为覆盖率有门禁 |

### S2

| # | 位置 | 规模（复算） | 能掩盖什么 | 可否收紧 | 现状 / 建议 |
|---|---|---|---|---|---|
| 10 | `.github/growth_gate.py` → `classify_file` 的 `unmatched` 分支 | C7 抽样：`frontend/admin-web/src/hooks/*.ts`、`.github/**`、`scripts/**`、`verify-all.sh`、`…/config/GlobalExceptionHandler.java` 均为 `unmatched` | 「未识别」**既非 block 也非 warn**，控制台只显示「ℹ️ 未识别，跳过」。⇒ **新出现的源码目录天然免检且零告警**（`src/hooks/**` 就是这样，其 `useVoiceRecorder.ts` 至今靠一条 qa-exemption 兜着）。 | ✅ 可（但需先给 `.github/**`、`scripts/**` 补规则，否则会误伤基础设施路径 —— 见 §3.3） | 建议：把 `unmatched` **升为 warning**（可见即可，不动判据），或在 `tech-stack.yml` 补 `scripts/(.+)\.py` / `.github/(.+)\.py` 的规则映射后升为 block |
| 11 | `.github/growth_gate.py` → `is_auto_pass` | C7 → auto_pass **1167 / 2112**；其中「路径不像测试文件」的源码仅 **1** 个（`docs/deployment/accept-onboarding-ai.py`，本就 `docs/` 自动通过） | 段级 `any(s.startswith("test") for s in segs)`：任何**路径段**（含**文件名**）以 `test` 开头即自动通过（`testing/`、`testdata/`、`testUtils.ts`）；`.md/.json/.sql/.xml/.lock/图片` + `docs/` 同理。⇒ 把源码挪进一个 `test…` 目录即可让 required 门禁跳过它。 | ✅ 可 | **当前无实际渗漏**（实测仅 1 个可疑且本就该通过）⇒ 建议 **加一条 L0 断言**锁住「auto_pass 的源码文件必须真的是测试文件」，而不是改判据（改判据风险大于收益） |
| 12 | `.github/growth_gate.py` → `get_added_files` | 1 处；与 `get_changed_files` 的 fail-closed **不对称** | 失败时返回 `[]`（只打 `⚠️`）⇒ `added` 为空 ⇒「新增测试未声明 case_ids」从 **block** 降级。实际影响窄（新增测试通常同时在 `--files` 的 changed 集里，仍会 block），但**方向错了**：同一函数族里一个有 fail-closed、一个没有。 | ✅ 可（一行） | 建议：返回 `None`，由 `case_trace_check` 视为「无法判定」而非「没有新增」 |
| 13 | `verify-all.sh` → `gate_check`（第 241–252 行 `@f88f8639`） | 1 处分支 | **只有未提交改动**时（`CHANGED` 空、`UNCOMMITTED` 非空），G1 缺测分类与 G5 case_ids 追溯**完全不跑**，`BLOCKERS` 保持 0。弱断言已并入工作区（#3724 修过），但缺测那一半没并入。 | ✅ 可 | 现有一行 `::warning::` 如实声明未覆盖范围（**不是静默**）⇒ 属「已知且已声明」。建议：把工作区改动也喂给 `--files`（`growth_gate` 已按 `os.path.exists` 过滤，删除项自动免疫） |
| 14 | `scripts/xiaobu_coverage.py` → `COVERAGE_EXEMPT` | 1 条（`customer_address_query`） | 一条**无 issue 号、无日期、无陈旧校验**的抑制原语，与 `.github/eval-coverage-baseline.yml` 的四道锁**完全不对称**；`grep -rn 'exempt=' tests/unit_ci_workflows/*.py` → **0 命中** ⇒ 整条 exempt 通道零测试覆盖。且该条**理由已过期**（声称对应用例带 `skip_reason`，实已解除）。危险形状：**预置吸收器** —— 该工具一旦失去覆盖，`uncovered` 缺口会被无声吞掉。 | ✅ 可 | 建议：删掉该条（已证不红），或改写成 `eval-coverage-baseline.yml` 条目（自带 issue/日期/陈旧即红） |
| 15 | `scripts/mibao_coverage.py` → `COVERAGE_EXEMPT: dict = {}` | 0 条（**空即最严**） | 空 dict 使 `case_coverage.py` 的 4 条 exempt 路径**空转**（第 537/548/712 行 + `mibao_coverage.py` 第 137/150 行），叠加「零测试覆盖」⇒ 未来往这里加豁免会走一条**完全未经测试**的抑制路径。 | ✅ 可（正向空值守卫） | 建议照 `test_migration_idempotency.py` 第 379 行（`@f88f8639`）`assert not GUARDED_DDL_EXEMPTIONS` 的范式加 `assert not COVERAGE_EXEMPT`（防回填） |
| 16 | `tests/unit_ci_workflows/test_verify_all_quick_scope.py` → `EXEMPT: frozenset = frozenset()`；`tests/unit_ci_workflows/test_xiaobu_coverage.py` → `INTERNAL_NO_CASE` | 均 **0 条** | 两个常量**本身是空的**，但它们的「陈旧登记」断言遍历空集合 ⇒ **恒真 = 空断言**（不会红的断言 = 空断言）。同族的 `_KNOWN_DANGLING`（同样 0 条）**已被刻意去空转**（抽 `_stale_exemptions()` + ghost 注入自证）—— 那才是本仓的正面范式。 | ✅ 可（纯测试改动，必然绿） | 建议照 `test_eval_assertion_action_binding.py` 的注入自证范式改造这两处 |
| 17 | `tests/unit_ci_workflows/test_migration_version_uniqueness.py` → `KNOWN_DUPLICATE_VERSIONS` | **2**（`V29` / `V33`，**真重复，已实测**） | 同号迁移真实存在（`V29__backfill_default_positions.sql` 与 `V29__rebuild_notification_tables.sql` 等）⇒ `schema_migrations` 版本链语义不确定。文件里**没有任何基数钉** ⇒ 往集合里加 `V46` 即可静默放行（注释里的「禁止加」只是注释）。 | ✅ 可（不会红） | 建议照 `test_migration_idempotency.py` 第 375 行（`@f88f8639`）`assert len(LEGACY_UNGUARDED) == 3` 的范式加基数钉或「只许缩短」 |
| 18 | `tests/unit_ci_workflows/test_xiaobu_coverage.py` 的 `assert len(all_entries) <= 8` | 实际 **4** ⇒ **4 格静默扩容余量** | 上界留了 4 格，往 baseline 加条目不会出声。 | ✅ 可（不会红） | 建议改 `<= 4`（或直接断言与 `load_baseline()` 真值相等） |
| 19 | `.github/tool-input-contract-baseline.json`（消费方 `tests/unit_ci_workflows/test_tool_input_contract_guards.py`） | **7 文件 / 18 站点**（`api/asr.py 1 · graph/skills/base_skill.py 6 · production/routing.py 2 · router/rule_matcher.py 5 · tools/inventory_manage.py 1 · tools/logistics_track.py 2 · tools/product_detail.py 1`） | 放行 18 处「**中文措辞当判据**」站点（`<中文串> in <文本>`）—— 判据绑在错误文案的子串上 ⇒ 改一个字判据静默失效。增长侧已被双锁（逐文件不超基线 + `sum(current) <= sum(baseline)` + 防空基线退化），**残留口子**：无「基线自身只许缩短」的单调性守卫 ⇒ 调大 `count` 即可容纳增长。 | ✅ 可（不会红） | 建议加单调性钉（比对 `origin/main` 侧 counts，不写死数字） |
| 20 | `.github/assertion_taxonomy.py` → `UNIMPLEMENTED`（7 条）/ `KNOWN_PRECLEAN_TARGET_FIELDS`（6）/ `LOCATOR_EXEMPT_KEYS`（7） | 7 / 6 / 7 | `UNIMPLEMENTED` = **7 个已知盲区**，最重的是「纯散文 `data_checks` 是否真在测它声称的东西」（语义不可机器判）与「拼错 `pre_clean.type` ⇒ runner 静默跳过」。`KNOWN_PRECLEAN_TARGET_FIELDS` 对**未知类型 `continue`（不登记）**。`LOCATOR_EXEMPT_KEYS` 的 7 个键都合法，但**没有「豁免键不得其实是定位键」的自洽性守卫**。 | ⚠️ / ✅ | `UNIMPLEMENTED` **登记诚实**（先 `assert tax.UNIMPLEMENTED` 非空守卫，再要求每条带 `why_not`+`needs`）⇒ **不该删，该逐条实装**。后两者可加自洽性守卫（**本 PR 未动该文件** —— 它与 case-trust 门禁共享，另有专路在改） |
| 21 | `tests/agent_eval/local_runner.py` → `_COMPLETION_RELEASED_CLASSES = frozenset({"llm-noise"})` + `history_available` 传参 | 1 类；阈值 `CROSS_RUN_RECURRENCE_MIN_PRIOR=1` | 类目层已堵死（硬编码 frozenset + 两道强制红）⇒ 新增失败类不可能静默。**但放行体量开放式**：任何「首跑 `score<1.0` + 重试 `score>=1.0`」都判 `llm-noise`，**无上限常量**。且传参传的是 `bool(_hist_path)`（**路径在不在**）而非 `bool(_history)`（**索引里有没有数据**）⇒ **索引存在但为空**时，放行台账写「同一首跑指纹**未在历史 run 复发**（随机波动）」= **「没拿到数据」被记成「查过，没复发」**。 | ✅ 可（一行 + 一条用例） | 建议：`bool(_history)`，或引入第三态（未提供 / 提供了但为空 / 有数据）。**runner 侧该口径无任何测试覆盖** |
| 22 | `.github/scripts/flake_history.py` 的 `AGENT_EVAL_FLAKE_HISTORY` 接线面 | workflow 侧**仅 1 处**（`post-deploy-eval.yml`） | #3806 的「跨 run 复发」收紧只在 1 个 workflow 生效；另两个 workflow（上传台账却**从不注入**该 env）里 `_is_recurring()` 恒假 ⇒ 放行政策退回「只看本次两次尝试」⇒ **「首跑必败、重试偶过」每轮都绿**。 | ✅ 可（无历史时行为逐字不变 ⇒ 不会红） | 建议把这步抽成可复用步骤接到另两个 workflow；接线后会出现新的红条目，需先接受 |
| 23 | `tests/unit_ci_workflows/test_verify_all_quick_scope.py` 的行为判据（`_ai_agent_env()` → `pytest.skip`） | **3 skipped**（缺 `fastapi`）；`ci-workflow-tests` job 只装 `pytest pyyaml` ⇒ **CI 同样 skip** | 该文件**最强的**行为判据（真跑 `--collect-only` 断言每个顶层 `test_*.py` 真被收集）在 CI 里**从不执行**，只剩静态文本判据。issue #3680 的**行为兜底在 CI 中不存在**。 | ⚠️ 可（贵） | 建议：至少在 CI 里把 skip 转成显式「行为验证未跑」的可见标记（别让它长得像通过） |
| 24 | `tests/unit_ci_workflows/test_drift_audit_contract.py` 的两处 `pytest.skip`；`tests/unit_ci_workflows/test_gate_uncommitted_noop.py` / `test_verify_all_quick_scope.py` 的 locale skip | 4 处 | `drift_audit_baseline.json` 不存在即 skip ⇒ **删掉基线文件 ⇒ 守卫绿**；`origin/main` 不可解析即 skip **整条自证** —— 而跑本文件的 job 是**浅检出** ⇒ 自证可能永不执行。 | ⚠️ 可（第一处应改「缺失即红」；第二处收窄到只跳 diff 相关断言） | 登记 + 建议 |
| 25 | `.github/workflows/xiaobu-acceptance.yml` 的验收剧本步骤（第 432–447 行 `@f88f8639`）；同族：`smoke-test.yml` 的就绪探测；`issue-contract-check.yml` 的 "Validate cases references"；`agent-behavior-eval.yml` 的 `"blocking"` 标签 | 4 处「名字像门、正文只打印」 | `if [ ! -f "$SCEN" ]; then …; exit 0; fi` + `\|\| RC=$?` 后**只 `echo` RC**、末条命令是 echo ⇒ 该步骤**在任何情况下都不可能失败**（协议里价值最高的 L1/L2 真实验收**零红/绿信号**，真红只来自别的 step）。 | ⚠️ 部分可 | 验收剧本步骤可收紧（缺剧本 ⇒ exit 1，末尾 `exit $RC`；workflow_dispatch/schedule only ⇒ 不影响 PR 门禁）；`smoke-test` 就绪探测**不该**收紧（滚动重启瞬态 502 会造部署窗口假红），只改名 |
| 26 | `.github/workflows/nightly-verification.yml` 第 50 行 `@f88f8639`；`.github/workflows/verify-trigger.yml` 的 `REMAIN=$(… \|\| echo "9999")` | 各 1 处 | nightly：`pytest -m "p1" … \|\| pytest -m "not p0" …` ⇒ 步骤退出码 = **回退命令**的码 ⇒ p1 档失败被更宽档的成功掩盖（教科书形态）。verify-trigger：取额度失败**伪装成「额度充足」**⇒ 后续候选收集失败变空 ⇒「合法空跑 exit 0」⇒ 合并后静默永不贴出 | ⚠️ 可（不影响 PR 门禁） | 登记 + 建议：nightly 去掉回退（或分别记录两档结论）；REMAIN 改三态 |
| 27 | `.github/workflows/*.yml` 的 `continue-on-error: true` | **4 处真实设置**（全为 step 级，**job 级 0 个**）：`post-deploy-eval.yml` 的 flake 索引 / 真实 LLM 评测 / Download 汇总；`pr-check.yml` 的 Security audit | step 级 ⇒ 该 step 的失败不阻塞其 job。真实 LLM 评测那条**有意如此**（判红交给 `completion_verdict`），另三条属诊断。 | ⚠️ **多数不宜收紧** | 见 §3.1；建议只收紧「flake 索引」那条（索引为空 ⇒ 结论标 unknown 而不是静默） |
| 28 | `.github/llm_sink_check.py` 的 `EXIT_UNKNOWN = 3` | 1 常量；CI 唯一调用是 `--selftest`（只可能返 0/1） | 产生 exit 3 的分支全在 `--issue --check-backfill` / `--all`，**CI 从不调用** ⇒ 「无法判定」这一态在 CI 不可达。 | ⚠️ 可 | 登记：不是「放行」，是**判据没被用上**。建议接线 `--all` 或删掉该态以免误以为有覆盖 |
| 29 | `.github/cases/**` 的 `skip_reason` | C2 → **156 / 317 条用例 = 49%** | **另一专路在治**（本 PR 只登记，不重复）。机制：非空 ⇒ 从 active/smoke/adversarial 生成集与覆盖计数中剔除；门禁只校验「点名的 pytest 文件存在且可被 collect」，**不校验它是否真覆盖该用例**。 | ✅ 可（另有专路） | 登记 |
| 30 | `.github/case-trust-baseline.json` → `violations`（另有 `.github/case_trust_gate.py` 的 `_REF_EXEMPT_FILES`） | C3 → **135 用例 / 214（用例,违规码）行**，`burn_down` 10 键 | **另一专路在治**（本 PR 只登记）。含 `EMPTY-ASSERTION`（恒真断言）与 `NO-EFFECT-ASSERTION`（写类无效果层断言）等真实未修缺陷。机制本身已是本仓最佳实践（全量对账陈旧即红、增长即红、生效配置读 `origin/main`）。 | ✅ 可（另有专路） | 登记 |
| 31 | `scripts/drift_audit.py` 的 `REF_SURFACE_EXEMPT` / `MUTABLE_KEY_EXEMPT` / `scripts/drift_audit_baseline.json` | 基线：**65 条存量放行 / 可销账 0**（`python3 scripts/drift_audit.py` 汇总行） | **#4045 在飞，本 PR 只登记不改**。注意该脚本已在 `f88f8639` 上判 **DRIFT**（新增漂移 3，全部来自 worktree 落后 main 造成的技能版本回退 —— 本 PR rebase 后已消失，见 §5 实测）。 | ⛔ 本 PR 不动 | 登记 |
| 32 | `.github/eval-coverage-baseline.yml`（`scripts/case_coverage.py` 的四道锁） | C4 → **4 条**（1 阻塞 + 3 只报告） | 唯一阻塞条目 `order_manage[missing_positive]` **真在抑制一个真实缺口**：B 端改状态/发货的正常档路径零评测证据。**这是本账里唯一「删掉就红」的收紧**（`python3 scripts/mibao_coverage.py --check --strict-gaps` → exit 1）。 | ⚠️ 正解是补用例，不是删条目 | 见 §3.4。机制已带 issue/日期/陈旧即红/增长即红 ⇒ **不建议再收紧机制本身** |

### S3（诊断留痕，不需动）

| # | 位置 | 规模（C5） | 说明 |
|---|---|---|---|
| 33 | `.github/workflows/*.yml` 的 `\|\| true` | **60 处** | 逐条看过：绝大多数是 `logs` / `ps` / `psql` / `tail` / 打标签 / 记账类**诊断**命令，`\|\| true` 是有意让诊断失败不阻塞判定（收紧会造二次污染）。**已知需收的只有 S1 的 #7 / #8 三处**（它们后面跟着判定分支）。 |
| 34 | `.github/workflows/automerge.yml` 的 `set +e`；`deploy-*` 的 `if:` | — | `set +e` 是幂等语义（恒绿），非豁免；`deploy-*` 的 `if:` 是「是否部署」门，不是「是否检查通过」门。 |
| 35 | `scripts/check_ontology_contract.py` 的 `_BUSINESS_EXCLUDE = {"general"}` | 1 | 作用域正确（由 `schema.yaml` 注释背书）。**但该脚本在 main 上已 exit 1**（3 条 `processing_order_*` 违规），而 `contract-check.sh` **不被任何 workflow 引用**、`verify-all.sh` 也不调它 ⇒ **本地红、CI 看不见的死门禁**。 |

---

## §2 本 PR 实际收紧的三处（改前/后 + 注入红证 + 负例）

三处都满足选择标准：① 当前**真的能**让检查变绿而不必真修（实测，非理论）；
② 收紧后**当前 main 不会变红**（实测）；③ 改动面可控（3 个文件 + 3 个测试文件）。

### §2.1 T1 — `.github/danger_scan.py`：取证失败不得被读成「没有破坏性变更」

**改前/后对照（同一份输入，纯 CLI 实测）**

| 场景 | 改前 | 改后 |
|---|---|---|
| 新增 `.github/workflows/evil.yaml`（取证正常） | `✅ danger-scan: 0 blocker / 0 warning` → **exit 0** | `❌ 新增 workflow 文件 .github/workflows/evil.yaml —— 需人工安全审查…` → **exit 1** |
| `DANGER_BASE` 指向不存在的 ref（取证失败） | `✅ danger-scan: 0 blocker / 0 warning` → **exit 0** | `❌ 无法获取变更清单…（3 处取证失败）` → **exit 1** |
| 负例：无 workflow 变更、取证正常 | `✅ … 0 blocker` → exit 0 | `✅ … 0 blocker` → **exit 0**（不变） |

**注入式红证**：`tests/unit_ci_workflows/test_danger_scan.py::TestForensicsFailClosed`
（5 条）。把 `danger_scan.py` 退回 `origin/main` 版本后实测：

```
FAILED test_git_name_status_distinguishes_failure_from_empty
FAILED test_main_fails_closed_when_forensics_fail
FAILED test_new_yaml_workflow_is_in_scan_scope
FAILED test_non_workflow_files_in_dir_are_not_flagged
4 failed, 1 passed
```

**负例原文**（合法形态不得误报）：`test_non_workflow_files_in_dir_are_not_flagged`
—— `.github/workflows/README.md` 属于「Actions 不执行的后缀」，不得进判定；
`test_new_yaml_workflow_blocks_end_to_end` 证明覆盖范围的放宽不改变判据本身。

### §2.2 T2 — `.github/growth_gate.py`：规则源退化必须 fail-closed

**改前/后对照**

| 场景 | 改前 | 改后 |
|---|---|---|
| `.github/tech-stack.yml` 的 `modules: []` + 真实源码文件 | `ℹ️ 未识别，跳过` + `## ✅ 全部通过` + `blocker_count=0, warning_count=0` → **exit 0** | `::error:: …modules 为空…缺测门禁整条失效…` → **exit 2** |
| 某条 `pattern` 正则非法（其余合法） | 静默丢弃该条 → 对应文件落 `unmatched` → **exit 0** | `::error:: …有 1 条规则无法编译…` + 逐条点名 `service=x: 正则非法 'app/(.+\.py'（missing )…）` → **exit 2** |
| 负例：合法规则源 | exit 0 | **exit 0**（不变） |

**注入式红证**：`tests/unit_ci_workflows/test_growth_gate_fail_closed.py` §⑥（5 条）。
退回 `origin/main` 版本后实测 `3 failed`（`test_compile_rules_reports_discarded_patterns` /
`test_empty_modules_fails_closed` / `test_invalid_regex_fails_closed`）。

**负例原文**：`test_valid_rules_still_pass`（合法规则源 + 无规则命中 ⇒ exit 0 且打印
`✅ 全部通过`）；`test_repo_tech_stack_is_not_degenerate`（真值不回退 —— 谁把 `modules`
清空了，单测层立刻可见）。

> **reb 适配说明**：`origin/main` 的两个 harness（`test_gate_uncommitted_noop.py`、
> `test_growth_gate_fail_closed.py`）原本用 `modules: []` 当「不关心规则」的桩。收紧后
> 「空 modules」**本身就意味着门禁整条失效**，会把这些只关心「未提交感知 / 弱断言扫描集」
> 的 harness 自己打红（**红因变成「规则源退化」⇒ 判别力丢失**）。故两处桩改为
> **一条匹配不到任何被测文件的无害规则**，分类结果与被替换前逐字一致（`unmatched`）
> —— 这是**夹具适配**，不是断言放宽。

### §2.3 T3 — `.github/qa-exemptions.yml`：死豁免清零 + 活性守卫

**改前/后对照**

| 项 | 改前 | 改后 |
|---|---|---|
| 条目数 | **53** | **29**（−24，−45%） |
| 僵尸（pattern 匹配不到任何现存文件） | 2（`app/context/*`、`components/ops/OpsSidebar.tsx`） | 0 |
| 冗余（盖住文件走规则本来就 `pass`/`auto_pass`） | 22 | 0 |
| 守卫 | **无**（仓库内没有任何东西会因死条目变红） | `tests/unit_ci_workflows/test_qa_exemptions_liveness.py`（结构不变式 + 三向注入自证） |

**注入式红证**：把 `qa-exemptions.yml` 退回 `origin/main` 版本后实测：

```
FAILED test_no_dead_exemption_entries
E  assert not ['frontend/admin-web/tests/* —— 冗余：…auto_pass…',
E            'backend/ai-agent-service/app/api/chat.py —— 冗余：…pass…', …]
1 failed, 4 passed
```

**负例原文**（活条目不得误报，防「判据过宽 = 假红」）：`test_live_pattern_is_not_flagged`
—— `frontend/admin-web/src/components/ui/Badge.tsx` 规则侧判定为 `block` ⇒ 该条**在做实事**，
必须返回空原因；`test_exemption_list_is_parseable_and_scanned` 另防「清单被清空 ⇒ 上一条
断言静默空过」（绿了但没跑）。

**判据是结构不变式，不是阈值**：本守卫**不断言条数**（`<= 29` 这类数字会随迭代腐烂，
§19.2③），只断言「不许有死条目 + 不许空转」。

### §2.4 关于 `--new-tests-only`（#4077 复核：**没被放宽**）

`origin/main` 的 `.github/growth_gate.py` 新增了 `--check-weak --new-tests-only`。
**复核结论：它是「只缩小扫描集」的过滤器，不是放宽。**

- 过滤走 `_is_test_file` 单一事实源（与 G5 用例追溯共用），产物只可能**变少**；
- 新增的早退分支（`if not files: … return 0`）只在「候选集被过滤后为空」时触发，
  而**真正空输入**仍走原来那条 fail-closed 分支（`return 1`）；
- 真弱断言仍逐个检出（`--check-weak` 的判定逻辑一字未动）。
- **唯一可议之处不在它本身**，而在调用侧：CI 的 `NEW_TESTS=$(git diff … || true)`
  让「git 失败」退化成「没有新增测试」⇒ 整层不执行（已登记为 S1 #7）。

---

## §3 判定**不该**收紧的口子（附理由）

### §3.1 真实 LLM 评测步骤的 `continue-on-error`（`post-deploy-eval.yml`）
判红交给 `completion_verdict`（放行集合只有一个 `llm-noise`），收紧这一层会让一条
`llm-noise` 打红整条腿。要收的是**放行政策**（S2 #21/#22），不是这一层。

### §3.2 `qa-exemptions.yml` 里 19 条「历史分支 UI 重设计组件」的 break-glass
它们是**本清单里最大的一块真豁免面**（`components/chat/*` 9 条 + `dashboard/*` 3 条 +
`ui/*` 5 条 + `providers/*` 1 条 + `ops/*`（已随僵尸条目删除）），理由统一是
「#2575 随分支部署，本次 PR 未改其逻辑」—— **一次性的 break-glass 从未过期**，
现在这些组件都在 main 上被正常迭代，而改动它们**永远不需要测试**。

**为什么不删**：删掉会让**任何人**（含并行工作的其它会话）下次触碰这些组件时突然被
required 门禁拦住；这是一条**团队节奏决定**，不该由收紧 PR 单方面改。
**建议**（交用户裁定）：要么删掉整块（每次组件改动需补 `tests/unit/components/<Name>.test.tsx`，
与仓库既有约定一致），要么给 break-glass 一个**日落条件**（例如「本条目引用的 PR 已合并
N 个月」即视为陈旧 ⇒ 红），而不是留成永久门票。

### §3.3 `growth_gate` 的 `unmatched` 升为 block
直接升会**误伤基础设施路径**：`.github/**`、`scripts/**`、`verify-all.sh` 都不在
`tech-stack.yml` 的规则里（C7 实测），而它们**不该**被要求配套测试。正解是先补规则映射、
再升级判据；顺序反了就是把假红引进 required 门禁。

### §3.4 `.github/eval-coverage-baseline.yml` 的 `order_manage[missing_positive]`
删掉它 ⇒ `python3 scripts/mibao_coverage.py --check --strict-gaps` **exit 1**（本账唯一
「删了就红」的一条）。正解是**补一条 B 端 normal 档正向用例**（改订单状态/发货），不是删条目。
机制侧已有四道锁（issue/日期/陈旧即红/增长即红）⇒ **机制本身不必再收紧**。

### §3.5 `danger_scan` 的 `trusted_actor`（S1 #5）
单 actor 仓库：改成永远 BLOCK 会阻塞唯一贡献者并触发自动打标签 + agent-poll 回路。
需换判据形态（label / 人工批准驱动），属**流程裁定**。

### §3.6 `LEGACY_UNGUARDED` / `KNOWN_SAVE_MESSAGE_DOUBLES` / `KNOWN_REGISTERED_TOOLS` / 各类空常量
- `LEGACY_UNGUARDED`（3 文件 / 8 缺口）：修这几个已发布迁移受 danger-scan「迁移只增不改」
  required 护栏约束，需先裁决豁免机制；且该文件已是全仓最严写法（基数钉 + 新增即红 +
  销账未删即红 + 与 Java 常量键集合逐条相等 + 标记缺失 fail-closed）。
- `KNOWN_SAVE_MESSAGE_DOUBLES`（5）：`⊆`（下界）语义，**新替身零摩擦、已知替身消失必红**
  —— 是解析器自证，不是放行。
- `KNOWN_REGISTERED_TOOLS`（35）：已是 `==`（双向精确相等），无收紧空间。
- `GUARDED_DDL_EXEMPTIONS` / `EXTERNAL_TABLES` / `_KNOWN_DANGLING` / `tool-suggestion-baseline`
  的 0 条：**「正确的空 = 最严」**，且前两者有主动「必须为空」守卫、`_KNOWN_DANGLING`
  有注入自证。
- `_SILENT_SKIP` / `_EVIDENCE_FAST_SKIP`：**反放行检测锚**（含旧行为红证），不是放行机制。
- `test_runner_polish_*`：零豁免常量。

### §3.7 `verify-all.sh` 的 ⏭️「未就绪」三态
未就绪**不计入通过也不计入失败**，且脚本已用 `exit 4` 兜底「有变更却零项真跑 = 纯空跑」。
把它改成失败会造**假红**（缺 venv / 缺 node_modules 是环境问题，不是代码问题）——
这正是当初引入三态要消除的形态。

---

## §4 未做 / 存疑

1. **`skip_reason`（C2，156/317）与 `case-trust-baseline`（C3，135/214）**：另有专路在治，
   本账只登记，不重复改动（避免同文件双写冲突）。
2. **`scripts/drift_audit.py` 的基线与豁免**：#4045 在飞，本 PR 只登记。
3. **workflows（`.github/workflows/**`）的 4 类改动**（S1 #6/#7/#8、S2 #25/#26）：本 PR
   **禁止动该目录**，故全部只登记 + 给收紧方式。
4. **`assertion_taxonomy.py` / `case_trust_gate.py`**：与 case-trust 门禁共享、另有专路在改，
   本 PR 未动。
5. **一处被证伪的子代理判据（归因纪律）**：曾有分析称 `ai-agent-tests.yml` 的
   `HITS=$(… \|\| true)` 会让「git diff 失败 ⇒ CHANGED 空 ⇒ required 绿而零单测」。
   **实测不成立**：该文件里 `CHANGED=$(git diff …)` **没有** `|| true`，而 GitHub 默认
   `bash -e` 下 `VAR=$(cmd)` 的失败会让脚本退出。对照实验（§5）：
   `bash -e -c 'CHANGED=$(git diff --name-only origin/nope...HEAD); echo REACHED'` → **exit 128**（没到 REACHED）；
   而 `bash -e -c 'F=$(git diff … | grep … || true); echo REACHED'` → **exit 0**（到 REACHED）。
   ⇒ 「管道 + `|| true`」吞失败（S1 #7 成立），「裸 `VAR=$(git diff)`」不吞（该判据不成立）。
6. **未逐条枚举**的项：`KNOWN_PRECLEAN_TARGET_FIELDS` 收紧后是否变红（需先枚举全库
   `pre_clean[].type`）；`.github/truths.py` 的 `ALLOWED_VERIFY_METHODS` 语义匹配缺口
   （需先枚举 DRAFT_JSON 实际 method 值）；`assertion_taxonomy.UNIMPLEMENTED` 7 条的实装成本。
7. **两处观察到的 flake / 自证留痕（如实标注，未归因）**：
   - 本 PR rebase 后**第一次**全套跑出现 1 例失败（`tests/unit_ci_workflows/test_gate_uncommitted_noop.py`
     的 `test_uncommitted_workspace_weak_assert_is_caught`，结果 `1 failed, 1401 passed`）；
     **第二次**全套跑为 `1402 passed`，该文件单跑与配对跑均通过。可疑机制是该 harness 用
     `/tmp/verify-all-<pid>-*.log` 按 PID 定位并断言「恰好 1 个日志」，PID 复用 + 前序测试
     残留会造成**顺序相关**的假失败；与本 PR 无因果（该用例走的是「未提交感知」路径，
     压根不经过被改的代码）。**未做确定性隔离实验**（需在冻结的树上重放）
     ⇒ 记为**观察到的 flake，未归因**。
   - 本账**自身**在入册时命中过 drift 的 `ref-freshness`：当时判 **DRIFT（新增漂移 4，面内阻塞）**，
     修正引用写法后 `⇒ OK`。留痕于此：**账本也要守引用纪律** —— 「每个数字都附复算命令」
     不等于可以写裸行号。

---

## §5 关键判据的实测留痕（可复算）

```bash
# ① 缺测门禁可被「清空 modules」关掉（收紧前）
D=$(mktemp -d); printf 'modules: []\ntest_commands: {}\n' > "$D/e.yml"
python3 .github/growth_gate.py --files backend/ai-agent-service/app/graph/builder.py --tech-stack "$D/e.yml"
#   改前：| … | — | ℹ️ 未识别，跳过 |  +  ## ✅ 全部通过   （blocker 0 / warn 0，exit 0）
#   改后：exit 2 + ::error:: …缺测门禁整条失效…

# ② danger-scan 的两种「免检」形态（收紧前后对照见 §2.1）
#   刻一个最小仓库，第二笔 commit 新增 .github/workflows/evil.yaml：
DANGER_BASE=origin/main python3 .github/danger_scan.py            # 改前 0 blocker / 改后 1 blocker
DANGER_BASE=origin/nonexistent-ref python3 .github/danger_scan.py # 改前 0 blocker / 改后 3 blocker

# ③ 管道 vs 裸赋值对 set -e 的差别（S1 #7 成立 / 「ai-agent-tests」判据不成立）
bash -e -c 'CHANGED=$(git diff --name-only origin/nope...HEAD); echo REACHED'; echo "exit=$?"   # 128，未 REACHED
bash -e -c 'F=$(git diff --name-only origin/nope...HEAD | grep -E "\.env$" || true); echo REACHED'; echo "exit=$?"  # 0，REACHED

# ④ 三处收紧的注入红证（把源文件退回 origin/main 版本后跑守卫）
git show origin/main:.github/danger_scan.py > .github/danger_scan.py
python3 -m pytest tests/unit_ci_workflows/test_danger_scan.py -q -k ForensicsFailClosed   # 4 failed
git show origin/main:.github/growth_gate.py > .github/growth_gate.py
python3 -m pytest tests/unit_ci_workflows/test_growth_gate_fail_closed.py -q -k "empty_modules or invalid_regex or discarded"  # 3 failed
git show origin/main:.github/qa-exemptions.yml > .github/qa-exemptions.yml
python3 -m pytest tests/unit_ci_workflows/test_qa_exemptions_liveness.py -q             # 1 failed
#   （务必用 git show/checkout 还原，勿用 git stash —— §2.3 硬红线）
```

---

## §6 与既有规范的关系

- 本账是 `migao-dev-flow` §19.1「断言可信度」与 §19.2「交付与账本新鲜度」在**门禁自身**
  上的应用：每处收紧都有注入式红证（不会红的断言 = 空断言）、负数不写死易变数字、
  收紧后必须重放验证。
- 收紧判据与 `migao-acceptance` 的「假绿 / 空跑」同族：**取证失败 ≠ 无变更**、
  **规则源退化 ≠ 无规则**、**没跑必须长得像没跑**。
- 新增守卫的 `case_ids` 声明：`tests/unit_ci_workflows/test_qa_exemptions_liveness.py`
  → `MC-011`；`test_danger_scan.py` → `DF-010, OB-001`；`test_growth_gate_fail_closed.py`
  → `MC-012`。