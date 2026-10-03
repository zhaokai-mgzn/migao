# CI/CD 流水线

## GitHub Actions 工作流

> **数量不写死**（易腐：24 小时内真值从 34 变 33，见 issue #5082）—— 现值现取：
> `ls .github/workflows/*.yml .github/workflows/*.yaml 2>/dev/null | wc -l`

| 工作流 | 触发 | 说明 |
|--------|------|------|
| `pr-check` | PR → main | 多 job 门禁: 拦截 .env / admin-api 单测 / admin-web tsc+lint+vitest / E2E 质量门禁(4 个 fixture spec) / UI 回退检测 / QA Growth Gate(G1+G5+弱断言) / Case Contract 校验 / needs-changes 打标（**agent-eval-smoke 已于 #3653 移除**：B 端云冒烟评的是已部署 main、与本 PR 无因果；B 端行为信号**不再挂在 PR 上** —— 原 `agent-behavior-eval` 映射 workflow 已按 #4275 整体删除，改由**本机按 §13.2 映射**承担）。**2026-09-26（#3507 ①）**：`admin-api unit tests` / `admin-web typecheck + unit tests` / `E2E quality gate` 三条腿改为 **job 内 diff 门控**（原先 `admin-web` 只门控 `next build`，其余步骤每个 PR 都跑） |
| `ai-agent-tests` | PR → main | ai-agent-service 单测全量（排除 integration / e2e-real / 4 个 ignore 文件）；**v1.3 起 job 内门控**：无 ai-agent 相关变更时跳过实际单测（required check 仍报告 success，防 dependabot 空跑） |
| `deploy-admin-api` | push main `backend/admin-api/**` | 单测 → **服务器侧就地构建镜像（C′，2026-09-30 起；CI 不再构建、不再推 ACR）** → 云助手触发 SWAS `deploy.sh` → post-deploy 冒烟 |
| `deploy-ai-agent-service` | push main `backend/ai-agent-service/**` | 单测全量 → **服务器侧就地构建镜像（C′）** → 云助手触发 SWAS `deploy.sh` → post-deploy 冒烟 |
| `deploy-frontend` | push main `frontend/admin-web/**` | tsc + vitest → **服务器侧就地构建镜像（C′）** → 云助手触发 SWAS `deploy.sh` |
| `smoke-test` | workflow_call (可复用) | P0 冒烟 (pytest+httpx)，被 deploy 工作流调用 |
| `agent-eval` | workflow_dispatch（按需） | 米宝能力评测（normal tier 按需手动，真实 LLM + `cases/*.yml` 单一源；2026-08-29 起取消每日定时） |
| `agent-eval-adversarial` | workflow_dispatch（按需） | 对抗用例评测（只追踪不阻塞）。⚠️ **口径订正（2026-09-26，#3507 ②）**：本行原写「schedule 每周六 03:00」**已不成立** —— 现取 `origin/main` 的 `on:` 只有 `workflow_dispatch`（每周一 cron 已按 #4974 删除，与本文件「真实 LLM 成本」段「全仓自动真实 LLM 触发 = 0 条」一致）；频率读数见 `tests/unit_ci_workflows/ci_cost_ledger.json` 的 `eval_cadence` |
| `e2e-real` | schedule 每日 00:00 + 手动 | backend `tests/e2e/real/` 真实 LLM 测试，失败自动建 Issue |
| `mini-app` | PR/push `frontend/mini-app/**` | tsc + 单测 + xiaobu H5 视觉回归；**v1.3 起 job 内门控**（同 ai-agent-tests） |
| `issue-contract-check` | issue opened | 校验 CONTRACT_JSON → needs-verification / needs-truths + cases 引用校验 |
| `case-draft` | issue opened/edited/labeled | 自动生成验收用例草稿 + DRAFT cases 引用提醒 |
| `case-redraft` | issue_comment (reject) | 驳回后隐藏旧 DRAFT 重新生成 |
| `verify-trigger` | PR closed (merged) | 贴 VERIFY_TRIGGER → 双验收 → 通过自动 close issue |

## CI 队列治理（v1.3，2026-09-04）

- **concurrency 取消旧 run**：`pr-check`/`ai-agent-tests`/`mini-app` 均加 `concurrency.group`（按 PR 号），同 PR 新 push 自动取消旧 run，防多 commit 并发打满 runner 队列。
- **变更门控（job 内，不整层 skip）**：`ai-agent-tests`/`mini-app` 等 required job 在 job 内用 `git diff origin/main...HEAD` 检测相关路径；无变更时实际执行 step 跳过（job 仍 success，required check 永不悬空）。**注意：不要改回 workflow 级 `paths` 过滤——required check 会卡在 "Waiting" 永不报告**（见 §3.2 技能说明）。`worker-h5-tests.yml`（只认 `frontend/worker-h5/**`，跑 Node 内置 `--test`，零 install/零构建）是这类信息性 check 的现存例子（**非 required 信息性 check**，#4786）。（原另一个同族例子 `agent-behavior-eval.yml` 已按 **#4275** 整体删除 —— 它的唯一产物是 PR 评论、绑死 PR 上下文，无法改造成有意义的手动档。）
  · **2026-09-26（issue #3507 ①）扩到 `pr-check` 的三条腿**：`admin-api-test`（`detect_api`）/ `admin-web-test`（`detect_aw`，由「只门控 `next build`」扩到**整条腿**）/ `e2e-quality-gate`（`detect_e2e`）。触发谓词、`must_cover` 面与被门控的**步骤名**逐条登记在 `tests/unit_ci_workflows/declaration_gate_registry.json` —— 「未登记即红 / 谓词必须与现取逐字相符 / 触发面必须覆盖断言所读的对象面 / 按**步骤名**定位（改步骤序列必须同改登记册）」四条由 `tests/unit_ci_workflows/test_gate_coverage_and_same_source.py` 机械执行。
  · **类级锁（为什么这次不会再被烧）**：`tests/unit_ci_workflows/test_required_check_no_paths_filter.py` —— 凡**上报 required 检查名**的 workflow，其 `on.pull_request` **不得**有 `paths:` / `paths-ignore:`（命中即红；红证 = 往 `mini-app.yml` 的 `on.pull_request` 加一行 `paths:`）。required 集合**现取** `gh api …/branches/main/protection`（复用 `scripts/merge_gate.py` 的读法，不另写一套）；CI 里读不到（**需 admin**）⇒ 退回 `tests/unit_ci_workflows/required_status_snapshot.json` 并打印退路横幅 —— **退路不覆盖「分支保护新增了一条 required 而 snapshot 还不知道」**，改分支保护后请在能读该 API 的环境跑一次 `python3 tests/unit_ci_workflows/test_required_check_no_paths_filter.py --refresh`。
  · **🔴 required 腿为什么只能「步骤级」门控 —— job 级 `needs` / `if` 一律不许（2026-10-03，issue #6144 P1-5）**：GitHub 对**被 job 级 `if` 跳过**（或**因 `needs` 上游被跳过 / 取消而未创建**）的 job **不上报该 context** —— 只有 job 真创建了才上报（**步骤**级 `if` 跳过照旧上报 `success`）。⇒ 一旦 required 腿挂上 job 级门控，在不命中该面的 PR 上该检查**永不到来**，PR 永久停在 `Expected — waiting for status to be reported`，**没有任何检查会变红**（与 #3507 ① / #4786 / #5101 / #4231 同族）。
    · **实测（#6099）**：15 条 required 腿现取**没有一条**用 job 级 `if` 跳过；窗口内 required 的缺席**全部**来自「并发取消（`cancel-in-progress`）导致 job 未创建」（缺席率 ≤1.35%），**不是** job 级跳过 ⇒ **风险尚未发生，但此前没有任何判据拦它**。
    · **实测（#6052 / issue #6051）**：`E2E quality gate` / `xiaobu H5 visual regression` / `bmini-app build (h5 + weapp)` / `bmini H5 tabBar geometry (e2e)` 这 **4 条非 required** 重腿被改成 `needs: <面判定 job>` + `if: … needs.<job>.outputs.run == 'true'` ⇒ 被跳过时 **context 根本不创建**（实测 65 条新格式 run 里 **17 条被跳 = 26.2%**）。那**是**有意的（它们**不是** required，且面判定 job 会播报「未跑」）⇒ **判据只对 required 名生效、不许误伤它们**。
    · **判据（两条腿，各自能单独变红）** —— 都在 `tests/unit_ci_workflows/test_required_check_no_paths_filter.py`：① `::test_no_job_level_needs_on_a_job_reporting_a_required_check`：required 腿**不得**带**任何** job 级 `needs:`（上游会不会被跳是运行期行为、静态判不了 ⇒ 只能禁掉整个依赖面；现取 15 条 required 腿**一条 `needs` 都没有** ⇒ 零误伤）；② `::test_no_context_dependent_if_on_a_job_reporting_a_required_check`：required 腿的 job 级 `if:` **只许恒真形态**（无条件 / `always()` / 常量比较）。`event_name` 白名单单独一条规则，判定式 = **白名单字面量 ⊇ 该 workflow 的自动触发面**（`workflow_dispatch` / `workflow_call` 是**人为**触发面，不计入覆盖面）—— 这条把「**今天恒真**」与「**永远恒真**」分开了：现取 9 条 required 腿带 `if: github.event_name == 'pull_request'`，`pr-check` 的自动触发面只有 `pull_request` ⇒ **现在是绿的**；但**加任何自动触发面**（`push` / `schedule` / `merge_group` …）而不同步改谓词 ⇒ **当场红**。判别力自证 = `::test_discriminating_power_on_injected_job_gates`（三条注入：required 腿加 `needs` ⇒ 必红 / required 腿加 `if: github.event_name == 'schedule'` ⇒ 必红 / **非 required** 腿加同样的 `if:` ⇒ **仍绿**）。
    · **正确修法**：required 腿的门控**下沉到 step**（`if: steps.detect_xx.outputs.run == 'true'`，job 照常创建、照常上报 `success`；范式 = `pr-check.yml` 的 `Detect admin-web changes` 一族，登记册 = `tests/unit_ci_workflows/declaration_gate_registry.json`）；或该检查**本就不该是 required** ⇒ 从分支保护里撤掉（顺序不可换：**先改门控、再改分支保护**）。
  · **本地孪生：`verify-all.sh gate` 的 bmini 腿（2026-09-27，issue #4221 族）**：CI 的 `bmini-app` 两条腿此前**在本地没有任何腿**（改 bmini 的包只能手工跑 tsc/jest/build，实测两个 bmini 包都如此）⇒ `gate` 档按「变更集命中触发面」派发一条与 CI **逐字同命令**的本地腿（`npx tsc --noEmit` / `npm test` / `npm run build:h5` / `npm run build:weapp`）。三条口径：① **只在 `gate` 档**（`quick` 是开发者快循环，刻意不塞）；② 触发面 = 该腿**判定对象的输入闭包**（`frontend/bmini-app/**` ∪ 它 import 到的跨目录仓内文件，现取 `frontend/admin-web/src/lib/print-media.json`）—— **不照抄** CI 谓词（CI 含 `tests/|.github/`，那两类改动影响不到 tsc/jest/build）；③ 🔴 **缺依赖 ⇒ fail-closed 记 ❌**（不是「未就绪」跳过 —— 在合并门禁上「没跑」不得被读成「通过」），未命中触发面时控制台显式声明「未跑」。覆盖面登记在 `tests/unit_ci_workflows/local_gate_matrix.json`，判据 = `tests/unit_ci_workflows/test_local_gate_matrix.py`（新增模块目录 / 登记已死的腿 / 未裁定的跨目录输入 ⇒ 红；未覆盖台账只许缩短）。⚠️ 与本节同口径：本地腿也是**job 内 diff 门控**（未命中 ⇒ 显式「未跑」），**不动任何 workflow**、也不改回 workflow 级 `paths` 过滤。
  · **新增 CI 守卫文件要过的三张登记面（2026-09-27 实测，关联 #5001）**：往 `tests/unit_ci_workflows/**`（以及 `.github/`、`scripts/` 的判据面）**新建一个守卫文件**时，同一个文件会命中**三张互不相干的登记面**，缺任何一张 ⇒ **卡合并**。实测代价：本单为第三张**白烧一轮 CI**（run `36281997395` 的 `ci workflow helper unit tests` = 5211 passed / 1 failed）。
    · **面 1 —— 测试文件头的 `# case_ids: <ID>`**：**任何**新增/修改的测试文件都要。判据 = `QA Growth Gate`（ID 必须是**注释起始行**、落在**前 50 行**内、且真实存在于 `.github/cases/**`；用例号往现有最大号**顺延**）。
    · **面 2 —— `tests/unit_ci_workflows/declaration_gate_registry.json` 的 `same_source_claims`**：模块级字面量集合**正上方**的 `#` 注释里出现「同源 / 逐字一致 / 必须等于 / 保持一致 / 同一集合 / 单一实现 / 两份实现」任一措辞时。判据 = `tests/unit_ci_workflows/test_gate_coverage_and_same_source.py::test_same_source_claims_have_criteria`（要 `criterion` = **真实存在**的测试，或 `unfixed` + 理由/单号/owner）。
    · **面 3 —— `tests/unit_ci_workflows/guard_scope_ledger.json` 的 `guards`**：模块里出现**语料字面量**时（当前语料 = `*.sh` ⇒ 任何含 `*.sh` 的字符串常量，**包括红证注入串**）。判据 = `tests/unit_ci_workflows/test_guard_scope_declaration.py`（真扫描语料 ⇒ `kind=scans` + 结构化 `GUARD_SCOPE`；只**点名**语料 ⇒ `kind=mentions` + reason/issue）。
    · **自查清单（可复制；两条 pytest 都应绿）**：
      ```bash
      F=tests/unit_ci_workflows/<你的新守卫>.py
      grep -nE '^#[[:space:]]*case_ids[[:space:]]*[:=]' "$F" | head -1      # 面 1：必须落在前 50 行
      python3 -m pytest tests/unit_ci_workflows/test_gate_coverage_and_same_source.py -q   # 面 2
      python3 -m pytest tests/unit_ci_workflows/test_guard_scope_declaration.py -q         # 面 3
      ```
    · 🔴 **边界（明确的，不要把本节读成覆盖面更大的东西）**：① `declaration_gate_registry.json` 的 **`gates` 只收 `on.pull_request` 面的门禁**（workflow 级 `paths` / 步骤级门控输出）—— 改 **`on.push.paths`**（部署/发布触发面）**不需要**登记 `gates`（本单即如此，只登记了 `same_source_claims`；别去改错册子）；② 三张面**各自已有 fail-closed 判据**，本节**不是新门禁**、**不改任何判据的通过条件** —— 它只解决「作者事前不知道去哪三处登记」（本单实测：三张面把我**逐一**拦下；事先知道可省一轮 CI）；③ 各面自己的残余照旧（见各判据 docstring，例如「完全不声明射程、也不引用语料字面量的新守卫**不会**有东西变红」）。
    · **复算 #5687（同一天第二个新守卫，结论：三张面**一张都没命中**）**：新增 `tests/unit_ci_workflows/test_rerun_to_clear_paths.py`（类级 meta-guard：消红路径未登记即红）时按上面清单自查 —— 面 1 **命中**（声明了 `# case_ids: MC-024`，新用例号顺延自当时最大号 MC-023）；面 2 / 面 3 **未命中**（该文件的模块级字面量注释里没有那七个措辞、也不含 `*.sh` 语料字面量）⇒ 两条 pytest 全绿 ⇒ **无须**动 `declaration_gate_registry.json` / `guard_scope_ledger.json`。⇒ 与上面的「边界 ①」合起来读：**三张面是按形态触发的，不是「新守卫一律要登记三处」**（把它读成后者会去改错册子）。
    · 🔴 **本节只覆盖「新建守卫文件」这一种形态**：往**既有**守卫文件里加判据（如本单同时给 `test_flaky_ledger_kind_semantics.py` 加了 10 条）**不在本节面内** —— 那类改动命中的是各面自己的判据（如用例号真实性、弱断言面），**没有**「新文件三张面」这条路径。
  · **`Flaky Ledger Reconcile` 的红是给人看的，不是拦合并的（issue #5687 顺带登记，**有意不修**）**：该 job **不在** `branches/main/protection` 的 required 集合里（人已裁定：用阻塞换可见性不划算）。它的**唯一**价值是「把 `kind=flaky` 且 `status=open` 且没有 `follow_up` 的欠账渲染成 job summary + `::error::`」。⇒ 🔴 **别把「它没红」读成「没问题」**：`kind=suspect-window-deterministic`（跨时间桶的「重跑通过」）这类**窗口型确定性缺陷**此前**只有这一个信号**，而它可以无限循环（缺陷留在 main 上、明天同一时段再红一次）。真正的护栏改成**在判定侧收紧**：跨桶 ⇒ 不再判普通 `flaky` + **强制跟踪**（缺 `follow_up` ⇒ `selftest` / `append` 判违规，fail-closed）；判据见 `tests/unit_ci_workflows/test_rerun_to_clear_paths.py`（类级 meta-guard：任何以重跑结果为唯一依据消红/降级的路径**未登记即红**）与 `tests/unit_ci_workflows/test_flaky_ledger_kind_semantics.py`（实例，含 run `36280962072` 的真实读数复算）。
