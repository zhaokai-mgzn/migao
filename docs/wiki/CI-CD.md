# CI/CD 流水线

## GitHub Actions 工作流

> **数量不写死**（易腐：24 小时内真值从 34 变 33，见 issue #5082）—— 现值现取：
> `ls .github/workflows/*.yml .github/workflows/*.yaml 2>/dev/null | wc -l`

| 工作流 | 触发 | 说明 |
|--------|------|------|
| `pr-check` | PR → main | 多 job 门禁: 拦截 .env / admin-api 单测 / admin-web tsc+lint+vitest / E2E 质量门禁(4 个 fixture spec) / UI 回退检测 / QA Growth Gate(G1+G5+弱断言) / Case Contract 校验 / needs-changes 打标（**agent-eval-smoke 已于 #3653 移除**：B 端云冒烟评的是已部署 main、与本 PR 无因果；B 端行为信号**不再挂在 PR 上** —— 原 `agent-behavior-eval` 映射 workflow 已按 #4275 整体删除，改由**本机按 §13.2 映射**承担）。**2026-09-26（#3507 ①）**：`admin-api unit tests` / `admin-web typecheck + unit tests` / `E2E quality gate` 三条腿改为 **job 内 diff 门控**（原先 `admin-web` 只门控 `next build`，其余步骤每个 PR 都跑） |
| `ai-agent-tests` | PR → main | ai-agent-service 单测全量（排除 integration / e2e-real / 4 个 ignore 文件）；**v1.3 起 job 内门控**：无 ai-agent 相关变更时跳过实际单测（required check 仍报告 success，防 dependabot 空跑） |
| `deploy-admin-api` | push main `backend/admin-api/**` | 单测 → Maven 构建镜像推 ACR → 云助手触发 SWAS `deploy.sh` → post-deploy 冒烟 |
| `deploy-ai-agent-service` | push main `backend/ai-agent-service/**` | 单测全量 → 构建镜像推 ACR → 云助手触发 SWAS `deploy.sh` → post-deploy 冒烟 |
| `deploy-frontend` | push main `frontend/admin-web/**` | tsc + vitest → 构建镜像推 ACR → 云助手触发 SWAS `deploy.sh` |
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
- **把 paths 门控的信息性 check 提升为 required 的顺序（2026-09-20 固化，#4786）**：**必须先删掉 workflow 级 `paths:`、改成 job 内 diff 门控**（`git diff --name-only origin/main...HEAD` + `GITHUB_OUTPUT`，同 `pr-check.yml` 的 `Detect admin-web changes` 步），**再改分支保护** —— **顺序不可换**：先改分支保护 ⇒ required check 在不命中 `paths` 的 PR 上**卡在 "Waiting" 永不报告** ⇒ 形态 =「**没有任何检查会变红，但 PR 合不了**」（#4231 同族）。
- **真实 LLM 成本**：**PR 层 = 0 次真实 LLM**（2026-09-17 用户裁定 2′/4′，承载 issue #4034；**#4275** 之后 PR 层连**零 LLM 的映射信号**也没有了 —— `agent-behavior-eval.yml` 已整体删除，PR 上**不再有任何自动行为信号**，代价已知并接受）。判定走**单一入口** `post-deploy-eval`（**仅手动 `workflow_dispatch`**：#4262 收敛定时档、**#4974 删掉最后一条每周一 cron** ⇒ 全仓自动真实 LLM 触发 = **0 条**）；映射能力保留在 `tests/agent_eval/behavior_mapping.py`（零依赖纯函数，本机可调）。LLM 红例的闭环改由**确定性下沉台账**承接（`.github/llm-finding-ledger.json` + `llm_sink_check.py`，见 `docs/testing/llm-finding-sinking.md`）。
- **观察指标**：`gh run list --status queued` 排队 >20 即需治理（先按 DEV-FLOW §7 清 dependabot 潮）。

## CI / 台账反复出错点：具名清单（2026-09-27 固化，用户逐字「**如果 ci 或者台账经常出错的点也应该固化下来**」）

