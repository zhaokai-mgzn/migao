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
| PR（AI 行为文件） | **映射用例**（diff → §13.2 用例集，独立栈 + PR 评论）——**分层**：规则命中失败→**阻塞**；兜底默认集失败→**只报告**（评论标"无因果"） | 规则桶阻塞 / 兜底网信息性 | `agent-behavior-eval.yml`（#3502/#3523） |
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
| `agent-behavior-eval.yml` | ⏳ 待改（另包） | 第 58-60 行：`group:` 从 `agent-behavior-eval-${{ github.event.pull_request.number \|\| github.ref }}` 改为 `eval-stack-global`；`cancel-in-progress: true` **保持不变** | 同 PR 新 push 仍即时取消旧 run（省栈省 token）；**跨 PR** 不再并发建栈，改为排队 |
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

### 3.4 抑制「已被取代的 run」（#3587）：门禁不因抑制而消失

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
- **手动逃生口**：`workflow_dispatch` 的 `force_eval=true` 可强制评测（回滚复验/补跑特定部署）。

## 四、与米高研发模式的衔接

- 档位纪律 / 全量降频 / 完成定义 / **门禁矩阵（含量化 blocking 属性）**：`migao-dev-flow` §16（§16.5）；
- **并行修复原则（发现即并行，合并串行）**：仓库 `AGENTS.md` 铁律 6 + `migao-dev-flow` §17；
- **用例编写陷阱**（卡回放/答卡/自包含化 7 条实证坑）：`migao-dev-flow` §13.5；
- 结论档协议（L1/L2/UA + 双裁判 + 证据链）：`migao-acceptance` + `docs/testing/acceptance-protocol.md` v1.3；
- 提交前/迭代中体检：§13（行为改动映射用例）、§13.3（bug 沉淀有效性验证）；
- 三把工具（verify-all / check-ui-regression / contract-check）保证"不崩、契约对"，
  本文档与 §16/§17 保证"评测在正确的环境、用正确的档位、以可判定的标准下结论，且修复并行不串行"。