## 红证机具的可靠性：改磁盘文件的变异**可能不被读到**（2026-09-27 实测，关联 issue #5687）

**这一节是一个被实测证伪的假设的下场记录**：做红证时我以为「改磁盘上的真文件 → 跑 pytest ⇒ 判据必红」是稳的。**它不是。**

### 形态（现象）

给判据做注入式红证时，用「**改磁盘上的真文件 → 跑 pytest**」这条路：**判据函数直调能判红，而 pytest 跑法下判据拿到的是未变异的文本** ⇒ 该红证**在 CI 上永远绿** = **空断言**（正是「每条断言都要有红证」要防的那个东西本身）。

### 本会话的实测读数（三条红证，逐条）

对 `tests/unit_ci_workflows/test_rerun_to_clear_paths.py::TestWorkflowStructure` 的三条 workflow 红证（被测文件 = `.github/workflows/flaky-triage.yml`）：

| 注入的坏形态 | 期望 | 实测（**改盘后跑 pytest**） | 同一函数**直调**（`python -c`） |
|---|---|---|---|
| `mark_suspect` 步骤条件改 `false` | 判红 | `1 passed`（`bad` 为空） | **正确判红** |
| 给 `mark_suspect` 步加 `--add-label "flaky/rerun-green"` | 判红 | `1 passed`（`bad` 为空） | **正确判红** |
| 摘掉 `triage-follow-up` 调用 | 判红 | `1 passed`（`bad` 为空） | **正确判红** |

补充读数（说明它不是「注入压根没落盘」）：

- 改盘后**在测试方法里**读回文件，`REAL_WORKFLOW` 与 `WORKFLOW_PATH.read_text()` **都**含注入串（`True`）；把 `bad` 打印出来也**确实非空**；
- 但把该处的断言换成 `raise AssertionError` ⇒ **测试会失败**。⇒ **同一个测试方法里，"变异被读到"时有时无** —— 不是简单的"文件没改到"。
- 已排除：`.pyc` 缓存（清空 `__pycache__` 后仍复现）、`tests/unit_ci_workflows/conftest.py` 的文件级缓存（该 conftest 只缓存用例语料解析，不缓存 workflow 文本）。

🔴 **机制未定（如实登记，不编一个听起来对的机制）**：**现象已定、机制未定**。排查到此为止 —— 继续追这条线索的收益低于「换一条结构上不可能出这个问题的做法」（见下）。

### 正确做法（本仓现成范例）

**当场在内存里构造坏形态**，不要改磁盘：

```python
wf = yaml.safe_load(REAL_WORKFLOW)                       # 真文件当基线
wf["jobs"]["triage"]["steps"] = [ …按判据语义改结构… ]    # 变异发生在**内存对象**上
mutant = yaml.safe_dump(wf, allow_unicode=True, sort_keys=False)
bad = workflow_structure_violations(mutant)              # 判据吃的是**当场构造**的文本
```

并配一条**判别力自证**（否则「内存构造」也只是"我以为构造成功了"）：

- 判据：`tests/unit_ci_workflows/test_rerun_to_clear_paths.py::TestWorkflowStructure::test_guard_has_discriminating_power_in_memory`
- 读数（三条各自判红，逐条记在本 PR body）：条件改 `false` ⇒ `没有 action == 'mark_suspect' 的步骤 ⇒ …没有任何动作落地（= 静默放行，红线）`；加 flaky 标签 ⇒ `mark_suspect 打了 flaky/rerun-green ⇒ …⇒ 红线`；摘跟踪单调用 ⇒ `没有调用 flaky_ledger.py triage-follow-up 的步骤 ⇒ 「强制跟踪」没有实体动作`。

### 通用判据（写给下一个包）

> **凡红证涉及"改磁盘文件"，必须额外有一条断言证明「该变异真的被读到了」**（读回文件内容比对 / 断言变异体 ≠ 原文 / 直接喂构造体）；否则**视为空断言**。

本会话出现的**三个同族对照读数**（**读数各不相同**，别混为一谈）：

1. 另一包：「**只改注释**」⇒ 命中**锚失配**而**不是目标分支**（红证打偏 —— 注入了，但打的不是那条判据）；
2. 「**撤掉整条禁则** ⇒ 主判据**转绿**」⇒ 那才是**真的反向红证**（拿掉实现就变绿 = 该红是它挣来的）；
3. 本条：**变异没被读到 ⇒ 恒绿**（`bad` 为空、测试通过）。

### 🔴 边界（显式登记：这一节**覆盖不到**什么）

- ❌ **「内存构造」这条路覆盖不到「该文件根本没被任何判据读过」**：那种情况下判据**连红都不会红**，得靠「**语料非空 / 判据非空转**」那条自证（`problems_rerun_to_clear_paths` 的 `语料为空` 分支即此类）。
- ❌ 本节的结论来自 **workflow 文件（YAML 文本）**的实测 —— **是否适用于所有语料类型（Python / JSON / SQL / 生成物）未逐一验证**。⇒ 别把它读成「所有红证都不可信」，也别读成「只改 workflow 才要小心」。
- ❌ 本节**不是新门禁、不改任何判据的通过条件**：没有任何东西会拦住「用改磁盘文件做红证」——**只有纪律**。
- ❌ 本节**不声称**「CI 上跑就一定复现」：观测发生在**本机**（pytest 9.1.1 / Python 3.11）；「CI 上永远绿」是**由形态推出的结论**（若注入不被读到，判据就不会红），**未在 CI 上直接观测**到某条红证恒绿。

  · **成本读数 / 上限 / 预算（issue #3507 ②）**：`tests/unit_ci_workflows/ci_cost_ledger.json` 逐条记录 PR 触发腿的**实测**中位/p90/max、**硬杀上限**与**目标预算**。
    · **硬杀上限** = 该腿自己声明的 `timeout-minutes`（判据与现取 YAML 逐条复比 ⇒ 手抄腐烂即红）；
    · **目标预算** = 该腿**实测 p90 向上取整**（owner 裁定 2026-09-26）—— 预算是**读数的函数**，不是人手填的数；取不到读数（n < 3）的腿保持 `null` + 显式留白，**不编数**（判据 4 手改任一预算即红）；
    · **超预算判红**：新实测 p90 上取整 > 已冻结预算 ⇒ `--measure` **非零退出且不写台账**，并要求**先查「新增」开销**（钉与负载无关的计数：新判据文件数 / 真库 `initdb` 次数 / 语料真解析次数 / 新增依赖安装），**不得**靠抬 `timeout-minutes` 交差（与 #5365 同源）；确有必要抬 ⇒ 显式 `--measure --accept-raise`（改动在 diff 里可见）。⚠️ 该判红在**能读 Actions API 的环境**（本机/attended）生效 —— CI 读不到历史时长，只锁「预算 == 实测 p90 上取整」这条文件不变式（边界写在台账 `attribution_policy.enforced_where`，判据 5 核它非空）；
    · **频率议题**：`agent-eval` / `agent-eval-adversarial` 现取都只有 `workflow_dispatch` ⇒ 裁定**有意不设月度上限**（只登记手动触发现状），条件 = 任一评测 workflow 恢复/新增自动触发面时**重开**（见台账 `policy_decisions`，判据 6 核裁定人 + 重开条件）；
    · 判据 = `tests/unit_ci_workflows/test_ci_cost_ledger.py`（7 条，含超预算判定的纯函数红证）；复算 = `python3 scripts/ci_cost_ledger.py --measure`。
  · **静态落地面腿**：`worker-h5-publish.yml`（`push: main` + paths 只认 `frontend/worker-h5/**` 与发布链路自身；**刻意不加 `pull_request`** —— 它写的是**线上静态根**，PR 分流内容不该有机会落上去，故也没有「required 卡 Waiting」的形态）把 `frontend/worker-h5/` 的 `index.html` + `src/**` **逐字**发布到 `app.migaozn.com` 静态根下的 `w/`（零构建，**不引 npm build**），发布后断言线上 `/w/` 的 body 哈希 == 仓库文件且不含 C 端标识（issue #4837；nginx `root` 与 `w/` 子树的红线见 `deploy/swas/h5-publish-remote.sh` 的目标守卫）。**发布兜底（issue #5001）**：该腿唯一的自动触发面是 `push: main`，而被 `GITHUB_TOKEN` 合并的 auto-merge **吞掉那个 push**（#3113 同族）⇒ `deploy-reconcile.yml` 把它列为**第四条对账腿**（`reconcile_one worker-h5 worker-h5-publish.yml frontend/worker-h5 ""`；它不构建镜像 ⇒ 镜像判据对它恒不成立，判定走**漂移判据**：自上次成功发布起 `frontend/worker-h5/**` 有无改动，有则 `gh workflow run worker-h5-publish.yml`）—— 对账由 `schedule` 触发，免疫该抑制。
  · **第二条静态落地面腿（issue #5668）**：`bmini-h5-publish.yml`（`push: main` + paths 只认 `frontend/bmini-app/**`、`deploy/swas/nginx.conf` 与发布链路自身；同样**刻意不加 `pull_request`**）把 B 端 h5（`npm run build:h5`，按 `TARO_APP_H5_PUBLIC_PATH=/b/` 构建）发布到 `app.migaozn.com` 静态根下的 `b/`（nginx 的 `location /b/` 带**自己的** fallback `/b/index.html` —— 借用根的 fallback 会让 `/b/<子路由>` 静默渲染出 C 端）。产物经**ACR 传输镜像**（`deploy/bmini-h5/Dockerfile`，实例无 node 工具链）搬到实例，发布后断言「线上 body 哈希 == 本次构建产物」+ `/b/<子路由>` 不串端 + `/` 仍是 C 端 + worker-h5 零回归。**发布兜底**：同 worker-h5，它已登记进 `deploy-reconcile.yml`（腿名 `bmini-h5-hosting`，走漂移判据 ②；腿名与传输镜像名有意不同，见该 workflow 内的注释）。
  · **第三条静态落地面腿（issue #4184）—— 第一条「拥有静态根**本身**」的腿**：`c-end-h5-publish.yml` 把 C 端小布 h5（`frontend/mini-app` 的 `npm run build:h5`，`publicPath: '/'`）发布到 `app.migaozn.com` 的**静态根本身**（nginx `root` = `/opt/migao-deploy/h5`）。建腿前的现取读数：`curl -sI …/js/app.js` 的 `Last-Modified` = **08-30 06:54 GMT**，而 `frontend/mini-app` 最近改动 = 09-26 ⇒ 线上落后 **~28 天**而**没有任何东西会因此变红**（「C 端已部署」一直被当真）。
    🔴 **红线（本腿特有）**：同根下**已经住着**工人端 `w/`（#4837，线上有工人在用）与商家端 `b/`（#5668）⇒ 远端执行体 `deploy/swas/c-end-h5-publish-remote.sh` **只删/只替换「上一次由本脚本登记过的顶层条目」**（删除集 = 托管清单 `∩` 磁盘现值；首次发布无清单 ⇒ **空集**，且根上有无人认领的条目时判 `TAKEOVER_REQUIRED` = 要人**显式签字**），并对 `w` `b` 两个**保留前缀**做三层判据：① 结构层（产物顶层/托管清单出现保留前缀 ⇒ 立刻 die）② 产物层（根 `index.html` 不许引用 `/<保留前缀>/…` = 串端）③ 自证层（发布前后逐子树的**规范化摘要**——路径+内容，不吃 mtime/顺序——与各自 `index.html` 哈希**逐字相等**，CI 侧四条读数缺一即判红）。
    🔴 **只手动发布**（用户 2026-09-27 裁定 B「通路建好并自证，但首次发布由人手动触发」）：`on.push.paths` **恰好**只有 `frontend/mini-app/**`（**刻意不含** `deploy/**` 与 workflow 自身 ⇒ **合并建通路的那个 PR 不会发布任何东西**）。**三种触发形态只有一种会发布**（模式判定步 `Resolve mode` 是唯一决定点，它逐字读 `github.event_name` 与 `inputs.publish`）：`push` / `schedule` / 不带 `publish=true` 的 dispatch ⇒ `notify`（**只报告**）；`workflow_dispatch` + `publish=true` ⇒ `publish`（写盘）。写盘步 / `build:h5` / 落地面断言三步都逐字 `if: steps.mode.outputs.mode == 'publish'`（纵深防线）。`publish` 默认 `false` ⇒ 连 `deploy-reconcile.yml` 的兜底 dispatch 也**不会**发布（它只会跑 notify）。**发布入口**：`gh workflow run c-end-h5-publish.yml --ref main -f publish=true`。
    **兜底面（`FM-E17` 同批）**：`push` 在本仓会被 `GITHUB_TOKEN` 合并吞掉 ⇒ 本腿也有每日 `schedule`（`53 18 * * *` = 02:53 +08），登记在 `tests/unit_ci_workflows/publish_leg_fallback_ledger.json`；它的 notify 步判的是**线上产物是否落后**（判据本体 = `scripts/h5_freshness_guard.py`，**不写第二份口径** —— 比 `dist/index.html` 会是**空转**：`dist/` 在 `.gitignore` 里，CI 检出里没有它）。
    **兜底对账（FM-E3 同批）**：`deploy-reconcile.yml` 新增第六条腿 `c-end-h5`（无镜像 ⇒ 走漂移判据 ②），并在 `test_swas_deploy_ci_hardening.py::SVC_TO_DEPLOY_WORKFLOW` 登记；发布链路自身的两个文件（CI 包装 / workflow）按同口径逐条登记进 `reconcile_trigger_paths_ledger.json` 并标 **`never_in_trigger`** —— 该标记 = 明文**禁止**「把它们加进触发面来消账」这条出路（它们的标法比常规缺口**更严**：加了就红）。
    **判据**：`tests/unit_ci_workflows/test_c_end_h5_hosting.py`（48 条：结构层真 YAML/真脚本 + **行为层在 `tmp_path` 沙箱真跑远端执行体** + 本地 http server 上落地面断言的红绿两面 + 「只改注释 ⇒ 不红」对照）。
    🔴 **产物怎么到达服务器（#6095 第三层，2026-10-03）**：`dist/` 是**构建产物、不在 git 里**（`.gitignore` 有 `dist/`；`git ls-tree -r origin/main --name-only frontend/mini-app/dist` = **0 个文件**），而本腿唯一的取回通道是「按不可变 sha 从 codeload 取 tarball」（远端 `stage_product()`）⇒ 源码 tarball 里**永远没有** `dist/index.html`（run `37078030820` / sha `d4babbf17` 的 `❌ 发布源里没有 index.html` 就是这个形态）。
    修法 = `deploy/scripts/c-end-h5-dist-push.sh` 把 `dist/**` 打成**孤儿单提交**（`git commit-tree` **不给 `-p`** ⇒ 无父、不胀历史）force-push 到专用分支 `h5-dist`，发布步按 **`steps.dist.outputs.sha`**（不可变 sha）取回 ⇒ 远端取回逻辑**一行不改**（`H5_SRC_SUBPATH=frontend/mini-app/dist`）。
    `permissions` 因此从 `contents: read` 抬到 **`write`**（只为推分支）；推送目标分支现取**不触发任何 workflow**（全部带 `push` 的 workflow 其 `on.push.branches` **一律 `['main']`**，判据从真 YAML 现取）；触发面 / 人工门 / `TAKEOVER` 闸**逐字未动**；命令内容仍 **909 字节** < 16 KB（dist **绝不**进命令内容）。
    判据 = `TestDistDeliveryWiring`（5 条：接线 / 不可变 sha / 拒漂移 ref / identity 仍在 / 注入式红证）+ `test_dist_pipeline_end_to_end_stub_drill`（**端到端桩演练**：本地假 origin + 真 `commit-tree`/`push`/`archive` ⇒ 按 sha 取回真有 `dist/index.html`），并把新链路面文件登记进 `reconcile_trigger_paths_ledger.json`（`never_in_trigger`）。
    🔴 **第四层：推送步骤不许继承运行环境（#6095 第四层，2026-10-03）**：第三层合入后人工发布 run `37081920188`（sha `aedc51ffb`）在**新加的那一步**挂 —— `Prepare dist ref` ⇒ `fatal: empty ident name (for <runner@…>) not allowed`（exit 128），后面三步 skip（连 `RunCommand` 都没走到）。判因 = **脚本继承了运行环境**：`git commit-tree` 需要作者/提交者身份，而 **CI runner 上没有身份源、系统 GECOS 为空**；**开发机**会用 GECOS + hostname 自动兜一个非空身份 ⇒ 同一脚本**本机 rc=0 / runner rc=128** ⇒ 「本机跑一遍」**证明不了 CI 会过**（同族 #6113 剔除继承来的 `MIGAO_HEAVY_L*`）。
    修法 = 造孤儿提交时**显式给身份**（`GIT_AUTHOR_NAME/EMAIL` + `GIT_COMMITTER_NAME/EMAIL` 四个**环境变量前缀**，取环境变量而非 `-c user.name`，因为**环境变量优先于 config**：调用方环境里一个**空**的 `GIT_AUTHOR_NAME` 会把 `-c` 盖掉、仍报 `empty ident name`（实测）；身份 = `github-actions[bot]`（ID 41898282）⇒ 推上去的提交**可追溯**）+ 清掉「我在哪个仓」的环境（`unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR`）。判据 = `TestDistPushIdentityIndependence`（4 条）+ **桩演练改为在「无 ambient 身份」下跑**；注入式红证 = 摘掉显式身份 ⇒ 复现 CI 那条 `empty ident name`；摘掉 `unset` 行 + 敌意 `GIT_DIR` ⇒ 具名判红。
    同批扫出的**同类继承面**：① `H5_PUBLISHED_COMMIT`（新加、会被拼进 SWAS 命令内容）此前**没有**字符集白名单 ⇒ 已补（空或 40 位十六进制）；② 报错文案里**双引号内的裸反引号**被 bash 当**命令替换执行**（DIST_SHA 那句是第三层引入的、清单名那句是存量）⇒ 已转义 + 新增**类级判据 6**（`test_scripts_bash32_var_brace.py`，全仓受控 `*.sh` 射程，heredoc 正文不算）。
    🔴🔴 **第五层：引导取执行体 ≠ 远端取产物（#6095 第五层，2026-10-03）**：第四层合入后真发布 run `37084280991`（sha `c22514360`）前三步全绿（`Prepare dist ref` 真跑通、远端 `refs/heads/h5-dist` 已存在），第四步挂 —— 远端 `bash: /tmp/tmp.XXXX/deploy/swas/c-end-h5-publish-remote.sh: No such file or directory`（`InvocationStatus=Failed`）。
    判因 = **第三层的引导与第二层的引导组合起来错了**：第三层把命令内容第 5 参数换成**产物 ref**（只含 17 个 dist 文件的孤儿单提交）之后，**引导也按它取 codeload tarball** ⇒ 取回的执行体目录里没有远端脚本。
    **为什么前四层都放它过去了**：第三层的桩演练把「远端执行」**打桩**了（从不真取回并执行执行体），第二层的桩演练当时还没有「产物 ref ≠ 源码 commit」这个形态 ⇒ 两侧各自的假设都成立、**组合**不成立（「每块判据都绿，拼起来错」）。
    修法 = **两个 ref 各司其职**：`DIST_SHA`（产物 ref，第 5 参数 / `H5_DIST_SHA`，**不再回落 `$GITHUB_SHA`**）→ 命令内容 `export H5_PUBLISH_SHA=$SHA`、远端 `stage_product()` 按它取产物；`SCRIPT_SHA`（执行体 ref = `H5_PUBLISHED_COMMIT` / `GITHUB_SHA`）→ **只有引导**按它取回并执行 `deploy/swas/c-end-h5-publish-remote.sh`（CLI 侧同等白名单 + 40 位断言）。⚠️ **不**把远端脚本塞进 dist 孤儿提交（会破坏「只含产物」的可审计/可清理性质），也**不**退回内联（16 KB 墙）。
    判据 = `TestTwoRefsCombination`（**组合层**：真造两个提交、真跑组装段、真 `git archive` 取回两棵 tarball、真执行取回的执行体 ⇒ 发布成功且清单两个字段各就各位）+ 静态接线两条 + 注入式红证（① 引导改回按产物 ref 取 ⇒ **用合并后 main 那份脚本在同一夹具上真复现 rc=127 + 同一句报错** ② 产物 ref 漂成执行体 ref）。审计面同族修：清单 `published_commit or sha` → `published_commit or ""`。
     ✅ **同族风险已修（#6124，2026-10-03）**：另两条腿此前也把整份远端执行体**内联**进 SWAS 命令内容 —— `deploy/scripts/bmini-h5-publish-ci.sh` 的命令内容 **10853** 字节、`deploy/scripts/swas-h5-publish-ci.sh` **9256** 字节（上限 16384 ⇒ 余量只剩 ~5.5 KB / ~7 KB）。治法与 C 端那条**同款**：命令内容只留**极小的引导**（按**不可变 sha** 从 codeload 取回 `deploy/swas/{h5,bmini-h5}-publish-remote.sh` 并执行），发布逻辑仍在远端脚本里（单一出处）⇒ 真跑组装段读数降到 **719 / 786** 字节，且与远端脚本大小**解耦**（20 KB 夹具下读数不变）。两条腿同批加**字节前置断言**（超限在**本机**具名判红 + 给出上限出处）；`deploy/scripts/swas-deploy-ci.sh`（部署腿）此前没有这道断言、同批补上（类内**零豁免**）。bmini 腿的**执行体 ref** 由 workflow 显式注入（`H5_PUBLISHED_COMMIT = github.sha`）；worker 腿的产物就是源码树 ⇒ 两个 ref 天然同一个，刻意只用一个变量（结构上排掉第五层那种「两个 ref 混用」）。
     **类级元守卫** = `tests/unit_ci_workflows/test_swas_command_content_limit.py` + 台账 `tests/unit_ci_workflows/swas_command_content_legs_ledger.json`：射程**现取**（`deploy/scripts/**/*.sh` 里含**活代码行** `--command-content` 且文件名出现在某个 workflow 里的），台账 ⇄ 现取集合**双向相等** ⇒ **未登记即红**；每腿必须有字节断言 + 上限出处 + 不许内联 + 断言在云调用**之前**。**读数判据**在各腿自己的 `TestCommandContentLimit`（解耦 / 不可变 sha + 语义 / 超限注入本机判红 / 取不到执行体 fail-closed）。⚠️ 合并后由两条腿的 `push` 面**真跑一次**新引导 ⇒ 在那之前「线上已走通」属「**没跑**」。
     出射程项（照实登记）：`deploy/scripts/wx-mini-test-env-setup.sh` 也有人跑的 `--command-content`，但它是**人交互的一次性向导**（不被任何 workflow 调用）⇒ 不进射程；射程规则**机械可判** ⇒ 它一旦被接进 workflow 就自动进射程、未登记即红。