**这一节不是劝告**：下面每一条都带 `FM-EN` 记号，**逐条**给出「现状（有无守护）→ 守护是什么 →
证据」。记号与 `tests/unit_ci_workflows/dev_mode_failure_modes_ledger.json` 的 `ci_findings` **双向绑定**，
判据 = `tests/unit_ci_workflows/test_dev_mode_failure_modes.py`：

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
| **FM-E7** | 🔴→✅ **本单补判据（原先零守护）** | `test_dev_mode_failure_modes.py::test_case_ids_are_unique_across_the_corpus` | **用例号被抢**：两个并行包各自「取现取最大号 +1」⇒ 双双写成同一个新号；先合的无事，**后合的**把重号带进 main（本会话实测 7 次：UI-061 / UI-064 / MC-022 / MC-023 / BM-019…）。**修法不是「rebase 后再查一次」这句劝告** —— 而是把唯一性变成判据：重号一进 PR 就红（**红在后合的那一个**，正是它需要改号的那一个） 🔴 **缓解办法（实测有效，RBAC P3）**：① 现取已合并最大号 `grep -rhoE "\b(BM|UI|MC|PR|OR|DF|HR)-[0-9]+" .github/cases/ | sort -u`；② **再查一遍在飞 PR 的 diff / 最新内容**（`gh pr list --state open` 后逐个取 `cases/` 里的 id）—— **这一步就是能拦住「main + 在飞」的那一步**；③ **rebase 后再查一次**。⇒ 与 `CASE_ID_ALLOCATION_BOUNDARY` 的关系：**判据只看已合并状态、拦不住在飞 ⇒ 判据拦不住的地方，判别动作补上** |
| **FM-E8** | 🔴→✅ **本单补判据（原先零守护）** | `test_dev_mode_failure_modes.py::test_migration_versions_are_unique_in_the_live_dir`（**射程 = 活的 `db/migration/`**） | 两包同抢 V132 ⇒ 改名 V133/V134。既有 `test_migration_immutability.py` 只判**文件名**在两个载体目录间不重复 + 已登记文件逐字节冻结，**不判版本号**。**边界**：`migration-archive/` **存量**就有版本号重复（同一 V 号两份、文件名不同）⇒ 把唯一性套到归档上会是存量假红，故**只登记为只许缩短的常量** |
| **FM-E9** | ✅ **已有守护** | 三张面**各自**已有 fail-closed 判据（本单实测三张面全绿）+ 本页『新增 CI 守卫文件要过的三张登记面』节（作者事前自查清单） | `case_ids` / `same_source_claims` / `guard_scope_ledger` —— 新守卫文件**常同时命中多面**；今天有包为此多烧一轮 CI。判据：`test_gate_coverage_and_same_source.py::test_same_source_claims_have_criteria` + `test_guard_scope_declaration.py::test_every_corpus_referencing_module_is_registered` |
| **FM-E10** | 🔴 **未守护（gap；本单只取证 + 出方案，不改）** | owner = 门禁 owner（`verify-all.sh` 面）。**判据已存在但射程有限**：`tests/unit_ci_workflows/local_gate_matrix.json::_invariants` 第 3 条（判据 = `test_local_gate_matrix.py` 的 C4）机械要求「`fail_closed: true` 的条目必须走 `report_strict`」—— **现取只有 1 条这样声明**（`frontend/bmini-app`） | **「未就绪」被当通过**：`report_env()` 在依赖没装好时打 `⏭️ 未就绪`（跳过），而在**合并门禁**上「没跑」会被读成「这项没事」。**本单现取（2026-09-27，`./verify-all.sh quick` 实跑）**：`ai-agent` / `admin-web vitest` / `admin-web tsc` **打 ⏭️**（原因**全是缺依赖**：`.venv` / `node_modules/.bin/{vitest,tsc}`），`admin-api` 与 `worker-h5` **真跑**。🔴 **两个口径必须分开**：本机「没装依赖 ⇒ ⏭️」是**环境**、**不是门禁缺陷**（CI 上这些腿都真跑）；门禁缺陷只是「变更集命中该模块 + 依赖缺 ⇒ 本地绿」这一形态 —— 而 `gate`（合并门禁）档主路径**一条 `report_env` 模块腿都没有**（唯一模块腿走 `report_strict`）。**方案（本单不改 `verify-all.sh`，写面冲突：`FM-E4`/bmini 腿刚动过它）**：把「变更集**命中**某模块 ⇒ 该腿用 `report_strict`」逐条落成 `local_gate_matrix.json` 的 `trigger{kind: diff-face-hit, hit_fn, predicate_fn, fail_closed: true}`（bmini 已是这个范式，基础设施与判据 C4 都在）—— 代价 = 每个模块写一个 face 谓词 + 一处 `if/else` 分支；**不建议**给整档无条件套 `report_strict`（本机只启 3 组件，会让快循环档在缺依赖时整片变红） |
| **FM-E11** | ✅ **已有守护** | 内容指纹账本（已登记文件被改 ⇒ `exit 1` **拒绝重生成**）+ `.github/danger_scan.py` 的 `/danger-ack rewrite-migration`（**只有仓库 owner** 的评论算数）；判据 `test_migration_immutability.py::test_registered_migrations_are_byte_identical` | **迁移文件不可改**：改已应用迁移会被按文件名**整份 skip**（CI 绿、功能静默缺失）。⚠️ 连带后果：住在已发布迁移里**注释**中的失效判据**改不了** ⇒ 处置必须是**结构性**的（见 `docs/design/rbac-single-source.md` §1.4 实例 6 与跟踪单 #5699），不是"改注释" |
| **FM-E12** | ✅ **已有守护** | 建库终态脚本判据（表/列真值）+ 跨源逐键守卫；判据 `test_schema_integrity.py::test_schema_has_expected_tables` | **新建库路径不跑迁移链**：`backend/admin-api/src/main/resources/db/init/schema.sql` 与迁移链是**同一事实的两条路** —— 只改一路会让两种建库方式分叉（两条路的登记见 `docs/wiki/Database.md` 的「建库脚本（唯一）」） |
| **FM-E13** | ⚠️ **已登记，未接 CI** | `scripts/sync-main.sh` 的**前置拒绝**（本分支与 `origin/main` 都改过受管用例面 ⇒ **拒绝 merge** 并给出 `--rebase`；本单实测命中一次，改用 `--rebase`）+ 「生成物新鲜度校验」 | 工装级反复出错点：**裸 `git merge/rebase origin/main`** vs `./scripts/sync-main.sh`；**生成物不许手改**（要重渲染）；`dev-worktree.sh add` 与「裸 `git worktree add`」**两条路径并存**（集成侧一手读数：本会话每个包都被要求用裸命令 ⇒ 那条路径**被规避**，`add` 路径上的挂死**既未复现也未证伪** —— 按**事实**登记，不写成「某路径挂死」这一**断言**）；**仓库路径含空格** ⇒ 工具抽风（用软链）。**后两条无判据**（台账 `not_solidified` 的 `NS-2` / `NS-3`） |
| **FM-E14** | ✅ **已修（#5707 销账，`guarded`）** | **判据 13** = `tests/unit_ci_workflows/test_dev_mode_failure_modes.py::test_node_test_targets_are_globs_in_the_registered_carriers` —— 射程 = **两处具名载体**（`verify-all.sh` + `.github/workflows/worker-h5-tests.yml`，见判据常量 `NODE_TEST_GLOB_CARRIERS_FROZEN`）；目标参数不含 glob 且不在**只许缩短**的载体台账（`NODE_TEST_TARGET_ALLOWLIST_FROZEN`，现取 1 条 = 就绪探针的 `/dev/null`）里 ⇒ **红** | **`node --test <目录>` 会被读成 1 条失败的假红**（必须用 glob：`node --test <目录>/*.test.mjs`）。2026-09-27 实测。🔴 **本单复核后订正原文的「未写进任何地方」**：`docs/wiki/Development.md` 的「工装坑」节**已经写了这个坑**（散文）—— 缺口在「**无判据**」而不在「无文字」；散文拦不住任何人对腿的参数字面量做改写。判据含两条收紧以免**被自己的说明文字喂红**（`FM-A11` 形态）：① 剥 `#` 注释（**prose 豁免**）；② 目标参数须**像路径**（含 `/` 或 `.`），故 job 名里的 `(node --test)` 不被读成调用。**登记边界（假绿方向）**：`node --test <裸目录名>`（既无 `/` 也无 `.`）**不判** |
| **FM-E15** | ⚠️ **已登记（本单补判据 + 边界）** | 本单补的两条唯一性判据（用例号 / 活的迁移目录版本号）+ 顺延口径；边界声明 = `tests/unit_ci_workflows/test_dev_mode_failure_modes.py::CASE_ID_ALLOCATION_BOUNDARY`（**删掉即红**） | **编号分配只看已合并状态**：取号时现取「main 上最大号 + 1」，**看不到在飞分支** ⇒ 两个并行包取到同一个号；先合的无事，**后合的**把重号带进 main。本会话用例号已撞 **7~8 次**（UI-061 / UI-064 / MC-022 / MC-023 / BM-019 / MC-025 / MC-026），迁移号 1 次（V132 两包同抢）。🔴 **本单自己中招**：写侧取 `MC-026`（当时现取最大 = `MC-025`），#5705 合并时已占 `MC-026`/`MC-027` ⇒ 顺延 `MC-028`。**为什么不加强判据**：在飞分支在 CI 的 `actions/checkout` 下**不可见** ⇒ 同一份代码会给出不同读数（判定不确定）；走 API 则引入网络依赖 ⇒ 与「判定方式必须确定」冲突。**显形条件**：main 上已合并占号 且 某个在飞分支同号 |
| **FM-E16** | ✅ **已有守护（本单初版写错、被它当场抓住）；但「守护存在」≠「覆盖实际形态」** | `scripts/pr_body_guard.py`（issue #4232）：**工具** = `python3 scripts/pr_body_guard.py new --issue <N>`（**会话/工作区作用域唯一**、`O_CREAT|O_EXCL` 原子创建）+ 提交前 `check` + 写完 `verify`；**静态面 R1/R2** = 仓内被跟踪文本里出现「共享临时根 + `pr-body` 族文件名」的形态 ⇒ 判红，由 `tests/unit_ci_workflows/test_pr_body_guard.py::test_scan_real_repo_has_no_shared_fixed_pr_body_carrier` 在 required 的 `ci workflow helper unit tests` 里代跑 | **共享临时路径**：并发包复用共享临时根下的**约定俗成的固定文件名**承载 PR body / 评论 / payload ⇒ 互相覆盖；🔴 **失败是静默的**（后写覆盖先写、**双方都不知道**）。**两例实证，第 2 例已有实际损害**：① issue #4232 的原始实测（A 的 body 被写成 B 的；若此时被 auto-merge 合了会**误关 4 个别人的 issue**）；② **已实质性发生（PR #5704 的包报告）**：其 PR body 载体被**另一并发会话覆盖** ⇒ `gh pr edit` 把**别人的正文贴到了 #5704 上约 90 秒**（损害 = 另一个包的交付说明被公开发布在别人的 PR 上；发现 = 当场改回；最终核验 = 83 行 / 关闭关键词 0）。⚠️ **两侧都在犯**（集成侧也长期用固定临时路径）⇒ 不是某个包的疏忽，是这个工作模式自带的坑。🔴 **残余已从「边界」升级为「主路径」**：静态面射程是**仓内文本**，**管不到手敲的命令行** —— 而手敲命令正是原始形态。**判别动作（降低概率，非机械守护）**：PR body 临时文件一律用**会话唯一路径**（含单号 / 分支 / pid），优先 `pr_body_guard.py new`。**同族**：§17.2 写面冲突 / §17.3 ④ 共享写面 / §2.3 零共享写路径 / §23.6 工装纪律 / 清单 B 的 `FM-B4`；**本次推广 = 「共享写面出事的形态，往往不是你以为的那个入口」**（你防文档里的固定名，出事在命令行里的固定名） |

