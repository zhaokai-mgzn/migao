# 评测环境分工与门禁（eval-environments）

> **一句话**：评测只在**标准考场**（CI 独立栈）下结论；云测试环境负责部署验证与冒烟；
> 生产上线前必须过"发布门禁"。三层分工写死，避免"在哪个环境上跑、跑什么档位"靠口口相传。
> 维护：#3483（评测体系根本解）；相关：#3506（本文档）、#3504（PR 门禁）、#3503（部署后回归）。

## 一、三层环境（现状：前两层已落地，生产待部署）

| 层 | 状态 | 定位 | 评测角色 |
|---|---|---|---|
| **① 独立栈（CI docker 标准考场）** | ✅ 已落地（C 端 + B 端 persona=mibao） | 每次 `down -v` 从零重建、跑完即弃、与云环境物理隔离 | **normal / adversarial 全量回归的主战场**；迭代档（case_ids/fast）；任何"下结论"的评测都在这里 |
| **② 云测试环境（SWAS）** | ✅ 已落地（当前**唯一**部署目标） | 合并 main 自动部署（deploy-ai-agent-service / admin-api / frontend） | **冒烟 + 真实存量数据验证**；PR 门禁 smoke 当前打这里（B 端米宝） |
| **③ 生产** | ❌ 未部署（`deploy-prod` 为规划项） | 未来正式生产 | **发布门禁 + 运行期冒烟**（见第三节） |

**为什么独立栈是"标准考场"**：数据干净（无同名商品/存量订单污染）→ 失败可归因到能力而非环境；
无部署窗口干扰；可注入快模型与并发（当前 `deepseek-flash` + `EVAL_CONCURRENCY=6`）。
代价：起栈固定成本 ~2-3 min（#3426 GHCR 预构建镜像在压）、干净栈需 seed 补齐业务数据（T3.2 `mibao_eval_seed.sql`）。

### 1.1 种子口径：单一实现 + 每个 persona 一套栈（#3563，2026-09-14 固化）

「标准考场」的前提是**同一个 persona 在任一 workflow 上拿到同一份数据栈**。此前三个
评测 workflow 各写一份种子规则、且互不相等（`xiaobu-acceptance`/`post-deploy-eval`
只在 `persona=mibao` 时叠 B 端种子，`agent-behavior-eval` **无条件**叠加），后果是
**同一用例结论相反**：CH-010 在 `agent-behavior-eval` 上 0%（栈里 `products=4`，
B 端 `prod_eval_2699` 因 `created_at` 更新而排在首条 → 用例的「第一款」指到了 B 端商品）、
在 `xiaobu-acceptance` 上 100%（`products=3`，首条是 C 端「北欧风窗帘」）。

**口径（单一真值 = `scripts/eval_stack_seed.sh`，三个 workflow 都调用它）**：

| persona | 栈内种子 | 为什么 |
|---|---|---|
| `xiaobu` | **仅** C 端 `xiaobu_eval_seed.sql` | 叠加 B 端会改 `created_at` 排序 → 商品列表（`ORDER BY created_at DESC`）首条漂到 B 端 → C 端选品/「第一款」链路假失败 |
| `mibao` | C 端 `xiaobu_eval_seed.sql` + B 端 `mibao_eval_seed.sql` | B 端点名数据缺失（2699 商品/刺绣工艺/客户张三/员工王五）会被误判成能力回归（#3496/#3511） |

两条纪律：
1. **一个栈只服务一个 persona**：`agent-behavior-eval` 已改 persona matrix
   （每个 persona 一个 job + 独立栈 + 该 persona 的种子），与 `post-deploy-eval`
   的 matrix 同款「独立 runner + 独立栈 + 独立新库」（#3515）；
2. **能 L0 拦的不许流到 L2+**：口径漂移由
   `tests/unit_ci_workflows/test_eval_stack_seed_parity.py` 秒级静态锁拦
   （workflow 只许调单一源、xiaobu 栈不许含 B 端、同栈不许混 persona、
   评测旋钮/节流值三路同值），**零 LLM**。