- **把 paths 门控的信息性 check 提升为 required 的顺序（2026-09-20 固化，#4786）**：**必须先删掉 workflow 级 `paths:`、改成 job 内 diff 门控**（`git diff --name-only origin/main...HEAD` + `GITHUB_OUTPUT`，同 `pr-check.yml` 的 `Detect admin-web changes` 步），**再改分支保护** —— **顺序不可换**：先改分支保护 ⇒ required check 在不命中 `paths` 的 PR 上**卡在 "Waiting" 永不报告** ⇒ 形态 =「**没有任何检查会变红，但 PR 合不了**」（#4231 同族）。
- **真实 LLM 成本**：**PR 层 = 0 次真实 LLM**（2026-09-17 用户裁定 2′/4′，承载 issue #4034；**#4275** 之后 PR 层连**零 LLM 的映射信号**也没有了 —— `agent-behavior-eval.yml` 已整体删除，PR 上**不再有任何自动行为信号**，代价已知并接受）。判定走**单一入口** `post-deploy-eval`（**仅手动 `workflow_dispatch`**：#4262 收敛定时档、**#4974 删掉最后一条每周一 cron** ⇒ 全仓自动真实 LLM 触发 = **0 条**）；映射能力保留在 `tests/agent_eval/behavior_mapping.py`（零依赖纯函数，本机可调）。LLM 红例的闭环改由**确定性下沉台账**承接（`.github/llm-finding-ledger.json` + `llm_sink_check.py`，见 `docs/testing/llm-finding-sinking.md`）。
- **观察指标**：`gh run list --status queued` 排队 >20 即需治理（先按 DEV-FLOW §7 清 dependabot 潮）。

## CI / 台账反复出错点：具名清单（2026-09-27 固化，用户逐字「**如果 ci 或者台账经常出错的点也应该固化下来**」）

**这一节不是劝告**：下面每一条都带 `FM-EN` 记号，**逐条**给出「现状（有无守护）→ 守护是什么 →
证据」。记号与 `tests/unit_ci_workflows/dev_mode_failure_modes_ledger.json` 的 `ci_findings` **双向绑定**，
判据 = `tests/unit_ci_workflows/test_dev_mode_failure_modes.py` 的**判据 7**（`ledger → doc`：台账每条必须
在这里具名）+ **判据 23**（`doc → ledger`：这里具名的记号必须已登记，册外的按**只许缩短**的
`CI_MARKS_WITHOUT_ENTRY_FROZEN` 登记，现取 = 缺号的 `FM-E6`）：

- **未守护（`state=gap`）条目只许缩短**：条数 ≤ 判据里**冻结**的上限（上限写在判据里，台账改不动它），
  且每条必须带 `gap_owner` + **显形条件**（`gap_shows_when`，即"无守护时它会长成什么样"）；
- 🔴 **已修的不重复登记**：`state=guarded` 的条目**只点名判据**（说明它已在别处登记），不新开缺口账；
- `state=registered` = 有具名台账登记但**未接 CI 门禁**（人工 / 集成环节调用）。

