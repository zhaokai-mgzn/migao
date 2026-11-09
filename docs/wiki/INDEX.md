# Wiki 索引

> 本仓 = **观星台 —— 布艺行业 AI 经营平台**。读法：先按「你要做什么」选入口；产品定位先读 [Home](Home.md) → [Product](Product.md)。
> 本页只做索引，正文在各自页面。易变现值（工具数 / 版本 / 表数 / workflow 数）一律现取，不抄数（issue #5082）。

## 1. 产品与架构

| 场景 | 先读 |
|------|------|
| 不了解项目整体 | [Home](Home.md) |
| **产品定位 / 四端 / 能力地图 / 能力边界** | **[Product](Product.md)** |
| 系统拓扑 / 多租户 / 数据模型 / AI 链路 | [Architecture](Architecture.md) |
| 四个前端包与路由 | [Frontend](Frontend.md) |
| AI 服务 / 工具 / Skill / 知识检索 | [AI-Agent](AI-Agent.md) |
| **Skill / Tool 设计范式** | **[agent-design-standard](agent-design-standard.md)** |
| **Agent 能力研发范式（声明=投影 / 元守卫 / 现实快照）** | **[agent-capability-paradigm](agent-capability-paradigm.md)** |
| **B 端 Agent 写操作边界（去留清单 / 补回前提）** | **[agent-write-boundary](agent-write-boundary.md)** |
| **B 端 Agent 功能设计（能力地图 / 判据来源）** | **[agent-feature-design](../agent-feature-design.md)** |
| 数据库 / 建库脚本 / 迁移 | [Database](Database.md) |
| 权限 / 认证 | [RBAC](RBAC.md) |
| **算料 / 计价规则真值源** | **[curtain-fabric-quote-rules](../curtain-fabric-quote-rules.md)**（`curtain_calc` 的公式与常量；漂移守卫 `tests/unit_ci_workflows/test_prose_constant_drift_guard.py`） |
| **生产 / 工序术语真值源** | **[curtain-production-process-standard](../curtain-production-process-standard.md)** · [curtain-production-rules](../curtain-production-rules.md) |

## 2. 研发与质量

| 场景 | 先读 |
|------|------|
| 首次搭建 / 本地运行 | [Quick-Start](Quick-Start.md) |
| 写代码前确认规范 | [Development](Development.md) |
| **改了某个面 ⇒ 还该跑哪几条具名判据** | **[Change-Blast-Radius](Change-Blast-Radius.md)** |
| **写码最少化（防过度建设 / 加依赖前）** | **[Code-Minimalism](Code-Minimalism.md)** |
| **加表 / 加列 / 加 JSONB 前（防 ERP 化）** | **[Domain-Modeling](Domain-Modeling.md)** |
| **并行开发 / 契约一致性** | **[CONTRACT-LEDGER](CONTRACT-LEDGER.md)** + **[DEV-FLOW](DEV-FLOW.md)** |
| 测试体系 | [Testing](Testing.md) |
| **测试工程规范（拆分 / ignore / 脱敏 / 分层）** | **[test-engineering-standards](../testing/test-engineering-standards.md)** |
| **冒烟数据质量（空态不得冒充绿 / 必须带 SKU / 清理自证）** | **[smoke-data-quality](../testing/smoke-data-quality.md)** |
| **查全库有没有「测试声明了不存在的用例 id」** | **[case-ids-dangling](../testing/case-ids-dangling.md)**（`python3 .github/case_ids_dangling.py`；报告面列全貌，基线面新增即红） |
| **AI 可执行验收协议（验收 / 评测结论前的必读）** | **[acceptance-protocol](../testing/acceptance-protocol.md)** |
| 评测环境分工 | [eval-environments](../testing/eval-environments.md) |
| 评测流水线性能账 | [eval-pipeline-performance](../testing/eval-pipeline-performance.md) |
| LLM 发现 → 确定性下沉 | [llm-finding-sinking](../testing/llm-finding-sinking.md) |
| C 端对抗评测基线 | [xiaobu-adversarial-baseline](../testing/xiaobu-adversarial-baseline.md) |
| **复杂交互验证机制（契约 / 协议流 / 行为）** | **[interaction-verification](../testing/interaction-verification.md)** |
| **检查功能自洽性（闭环谓词 P0/P1/P2）** | **[self-consistency-checklist](self-consistency-checklist.md)** |
| **真库 / 现场只读复核包** | **[production-readonly-verification-pack](../testing/production-readonly-verification-pack.md)** |
| **终端壳差异验收矩阵** | **[terminal-shell-capability-matrix](../testing/terminal-shell-capability-matrix.md)**（issue #8609） |

## 3. 运行与部署

| 场景 | 先读 |
|------|------|
| CI/CD 流水线 | [CI-CD](CI-CD.md) |
| 部署 / 环境变量 / 回滚 | [Deployment](Deployment.md) |
| 可观测性 / 监控 / ARMS | [Observability](Observability.md) |
| **合规 / AI 客服新国标 GB/T 47746-2026** | [gb47746-2026-compliance](gb47746-2026-compliance.md) |
| 遇到问题 | [Troubleshooting](Troubleshooting.md) |
| **生产最小可观测（5xx / 证书 / 发布失败）** | [observability-minimum](../deployment/observability-minimum.md) |
| TLS 证书续期 | [tls-renewal](../deployment/tls-renewal.md) |
| 终端发布与回滚 | [terminal-release](../deployment/terminal-release.md) |
| 微信扫码打开小程序 | [wechat-mini-program-qr](../deployment/wechat-mini-program-qr.md) |
| 试用客户上线 runbook | [trial-onboarding](../deployment/trial-onboarding.md) |

## 4. 专题台账与归档

| 场景 | 先读 |
|------|------|
| **陈旧快照 / 移动靶的判定（真相源契约）** | **[truth-source-contract](truth-source-contract.md)**（统一审计入口 `python3 scripts/drift_audit.py`） |
| **门禁豁免口子总账** | **[gate-exemption-ledger](gate-exemption-ledger.md)**（每个数字附复算命令） |
| 研发模式三维平衡（墙钟 / 质量 / token） | [Dev-Mode-Balance](Dev-Mode-Balance.md) |
| 审计归档（2026-09-17，冻结快照） | **已迁至私有仓 `migao-internal`** —— 迁出记录见 [internal-assets-migration](internal-assets-migration.md) |
| 上游框架出处（二郎神 / ershen，已删除） | [upstream-ershen-archive](upstream-ershen-archive.md) |
| 内部资产迁出公开仓 | [internal-assets-migration](internal-assets-migration.md) |
| API 参考 | [api-reference](../api/api-reference.md) |
| 建库脚本 | [schema.sql](../../backend/admin-api/src/main/resources/db/init/schema.sql)（唯一建库脚本；机制见 [Database](Database.md)） |
| 部署踩坑 / 检查单 | [swas-migration-lessons](../deployment/swas-migration-lessons.md) · [deployment-checklist](../deployment/deployment-checklist.md) |
