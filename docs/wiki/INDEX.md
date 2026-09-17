# Wiki 索引

LLM 开发时按需加载对应页面 (~50 行/页，按场景索引)：

| 场景 | 先读 |
|------|------|
| 不了解项目整体 | [Home](Home.md) |
| 首次搭建/运行 | [Quick-Start](Quick-Start.md) |
| 写代码前确认规范 | [Development](Development.md) |
| **写码最少化（防过度建设/加依赖前）** | **[Code-Minimalism](Code-Minimalism.md)** |
| **并行开发/契约一致性** | **[CONTRACT-LEDGER](CONTRACT-LEDGER.md)** + **[DEV-FLOW](DEV-FLOW.md)** |
| 改前端/小程序 | [Frontend](Frontend.md) |
| 改 AI 服务/Tool/Skill | [AI-Agent](AI-Agent.md) |
| **Skill/Tool 设计范式** | **[Agent-Design-Standard](agent-design-standard.md)** |
| 改架构/数据模型/路由 | [Architecture](Architecture.md) |
| 改数据库/查表结构 | [Database](Database.md) |
| 改权限/认证 | [RBAC](RBAC.md) |
| 部署/CI/CD/环境变量 | [Deployment](Deployment.md) |
| **合规/AI客服新国标 GB/T 47746-2026** | **[gb47746-2026-compliance](gb47746-2026-compliance.md)** |
| **可观测性/监控/ARMS 接入** | **[Observability](Observability.md)** |
| **陈旧快照/移动靶的判定与处置（真相源契约）** | **[truth-source-contract](truth-source-contract.md)**（统一审计入口 `python3 scripts/drift_audit.py`） |
| CI/CD 流水线详情 | [CI-CD](CI-CD.md) |
| 写测试/了解测试体系 | [Testing](Testing.md) |
| **测试工程规范（拆分/ignore/脱敏/分层）** | **[test-engineering-standards](../testing/test-engineering-standards.md)** |
| **复杂交互验证机制（三层：契约/协议流/行为）** | **[interaction-verification](../testing/interaction-verification.md)** |
| **AI 可执行验收协议（验收/评测放心交给 AI）** | **[acceptance-protocol](../testing/acceptance-protocol.md)** |
| **评测环境分工与门禁（标准考场/云测试/生产三层）** | **[eval-environments](../testing/eval-environments.md)** |
| **评测流水线性能账（为什么慢/怎么快，实测 + 反模式 + 思考开关真伪）** | **[eval-pipeline-performance](../testing/eval-pipeline-performance.md)** |
| **LLM 发现 → 确定性下沉（红例必须落成确定性断言；台账 + 机械检查）** | **[llm-finding-sinking](../testing/llm-finding-sinking.md)** |
| **C 端对抗评测基线与反模式（B 端形状断言为何误判）** | **[xiaobu-adversarial-baseline](../testing/xiaobu-adversarial-baseline.md)** |
| **检查功能自洽性（闭环谓词 P0/P1/P2）** | **[self-consistency-checklist](self-consistency-checklist.md)** |
| 遇到问题 | [Troubleshooting](Troubleshooting.md) |

## 深入阅读

Wiki 页面是摘要，详细文档在：

| 域 | 详细文档路径 |
|----|------------|
| 架构 | [docs/wiki/Architecture.md](Architecture.md)（当前事实） |
| 部署 | [docs/deployment/swas-migration-lessons.md](../deployment/swas-migration-lessons.md)（SWAS 踩坑）· [deployment-checklist.md](../deployment/deployment-checklist.md) |
| API | [docs/api/api-reference.md](../api/api-reference.md) |
| SQL | [docs/sql/schema.sql](../sql/schema.sql) |
