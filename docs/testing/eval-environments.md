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

## 四、与米高研发模式的衔接

- 档位纪律 / 全量降频 / 完成定义 / **门禁矩阵（含量化 blocking 属性）**：`migao-dev-flow` §16（§16.5）；
- **并行修复原则（发现即并行，合并串行）**：仓库 `AGENTS.md` 铁律 6 + `migao-dev-flow` §17；
- **用例编写陷阱**（卡回放/答卡/自包含化 7 条实证坑）：`migao-dev-flow` §13.5；
- 结论档协议（L1/L2/UA + 双裁判 + 证据链）：`migao-acceptance` + `docs/testing/acceptance-protocol.md` v1.3；
- 提交前/迭代中体检：§13（行为改动映射用例）、§13.3（bug 沉淀有效性验证）；
- 三把工具（verify-all / check-ui-regression / contract-check）保证"不崩、契约对"，
  本文档与 §16/§17 保证"评测在正确的环境、用正确的档位、以可判定的标准下结论，且修复并行不串行"。