同族 workflow 的旋钮（`EVAL_ROUND_SLEEP` / `EVAL_CASE_SLEEP` / `EVAL_CONCURRENCY` /
`AGENT_EVAL_TRACE_ALL` / `AGENT_EVAL_FLAKE_LOG`）也由同一组静态锁逐项钉住 ——
`AGENT_EVAL_FLAKE_LOG` 曾真实漏设（`post-deploy-eval` 上传了永不存在的
`agent-eval-flakes.json`，`agent-behavior-eval` 既不落盘也不上传）。


## 二、各层用例档位（档位纪律见 migao-dev-flow §16）

| 触发 | 环境 | 档位 | 说明 |
|---|---|---|---|
| PR（AI 行为文件改动，**仅 app/** 源文件） | 独立栈 | **映射用例 fast 迭代档**（persona 按命中用例分桶） | #3502 diff 驱动 + #3653 收窄：只跑 §13.2 映射用例（规则命中或兜底网），normal 桶 `--max-retries 0`；**C 端 smoke 不再进 PR 门禁**（#3653 与行为映射档合并去重，降为按需 `workflow_dispatch`）；B 端云冒烟已从 pr-check 移除（评的是已部署 main，与本 PR 无因果） |
| 手动 `workflow_dispatch`（部署后复核/里程碑/回滚复验） | 独立栈 | **normal 全量**（mibao + xiaobu）或手动选档（smoke/adversarial/case_ids 定点） | #3925 起：部署后自动触发（workflow_run）**已移除**（真实 LLM 成本治理，用户裁定）；需要时手动派发，判定口径（completion_verdict）不变 |
| 每 3 天（schedule cron `0 3 */3 * *`） | 独立栈 | **normal 全量（mibao + xiaobu）** | #3654 起承担宽度覆盖（长期漂移兜底）；main 自上次全量未动 → 抑制不白跑 |
| 每周六 | 独立栈 | adversarial | 只追踪不阻塞 |
| 里程碑 / 下结论前 | 独立栈 | **结论档**：全量 + 验收剧本 + 双 AI 交叉验证（GLM-5.3-Flash 复核）+ `completion_verdict` | 见 acceptance-protocol v1.3 §1.6/§1.7 |

**完成判定**（T2，#3487）：`completion_verdict` = 必须处理的失败 0（除 `llm-noise` 外的一切
score<1，含 `unstable`）+ 关键旅程全过 + **仅 `llm-noise`** 台账放行。
完成 ≠ 全量 100% 绿（追 LLM 方差边际收益为负）。

## 三、生产上线门禁（#3503 预演 → 未来生产发布）

生产层尚未部署，门禁定义现在固化，避免上线时裸奔：

1. **发布门禁（生产部署前必过）**：独立栈 normal 全量（B/C 双 persona）+ `completion_verdict` ✅
   + 结论档双裁判（主判 + GLM-5.3-Flash 复核）无未裁定分歧；
2. **运行期**：生产只放 smoke 冒烟 + 抽样复核 + 波动台账，**不做全量**（全量留在标准考场，
   避免污染生产数据、避免长链路成本）；
3. **回归触发**：生产发布前后由**人显式派发**全量回归（#3925 起：云测试环境部署后自动触发已移除，改手动 workflow_dispatch；生产门禁沿用同一机制，目标改为生产）。

### 3.1 已落地的自动门禁（2026-09-14，含 blocking 属性）

| 触发 | 门禁 | 属性 | 实现 |
|---|---|---|---|
| PR（任意） | 三模块单测 / QA Growth Gate / ci-helper / gitleaks / Danger Scan | ★ **required（硬拦合并）** | pr-check 等 |
| PR（AI 行为文件，**仅 app/**） | **映射用例 fast 迭代档**（persona 按命中用例分桶派生；规则命中失败 → 报告 + 评论 + 自动开 issue，兜底网失败 → 只报告；**均不拦合并**） | **均为信息性** | `agent-behavior-eval.yml`（#3502/#3523/#3563/#3653） |
| PR（AI 行为文件） | ~~C 端 smoke + B 端云冒烟~~ —— **已移除**（#3653）：C 端 smoke 降为按需 `workflow_dispatch`（xiaobu-acceptance 不再 pull_request 触发）；B 端云冒烟从 pr-check 移除（评的是已部署 main，与本 PR 无因果） | — | — |
| 手动 `workflow_dispatch`（部署后复核/里程碑/回滚复验） | **双 persona 矩阵行为回归**（各自独立栈/全新库）→ 档位 = 手动选（normal 全量 / smoke / adversarial / case_ids 定点）→ completion_verdict 判定 → 失败去重建 issue | 按需手动 | `post-deploy-eval.yml`（#3503/#3515/#3654/#3925） |
| 每 3 天（本 workflow 的 schedule cron） | 双 persona 矩阵 **normal 全量**（各自独立栈/全新库）→ completion_verdict 判定 → 失败去重建 issue | 定期拦截（宽度覆盖） | `post-deploy-eval.yml`（#3654/#3925） |
| 每周六 | adversarial 档 | 信息性 | `xiaobu-acceptance.yml`（schedule） |
| 里程碑 / 下结论 | 结论档（全量 + 验收剧本 + 双裁判 + completion_verdict） | **结论前置（必过）** | 协议 v1.3 §1.6/§1.7 |

> **⚠️ 最容易误读**：required 只有确定性层那 9 项——LLM 行为层**有意不进 required**
> （真实 LLM 方差会卡死合并流水线；job 名随 persona 参数化也不适合）。
> ⇒ 「C 端 smoke 红 ≠ 不能合并」，它是强信号；硬拦截由确定性层 + 定期/手动全量回归承担。

### 3.2 决策记录：行为映射门禁**不纳入** required checks

- **决策**（2026-09-14，用户确认"遵循建议"）：`行为映射用例评测`（agent-behavior-eval）
  与 C 端 smoke 一样**保持信息性**，**不**加入分支保护 required_status_checks；
- **理由**：① 真实 LLM 方差（unstable/llm-noise）会随机卡死**无关** PR 的合并流水线；
  ② job/check 名随 persona 参数化，做 required 不稳定；③ 现有 required 9 项已覆盖确定性层，
  部署后全量（post-deploy-eval）承担真拦截；
- **它的实际拦截力**：规则命中用例失败 → **workflow 内红 + PR 评论**（强信号，人工/AI 据此决定）；
  兜底默认集失败 → 只报告（标"无因果"）。**不要**把这条当成"可以忽略红灯"的理由——
  规则命中红 = 改动真的影响了行为，必须先看产物再决定；
- **翻案成本**：若将来要纳入 required，需先解决"方差卡合并"（例如只对确定性失败 required、
  或把该 job 拆成"确定性部分 required + LLM 部分信息性"），**禁止裸加 required**。

### 3.3 仓库级评测槽位 `eval-stack-global`（#3587）：排队，不 cancel

**问题**：每个评测 workflow 各自一条排队队列 → 多个 workflow / 多个 PR 同时**并发建栈**互抢
runner 与 Docker Hub 出口，栈启动从 3.4min 被抬到 12min，评测轮次从 8min 被抬到 12min、
确定性失败从 9 条涨到 13 条（#3417 实测；`eval-pipeline-performance.md` §2.2）。
排队不只是慢 —— **它让结论变不准**（并发制造假失败）。

**做法**：让所有**会起独立栈**的评测 workflow 共用同一个 concurrency group
（`eval-stack-global`）。GitHub 的语义是「同 group 至多 1 个 running，其余 queued」，
group 名不带 workflow 前缀即**跨 workflow 生效**。

| workflow | 现状 | 落地改法（精确到行） | 预期效果 |
|---|---|---|---|
| `post-deploy-eval.yml` | ✅ **已改**（#3587） | 文件级新增 `concurrency: { group: eval-stack-global, cancel-in-progress: false }` | 部署后全量回归全局串行，不再与其它评测抢栈 |
| `agent-behavior-eval.yml` | ✅ **已改**（#3563） | 与 xiaobu 同款**两层**：文件级 group 保持按 PR（`cancel-in-progress: true`）；在 `behavior-eval` job 加 job 级 `eval-stack-global-${{ matrix.persona }}`（`cancel-in-progress: false`） | 同 PR 新 push 仍即时取消旧 run；每个 persona 的栈全局串行（带 persona 后缀 = 该 workflow 的两条腿本就是两套独立栈，不带后缀会互相挤掉 pending 腿） |
| `xiaobu-acceptance.yml` | ⏳ 待改（另包） | 文件级（第 86-88 行）**保持不变**；在 `xiaobu-acceptance` job（第 125 行 `xiaobu-acceptance:` 下、`timeout-minutes` 之后）新增 job 级 `concurrency: { group: eval-stack-global, cancel-in-progress: false }` | PR 级取消语义**完全保留**（新 push 仍能立刻杀掉排队中的旧 run —— 它还没起栈，杀掉最省）；真正起栈的 job 进入全局槽位，**同一时刻仓库内只有一套评测栈在构建** |

**为什么 xiaobu 的改法与其他两个不同（关键取舍，别抄错）**：
`xiaobu-acceptance.yml` 的文件级 `cancel-in-progress: true` 是**PR 迭代**的必需品
（同一个 PR 连推 3 次，前两次的栈构建与 token 全废）。若把文件级 group 换成共享槽位并
`cancel-in-progress: false`，新 push 就必须**排在**旧 run 后面 —— 那既丢了 PR 迭代性，
又让旧 run 有机会跑完整套栈，是最坏组合。
故 xiaobu 用 **job 级** group：PR 级"取消旧的排队 run"（便宜、正确）+ job 级"全局串行建栈"
（消除互抢）。两层语义各司其职，**不做二选一**。

**注意事项**：
1. **不要为了"更快"把 `cancel-in-progress` 改成 true**（对 post-deploy-eval）——
   取消在跑的长评测会让门禁永远跑不完（活锁）+ 结论档永久丢失（#3526 决策，勿翻案）；
2. **共享槽位的代价是排队**：并发建栈消失后，同时提交的多条评测会串行。
   这正是 #3587 要的（少付一份栈构建 + 少一份假失败），但它**不缩短单次评测** ——
   单次提速仍靠 `case_ids` 收窄 + `fast`（评测档）+ GHCR 预构建镜像（栈固定成本，
   见 `eval-pipeline-performance.md` §2.7）；
3. 新增**会起独立栈**的评测 workflow 时，一并加入 `eval-stack-global`
   （不起栈的纯计算 job/workflow 不必加入）；
4. group 名是**契约**：改名等于把队列拆散，改名必须同步改所有 workflow + 本文档
   （守卫：`tests/unit_ci_workflows/test_post_deploy_eval_supersede.py::TestGlobalEvalSlot`）。

**落地细节（#3563，与本文档其余部分一致）**：PR 触发的两条评测走**两层** group ——
文件级管「同 PR 新 push 取消被取代的 run」（PR 迭代必需，**别丢**），job 级才是共享槽位。
`agent-behavior-eval` 是 persona matrix（两条腿 = 两套独立栈），其 job 级 group 带
`-${{ matrix.persona }}` 后缀：不带后缀时，新 run 的 mibao 腿会把旧 run 的 **pending xiaobu 腿**
挤掉 → 丢掉一整个 persona 的结论。
**诚实边界**：该槽位保的是「**最新的评测 run 会跑**」，不是「每个 PR 都拿到行为信号」——
突发期被取代的 pending run 会 `cancelled`（信息性检查，不阻塞合并；行为信号由部署后全量轮承担）。
要「每 PR 都有信号」必须分离 runner 池（超出仓库范围，本轮不选）。

**派发侧守卫 + 取消/空跑口径（#3761/#3770，2026-09-15 起已落码，不靠文档约定）**：
上面那条 concurrency 只保证「排队不互杀**建栈**」，**治不了派发侧并发**——实测一个窗口
**10 个 run 被 `cancelled`**：7 个死在 pending（0 建栈成本）、2 个已进 `Start local stack` ~1.6min 才被杀
（**栈付过费、零结论**）、3 个还被记成「部署后回归失败」的**假评论**（落进 issue #3534）。
故口径落在**派发侧**，四条都在代码里：

1. **派发前查槽位**：`.github/scripts/eval_slot_status.sh`（零成本只读 `gh run list`）——
   `0` 槽位空闲可派 / **`2` 被占用 ⇒ 不要派发**（`🚫 槽位被占用（N 个 run 在跑/排队）—— **不要派发**`）/
   `3` 无法判定（gh 不可用/未登录）⇒ **不谎报「空闲」**；
2. **`cancelled` 不是结果，也不再是失败**（#3761）：判定步骤补 `!cancelled()`、建 issue 条件去掉
   `|| cancelled`、新增「被取消记录 / 被取消留档」步骤（`::warning::` + step summary 抬头
   「本 run 被取消（未评测，不构成结论）」）。它与 §3.5 的**抑制**是**同族不同源**：
   抑制发生在花钱之前（秒级比对、0 token），取消发生在建栈之后（钱已烧）——共同点是**零结论**：
   都不得读成「跑了没过 / 过了」，也都不判 failure、不建 issue；
3. **结论复用（ledger）**：判定结论按 summary 的 **`run_key`** =
   `(sha, tier, case_ids=空, 用例库 tree hash, 跑批策略版本)` 复用 —— 同 SHA 已有两个 persona
   都 `completion.ok=true` 的**全库** run ⇒ **不重复跑**（派发前守卫 `.github/scripts/eval_dispatch_guard.sh`
   命中即给出可引用的 run id）。⚠️ 这里的「全库」= **该档**全库（`normal` 档**不含** smoke/adversarial，
   三档互斥），**不等于「覆盖全部用例」** —— 判定用途的 normal 跑只代表 NORMAL 档的结论。键**缺一不可**是刻意的：旧 run 无 `run_key` / artifact 缺失 ⇒
   **不命中，宁可多跑**；判定用途被收窄（`case_ids` 非空 + `PURPOSE=determination`）⇒ **拒绝派发**；
4. **空跑守卫**：**评测相关路径**（runner / 用例库 / ai-agent 行为源 / 评测 workflow）变更集为空 ⇒ 不派发，
   打印 **`⏭️ 评测相关代码无变更 ⇒ 未跑（引用 <run_id>）`** —— **「没跑」必须长得像「没跑」**
   （同族：`verify-all.sh` 的「⚠️ 无变更或无法对比 origin/main，跳过」）。

口径全文（含理由与 run 级实证）见 `migao-dev-flow` §16.6 ⑥ 与 §16.7（派发前 / 派发后 / 禁空跑）；
档位纪律表仍在本文 §二，**条数与成员仍以单一事实源为准**（见 §3.6 的说明）。

### 3.4 决策记录：规则命中**不再阻塞**，降为「报告 + PR 评论 + 自动开 issue」（2026-09-14 用户确认）

- **决策**（2026-09-14，用户裁定原话"按建议来"）：`agent-behavior-eval` 的**规则命中**用例
  失败时，workflow **不再变红**（评测步骤恒 `exit 0`），门禁语义从「规则桶阻塞 / 兜底网信息性」
  降为「**均为信息性**」，但**高可见**：
  1. **PR 评论**（每个 persona 一条，marker 带 persona）：明确写「命中的规则 = 哪个文件 → 哪条
     规则 → 哪些用例」+「执行计划」+「结果」，并**显式标注这是强信号、必须人工/AI 判断，只是不拦合并**；
  2. **自动开 issue**（去重守卫照 `post-deploy-eval.yml` 范式）：标题含**用例 ID + PR 号**，
     body 带映射来源（命中规则明细）+ 失败要点 + 门禁语义说明；同标题 open issue 存在则追加评论；
  3. 两者都**区分规则命中与兜底网**（兜底网失败只报告，**不开 issue**）。
- **理由**：
  ① 它产出过**假阻塞红** —— 规则按路径**正则**匹配，存在误命中风险（实测形态：测试文件名含
     `guard` 就命中 `(guard|defense|injection)` 规则 → 把一个改 finance 工具的 PR 判成命中
     防御规则、跑 DF-011/DF-012；该误命中的**修正**由另一个包改
     `tests/agent_eval/behavior_mapping.py` 承担，与本文档的门禁语义是两件事）；
  ② PR 层 LLM 评测**不构成合并门禁**（§16.5：LLM 行为层有意不进 required），
     阻塞只带来「必须先证伪才能继续」的摩擦；
  ③ 真拦截由**确定性 required 层**（9 项）+ **部署后全量**（post-deploy-eval，双 persona）
     承担 —— 少一层 PR 层阻塞不会让真回归漏网。
- **不弱化信号的落点**：step summary（`## 🧪 行为映射用例评测结果`）+ `::warning::` +
  PR 评论 + **自动开 issue**；issue 是这条"强信号"的持久承接，不会随 PR 关闭而消失。