| 记号 | 现状 | 守护 / 登记 | 要点 |
|---|---|---|---|
| **FM-E1** | ✅ **已有守护** | `.github/workflows/deploy-reconcile.yml` 的 schedule 对账（4 条腿）；判据 `tests/unit_ci_workflows/test_config_change_triggers_deploy.py::test_every_deploy_trigger_path_reaches_its_reconcile_leg` | auto-merge 吞掉 `push`（`GITHUB_TOKEN` 合并的 push **不产生 run**）⇒ 唯一的自动触发面失效；对账由 `schedule` 触发 ⇒ **免疫该抑制** |
| **FM-E2** | ⚠️ **已登记，未接 CI** | `scripts/stranding-check.sh`（内容级三态 `0/1/3`，`3` 不得当 `0` 读）+ `migao-dev-flow` §2.2 的硬规则（改完全部 commit 再开 PR / 全程 draft） | **auto-merge 抢在 `commit` 之前**合并 ⇒ 改动**搁浅在工作区**（实证：包声称「已随 #5695 合并」而两处文档改动没进 main，补 PR #5698）。**显形条件**：PR ready 后补 commit ⇒ 本地有、`origin/main` 无、且**无 PR 承接**；核法 = 逐文件 `git show origin/main:<path>`（**不是**看 commit 可达性） |
| **FM-E3** | ✅ **已修（本会话），不重复登记** | 触发面 `deploy-admin-api.yml` 的 `on.push.paths` + 对账面 `deploy-reconcile.yml` 的 pathspec **两处同批**接线；判据 `...::test_config_only_commit_is_judged_as_drift_and_dispatches_a_deploy` | 只改 `deploy/swas/**` 原先**一条部署腿都不触发** ⇒ 改动静默不生效（#5668 的 `/b/`、#5676 的 `/i/` 都只靠人工 dispatch 才生效）。两处是**同一事实的两处投影**，常驻双向比对（`reconcile_trigger_paths_ledger.json` 的存量缺口**只许缩短**） |
| **FM-E4** | ✅ **已修（#5707 销账，`guarded`）** | `.github/workflows/main-freshness-guard.yml`（`push: [main]` + `schedule '43 * * * *'` + `workflow_dispatch`，**刻意无 `pull_request`**）+ **单一实现** `scripts/generated_artifacts_freshness.py`（三态 `0/1/3`，**没有「跳过」这一态**）；判据 = `tests/unit_ci_workflows/test_main_freshness_guard.py` | **生成物新鲜度原先只在 `pull_request` 面** ⇒ main 上先漂移、**下一个无辜 PR 才红**，而红的信息指向那个 PR 的 diff（**归因指向错误的对象**）。2026-09-27 咬了两次。**现取读数（本单独立复核）**：run `36295323465`（`workflow_dispatch`、`headBranch=main`、2026-09-27T04:47:19Z = **12:47 +08**）`conclusion=success`；本机 `python3 scripts/generated_artifacts_freshness.py` ⇒ rc=0。⚠️ **本腿不拦合并**（报告型 + 判红开 P1 值班 issue：§2.2 的两条前置它都不满足 —— 无 `pull_request` 稳定判定面、判定含 `git` 历史） |
| **FM-E5** | ✅ **已修（#5695），不重复登记** | 时间桶判据（跨桶 ⇒ `suspect-window-deterministic` + **强制跟踪**）+ 类级 meta-guard；判据 `test_rerun_to_clear_paths.py::test_unregistered_clear_path_turns_red` | flaky 分类只凭「重跑通过」⇒ 掩盖**窗口型确定性缺陷**（缺陷留在 main、明天同一时段再红，可无限循环）。**唯一信号**是那个**非 required** 的 `Flaky Ledger Reconcile` 红 —— 它逐字声明「判红不等于阻塞合并」 |
| **FM-E6** | ⚪ **未固化（转述未获 durable 证据）** | — | 转述里有一条「`burn-down` 与生成物陈旧耦合 ⇒ 报错误导（同一审计两条红、其中一条是次生后果）」，**本机只读复核未找到**可复核读数 ⇒ 按「找不到 durable 证据的 ⇒ 不写进技能」的口径**不入册**；重启条件写在台账 `not_solidified` 的 `NS-1` |
| **FM-E7** | 🔴→✅ **本单补判据（原先零守护）** | `test_dev_mode_failure_modes.py::test_case_ids_are_unique_across_the_corpus` | **用例号被抢**：两个并行包各自「取现取最大号 +1」⇒ 双双写成同一个新号；先合的无事，**后合的**把重号带进 main（本会话实测 7 次：UI-061 / UI-064 / MC-022 / MC-023 / BM-019…）。**修法不是「rebase 后再查一次」这句劝告** —— 而是把唯一性变成判据：重号一进 PR 就红（**红在后合的那一个**，正是它需要改号的那一个） 🔴 **缓解办法（实测有效，RBAC P3）**：① 现取已合并最大号 `grep -rhoE "\b(BM|UI|MC|PR|OR|DF|HR)-[0-9]+" .github/cases/ | sort -u`；② **再查一遍在飞 PR 的 diff / 最新内容**（`gh pr list --state open` 后逐个取 `cases/` 里的 id）—— **这一步就是能拦住「main + 在飞」的那一步**；③ **rebase 后再查一次**。⇒ 与 `CASE_ID_ALLOCATION_BOUNDARY` 的关系：**判据只看已合并状态、拦不住在飞 ⇒ 判据拦不住的地方，判别动作补上**。 🔴→⚙️ **上面的三步手工动作已于 2026-09-27 被机械化**（`MC-046` 被三个包同时取到之后）：取号 = **一条只读命令** `python3 scripts/next_case_id.py <PREFIX>` —— 候选 = main ∪ **全部 open PR 的分支** ∪ 本工作区、取**最小空闲号**、并在同一次调用里断言「返回的号 ∉ 候选集」；**看不到在飞面**（`gh` 不可用 / 未登录 / 离线 / 某个 PR 内容读不到）⇒ 打印「**无法判定 ⇒ 不许取号**」并 `exit 3`（**禁止**乐观给号）。判据 = `tests/unit_ci_workflows/test_next_case_id_allocator.py`（只读性 / 三态 / 内部自证 / **内存构造复现「main + 在飞」现场** / `scripts/**` 单一实现 / 技能面口径唯一），用例 `MC-041`；用法与输出形态见 `migao-dev-flow` §26.3 ⑫，**盖不到的事**见 §26.4 |
| **FM-E8** | 🔴→✅ **本单补判据（原先零守护）** | `test_dev_mode_failure_modes.py::test_migration_versions_are_unique_in_the_live_dir`（**射程 = 活的 `db/migration/`**） | 两包同抢 V132 ⇒ 改名 V133/V134。既有 `test_migration_immutability.py` 只判**文件名**在两个载体目录间不重复 + 已登记文件逐字节冻结，**不判版本号**。**边界**：`migration-archive/` **存量**就有版本号重复（同一 V 号两份、文件名不同）⇒ 把唯一性套到归档上会是存量假红，故**只登记为只许缩短的常量** |
| **FM-E9** | ✅ **已有守护** | 三张面**各自**已有 fail-closed 判据（本单实测三张面全绿）+ 本页『新增 CI 守卫文件要过的三张登记面』节（作者事前自查清单） | `case_ids` / `same_source_claims` / `guard_scope_ledger` —— 新守卫文件**常同时命中多面**；今天有包为此多烧一轮 CI。判据：`test_gate_coverage_and_same_source.py::test_same_source_claims_have_criteria` + `test_guard_scope_declaration.py::test_every_corpus_referencing_module_is_registered` |
| **FM-E10** | 🟡 **部分守护（gap 收窄：快循环档 5 条模块腿已收口；残余 = redproof 档 9 条实跑腿）** | owner = 门禁 owner（`verify-all.sh` 面）。**本包落码**：`verify-all.sh::report_gated`（一个共享包装 + 每模块一个 face 谓词）+ `tests/unit_ci_workflows/local_gate_matrix.json` 的 5 条 `trigger{kind: diff-face-gated-deps, hit_fn: face_hit, predicate_fn, fail_closed: true}`；判据 = `tests/unit_ci_workflows/test_local_gate_matrix.py` 的 **C9**（静态接线：必须由 `report_gated` 在档位分支**顶层无条件**派发 + 三态行为：命中+缺依赖 ⇒ ❌/`FAIL=1`、未命中+缺依赖 ⇒ ⏭️/`READY=1` 不计通过、命中+就绪 ⇒ 照旧真跑）与 **C10**（覆盖面登记与现取事实自洽）。原先那段「判据已存在但射程有限」的论述（C4 只管声明了 `fail_closed: true` 的条目）**仍然成立**，只是射程现已覆盖快循环档：`tests/unit_ci_workflows/local_gate_matrix.json::_invariants` 第 3 条（判据 = `test_local_gate_matrix.py` 的 C4）机械要求「`fail_closed: true` 的条目必须走 `report_strict`」—— **现取只有 1 条这样声明**（`frontend/bmini-app`） | **「未就绪」被当通过**：`report_env()` 在依赖没装好时打 `⏭️ 未就绪`（跳过），而在**合并门禁**上「没跑」会被读成「这项没事」。**本单现取（2026-09-27，`./verify-all.sh quick` 实跑）**：`ai-agent` / `admin-web vitest` / `admin-web tsc` **打 ⏭️**（原因**全是缺依赖**：`.venv` / `node_modules/.bin/{vitest,tsc}`），`admin-api` 与 `worker-h5` **真跑**。🔴 **两个口径必须分开**：本机「没装依赖 ⇒ ⏭️」是**环境**、**不是门禁缺陷**（CI 上这些腿都真跑）；门禁缺陷只是「变更集命中该模块 + 依赖缺 ⇒ 本地绿」这一形态 —— 而 `gate`（合并门禁）档主路径**一条 `report_env` 模块腿都没有**（唯一模块腿走 `report_strict`）。**落码口径（本包已实现；与上面预案有一处**不同**）**：触发面只决定「依赖**缺**时记 ❌ 还是 ⏭️」——**未命中仍走 `report_env`（依赖齐备时照旧每次都跑）**，故 kind 取 `diff-face-gated-deps` 而非预案里的 `diff-face-hit`（后者「未命中就不跑」会让快循环档的选择集变成**失败开放**，issue #3680 的形态）；谓词含**跨目录输入**（admin-web 的测试直接读后端源码 = 现取 8 条；worker-h5 腿含 `frontend/shared/**`），由 C5 现取钉住。原预案：把「变更集**命中**某模块 ⇒ 该腿用 `report_strict`」逐条落成 `local_gate_matrix.json` 的 `trigger{kind: diff-face-hit, hit_fn, predicate_fn, fail_closed: true}`（bmini 已是这个范式，基础设施与判据 C4 都在）—— 代价 = 每个模块写一个 face 谓词 + 一处 `if/else` 分支；**不建议**给整档无条件套 `report_strict`（本机只启 3 组件，会让快循环档在缺依赖时整片变红） |
| **FM-E11** | ✅ **已有守护** | 内容指纹账本（已登记文件被改 ⇒ `exit 1` **拒绝重生成**）+ `.github/danger_scan.py` 的 `/danger-ack rewrite-migration`（**只有仓库 owner** 的评论算数）；判据 `test_migration_immutability.py::test_registered_migrations_are_byte_identical` | **迁移文件不可改**：改已应用迁移会被按文件名**整份 skip**（CI 绿、功能静默缺失）。⚠️ 连带后果：住在已发布迁移里**注释**中的失效判据**改不了** ⇒ 处置必须是**结构性**的（见 `docs/design/rbac-single-source.md` §1.4 实例 6 与跟踪单 #5699），不是"改注释" |
| **FM-E12** | ✅ **已有守护** | 建库终态脚本判据（表/列真值）+ 跨源逐键守卫；判据 `test_schema_integrity.py::test_schema_has_expected_tables` | **新建库路径不跑迁移链**：`backend/admin-api/src/main/resources/db/init/schema.sql` 与迁移链是**同一事实的两条路** —— 只改一路会让两种建库方式分叉（两条路的登记见 `docs/wiki/Database.md` 的「建库脚本（唯一）」） |
| **FM-E13** | ⚠️ **已登记，未接 CI** | `scripts/sync-main.sh` 的**前置拒绝**（本分支与 `origin/main` 都改过受管用例面 ⇒ **拒绝 merge** 并给出 `--rebase`；本单实测命中一次，改用 `--rebase`）+ 「生成物新鲜度校验」 | 工装级反复出错点：**裸 `git merge/rebase origin/main`** vs `./scripts/sync-main.sh`；**生成物不许手改**（要重渲染）；`dev-worktree.sh add` 与「裸 `git worktree add`」**两条路径并存**（集成侧一手读数：本会话每个包都被要求用裸命令 ⇒ 那条路径**被规避**，`add` 路径上的挂死**既未复现也未证伪** —— 按**事实**登记，不写成「某路径挂死」这一**断言**）；**仓库路径含空格** ⇒ 🔴 **先直连**（**逐工具取证**：`write` / `read` / `edit` / `grep` / `glob` 在含空格路径下**全部正常**，见台账 `NS-2` 的证伪读数）；**只有实测失败**（附命令 + 原始报错）才绕 —— 真正会失败的是**未加引号的 shell 路径**与**未用 `-z` 解析 git 输出**，那是**写法**、**不是**工具的确定行为。⛔ **不许再把「建软链」写成无条件步骤**（无根据的规矩：每单白做一步，且**会掩盖真实问题** —— 真出问题时会以为是「没建软链」），口径见台账 `NS-2` 的收窄与 `PD-6`。**后两条无判据**（台账 `not_solidified` 的 `NS-2` / `NS-3`） |
| **FM-E14** | ✅ **已修（#5707 销账，`guarded`）** | **判据 13** = `tests/unit_ci_workflows/test_dev_mode_failure_modes.py::test_node_test_targets_are_globs_in_the_registered_carriers` —— 射程 = **两处具名载体**（`verify-all.sh` + `.github/workflows/worker-h5-tests.yml`，见判据常量 `NODE_TEST_GLOB_CARRIERS_FROZEN`）；目标参数不含 glob 且不在**只许缩短**的载体台账（`NODE_TEST_TARGET_ALLOWLIST_FROZEN`，现取 1 条 = 就绪探针的 `/dev/null`）里 ⇒ **红** | **`node --test <目录>` 会被读成 1 条失败的假红**（必须用 glob：`node --test <目录>/*.test.mjs`）。2026-09-27 实测。🔴 **本单复核后订正原文的「未写进任何地方」**：`docs/wiki/Development.md` 的「工装坑」节**已经写了这个坑**（散文）—— 缺口在「**无判据**」而不在「无文字」；散文拦不住任何人对腿的参数字面量做改写。判据含两条收紧以免**被自己的说明文字喂红**（`FM-A11` 形态）：① 剥 `#` 注释（**prose 豁免**）；② 目标参数须**像路径**（含 `/` 或 `.`），故 job 名里的 `(node --test)` 不被读成调用。**登记边界（假绿方向）**：`node --test <裸目录名>`（既无 `/` 也无 `.`）**不判** |
| **FM-E15** | ⚠️ **已登记（本单补判据 + 边界）** | 本单补的两条唯一性判据（用例号 / 活的迁移目录版本号）+ 顺延口径；边界声明 = `tests/unit_ci_workflows/test_dev_mode_failure_modes.py::CASE_ID_ALLOCATION_BOUNDARY`（**删掉即红**） | **编号分配只看已合并状态**：取号时现取「main 上最大号 + 1」，**看不到在飞分支** ⇒ 两个并行包取到同一个号；先合的无事，**后合的**把重号带进 main。本会话用例号已撞 **7~8 次**（UI-061 / UI-064 / MC-022 / MC-023 / BM-019 / MC-025 / MC-026），迁移号 1 次（V132 两包同抢）。🔴 **本单自己中招**：写侧取 `MC-026`（当时现取最大 = `MC-025`），#5705 合并时已占 `MC-026`/`MC-027` ⇒ 顺延 `MC-028`。**为什么不加强判据**：在飞分支在 CI 的 `actions/checkout` 下**不可见** ⇒ 同一份代码会给出不同读数（判定不确定）；走 API 则引入网络依赖 ⇒ 与「判定方式必须确定」冲突。**显形条件**：main 上已合并占号 且 某个在飞分支同号 |
| **FM-E16** | ✅ **已有守护（本单初版写错、被它当场抓住）；但「守护存在」≠「覆盖实际形态」** | `scripts/pr_body_guard.py`（issue #4232）：**工具** = `python3 scripts/pr_body_guard.py new --issue <N>`（**会话/工作区作用域唯一**、`O_CREAT|O_EXCL` 原子创建）+ 提交前 `check` + 写完 `verify`；**静态面 R1/R2** = 仓内被跟踪文本里出现「共享临时根 + `pr-body` 族文件名」的形态 ⇒ 判红，由 `tests/unit_ci_workflows/test_pr_body_guard.py::test_scan_real_repo_has_no_shared_fixed_pr_body_carrier` 在 required 的 `ci workflow helper unit tests` 里代跑 | **共享临时路径**：并发包复用共享临时根下的**约定俗成的固定文件名**承载 PR body / 评论 / payload ⇒ 互相覆盖；🔴 **失败是静默的**（后写覆盖先写、**双方都不知道**）。**两例实证，第 2 例已有实际损害**：① issue #4232 的原始实测（A 的 body 被写成 B 的；若此时被 auto-merge 合了会**误关 4 个别人的 issue**）；② **已实质性发生（PR #5704 的包报告）**：其 PR body 载体被**另一并发会话覆盖** ⇒ `gh pr edit` 把**别人的正文贴到了 #5704 上约 90 秒**（损害 = 另一个包的交付说明被公开发布在别人的 PR 上；发现 = 当场改回；最终核验 = 83 行 / 关闭关键词 0）。⚠️ **两侧都在犯**（集成侧也长期用固定临时路径）⇒ 不是某个包的疏忽，是这个工作模式自带的坑。🔴 **残余已从「边界」升级为「主路径」**：静态面射程是**仓内文本**，**管不到手敲的命令行** —— 而手敲命令正是原始形态。**判别动作（降低概率，非机械守护）**：PR body 临时文件一律用**会话唯一路径**（含单号 / 分支 / pid），优先 `pr_body_guard.py new`。**同族**：§17.2 写面冲突 / §17.3 ④ 共享写面 / §2.3 零共享写路径 / §23.6 工装纪律 / 清单 B 的 `FM-B4`；**本次推广 = 「共享写面出事的形态，往往不是你以为的那个入口」**（你防文档里的固定名，出事在命令行里的固定名） |

