# 13 — 与 Loop Engineering 对比

二郎神体系与 Anthropic 提出的 Loop Engineering 范式在设计理念、角色模型、质量闭环、自愈能力 4 个维度上高度对齐，并有独特的工程实践。

## Loop Engineering 核心概念

> *"Build systems where AI agents continuously improve code through tight feedback loops of writing, testing, reviewing, and deploying — with humans in the loop for strategic decisions."*

## 4 维度对比

### 1. 设计理念

| 维度 | Loop Engineering | 二郎神 v6.0 |
|------|-----------------|------------|
| 核心理念 | AI agents in tight feedback loops | AI First — LLM 做大脑，CI 做闹钟，bash 做手臂 |
| 人类角色 | Strategic decisions, gate reviews | 填业务真值、review DRAFT、批准 merge |
| AI 角色 | Code generation + testing | 全链路: DRAFT 生成 → Review → TDD 写码 → 验收 |
| 反馈速度 | Continuous (CI-driven) | 事件驱动 (CI) + 轮询驱动 (crontab 5min) |
| 自愈能力 | Agent retries on failure | 8 种自愈 + 3 层进化 (L1/L2/L3) |

### 2. 角色模型

| Loop Engineering | 二郎神 |
|-----------------|--------|
| Developer Agent | **dev-agent** — TDD 写码 + Phase 1 Review |
| Reviewer Agent | **军师 (OpenClaw)** — merge 决策 + 模式反思 |
| Test Agent | — (CI + QA Growth Gate 替代) |
| QA/Verification Agent | **verify-agent** — 独立验收 |
| Orchestrator | **agent-poll.sh / verify-poll.sh** — 信号扫描 + 调度 |
| Human-in-the-loop | 用户 (填真值 / review DRAFT / approve) |

### 3. 质量闭环

| 阶段 | Loop Engineering | 二郎神 |
|------|-----------------|--------|
| Issue → Spec | Agent generates spec | 军师反推 case 草稿 (DRAFT_JSON) → 用户 review |
| Spec → Code | Agent + TDD | dev-agent Phase 2 TDD (CP-1~CP-7) |
| Code → Test | Agent writes tests first | 强制测试先行 (tdd-iron-law.md) |
| Test → Review | Automated + Human | 军师 automerge (4 项检查) + 人工 approve |
| Review → Deploy | CI/CD pipeline | GitHub Actions deploy-* workflows |
| Deploy → Verify | Agent verifies in production | verify-agent 独立验收 (curl + psql + check_assert) |
| Verify → Learn | Pattern analysis | L2 pattern-reflect 聚类 → 模板自修 |

### 4. 自愈与进化

| 能力 | Loop Engineering | 二郎神 |
|------|-----------------|--------|
| CI 失败自动修复 | Agent re-runs | needs-changes → dev-agent 自动修复 + push |
| 死循环检测 | — | verify-poll 3× HOLD → block/need-human |
| 熔断保护 | — | needs-changes 3 次 → 熔断 |
| 超时跳过 | — | VERIFY_TRIGGER 7 天无 VERDICT → skip |
| 模式反思 | — | pattern-reflect 每天聚类 → 自动修模板 |
| 覆盖率追踪 | — | coverage-track 每日 → 创建 qa-growth 子 issue |
| 权限自愈 | — | 巡检检测 feat/ refs root 独占 → chown |
| 脏状态恢复 | — | agent-poll 启动时 git reset --hard + clean -fd |

## 二郎神的独特贡献

### 1. 机械/LLM 分层
Loop Engineering 倾向于让 Agent 做所有事。二郎神明确划分：
- **机械操作** (标签、git、语法检查) → CI/脚本
- **需要理解** (DRAFT、Review、修复决策、验收判定) → LLM Agent

**收益**: 减少 LLM token 消耗，提高确定性操作的可靠性。

### 2. 信号-标签解耦通信
通过 GitHub Labels + JSN Comments 实现纯异步、可审计的组件通信：
- 任何组件可独立运行、崩溃、恢复
- 信号持久化在 Issue/PR 上，不丢消息
- OpenClaw / agent-poll / verify-poll 完全解耦

### 3. 双独立证据原则
- dev-agent 和 verify-agent **完全隔离**
- verify-agent 不知道代码怎么写的
- check_assert 是唯一判定层 (LLM 不判断 pass/fail)
- 双不一致 → block

### 4. 进化金字塔 (L1→L2→L3)
- L1: 即时自愈 (5 分钟级)
- L2: 模式反思 (每天级)
- L3: 结构演进 (每周级)

### 5. 覆盖率驱动的质量生长
QA Growth Gate 不仅是门禁，更是**生长系统**:
- 缺测 → 自动标记 → Agent 补测
- 覆盖率追踪 → 拆分子任务 → 渐进补全
- 从 0% 到 60% 的可追踪路径

## 对齐度评估

| 维度 | 对齐度 | 说明 |
|------|--------|------|
| Tight feedback loops | ⭐⭐⭐⭐⭐ | CI 事件 + crontab 5min 双驱动 |
| AI agents writing code | ⭐⭐⭐⭐⭐ | dev-agent 全流程 TDD |
| Automated testing | ⭐⭐⭐⭐ | QA Growth Gate + E2E + 单测 |
| Human in the loop | ⭐⭐⭐⭐ | 真值填写 + DRAFT review + merge approve |
| Continuous improvement | ⭐⭐⭐⭐⭐ | L1/L2/L3 三层进化 |
| Observability | ⭐⭐⭐⭐ | 健康指标 + 心跳 + 日报 + 巡检 |

## 仍待补强

1. **E2E 规模化**: 当前 314 个 E2E 测试运行 >4min，需选择性运行
2. **Agent 间直接通信**: 目前完全通过 GitHub 异步通信，无实时协作
3. **多租户隔离**: 当前只支持单租户 (tenant_id=1) 验收
4. **回滚自动化**: CI 失败后缺少自动 revert 机制