- **同源决策记录待同步**：`migao-dev-flow` 技能文件 §16.5 另有一份决策记录，
  由另一包（K）在改 —— 本决策在**技能文件侧**的同步待该包合并后进行（本 PR 不改技能文件）。


### 3.5 抑制「已被取代的 run」（#3587）：门禁不因抑制而消失

`post-deploy-eval.yml` 在**任何真实成本之前**比对「本次被评 SHA」与「远端 main HEAD」：
不等即说明这份镜像已被更新的 commit 覆盖，**跳过评测**并打印链接链
（被评 SHA 的 commit → 取代它的 main commit → 取代它的 run 列表），
**不计 failure、不建 issue**。

- **它不违反"不 cancel-in-progress"那条决策**：抑制不是取消 —— 取消发生在长评测跑了一半
  （钱和时间已烧掉、且没有任何结论）；抑制发生在花钱之前（秒级比对、0 token、0 栈构建），
  且结论由**取代它的那次 run** 承担并有链接可追。「某次部署时行为到底怎样」仍可回答 ——
  答的是"这个 **main 状态**"而不是"这个已被覆盖的 commit"；
- **fail-open**：`git ls-remote` 失败 / 取值不可得 / 手动 `workflow_dispatch` → **一律照常评测**。
  判定逻辑本身绝不能成为"漏评"的来源；