| **FM-E17** | ✅ **已收口（#5707 按用户 2026-09-27 逐字裁定 = 方案 A「给 `worker-h5-publish` / `bmini-h5-publish` 补一个兜底触发面（周期重建重发布）……静态形状判据才变成真绊线，可一并落判据收口」）** | **兜底面** = 两条腿**各自**的 `on.schedule`（每日档：`.github/workflows/worker-h5-publish.yml` 的 `23 18 * * *` · `.github/workflows/bmini-h5-publish.yml` 的 `43 18 * * *`）+ **判据** = `tests/unit_ci_workflows/test_publish_leg_fallback_surface.py::test_real_workflows_and_ledger_are_clean`（判据 1~8：未登记即红 / 删光即红 / 只许缩短 / 兜底面必须在位 / 声明 ⇄ 现取双向 / `workflow_run` 上游名可解析；判别力与对照读数见 `::test_discriminating_power_in_memory`）+ **登记表** = `tests/unit_ci_workflows/publish_leg_fallback_ledger.json` | **把 `push` 面当唯一自动触发面的**发布腿写的是**线上静态根**，而本仓的 `push` **是被吞的**（auto-merge 用 `GITHUB_TOKEN` 合并 ⇒ push run 不再触发 workflow）⇒ 合并后**静默停在旧产物、无红无告警**。**现取（2026-09-27）**：`gh run list --branch main --event push --limit 200` 覆盖 2026-09-25T09:41Z~2026-09-27T07:23Z、去重 43 个 sha，而同一窗口 `git log origin/main -40` 的 40 个 commit 里**只有 1 个**（`08dd30e7`）在其中 ⇒ **39/40 零 push run**；**两次现场咬过**（`/b/` 与 `/w/` 停在接线前的旧构建，都由人工 `workflow_dispatch` 补）。🔴 **原文的「重启条件」已达成 ⇒ 落判据**：原文写「发布/守护腿接上 `mechanism-liveness` 存活读数（**或补 `schedule`**）之后，静态形状判据才成为真绊线 ⇒ 届时再落」—— 本单走的正是括号里那一条，原文担心的 (b)（「登记的兜底面只会是 `deploy-reconcile` 的 `*/20`，而那**正是失效的那一环** ⇒ 给不存在的保护盖章」）因此**不再成立**（现在核的是这条腿**自己**的 `on:` 且**声明 ⇄ 现取双向**）。**三种兜底方案的现取对比**：③「让 `deploy-reconcile` 那条 `*/20` 真的派发这两条腿」—— **现取：它本来就会派**（`reconcile_one worker-h5 worker-h5-publish.yml frontend/worker-h5` 与 `reconcile_one bmini-h5-hosting bmini-h5-publish.yml frontend/bmini-app`），**无需改动**，但它是**共命**兜底（reconcile 挂了 / 它的 cron 被节流 ⇒ 两条腿同时失去兜底）；②「`workflow_run`（reconcile 完成时）」—— **现取否决**：reconcile 的完成次数约 **40~60 次/日**（绝大多数是 `pull_request:[opened,reopened]`），而 `workflow_run` **没有 paths 过滤** ⇒ 两条腿会被无条件重建重发布 40~60 次/日（bmini 那条要跑 Taro 构建 + 推 ACR 传输镜像）；①「各自加 `schedule`」= **选定**。🔴 **为什么取每日档（cron 节流现取实测）**：`*/20 * * * *`（名义 72 次/日）在 158.3h 里实得 **40 次 = 6.3 次/日 = 名义的 8.4%**（相邻间隔 最小 128 / 中位 244 / 最大 357 分钟，39/39 个间隔 > 60 分钟）；而两条**每日** cron（`mechanism-liveness.yml` 的 `37 20 * * *` / `post-merge-verify.yml` 的 `17 19 * * *`）的中位间隔分别为 **1446 / 1437 分钟（≈24.0h）** ⇒ **每日档未被节流**。**幂等与内容正确性**：`actions/checkout` 无 `ref` ⇒ `schedule` 取**默认分支 HEAD**（= main HEAD，线上应有的状态，不是陈旧内容）；远端发布脚本先建 stage 再整份覆盖、**不对静态根做清空** ⇒ 重复发布同一份产物只是同样的字节再覆盖一次。**失败可见**：两条腿发布后都有**身份断言**（`deploy/scripts/worker-h5-verify-served.sh` / `deploy/scripts/bmini-h5-verify-served.sh`）⇒ 发布错了会判红（不是静默）。🔴 **覆盖面（照实登记，**不是**「已全覆盖」；逐条写在登记表 `coverage_boundary`，由 `::test_coverage_boundary_is_registered` 正向核 face + reason + recompute）**：① **cron 被节流** —— 判据只证明「`schedule` 这个面在」，判不了它跑没跑（8.4% 就是这一面）；② **cron 到点被 `concurrency` 顶掉**（两条腿 `cancel-in-progress: false` ⇒ 至多 1 running + 1 pending）；③ **「腿跑了但发布内容不对」**（由运行期身份断言承接，判据不覆盖）；④ **`workflow_run` 的上游自己没跑**（判据只核上游名可解析，防**静默脱钩**）；⑤ **`push` 被 `GITHUB_TOKEN` 吞掉这一运行期事实本身**（刻意不进判据）；⑥ **「兜底面在位」≠「线上字节 == main HEAD」**（需线上复探）；⑦ **已登记腿之外的新族**（一条腿若同时有 `push` 与 `pull_request`，不在判决射程内 —— 这正是「不用宽泛正则一把梭」的代价，登记表**只许缩短**地人工维护）；⑧ **`deploy-reconcile` 那层是否真派发**（现取**会**，但本判据**不重复判它**：那两行的调用点与 pathspec 已由 `tests/unit_ci_workflows/test_config_change_triggers_deploy.py`（MC-023）冻结，另造第二套台账 = 双真相源）。**判定方式是确定的**：判据只读仓内文件（`.github/workflows/*.yml` + 同目录登记表 JSON），**零 `gh` / 零网络 / 零时钟**。**在真语料上双向自证**：判据跑在**未补兜底面**的语料上**判红两条腿**；补上 `schedule` 后 6 passed ⇒ 它是**真绊线**。**附带收益（本包现取发现）**：补了 `schedule` 之后这两条腿**自动进入** `scripts/drift_audit.py::check_heartbeat()` 的判定面（它遍历所有「头部有 `- cron:` 的 workflow」⇒ 现取调度面由 **14** 条变 **16** 条）；阈值 = 有效周期 + 2 天 = 1440 + 2880 分钟 = **3 天** ⇒ 停摆 >3 天产出 `<wf>|stale` finding。🔴 **但它不构成阻断**：`Drift Audit (真相源契约)` **不在 required 集合**里 ⇒ 判红照旧合并 ⇒ 这是**多了一层与 push 无关的停摆绊线**（真收益），**不是**「失败可见」的完整答案（3 天延迟 + 非阻断）；已作为第 8 条覆盖面登记。**同批**：台账 `FM-E17` 的 `state` 由 `gap` → `guarded`（`PD-8` 公开降 `GAPS_FROZEN` 2 → 1）· `GAPS_FROZEN` **2 → 1** · 用例 MC-039。⚠️ **本单未动的**：两条腿的**发布脚本**与产物路径（只动触发面）· `deploy-reconcile.yml`（属另一条在飞线的登记面）· `FM-E10`（**仍留 `gap`**，不许顺手销账）· 那 2 条腿的**路径**缺口（照旧在 `reconcile_trigger_paths_ledger.json`） |｜⚠️ **2026-09-27（issue #4184）现取复核**：新增的 `c-end-h5-publish.yml` 是**第三种形态** —— 它有 `push` 面，但**发布步骤只手动授权时才写盘**（模式判定步 + `if: mode == 'publish'`，`publish` 默认 `false`）⇒ 它**不是**「push 面 = 唯一生效触发面」那两条之一。🔴 **但它照样受本判据约束**：`push` 被吞时它同样**不会跑且无红** ⇒ 本单同批给它补了每日 `schedule`（`53 18 * * *`，只报告不发布）并登记进 `publish_leg_fallback_ledger.json`（`frozen_max`/`LEGS_FROZEN`/`PUBLISH_LEG_FILES_FROZEN` 三处 2 → 3），其 notify 步判的是「线上产物是否落后」（判据本体 = `scripts/h5_freshness_guard.py`，不写第二份口径）。 |
| **FM-E18** | ✅ **本单补判据（原先是「无判据可加」的**时序**漏点）** | 判据 = `tests/unit_ci_workflows/test_main_freshness_guard.py::test_merge_union_shape_is_red_even_with_equal_line_count`（**行数相同** + **分域合计 == 总数** ⇒ 仍必红且具名）+ `::test_line_count_compare_mutant_turns_that_fixture_green`（**判别力自证**：把「逐字节相等」换成「只比行数」的内存变异体 ⇒ 同一夹具**变绿**）+ 夹具构造函数 `::make_summary_stale_in_place`；判定本体仍是**单一实现** `scripts/generated_artifacts_freshness.py`（三态 `0/1/3`，没有「跳过」） | **生成物文件的 git 三方合并产物**：两个**各自自洽**的分支合并后，**块 hunk 取并集**（46 + 1 = 47）、而**两侧同值的汇总 hunk 干净合并、不重算** ⇒ 落地的 casebook 汇总读数比 `.github/cases/**` **少 1**，且 `git merge-tree` **零冲突**、文件**语法合法**、**内部自洽**（分域合计 == 总数）⇒ PR 面与 `Case Contract (truths_ref)` **都不会红**。**现场（2026-09-28，issue #5741）**：提交版 558（杂项域 46）/ 现取 559（47），**行数两侧同为 8112、仅 4 行不同**。**一条命令复现（零网络、幂等）**：`git fetch origin refs/pull/5733/head e3d35c130 && tree=$(git merge-tree --write-tree 2550bc4f4 e3d35c130 \| head -1)` ⇒ 该树与落进 main 的那份 casebook **逐字节相同**（`diff` 0 行），而它的用例源已是 47 条。🔴 **为什么「再加一条判据」不是这道题的答案**：漏点在**时序** —— 「**检查跑的那份快照 ≠ 实际落地的那份合并结果**」。两条真出口（**都会动合并门禁 / 仓库设置 ⇒ 需人裁定**，本包有意不做）：① 分支保护打开 **Require branches to be up to date before merging**（基线前进 ⇒ 强制重跑，代价 = 每次合并多一轮 CI）；② 合并落地后**即时**重渲染校验，把 main 侧那条腿从「报告型 + ≤1 个 cron 周期延迟」改成「即时 + 阻断」。**现状承接面** = `Main Freshness Guard（main 侧生成物新鲜度）`（判红自动开 P1 值班单 —— 本条的现场正是它的产物），**报告型、非阻断** |

| **FM-E19** | ✅ **本单补判据 + 真修** | 判据 = `tests/unit_ci_workflows/test_lifecycle_land_and_reap.py::test_remote_round_trips_are_constant_not_per_branch`（3 个远程分支 ⇒ `push --delete` **1 次**、批量读数 **≤ 2 次**）+ `::test_remote_round_trips_do_not_grow_with_target_count`（**不变性**：1 → 3 不增长）+ `::test_verify_clean_uses_the_batch_reading_not_a_per_branch_probe` + `::test_batch_reading_unavailable_is_marked_undecidable`（红证半边）；实现 = `scripts/issue_lifecycle.py::remote_heads` / `::batch_delete_remote_branches`（**四态**真值 `deleted`/`already-absent`/`absent-unverified`/`failed`，**不解析 stderr**；🔴 独立验收抓出两条并在同批修掉：**回退路径曾把幽灵分支谎报成 `deleted`**（现只给 `absent-unverified`）、**一个坏 ref 会让整批 push 被拒**（现对「仍在」的逐个补删，上限 20）） | **逐分支网络往返**：`reap-merged --apply` 原先每个目标各一次「删远程 + 探远程」= **2 × 目标数**次往返；单次实测 **3.70s**（本机 SSH）⇒ `dev-worktree.sh add`（把 reap 接在 add 上）整条命令 **~7 分钟**，用户侧表现 = **「挂死」**（`NS-3` 卡在「既未复现也未证伪」）。**前后对照（同一现场）**：修前 dry-run **55 个「可收尾」**、apply ≈ **6.8 分钟**；修后 apply **17.7s**、再跑 dry-run **可收尾 0**。🔴 **顺带销账的另一半**：**陈旧 remote-tracking ref**（现取 55 个：本地 `refs/remotes/origin/*` 有、远程没有）原先**常驻删除面**、每轮被尝试删除并「自证通过」⇒ 现在**不进候选**并具名给出真出口 `git fetch --prune origin`（候选 72 → 17）。**覆盖面**：判据只判**调用形状**（往返次数与目标数无关）⇒ 判不了「网络真的通」「远端权限够」；**显式退回**逐分支探测（慢；且**语义不变只对主路径成立** —— 回退路径判不了「是不是我删的」，只会给 `absent-unverified`，不会给 `deleted`） |
| **FM-E20** | ✅ **本单修 + 补判据（结构面）** | 判据 = `tests/unit_ci_workflows/test_lifecycle_land_and_reap.py::test_preset_refresh_fetches_the_baseline_before_self_check`（`preset_refresh_order_problems` 纯函数：`git -C "${BASELINE}" fetch` 必须在**自检调用之前**；红证 = 删掉 / 挪后各能单独变红）；修法 = `scripts/preset-anchor-refresh.sh` ⑤ 之前先 fetch（失败只降级打印，不静默） | **拿未 fetch 的旧 ref 当判定基线** ⇒ 「刚合并」被读成「落后」：2026-09-28 `land` 的 ⑦ `preset-refresh` 判红（逐字「❌ 活锚内容与 origin/main 不一致：1 个文件内容不同」，而该文件正是刚合并的 `SKILL.md`），**只差一次 fetch**；基线仓 fetch 后同一条命令立刻转绿。与 `FM-E18` 同族：**判据没错，错在它读的那份东西已过期**。🔴 **覆盖面**：文本顺序判定 ⇒ **证明不了**运行期真 fetch 成功，也不覆盖其它「对旧快照判定」的形态 |

| **FM-E21** | ✅ **本单修 + 补判据（含预算值域）** | 判据 = `tests/unit_ci_workflows/test_post_merge_verify_leg.py::summary_budget_problems`（三处预算齐备 + `tail -c`/`grep`/`head -n` 形态齐备 + 承接单不得读完整输出）+ `::test_real_workflow_has_the_three_budgets`（真 YAML）+ `::test_each_budget_mutation_turns_it_red`（**6 条注入式红证**：摘要不截断 / 摘要超 1024k / 承接单超 65536 / 清单不打 stdout / 清单无上限 / 承接单读完整输出）+ `::test_comment_only_change_does_not_turn_red`（对照）；实现 = `.github/workflows/post-merge-verify.yml` 的 `FAILED_MAX=40` / `SUMMARY_EXCERPT_BYTES=200000` / `ISSUE_EXCERPT_BYTES=30000` | **判红输出把自己的出口压垮**：判定步把**完整 pytest 输出**（现取 **17613k**）灌进 step summary ⇒ 超过 GitHub 的 **1024k** 上限 ⇒ **整份摘要上传被拒**（逐字 `$GITHUB_STEP_SUMMARY upload aborted … got 17613k`）⇒ 那次 **9 条失败明细在人默认读的两个面（step summary / job summary）都没有**（原始 job 日志里其实有，要人知道去 `grep FAILED`；**订正**：「哪都看不到」是过头写法，失效的是**默认阅读面**）；同一份输出还被**承接面**（P1 值班 issue）整段贴进 body，而 issue body 上限 **65536 字符** ⇒ 超了**开不出单**（判红无人接盘）。🔴 **预算值是判据的一部分**：把摘要预算改成 `2000000` 就红（那正是实测形态）—— 不是只看「有没有常量」。**覆盖面**：结构 + 值域判定 ⇒ 判不了「摘录够不够长到看得见根因」（人读的问题），也判不了 GitHub 未来改上限 |