| **FM-E17** | 🔴 **未守护（gap，本单复核后**维持**并给出「为什么不能机械判」）** | 无（部分兜底：`deploy-reconcile.yml` 的 schedule `*/20`；其 `pull_request:[opened,reopened]` 面在无新 PR 阶段不生效）。owner = CI 门禁 owner（deploy-reconcile / 发布腿触发面） | **把 `push` 面当唯一触发面的守护腿仍是本仓默认写法**（`worker-h5-publish` / `bmini-h5-publish`），而 `deploy-reconcile` 的 `pull_request:[opened,reopened]` **只在新 PR 打开时**兜 ⇒ 对**长时间没有新 PR 打开**的仓库阶段，实际只剩 `*/20` 的 schedule cron 在兜。**现取（本单，静态面可复算）**：全仓 `.github/workflows/*.yml` 里**自动触发面 == {push}** 的**只有这 2 条**（`workflow_dispatch` 是**手动**面、不算自动兜底；`h5-freshness-guard` / `stale-report-reaper` 另有 `workflow_run` ⇒ 不算）。🔴 **为什么不落判据（本单评估结论）**：(a) 可机械判的只有**静态形状**，而它**抓不到症状** —— 症状是**运行期**事实（`push` 被 `GITHUB_TOKEN` 合并吞掉 + cron 被 GitHub 节流 ⇒ 腿没跑**且无红**）；判它要么走 GitHub API 取 run 计数（**网络依赖 ⇒ 同一份代码给不同读数**，与「判定方式必须确定」冲突），要么把发布腿接进 `mechanism-liveness` 存活读数（= **改 workflow**，本单明令不改）；(b) 静态台账登记的「兜底面」**只会是 `deploy-reconcile` 的 `*/20`** —— 而**那正是失效的那一环** ⇒ 会变成一条「**给不存在的保护盖章**」的假判据（比 `gap` 更坏）；(c) 那 2 条腿的**路径**缺口已在 `tests/unit_ci_workflows/reconcile_trigger_paths_ledger.json` 逐条登记（另造第二套台账 = 双真相源）。**重启条件**：发布/守护腿接上 `mechanism-liveness` 存活读数（或补 `schedule`）后，静态形状判据才成为**真绊线** |
**计数器（现取）**：`state=gap` 的条目共 **2** 条（`FM-E10` / `FM-E17`）—— 这个数**只许缩短**，
上限冻结在判据 `tests/unit_ci_workflows/test_dev_mode_failure_modes.py` 的 `GAPS_FROZEN` 里，**台账改不动它**。
（沿革：#5706 建账 = 3 → #5709 新增 `FM-E17` 抬到 4（台账 `PD-1`）→ **#5707 两笔销账降到 2**（台账 `PD-2`：
`FM-E4` / `FM-E14` 转 `guarded`）。🔴 **口径订正**：判据语义是 **`现取 ≤ 上限`**（只许缩短）⇒
「把上限抬到高于现取条数」**本身不会红**；「上限 == 现取」靠**销账时同批降上限**这个动作，不是靠判据。）

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
push main / push tag v*（路径过滤）→ CI 测试/构建镜像推 ACR（tag=sha-<7> 或 vX.Y.Z + latest）
  → aliyun swas-open RunCommand（实例 b23c69e5..., 超时 3600s）
  → 服务器执行 /opt/migao-deploy/deploy.sh <IMAGE_TAG>（先自愈式同步最新 deploy.sh）：
     1. docker login ACR（服务器需凭据拉私有镜像）
     2. docker compose pull（拉 CI 预构建镜像，不做源码构建）
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
| workflow_dispatch（手动）空 image_tag | 构建当前代码 `sha-<7>` 并部署 | 手动部署测试环境 |
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
| **job 级**硬超时 | 三个 deploy workflow 的 `build-and-deploy`（`timeout-minutes: 45`） | 脚本整体卡死时由 GitHub 终止 run ⇒ run 进终态 ⇒ **锁一定释放** |
| 失败**不留坏状态** | `swas-deploy-ci.sh` | 失败**自动重试 1 次** → 仍失败**回滚到 `.last-good-tag`（上一个可用镜像）** → 回滚也不行 ⇒ `::error::` 显式告警 |
| 严格蓝绿（**内层**兜底） | `deploy/swas/deploy.sh`（#4785） | 新容器先起 → 健康检查通过 → **才**切流量；不通过 ⇒ **旧容器一动不动**（**失败窗口 = 0**）⇒ 坏镜像**永远碰不到**旧容器（外层回滚仍保留，见下） |
| 对账**断路器** | `deploy-reconcile.yml` | 同一 `head_sha` 的部署**已失败过** ⇒ 不再自动补部署（防止反复重试坏 commit、覆盖手工回滚）；fail-open |

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
（`deploy/swas/deploy.sh`，窗口 600s）⇒ run 按**创建时刻**排队，而 `main` 在排队期间前进
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
锁仍被它持有（下一个部署最多等 600s 后失败退出）。这就是**超时路径不做自动回滚**的原因
（此刻回滚只会与它抢锁）；超时走"显式告警 + 本手册"。

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