- **手动逃生口（#3709 更正，以实现为准）**：`workflow_dispatch` **默认免抑制**（人显式要求
  「我就要这一条」，回滚复验/补跑）；要恢复"被取代即抑制"必须**显式传 `force_eval=false`**。
  ⚠️ 旧文本写的是「`force_eval=true` 才强制评测」—— 与实现不符（此前 dispatch 走的是 deploy
  判据，默认被静默抑制），实测 run 34841093824 整体 `success` 而**每个评测步骤 `skipped`、
  artifact 为 0**（一条用例都没跑）。引用本条前先核实现，别照抄。
- **#3709 追加：未评测必须显眼**。被抑制时 workflow 打 `::warning::` annotation，并把
  step summary 抬头写成「本 run 未评测（不构成结论）」—— 让"绿"不再等于"评测通过"。
  ⚠️ 抑制**依旧不是 failure**（不刷红、不建 issue）：要的是**可见**，不是变红。
- **#3654 追加**：`MODE=schedule`（每 3 天全量）走**方向相反**的判据 —— 本次 schedule 的
  SHA 与**上一次 schedule 全量**的 SHA 比对，相等 = main 未动 → 抑制（同一状态已有结论，
  重跑是纯浪费）；不等 → 跑。查询失败/取值为空一律 fail-open。两种模式共同点：只有
  `skip` 会抑制、一切异常照常跑、skip 不计 failure 且留链接链。