| **FM-E22** | ✅ **本单补判据（PR 面可拦；**不改门禁配置**）** | 判据 = `tests/unit_ci_workflows/test_main_freshness_guard.py::probe_wiring_problems`（纯函数：探测在跑 + 路径门控在 + `fetch-depth: 0` + 门控覆盖四条路径 + 先取 main）+ `::TestMergeProbe`（**真 git 夹具**：两侧各自新鲜、合并结果陈旧 ⇒ `drifted`；自比 ⇒ `fresh`；基线取不到 ⇒ `undecidable`；CLI 退出码 1/0）+ **6 条接线变异红证**（含 `drop_rc_judge`） + 对照读数；实现 = `scripts/generated_artifacts_freshness.py::probe_merge`（`--merge-probe <ref>`，**同一份实现**）+ `.github/workflows/pr-check.yml` 的探测步 | **合并结果这一面原先无判据**（`FM-E18` 的时序根因）：两个**各自新鲜**的分支合并后，块 hunk 取并集、而两侧**同值的汇总 hunk 干净合并不重算** ⇒ **落地那份比源陈旧**（现场：**8112 行 / 8112 行、仅 4 行不同**，`git merge-tree` **零冲突**）。**探测只读**：`git merge-tree --write-tree` 取合并树 → `git archive` + `tarfile` 解到临时目录 → 跑同一个 `evaluate()`（不落工作区、不写仓内对象）。三态 `0` 仍新鲜 / `1` **会**陈旧 / `3` 无法判定（取不到基线 **或**与基线冲突 —— GitHub 侧本来也拦合并）。**归因两面都给读数**（本树 / 合并结果）。🔴 **路径门控（`.github/cases` / 渲染器 / 两个生成物）是有意的**：不碰受管用例面的 PR **不替 main 侧的漂移背锅**（`FM-E4`）。**门控面本身也要登记**：`tests/unit_ci_workflows/declaration_gate_registry.json` 的 `gates` 新增 `case-truth-check-merge-probe`（逐字路径谓词 + `must_cover` 四条 + `uncovered` 两条）—— **未登记即红**。**与 `FM-E18` 的关系**：`FM-E18` 的两条真出口（分支保护 `Require branches to be up to date` / 落地后即时阻断）**仍未被采用**（要动门禁配置），本条是不动配置的第三条出口。⚠️ **夹具环境读数（本单实测一次）**：真 git 夹具的提交必须**注入身份**（`GIT_AUTHOR_*` / `GIT_COMMITTER_*`）—— runner 上没有 `user.name/email` ⇒ `git commit` 报 `Author identity unknown` ⇒ **本机全绿、CI 整片红**（同族 `FM-A14`）。**覆盖面**：探测判不了「本该重渲染但两侧都没动」（无差分）与「GitHub 的合并不是 git 三方合并」的极端差异 |

| **FM-E23** | ✅ **本单补判据（存量只取窄口径）** | 判据 = `tests/unit_ci_workflows/test_dev_mode_failure_modes.py::pipe_rc_problems`（纯函数，跑**真 workflow**：`if/elif/while` 里的「被判定命令 \| grep/head…」若该 `run` 块无 `-o pipefail` ⇒ 必须登记进 `PIPE_RC_EXEMPTIONS`，**未登记即红 / 豁免陈旧即红**）+ `::TestPipeRcGuard` 四条（基线 / 注入红证 / `pipefail` 对照 / 注释对照 / 陈旧豁免只许缩短） | **控制流里的管道吞掉「命令自身 rc」**（同一天两处）：① `pr-check` 门控步 `if git diff … \| grep -qE` ⇒ `git diff` 真失败时管道 rc 取 `grep` 的 0 ⇒ 写成「未命中」并静默跳过（**归因写错**，已修为判 rc + fail-closed）；② 侦察命令 `gh pr checks --watch \| grep \| tail` 把判红吞成退出 0 ⇒ 「两条 dependabot 都红」一度被读成「有一条绿」（当场更正）。**现取基线 = 2 条刻意形态**（`flaky-ledger-reconcile::reconcile` 问 help 里有没有 `--branch`；`pr-check::label-needs-changes` 问标签在不在）—— 两条都写明「加 pipefail 会把结论读反」。**射程**：只判 `if/elif/while` 里的管道；宽口径另有 30 块「有管道无 pipefail」**有意不进射程**（重启条件 = 出现第二例由该形态造成的真缺陷） |

| **FM-E24** | ✅ **已有守护（PR #5931 落码；本单只登记，不重复实现）** | 判据 = `tests/unit_ci_workflows/test_deploy_watchdog.py::test_run_body_stays_under_the_github_limit`（**逐 workflow 逐 step 现取** `run` 正文长度，上限 `RUN_BODY_LIMIT = 13250` = 低于已知有效读数 13,303 留 53 字符差）+ 反空跑锚点（现取 >30 条）+ 对照读数（最长 >4000，防判据扫错对象）。**复算** = `python3 -m pytest tests/unit_ci_workflows/test_deploy_watchdog.py -q -k run_body` | **单个 step 的 `run` 正文超长 ⇒ GitHub 把*整份* workflow 文件判 invalid ⇒ 该腿静默永不跑**（GitHub 侧**未文档化**约束）：`push` 面每次只留一条 **0 个 job** 的 `push/failure` run（`name` 回落成文件路径、页面提示 "workflow file issue"），而 `pull_request` 面**根本不建 run**；**本地 PyYAML 解析 + 仓库全部守卫全绿**（完全静默）。实测阈值（11 个变体二分；与文件总大小、行数**无关**）：**≤13,303 字符有效 / ≥13,399 invalid**。**存量风险现取（2026-10-02，`origin/main` 3fa84ab89）**：全仓 **238** 条 `run` 正文，最长 = `.github/workflows/deploy-reconcile.yml` 的 step `Reconcile deploys` **13,125**（距上限仅 **125 字符**）、次长 = `.github/workflows/automerge.yml` 的 `Classify bot PR … and arm on` **10,975**。🔴 **订正一处转述**：那条正文的 **12,524** 是 PR #5931 **合并前**的读数（#5931 自己把它抬到 13,125）⇒ 余量不是 ~2.3K 而是 **125 字符**。**出口**：真要往那条正文里加东西 ⇒ **先把实现体外置**（`.github/scripts/*.sh` 再 `source`），**不要**靠「再加一点点应该没事」。出处 = issue #5929 / PR #5931（值守面首版正文 **13,820** 越线 ⇒ 该腿不跑；修正后 13,125）。⚠️ **覆盖面**：判据只在**本仓**的 workflow 上成立 —— 别的仓库（含本仓新增 workflow 之外的项目）没有这条判据 |

| **FM-E25** | ✅ **本单补判据（加载面文本锚；机制本身无判据可加）** | 判据 = `tests/unit_ci_workflows/test_dev_mode_failure_modes.py::conflict_diagnosis_problems`（**射程 = `migao-dev-flow` §2.2 那一节的加载面**：逐字要求 `gh pr view` / `--json mergeable` / `CONFLICTING` / `FM-E25` 四个锚）+ `::TestConflictDiagnosisAnchor` 四条（基线 / **删掉那一行 ⇒ 红** / 整节标题被改 ⇒ 红 / 只加一条注释 ⇒ 不红）。**判别动作** = `gh pr view <N> --json mergeable` | **「CI 迟迟不来」被读成「在排队」**：PR 与 main `mergeable=CONFLICTING` 时 GitHub **建不出 merge ref** ⇒ **`pull_request` 类工作流根本不触发**，PR 页面上只剩 `pull_request_target` 的辅助腿（**本仓现取 = 带 `pull_request_target` 的 4 条腿**：`Auto Merge` / `Close Linked Issues on Merge` / `Stale 清理` / `verify-trigger` —— 它们**不需要 merge ref** 所以照跑；复算 = `grep -l pull_request_target .github/workflows/*.yml`）⇒ 看着像在排队，**实际一个 required job 都不会来**（无红、无 pending、没有任何东西会报）。**实测出处 = 2026-10-01 PR #5922**：开成 draft 后 **3 次 push 都没有 `PR Check` run**；`gh pr view 5922 --json mergeable` 显示 `CONFLICTING`/`DIRTY`；用 `./scripts/sync-main.sh --rebase` 解冲突后 push ⇒ `PR Check` / `AI Agent Service Unit Tests` / `Mini-App CI` / `Bmini-App CI` **立即全部排队**。**顺带登记**：draft 起手 + native auto-merge 的组合下，**`ready` 不是 `pull_request` 工作流的触发面**（`ready_for_review` 只在 `.github/workflows/automerge.yml` 的 `types` 里）⇒ 解冲突后必须 **push**（`synchronize`）才会触发。🔴 **本次复核边界（照实登记）**：#5922 现已 MERGED ⇒ `mergeable` 现读 **`UNKNOWN`**（GitHub 只对 open PR 计算）⇒ **那条读数不能事后复算**，可复算的是**机制**（哪个 workflow 带 `pull_request` / 哪个带 `pull_request_target`）与**口诀**本身。⚠️ **覆盖面（判据 24）**：文本锚**只**证明「这条判别动作还在 **agent 每次都看得到的那一面**」，**不证明** GitHub 侧的 merge-ref 行为（那不是仓内内容 ⇒ 无机械判据可加；同 `FM-E15` 的 `CASE_ID_ALLOCATION_BOUNDARY` 形态） |

**计数器（现取）**：`state=gap` 的条目共 **1** 条（`FM-E10`）—— 这个数**只许缩短**，
上限冻结在判据 `tests/unit_ci_workflows/test_dev_mode_failure_modes.py` 的 `GAPS_FROZEN` 里，**台账改不动它**。
（沿革：#5706 建账 = 3 → #5709 新增 `FM-E17` 抬到 4（台账 `PD-1`）→ #5707 两笔销账降到 2（台账 `PD-2`：
`FM-E4` / `FM-E14` 转 `guarded`）→ **#5707 本包再销一笔降到 1**（台账 `PD-8`：`FM-E17` → `guarded`，
两条发布腿各自补 `schedule` 兜底面 + 落静态形状判据）。🔴 **口径订正**：判据语义是 **`现取 ≤ 上限`**（只许缩短）⇒
「把上限抬到高于现取条数」**本身不会红**；「上限 == 现取」靠**销账时同批降上限**这个动作，不是靠判据。）

## 口径：几条绿色腿**不是**它名字读起来的意思（2026-10-03 固化，CI 审计 issue #6144 的 P2）

> **为什么单开一节**：下面每条的**绿**都与「这条链真的跑通了」长得一模一样，而**没有任何东西
> 会因此变红** —— 同族见上节 `FM-A*`：**判据没错，错在它证明的东西被读大了**。
> 本节是这几条腿的**口径单一来源**，各 workflow 的**注释指回这里**（不在 workflow 里复制第二份口径）。
> 读法：每一行给的是「**该看什么才算数**」，不是「这条腿坏了」。

| 链路 / 位置 | 绿 ≠ 什么 | 需要判断时要看什么（可复制） |
|---|---|---|
| `.github/workflows/automerge.yml` 的 job `Enable auto-merge (bot, safe classes only)` | **绿 ≠ 已 arm** | `gh pr view <PR> --json autoMergeRequest`（非空 = 真 arm 了） |
| `.github/workflows/verify-trigger.yml` 的「API 预算闸」 | **绿 ≠ 本轮跑过**（**有意 fail-open**） | 该 step 日志的「`GITHUB_TOKEN` 剩余额度：N / 小时」+ 有没有 `⏭️` 那行；或 run 页面 **Summary** 的汇总行在不在 |

### ① `Auto Merge (bot, safe classes only)` 绿 **不等于**「已 arm」

这条腿只对 **bot 作者 + 安全类别**的 PR 走这条路径。它在**三种**情况下都会**判绿**：

1. **真 arm 了** —— job 里 `gh pr merge --auto --squash --delete-branch` 返回 0；
2. **判「不安全」而 fail-closed** —— 类别 / checks 判定不过时，job 写一条 `note({...})` 注解，
   打印「未 arm（fail-closed）—— 该 PR 保持人工处置」，然后**正常返回** ⇒ **该 check 是绿的**；
3. **arm 命令本身失败** —— `MERGE_CMD_FAILED` 同样只写 `note(...)` 后返回 ⇒ 绿。

⇒ **要判断某个 PR 到底 arm 没 arm，不许看这条腿的颜色**，看：

```bash
gh pr view <PR> --json autoMergeRequest --jq '.autoMergeRequest'   # 非空对象 = 已 arm；null = 没 arm
```

**唯一兜底 = `detect-dangling-prs`**（同文件）：它扫「**open、长时间没变红、也没合入**」的 PR，
判红并打 `::error::` ⇒ 走定时腿开 P1 值班 issue。⇒ **绿到兜底响之间有 ≥60 分钟的窗口**
（入口是 `schedule`，现取 `7 * * * *` = **小时级**；且 GitHub 对本仓 cron 有节流，实测 2~5.5h 并不罕见）。
它**只报警、不补 arm**。

### ② `verify-trigger` 的 API 预算闸 **有意 fail-open**

`.github/workflows/verify-trigger.yml` 的「API 预算闸」步：`gh api rate_limit` 取不到核心额度时按 `9999`
兜底；剩余 `< 150` ⇒ 写 `skip_run=true` ⇒ **后续所有步都被 `if: env.skip_run != 'true'` 跳过 ⇒ job 绿**。

- **这是有意的**（该步日志自带「fail-open：不半途而废，下次 run 继续」），**不是缺陷**。
  理由：绝不在限额边缘跑长循环，避免「跑到一半被限流 ⇒ 后半段静默失败」。同一形态在本链路里有两处：
  ① 预算闸（run 开头，`< 150` 整轮不跑）；② 逐 PR 循环内每 10 个候选复核一次，`< 150` ⇒ `break`。
- **代价（照实登记）**：**高负载时这条链静默不跑**，「合并 → 自动评审触发」延后到下一次 run
  （触发面现取 `pull_request_target: opened/reopened` 对账 + `schedule` + `workflow_dispatch`），
  而**该轮的绿不携带这个信息**。
- **人怎么发现**（读数沿用本仓既有形态：**每轮一行、含零动作**，见 `scripts/mechanism-registry.json`
  的 `reading_grammar` —— 本链路**没有**独立发射器，**它自己的汇总行就是读数**）：

| 形态 | 去哪看 | 逐字特征 |
|---|---|---|
| 预算闸整轮跳过 | 该 run 的 job 日志里「API 预算闸」步 | `⚠️  剩余额度 < 150，本次退出（fail-open：不半途而废，下次 run 继续）` |
| 循环中途停 | 「处理候选 PR」步日志 + 该 run 的 **Summary** | `⚠️  额度剩 N < 150，停止本轮（已处理 M 个候选，其余留给下次 run）`；Summary 表头仍在，但 `候选 PR` 与各计数**停在 M** |
| 正常跑完 | 该 run 的 **Summary** | `mode=… posted=N idempotent_skip=N guard_skip=N no_linked_issue=N failed=N` |

🔴 判别口诀：**「没跑」必须长得像「没跑」**。`posted=0` **且汇总行在** = 真零动作；
**汇总行不在** = 没跑到那一步（被闸跳过），**不许**把后者读成「今天没有要触发的」。

### ③ `npm audit` 装饰步（已按审计结论**删除**，2026-10-03）

`pr-check.yml` 的 `admin-web-test` 步列里曾有一步
`npm audit --production --audit-level=high` + `continue-on-error: true` ⇒ 它**既不出声也不拦**：
即使审计失败该步也不让 job 变红，**而 required 腿的绿会被读成「依赖面有人看」**。
2026-10-03 按 CI 审计（issue #6144）的裁定：**删除**（**不**改成 blocking —— 那会让无关 CVE 新闻随机卡住
所有 PR；也**不**另建报告腿 —— 本仓**没有**消费这条信号的面，见下）。

**这个信号以后去哪看**：**本仓目前没有依赖漏洞通道** —— 现取（2026-10-03）
`gh api repos/zhaokai-mgzn/migao/vulnerability-alerts` ⇒ `404 Vulnerability alerts are disabled`
（Dependabot 安全告警未开）；`code-scanning/alerts` ⇒ `no analysis found`。
`.github/dependabot.yml` 只在做**版本更新 PR**，**不是**漏洞告警。
⇒ 想恢复这个信号 = **显式开一个通道**（开 Dependabot 安全告警，或另接 pip-audit / trivy），
**不要**再把一条 `continue-on-error` 的步当成它已有。

