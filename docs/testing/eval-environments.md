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
| PR（AI 行为文件改动） | 独立栈 | **smoke**（B 端 + C 端 persona） | #3504 起 C 端 smoke 自动进 PR 门禁；B 端 smoke 由 pr-check 打云测试环境 |
| PR（行为文件改动） | 独立栈 | **映射用例迭代档** | #3502 起 diff 驱动自动跑 §13.2 映射用例（15-30 条） |
| 部署到云测试环境后 | 独立栈 | **normal 全量（mibao + xiaobu）** | #3503 起自动触发，失败去重建 issue |
| 每周六 | 独立栈 | adversarial | 只追踪不阻塞 |
| 里程碑 / 下结论前 | 独立栈 | **结论档**：全量 + 验收剧本 + 双 AI 交叉验证（GLM-5.3-Flash 复核）+ `completion_verdict` | 见 acceptance-protocol v1.3 §1.6/§1.7 |

**完成判定**（T2，#3487）：`completion_verdict` = 确定性失败 0 + 关键旅程全过 + 已知波动台账放行。
完成 ≠ 全量 100% 绿（追 LLM 方差边际收益为负）。

## 三、生产上线门禁（#3503 预演 → 未来生产发布）

生产层尚未部署，门禁定义现在固化，避免上线时裸奔：

1. **发布门禁（生产部署前必过）**：独立栈 normal 全量（B/C 双 persona）+ `completion_verdict` ✅
   + 结论档双裁判（主判 + GLM-5.3-Flash 复核）无未裁定分歧；
2. **运行期**：生产只放 smoke 冒烟 + 抽样复核 + 波动台账，**不做全量**（全量留在标准考场，
   避免污染生产数据、避免长链路成本）；
3. **回归触发**：生产部署后自动跑"部署后回归"（#3503 的同一机制，目标改为生产）。

### 3.1 已落地的自动门禁（2026-09-14，含 blocking 属性）

| 触发 | 门禁 | 属性 | 实现 |
|---|---|---|---|
| PR（任意） | 三模块单测 / QA Growth Gate / ci-helper / gitleaks / Danger Scan | ★ **required（硬拦合并）** | pr-check 等 |
| PR（AI 行为文件） | C 端 smoke（persona=xiaobu，独立栈）+ B 端 smoke（云测试环境） | 信息性（**不阻塞**） | `xiaobu-acceptance.yml`（pull_request + paths）/ pr-check |
| PR（AI 行为文件） | **映射用例**（diff → §13.2 用例集，独立栈 + PR 评论 + 规则命中失败自动开 issue）——**分层**：规则命中失败 → **强信号**（报告 + 评论 + issue，**不拦合并**）；兜底默认集失败 → **只报告**（评论标"无因果"，**不开 issue**） | **均为信息性**（报告 + 评论 + issue） | `agent-behavior-eval.yml`（#3502/#3523/#3563） |
| 部署（ai-agent 成功） | **双 persona 矩阵并行全量**（各自独立栈/全新库）→ completion_verdict 判定 → 失败去重建 issue | 部署后拦截 | `post-deploy-eval.yml`（#3503/#3515） |
| 每周六 | adversarial 档 | 信息性 | `xiaobu-acceptance.yml`（schedule） |
| 里程碑 / 下结论 | 结论档（全量 + 验收剧本 + 双裁判 + completion_verdict） | **结论前置（必过）** | 协议 v1.3 §1.6/§1.7 |

> **⚠️ 最容易误读**：required 只有确定性层那 9 项——LLM 行为层**有意不进 required**
> （真实 LLM 方差会卡死合并流水线；job 名随 persona 参数化也不适合）。
> ⇒ 「C 端 smoke 红 ≠ 不能合并」，它是强信号；硬拦截由确定性层 + 部署后全量承担。

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

### 3.3 决策记录：规则命中**不再阻塞**，降为「报告 + PR 评论 + 自动开 issue」（2026-09-14 用户确认）

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

### 3.4 评测类 workflow 统一并发槽位：`eval-stack-global`（2026-09-14 用户确认）

- **背景（实测，2026-09-14 05:28Z）**：13 个 in-progress 里 **6 条是评测型 job**
  （`Xiaobu Acceptance` ×5 + `Agent Behavior Eval` ×1，各自一套 docker 栈 + 真实 LLM），
  queued 60 个 run —— 其中一个 PR 的 **required** 检查（admin-api unit tests）也在队列里，
  **9 个 PR 全部 BLOCKED**。⇒ 不是队列深，是**并发预算被 PR 层评测吃光，required 被饿死**。
- **决策**：**评测类 workflow 统一加入 `eval-stack-global` 槽位**
  （`.github/workflows/{xiaobu-acceptance,agent-behavior-eval,post-deploy-eval}.yml`
  的 `concurrency.group` 同名，`cancel-in-progress: false`）。这条是**三处一致的单一说明**。
- **为什么排队而不 cancel 正在跑的那条**：评测 job 的产物就是结论本身，cancel 掉正在跑的
  一条 = 那个 PR 永远拿不到该信号（活锁；`post-deploy-eval.yml` 里 #3526 的既有论证同源）。
- **⚠️ 必须知道的语义副作用（有意取舍）**：GitHub concurrency 是「一个 group 同时
  **1 running + 1 pending**」，新 run 进入一个**已有 pending** 的 group 时，**旧的 pending
  会被取消** —— 突发期多数 PR 拿到的是 `cancelled` 而**不是**"排队后跑"。
  - 这两条评测是**信息性**（§16.5）：被取消**不阻塞合并**（PR 仍按 required 合并）；
  - 行为信号**延后到部署后全量轮**（`post-deploy-eval` 双 persona 全量）承担 ——
    与 §16.2「全量复测降频」、§16.5 门禁矩阵一致；
  - **诚实边界**：单槽位保的是"**最新的评测 run** 会跑"，不是"**每个 PR** 都拿到行为信号"。
    要"每 PR 都有信号"需要分离 runner 池（超出仓库范围，本轮不选）。
- **可观测性（防误读）**：两个 workflow 都在**抢槽位之前**把槽位语义写进
  `$GITHUB_STEP_SUMMARY` 并打印到日志 —— 让人从 UI 就能区分
  「**排队**」（评测单条 5~15min，正常）与「**被取代而取消**」（不代表代码有问题），
  不再把排队/取消误判成"CI 卡住"或"这个 PR 有问题"。

## 四、与米高研发模式的衔接

- 档位纪律 / 全量降频 / 完成定义 / **门禁矩阵（含量化 blocking 属性）**：`migao-dev-flow` §16（§16.5）；
- **并行修复原则（发现即并行，合并串行）**：仓库 `AGENTS.md` 铁律 6 + `migao-dev-flow` §17；
- **用例编写陷阱**（卡回放/答卡/自包含化 7 条实证坑）：`migao-dev-flow` §13.5；
- 结论档协议（L1/L2/UA + 双裁判 + 证据链）：`migao-acceptance` + `docs/testing/acceptance-protocol.md` v1.3；
- 提交前/迭代中体检：§13（行为改动映射用例）、§13.3（bug 沉淀有效性验证）；
- 三把工具（verify-all / check-ui-regression / contract-check）保证"不崩、契约对"，
  本文档与 §16/§17 保证"评测在正确的环境、用正确的档位、以可判定的标准下结论，且修复并行不串行"。