### 3.6 决策记录：部署后评测改**手动触发** + 每 3 天全量（#3925，2026-09-15 用户裁定）

- **决策**（2026-09-15，用户裁定，方向已定）：`post-deploy-eval.yml` 的**部署后自动触发
  （workflow_run）移除**，全量回归改**手动 workflow_dispatch**；每 3 天 schedule 全量保留。
  - 背景：部署后评测（即使 #3654 已收窄为 diff 定向）仍是真实 LLM 成本主因（近 2.5h
    ≈ ¥135-295）+ 挤占全局评测槽位（eval-stack-global），且每次部署都自动跑是
    "无人在场也要付钱"（自动跑的实际结论没人盯，#3925 用户裁定：手动的"跑一次算一次"
    更诚实）。
  1. **手动 `workflow_dispatch`**：部署后复核 / 里程碑 / 回滚复验 / 随机抽查——人显式
     触发，档位任选（normal 全量 / smoke / adversarial / case_ids 定点复验）；
     dispatch 默认**免抑制**（#3709：人显式要求 = 我就要这一条）；显式
     `force_eval=false` 逃生口保留（回到"被取代即抑制"判据）。
  2. **每 3 天 schedule cron**（`0 3 */3 * *`，03:00 UTC 低流量时刻）：tier 恒
     normal、双 persona 全量，承担**宽度覆盖**（手动档"没人记得跑"的长期漂移兜底）；
     main 自上次全量未动 → 抑制不白跑（`eval_supersede.sh` MODE=schedule）。
  3. **删除 diff 定向选择器**（`eval_targeted_cases.py` + 其测试）：无 workflow_run
     触发方后无存在意义（YAGNI；手动定点复验用 inputs.case_ids，定时档恒全量）。
  4. 判定口径不变（completion_verdict + 失败建 issue）：手动与定时两档一致。