（登记面同步：`tests/unit_ci_workflows/declaration_gate_registry.json` 的
`pr-check-admin-web-tests.gated_steps` 同批删掉该步骤名 —— 它按**步骤名**逐字校验，判据 =
`tests/unit_ci_workflows/test_gate_coverage_and_same_source.py`
的 `test_registry_entries_are_live_and_verbatim`；`docs/wiki/gate-exemption-ledger.md` 的
`continue-on-error` 条目同批复核。）

### ④ `mechanism-liveness.yml` 的 `watchdog` 死门控（2026-10-03 删除）

该 workflow 的 `on:` **只有** `schedule` + `workflow_dispatch`（`pull_request` 面已于 #5814 去掉，
且 `tests/unit_ci_workflows/test_ci_trigger_surface_slimming.py` 的 `mechanism_liveness_problems`
**逐字要求它不许长回 PR 面**）⇒ `watchdog.if: github.event_name != 'pull_request'` 是**恒真死条件**，
会让人误以为 PR 上会跑到它。**处置：删掉该 `if:`**，并把上下文注释改成「本 workflow 无 PR 面，
此 `if:` 曾是历史残留」。三张登记面的影响读数见 PR body（`ci_trigger_gate_ledger` **不涉**：
它只裁 `on.workflow_run` 消费面，本文件无该面；`schedule_scope_ledger` **不涉**：它只核
`on.schedule` 声明 ⇄ 现取的 cron；`test_ci_trigger_surface_slimming.py` **不涉**：它只读 `on:` 块）。

## 部署目标（2026-08-14 起：SAE → SWAS；当前 SWAS 为**测试环境**）

| 服务 | 目标 | 技术 |
|------|------|------|
| admin-api | SWAS 单实例（拉 CI 预构建镜像） | Java 21, 容器端口 8080 |
| ai-agent-service | SWAS 单实例（同上） | Python 3.11, 容器端口 8000 |
| admin-web | SWAS 单实例（同上） | Next.js, 容器端口 3001 |
| nginx | SWAS 同机 | 80/443 TLS 终结 + 域名分流 |

数据层不在 SWAS 上：PostgreSQL 用阿里云 RDS、Redis 用 Tair 公网代理（admin-api 已强制 Lettuce RESP2）、OSS/DashVector/DashScope 不变。

**环境定位**：当前 SWAS 即测试环境（自动部署）；未来正式生产走受控发布（见 [production-deployment.md](../deployment/production-deployment.md) 与 `deploy-prod.yml`）。

## 部署链路（测试环境自动部署）

```
push main / push tag v*（路径过滤）→ CI **只跑测试**（C′ 起**不再构建、不再推 ACR**；tag 规则仍是 sha-<7> 或 vX.Y.Z）
  → aliyun swas-open RunCommand（实例 b23c69e5..., 超时 3600s；**C′ 下轮询预算 4500s
     = 远端锁等待上限 1800s + 冷构建**上界** 2400s + 余量 300s**，见下「远端 flock」节）
  → 服务器执行 /opt/migao-deploy/deploy.sh <SERVICE_KEY> <IMAGE_TAG>（先自愈式同步最新 deploy.sh）：
     0. flock（既有那把锁，等待上限 `LOCK_WAIT_SECONDS=1800s`；🔴 **C′ 的 `docker build` 就在锁内**
        —— 否则单机并发构建会互踩，见 [swas-migration-lessons §二.2](../deployment/swas-migration-lessons.md)。
        三条腿共用**同一把锁**而 CI `concurrency` 组按服务分 ⇒ 跨服务会**排队**，一次实测 ~28min）
     1. **C′：就地 `docker build` 该服务镜像**（上界 `BUILD_TIMEOUT_SECS=2400s`，`rc=124` 显式点名判红；
        apt 源可经 `APT_MIRROR` 覆盖、默认 `deb.debian.org` 保持 CI 行为不变；
        admin-web 的 `NEXT_PUBLIC_*` 取服务器 `/opt/migao-deploy/.env.build`（可选）或**内置默认值**）
     2. docker login ACR（服务器仍需凭据 —— 回滚点/依赖镜像仍可能从 ACR 取）
     3. 严格蓝绿（#4785）：逐服务「先起 green 探针（第二端口）→ 健康检查通过 → **才**替换正式容器」
     4. nginx 优雅 reload（失败回落 restart）+ 健康检查 8080/8000/3001
  → CI 轮询 DescribeInvocationResult 至 Success
  → smoke-test.yml post-deploy 冒烟（api.migaozn.com / ai-api.migaozn.com）
```

### 触发面 = 对账面：只改配置也必须能自动生效（关联 #5001）

配置（`deploy/swas/nginx.conf` / `docker-compose*.yml`）与镜像**同源**：`deploy/swas/deploy.sh`
只取「镜像 tag 那个 commit」的配置（`CONFIG_REF_RESOLVED`，由 `config_ref_for_tag` 解析，见
issue #5083），把它们 `cp` 到 `nginx/` 与 compose 根，并无条件
`docker compose up -d --no-deps nginx` + `nginx -s reload`（`nginx` 是 `UP_SERVICES` 的初值，
那段在逐服务循环**之外**）⇒ **配置的应用面只在这条部署腿里**。

⇒ 改 `deploy/swas/**` **必须**触发一条部署腿，否则改动**静默不生效**（实测两次：#5668 的 `/b/`、
#5676 的 `/i/` 都只能靠人工 `workflow_dispatch` 才生效）。现在两处**同批**接线：

| 面 | 位置 | 内容 |
|---|---|---|
| 触发面 | `.github/workflows/deploy-admin-api.yml` 的 `on.push.paths` | `backend/admin-api/**` + `deploy/swas/**` |
| 对账面 | `.github/workflows/deploy-reconcile.yml` 里 admin-api 腿的第 4 个参数 | `deploy/swas`（**附加包含项**，与 `:(exclude)X` 排除项共用一个口子） |

⚠️ 这两处是**同一事实的两处投影**（「某服务的触发路径集合」）：只改一处 ⇒ 触发面与对账面脱钩，
而脱钩本身**不会有任何东西变红**（这正是 #5668 / #5676 两次静默生效的成因）。⇒ 常驻判据
`tests/unit_ci_workflows/test_config_change_triggers_deploy.py`：逐服务**双向**比对两处
（防静默 / 防空转）+ 三份 canonical 配置的覆盖 + 执行式「只改 `deploy/swas/nginx.conf` 的 commit
⇒ 判有漂移 ⇒ dispatch」+ 另外 4 条腿逐值不变。存量缺口（另 4 条腿的发布链路文件等）逐条登记在
`tests/unit_ci_workflows/reconcile_trigger_paths_ledger.json`，**只许缩短**。

**登记（本单未修，如实记录）**：`deploy/swas/deploy.sh` 在 `CONFIG_REF_RESOLVED` 处逐字要求
「配置（compose/nginx）必须与镜像**同一 commit**」⇒ **用旧 tag 重放/回滚一次部署，会把
`nginx.conf` 一起倒回那个旧 commit 的版本** ——「刚修好的配置被一次回滚静默撤销」。
它属发布链路语义（与「不许往回走」闸门同一面），本单**只登记、不修**。

### 镜像 tag 策略（2026-08-30 起）

| 触发 | 镜像 tag | 部署 |
|------|---------|------|
| push main（路径匹配） | `sha-<git 前7位>` + latest | 自动部署测试环境（SWAS） |
| push tag `vX.Y.Z`（release.yml 打标） | `vX.Y.Z` + `sha-<7>` + latest | 自动部署测试环境（回归） |
| workflow_dispatch（手动）空 image_tag | **服务器侧构建**当前代码 `sha-<7>` 并部署 | 手动部署测试环境（`gh workflow run deploy-<svc>.yml --ref main`） |
| workflow_dispatch 填 image_tag | 跳过构建，部署指定版本 | **回滚/指定版本** |

生产发布：`deploy-prod.yml`（Environment 审批 + 指定版本），详见 [production-deployment.md](../deployment/production-deployment.md)。回滚见 [rollback.md](../deployment/rollback.md)。

## 部署故障恢复手册（2026-09-21 云测试环境事故复盘后固化，issue #4767）

### 并发锁的行为（**"main 前进却无新部署"的真因**）

三个部署 job 各有一个 concurrency 组（`deploy-admin-api` / `deploy-frontend` / `deploy-ai-agent-service`，
`cancel-in-progress: false`）。**锁由 run 的终态（success / failure / cancelled）释放** ——
run 卡在 `in_progress` 时会**一直占着它**，后续 main 的部署**全被挡住**。
2026-09-21 实测：两条腿在 `ca724257e` 失败后挂住 `in_progress` 20+ 分钟（`updated` 冻在同一分钟），
之后 push 不再产生任何部署 —— 而**没有任何检查会因此变红**。

### 卡住 / 失败时的恢复步骤

```bash
# ① 找卡住的 run
gh run list --workflow=deploy-admin-api.yml --limit 5
# ② 清掉并发锁（不必等它自己结束）
gh run cancel <run-id>
# ③ 同 SHA 重跑，恢复推进
gh run rerun <run-id> --failed
# ④ 环境已不可用时，手工回滚到上一个可用镜像 tag
gh workflow run deploy-admin-api.yml -f image_tag=<上一个可用 tag>
```

### 自动化的四条兜底（#4767 落地）

| 机制 | 位置 | 行为 |
|---|---|---|
| 部署阶段**硬超时** | `deploy/scripts/swas-deploy-ci.sh`（`SWAS_DEPLOY_TIMEOUT_SECONDS`，默认 900s / 次尝试） | 超时即 `exit 1`（不再无限轮询把 run 钉在 `in_progress`）；每次 aliyun CLI 调用另有 60s 上界（`SWAS_CLI_TIMEOUT_SECONDS`） |
| **job 级**硬超时 | 三个 deploy workflow 的 `build-and-deploy`（`timeout-minutes: 90`） | 脚本整体卡死时由 GitHub 终止 run ⇒ run 进终态 ⇒ **锁一定释放**。90min **大于** C′ 的「发起+轮询」预算 4500s（= 锁等待 1800s + 冷构建**上界** 2400s + 余量 300s）⇒ 不会先被 GitHub 打死成 `cancelled`（那会让断路器不跳闸 ⇒ cron 自放大） |
| 失败**不留坏状态** | `swas-deploy-ci.sh` | 失败**自动重试 1 次** → 仍失败**回滚到 `.last-good-tag`（上一个可用镜像）** → 回滚也不行 ⇒ `::error::` 显式告警 |
| 严格蓝绿（**内层**兜底） | `deploy/swas/deploy.sh`（#4785） | 新容器先起 → 健康检查通过 → **才**切流量；不通过 ⇒ **旧容器一动不动**（**失败窗口 = 0**）⇒ 坏镜像**永远碰不到**旧容器（外层回滚仍保留，见下） |
| 对账**断路器** | `deploy-reconcile.yml` | 同一 `head_sha` 的**最新一条** run 只有结论落在**允许名单**（`success` / `skipped` / `neutral` / 空）才继续补部署；**其余一切结论**（`failure` / `cancelled` / `timed_out` / `startup_failure` / `action_required` / `stale` / 将来新增的）一律跳闸（防反复重试坏 commit、覆盖手工回滚）；同 sha 的 run **还在跑/排队** ⇒ 也跳过（重复 dispatch 是纯 churn）。**fail-open**：查询失败 / 无同 sha 记录 ⇒ 照旧补部署；跳闸时**显式**打印人工出口 `gh workflow run <wf> --ref main` |
| 推送**显式上界 + 一次重试**（#5814） | 三个 deploy workflow 的 `Build and push Docker image` / `Build and push` | 单次构建/推送挂 `timeout`（`PUSH_TIMEOUT_SECS`，默认 720s）⇒ 超时/失败**重试 1 次**（最坏 2×720s = 24min，**明显小于**上面那条 job 级 45min）；两次都不成 ⇒ `::error::` **点名卡在「推送到 ACR」** 后非零退出（不再留下「40 分钟零输出 + 一个 cancelled」这种不可归因的形态）。⚠️ 三条部署腿的 `Skip if already built (schedule reconcile)` 也加了同一道闸门 ⇒ 挂死的 commit **不会被自己的 cron 反复重试**。🔴 **2026-09-30（C′）后本条对三条 deploy 腿已失效** —— 它们**不再有 `Build and push` 步**（构建搬到服务器侧，见本文档「部署链路」节）；该上界**仍适用于** `bmini-h5-publish.yml` 的那处 `docker push`（PR #5821 补的） |

### 严格蓝绿（issue #4785）：新容器先起 → 健康检查通过 → 再切流量

**改动前**的替换语义是 compose 的「**停旧 → 删旧 → 建新 → 起新**」（不是滚动、更不是蓝绿）——
新镜像起不来时**旧容器已经走了**，这就是 2026-09-21 事故把 admin-api 打成 502 的那一步。
现在 `deploy.sh` 对每个待更新服务走四步：

```
① 先起 green 探针（新容器名 + 第二端口 18080/18000/13001，**旧容器完全不动**）
② 用与第 3 步**同一份**判据健康检查 green → 失败 ⇒ 删 green、exit 1，**旧容器一动不动**（失败窗口 = 0）
③ 通过才 `docker compose up -d --no-deps <服务>`（替换正式容器）
④ 正式容器健康后删 green；最后 nginx **优雅 reload**（失败回落 restart）
```

- **为什么用「第二端口」而不是 nginx upstream 切换**：`nginx.conf` 里 `proxy_pass http://admin-api:8080`
  走 compose DNS 名，nginx 在**启动/reload 时**解析并缓存上游 IP；改 `nginx.conf` 写坏 =
  **全站所有域名同时挂**（部署链最贵的一种事故）⇒ 本单不碰它。
  **残留窗口（如实登记，不粉饰）**：**失败路径窗口 = 0**；**成功路径**仍有「替换正式容器 + 启动 + reload」的
  **秒级**窗口 —— 与改动前**同量级、未变差**，且此刻镜像已被证明能起。
- **内存前提**：green 与旧容器**并存** ⇒ 部署前预检 `MemAvailable ≥ 2048MB`（最重服务 mem_limit 1536m + 512m 余量）；
  不足 ⇒ **中止部署**（fail-closed，旧容器不动、环境不受影响）。
- **green 探针 `restart: "no"`**：探针崩了不许自愈复活（`unless-stopped` 会让它在 docker 重启后
  被拉起来、占着第二端口并让下一次部署撞名字/端口）。
- **逐服务串行** ⇒ 内存峰值只多**一个**容器（不是三个）。

#### 改坏了怎么回退（**一条命令**）

```bash
# ① 最快放行口（不改代码、不必等 CI）：跳过蓝绿预验证，回到 #4767 的「失败即回滚」路径
ssh <swas> 'touch /opt/migao-deploy/.blue-green-off'
# ② 彻底回退（本单的代码改动）：revert 合入提交，走正常 PR 重跑部署
git revert <本 PR 的 merge sha>
# ③ 环境已不可用：手工回滚到上一个可用镜像 tag（同上面「卡住 / 失败时的恢复步骤」④）
gh workflow run deploy-admin-api.yml -f image_tag=<上一个可用 tag>
```

⚠️ **放行口只跳过「预验证」，不跳过更新本身** —— 否则 `.blue-green-off` 会静默变成「本次不部署」
（最恶劣的静默失效）。守卫 `test_exec_escape_hatch_skips_blue_green` 钉住这一点；放行后输出里会明写
「本次新镜像**未被预验证**」。

#### 上真机后怎么验证（**可执行判据**）