- **理由**：
  ① 近 2.5 小时 CI 真实 LLM 成本 ≈ ¥135-295；单次 persona 全量 ≈ ¥15-20
     （B 端 ~47 条 / C 端 ~35 条真实往返）；
  ② 部署后自动评测的**收益递减**：每次部署都跑（即使定向），而大多数部署只改个别域，
     且自动跑的结论无人即时消费（部署不因它阻塞）——成本照付、结论滞后；
  ③ 手动触发把"何时付真实 LLM 成本"交还给人：需要结论才付钱（#3925），
     与 milestone 结论档（§1.6/§1.7）同构。
- **persona 维度**：matrix 双 persona（mibao/xiaobu）各自独立栈 + 全新库（#3515 隔离
  语义不变）；手动 case_ids 定点时按本端可执行集过滤（复用 `select_cases_for_persona`，
  与 local_runner 同口径）。
- **成本模型**：手动档"按需付费"（跑一次全量 ¥15-20/persona）+ 每 3 天全量 ¥15-20/次
  （≈ 每周 2.3 次全量）——按 20 次合并/周估算 ≈ 2.3×¥36 ≈ **¥83/周**（对比原每次部署
  双 persona 全量 ≈ ¥360/周，省 ~77%；#3925 起自动触发已移除，成本进一步下降）。
- **守卫**：`tests/unit_ci_workflows/test_post_deploy_eval_supersede.py`（dispatch 默认
  免抑制 / force_eval=false 逃生口 / schedule 判据 / 槽位 / 审计链；#3925 更新为
  MODE=dispatch 语义）；`test_workflow_issue_permissions.py`（issues: write 权限）。

## 四、与米高研发模式的衔接

- 档位纪律 / 全量降频 / 完成定义 / **门禁矩阵（含量化 blocking 属性）**：`migao-dev-flow` §16（§16.5）；
- **并行修复原则（发现即并行，合并串行）**：仓库 `AGENTS.md` 铁律 6 + `migao-dev-flow` §17；
- **用例编写陷阱**（卡回放/答卡/自包含化 7 条实证坑）：`migao-dev-flow` §13.5；
- 结论档协议（L1/L2/UA + 双裁判 + 证据链）：`migao-acceptance` + `docs/testing/acceptance-protocol.md` v1.3；
- 提交前/迭代中体检：§13（行为改动映射用例）、§13.3（bug 沉淀有效性验证）；
- 三把工具（verify-all / check-ui-regression / contract-check）保证"不崩、契约对"，
  本文档与 §16/§17 保证"评测在正确的环境、用正确的档位、以可判定的标准下结论，且修复并行不串行"。