```bash
# ① 看 green 的「出现 → 消失」顺序（在 job summary 的远端输出里；CI 日志会被截断）
#    期望：up -d --no-deps <svc>-green → <svc>-green OK (200) → up -d --no-deps <svc> → rm -sf <svc>-green
# ② 红证（推一个坏镜像）：让新镜像起不来，观察 admin-api 是否**始终在服务**
curl -s -o /dev/null -w '%{http_code}\n' https://api.migaozn.com/          # 期望：非 502（旧容器仍在服务）
ssh <swas> 'docker ps --format "{{.Names}}\t{{.Status}}" | grep admin-api'  # 期望：旧容器未被替换
```

#### ⚠️ 通用坑：bind mount 的**单文件**必须原地改写（`mv` 会换 inode）

`nginx.conf` 是以 `./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro` 的**单文件** bind mount 进容器的。
单文件挂载绑定的是**创建时的 inode**：在宿主上用 `mv`/`cp` 覆盖会**换 inode** ⇒ 容器里读到的仍是**旧文件**
（**且不报错** —— 静默失效）。要改就用**原地改写**（`sed -i` / `cat > 文件 <<'EOF'`），
改完 `docker compose exec -T nginx nginx -s reload`。
`deploy.sh` 里的 `cp src/deploy/swas/nginx.conf ./nginx/nginx.conf` 是**原地截断+写入** ⇒ 不换 inode ✓。

### 不许往回走（issue #4852）：排队的旧 run 不得把服务回退

**事故形态**（2026-09-20 生产 CI 实测）：三条部署腿共用**同一把** server 侧 `flock`
（`deploy/swas/deploy.sh`，等待窗口 `LOCK_WAIT_SECONDS=1800s`）⇒ run 按**创建时刻**排队，而 `main` 在排队期间前进
⇒ **为旧 commit 创建的 run 会在更新的 run 成功之后才执行**；旧判据是「该 TAG 的镜像在不在本地」
⇒ 旧 tag 的镜像当时都在本地 ⇒ 服务被重建为旧 tag，而 **run 结论 success + 健康检查三个全 200 +
`✅ SWAS 部署成功（tag=旧tag）`** ⇒ **三重绿、零告警**，线上长期跑旧代码。

**闸门判据**（`deploy/swas/deploy.sh` 的「2.05」段，**在 flock 之内**）：

```
逐服务：target tag 是**该服务当前在跑 tag 的祖先**（提交图语义）⇒ 跳过该服务 + `::warning::`
判不出（非 sha tag / 容器没起 / API 取不到 / 分叉）                        ⇒ 放行 + `::warning::`（fail-open）
显式回滚（ALLOW_DOWNGRADE=1）                                             ⇒ 放行 + 日志写「这是显式回滚」
```

- **祖先关系 = 提交图语义**（等价于 `git merge-base --is-ancestor <target> <current>`），
  **不是**字符串比较、**不是**时间戳（tag 是 `sha-<7>`，字典序与提交序无关）。
- **实现走 GitHub compare API**（`api.github.com`，同一张提交图）而不是本地 `git`：**实测**
  服务器上 `git clone --filter=tree:0` 连 `github.com:443` **超时**，而 `api.github.com` 200/0.6s、
  `python3` 在（判据源只有一处：`DOWNGRADE_API`，可被守卫测试桩化）。
- **未认证限 60 次/小时/IP** ⇒ 一次部署内同「在跑 tag」**只查一次**（缓存）。
- **显式回滚仍能往回走**：`gh workflow run deploy-*.yml -f image_tag=<tag>`（= workflow 的 `MODE=rollback`）
  注入 `ALLOW_DOWNGRADE=1`；**#4767 的「失败即回滚」那次尝试同样带 1**（回滚本身就是往回走，
  否则新闸门会把既有护栏一起挡掉）。
- **本次实际生效 tag 逐服务一行**（`EFFECTIVE_TAG=<svc>:<tag>`，被跳过的服务也有一行，值 = 在跑的那个）
  落 `$GITHUB_STEP_SUMMARY` 并拼进部署结论行 —— 事故里那句只报**请求的** tag 的
  `✅ 部署成功（tag=…）` 正是误导源。

#### 取舍：`deploy.sh` 该不该只部署「本次变更涉及的服务」？（**本单不改**，如实登记）

现状判据 = 「该 TAG 的镜像**在不在**本地/ACR」（`docker compose pull <svc>` 成功 ⇒ 纳入 `UP_SERVICES`）。
它**其实已经是**一种「只部署本次变更涉及的服务」的弱形式：每个 deploy workflow 只构建**自己那个模块**
的镜像（`.github/workflows/deploy-admin-api.yml` 等的 `IMAGE_NAME` + paths 触发）⇒ 没改的模块在该 tag 下
**没有镜像** ⇒ pull 失败 ⇒ 被跳过。但它与「哪个模块改了」**不等价**，两类偏差：
① **同 sha 的兄弟 workflow**：一个 commit 同时改两个模块 ⇒ 两个 workflow 建出**同 tag** 的两个镜像
⇒ 后到的 run 会把两个服务都部署（同 commit、方向不会往回走 ⇒ 无害，但「谁部署了什么」变模糊）；
② **回滚 / 重放 / 手工指定 tag**：此时「镜像在不在」与「改了没改」完全无关，按模块判会**少部署**。
⇒ **结论：不加这一层。** 判据真值（「本次变更涉及哪些模块」）在**远端不可得**（远端只有 tag ⇒ 镜像），
只能由 CI 侧按 `git diff` 算完再传下去 ⇒ 新增一条跨进程契约（易漂移）、且与「失败即回滚」语义冲突；
更关键的是 **#4852 的危险方向是「往回走」，按模块判**不能**阻止往回走**（旧 run 的模块改动照样会被部署）。
本单用「不许往回走」闸门直接治危险方向，它同时覆盖回滚/重放/schedule 对账等**所有**来源。
**代价（如实登记）**：一次运行仍可能对「没改的模块」做一次**同 commit** 的重复部署（幂等、无回退风险，
只多花约一个服务的拉取时间）。

#### 上真机后怎么验证（**可执行判据**）

```bash
# ① job summary 的远端输出里看闸门结论行（CI 日志会被截断，summary 不会）
#    期望：`闸门结论：允许部署=[…] / 因「往回走」跳过=[…]` + 三条 `EFFECTIVE_TAG=<svc>:<tag>`
# ② 只读核对「线上到底是哪个 commit」（真机观测，不写任何状态）
aliyun swas-open run-command --biz-region-id cn-hangzhou --instance-id <实例> --type RunShellScript \
  --timeout 60 --name migao-ro --command-content \
  'cd /opt/migao-deploy && for s in admin-api ai-agent admin-web; do cid=$(docker compose ps -q $s); echo "$s $(docker inspect --format "{{.Config.Image}}" $cid)"; done'
# ③ 红证（自然发生，不能手工造）：连续合并造成排队 ⇒ 旧 run 排到新 run 之后
#    期望：它的 summary 出现 `DOWNGRADE_SKIPPED=<svc>:<target>:<running>` 且**没有** up -d 该服务
```

⚠️ **不要**用 `-f image_tag=<旧 tag>` 去"演练"回退 —— 那正是**显式回滚路径**（注入 `ALLOW_DOWNGRADE=1`），
必然放行，演练不出闸门。守卫测试：`tests/unit_ci_workflows/test_swas_deploy_no_downgrade.py`。

### 远端输出在哪看（**排查真因的第一步**）

`deploy.sh` 的输出在 SWAS API 里是 **base64**（`InvocationResult.Output`）。
workflow 现在**解码后**打印，并把**完整**输出写进该 job 的 **Summary**（CI 日志会被截断，summary 不会）。
⇒ **排查先看 job summary**，不要对着 base64 猜（事故里就是这么耗掉大量时间的）。

### 远端 `flock` 与"超时强杀"的关系

远端 `deploy/swas/deploy.sh` 用 `/tmp/migao-deploy.lock` + `flock` 串行化并发部署，
并有 `trap 'flock -u 9' EXIT`。**`flock(2)` 的锁挂在「打开文件描述」上**：进程以**任何方式**终止
（含 `SIGKILL`）时内核都会关闭 fd 并释放锁 ⇒ **不会留下陈旧锁**（trap 只是显式解锁的锦上添花）。
⚠️ 但要注意：**CI 侧的硬超时不会终止远端进程** —— `RunCommand --timeout 3600` 仍在跑，
锁仍被它持有（下一个部署最多等 `LOCK_WAIT_SECONDS` = 1800s 后失败退出）。这就是**超时路径不做自动回滚**的原因
（此刻回滚只会与它抢锁）；超时走"显式告警 + 本手册"。

🔴 **等待窗口为什么是 1800s（issue #5896，2026-10-01 实测）**：三条 SWAS 部署腿
（`deploy-frontend` / `deploy-admin-api` / `deploy-ai-agent-service`）**共用**这把远端锁，而它们各自的
CI `concurrency` 组是**按服务**分的（`deploy-*`）⇒ **跨服务不互斥**。同一次 push 同时改
`backend/admin-api/**` 与 `frontend/admin-web/**` 时两条腿**同刻起跑抢一把锁**，先到者实测跑了
**~28 分钟**（07:32:48Z → 08:00:22Z）⇒ 旧的 600s 等待上限对后到者**必然不够**：当天两次
`deploy-frontend` failure（06:15Z / 07:32Z）的报错都是「等待部署锁超时」，而**不是**构建/健康检查失败。
⇒ 后到者现在最多等 1800s（30min）；同期抬高的三处预算必须一致：
`C_BUILD_DEPLOY_TIMEOUT_SECONDS`（4500s = 1800 + 冷构建**上界** 2400 + 余量 300；用上界而非实测 1782s，
因为实测只是样本、上界才是脚本声明并被判据钉住的值）与 job `timeout-minutes: 90`。

⚠️ **超时文案必须如实归因（同批修正）**：旧文案写「可能有**卡死的部署进程**持有」并提示「确认无进程后再**删锁文件**重试」
—— 这两条都与事实相反（锁不可能被遗留；真因是兄弟部署在**正常**排队，只是比旧上限长），
集成侧曾按它去找「卡死进程」、**排查方向被带偏**。现在的文案说「并发部署在**排队**」，
`fuser -v` 只作**次要**核对手段，并明确写出「不要清 `$LOCK` 后重试、也不要 kill 占用者」。

## 验收流水线

```
Issue 创建（CONTRACT_JSON 含 business_truths + cases 引用）→ 自动生成验收草稿 (L2/L3/L4)
     → 研发 review → PR 合并
     → 自动触发双验收:
       主验收: spec + L2/L3 业务断言 + 逐用例打分（case_results）
       复核验收: DB/API 独立断言 (不看 spec, 避免合谋)
     → 双一致 + 100% → 自动 close issue
     → 不通过 → 留研发/凯总处理
```

## 关键环境变量 (GitHub Secrets)

| 变量 | 用途 |
|------|------|
| `ALIYUN_ACCESS_KEY_ID/SECRET` | 阿里云 CLI（SWAS 云助手 RunCommand + OSS） |
| `ACR_USERNAME/PASSWORD` | 容器镜像推送（CI 构建推 ACR，服务器 pull 消费） |
| `DASHSCOPE_API_KEY` | LLM API |
| `SMOKE_ADMIN_PASSWORD` | 冒烟测试登录 |
| `SMOKE_SERVICE_TOKEN` | 服务间调用 + agent-eval 评测 |

---
详见: [SWAS 迁移踩坑](../deployment/swas-migration-lessons.md) · [部署检查清单](../deployment/deployment-checklist.md)

## Danger Scan：删除 workflow 的人工确认通道（#4295）

`Danger Scan (破坏性变更检测)` 是 **required** check。它把「删除 workflow 文件」判为 BLOCK ——
但补本条之前，**没有任何记录"人工确认"的地方**（`DANGER_TRUSTED_ACTOR` 只对"新增"降级）。

⚠️ **这在本仓库会硬卡死**：分支保护开了 `enforce_admins=true`（"不允许绕过上述设置"），
它**对管理员同样生效** ⇒ 既没有 `gh pr merge --admin`，UI 也不提供 "Merge without waiting"。
实测（#4288）：`GraphQL: Required status check "Danger Scan (破坏性变更检测)" is failing.`
⇒ 在补通道前，**删除任何 workflow 在机制上都不可能合并**。

**怎么删**（owner 本人操作，两步）：

1. 在 PR 上评论一行（**必须由 owner 账号发出**；其他人的评论一律不采信）：
   ```
   /danger-ack delete-workflow .github/workflows/<要删的文件>.yml
   ```
   批量清理可用 `/danger-ack delete-workflow all`（展开为本次**全部**被删的 workflow）。
2. 重跑一次该 check（`gh run rerun <danger-scan-run-id> --failed`）。

之后该条降为 WARN，并在 `danger-scan-result.json` 的 `acks` 里留痕（谁确认的 + 确认评论链接）。

- **为什么用评论而不是 label**：`gh run rerun` **复用原始事件载荷**（标签快照是旧的），
  且 label 变更不在 `pr-check` 的 `pull_request.types` 里 ⇒ label 方案在重跑下不生效；
  评论在**运行期**读 API，故重跑能拿到最新确认。
- **fail-closed**：无删除 / 评论 API 失败 / 非 owner / 未命中 marker ⇒ ack 为空 ⇒ **仍 BLOCK**
  （无确认时的行为与补通道前**逐字相同**）。
- 判定逻辑在 `danger_scan.py` 的 `parse_delete_acks()` 纯函数里（**不在 YAML 字符串里**）——
  首版把判据写成脚本文本匹配，红证实测"不红"（空断言），故改挂到纯函数上。

## Danger Scan：已发布迁移被**重写**的人工确认通道（#4936）

「迁移不可变」判据只看 **git 状态（M/D）**，**不认指纹账本** ⇒ 经维护者裁定的**合并重写**
（#4936：5 条**从未在任何环境成功应用过**的迁移 V102~V106 合并为单条 V102）**结构性过不了 CI**。
本通道与上面的删除 workflow **同形**（同源 owner / 同源评论读取 / 同源 fail-closed），
但 **ack 不足以放行** —— 必须同时过 `verify_migration_acks()` 的交叉校验：

**怎么做**（owner 本人操作，两步）：

1. 在 PR 上评论一行（**必须由 owner 账号发出**；其他人的评论一律不采信）：
   ```
   /danger-ack rewrite-migration V102
   ```
   多条可用 `/danger-ack rewrite-migration all`（展开为本次**全部**被修改/删除的迁移）。
2. 重跑一次该 check（`gh run rerun <danger-scan-run-id> --failed`）。

之后该条降为 WARN，并在 `danger-scan-result.json` 的 `acks` 里留痕（版本号 + 确认人 + 评论链接）。

**ack 之外还必须同时满足**（任一条不满足 ⇒ 照旧 BLOCK，并在 blocker 文案里点名原因）：

- **账本同批更新**：`tests/unit_ci_workflows/migration_fingerprints.json` 本次 diff 状态必须是 `M`；
- **账本与磁盘一致**：修改型迁移在账本里的 sha256 必须等于**磁盘当前** sha256
  （不一致 ⇒ 先跑 `python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger`）；
- **删除型迁移**：账本里**不得**还留着该文件名（须同批删掉条目）；
- **一一对应**：ack 了本次没改的版本 ⇒ 不算数；本次改了没 ack 的 ⇒ 照旧 BLOCK（逐个报）。

- **fail-closed**：无 ack / 评论 API 失败 / 非 owner / 账本没改 / 哈希不符 ⇒ **仍 BLOCK**
  （无 ack 时的行为与补通道前**逐字相同**）。
- 判定逻辑在 `.github/danger_scan.py` 的 `parse_migration_acks()` + `verify_migration_acks()`
  两个纯函数里；scan 模式**重跑**交叉校验（不只信 `DANGER_ACK_MIGRATION` 环境变量）。

