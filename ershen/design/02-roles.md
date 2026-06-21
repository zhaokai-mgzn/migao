# 02 — 角色体系

二郎神体系定义了 5 个角色，每个角色有明确的职责边界和交互契约。

## 角色矩阵

| 角色 | 实体 | 触发方式 | 职责 | 禁止 |
|------|------|---------|------|------|
| **军师** | OpenClaw gateway | cron (7 个) | merge 决策、巡检、日报、模式反思(L2/L3) | 不写代码不跑测试 |
| **研发 Agent** | Claude Code (`dev-agent`) | agent-poll.sh 信号扫描 | DRAFT 生成、Phase 1 Review、TDD 写码 | 不验收自己的代码 |
| **验收 Agent** | Claude Code (`verify-agent`) | verify-poll.sh 信号扫描 | 独立验收 (curl + psql + check_assert) | 不写代码 |
| **调度工人** | agent-poll.sh / verify-poll.sh | Linux crontab 每 5min | 扫描信号 → 调用 Agent → 处理结果 | 不做决策 |
| **CI** | GitHub Actions | 事件驱动 (issue/PR) | 标签触发、VERIFY_TRIGGER、语法检查、PR 质量门禁 | 不做理解和判断 |

## 交互契约

所有角色间通信通过 GitHub Issue/PR 的评论和标签完成，详见 [`contracts/AI-Contracts.md`](../contracts/AI-Contracts.md)。

### 7 种交互契约

| 契约 | 触发方 | 目标 | 信号格式 | 响应 |
|------|--------|------|---------|------|
| CONTRACT_JSON | 用户/CI | dev-agent | issue body 中 `<!-- CONTRACT_JSON {...} -->` | DRAFT 生成 |
| DRAFT_JSON | dev-agent | 用户/verify-agent | comment 中 `<!-- DRAFT_JSON {...} -->` | 人工 review |
| REVIEW_JSON | 用户 | dev-agent | comment 中 `<!-- REVIEW_JSON {action,issues} -->` | accept→写码 / reject→重 draft |
| VERIFY_TRIGGER | CI (verify-trigger.yml) | verify-agent | comment + `ai-verify/pending` 标签 | 验收执行 |
| VERDICT_JSON | verify-agent | 军师/用户 | comment + close/edit | close/hold/block |
| BLOCK_LOG | agent-poll | 军师 | issue comment | 模式反思 |
| COMMENT_JSON | agent-poll | 军师 | issue comment `intent=clarification` | 人工介入 |

## 军师 (Junshi / OpenClaw Gateway)

**身份**: LLM 原生调度器，通过 OpenClaw 平台的 7 个 cron prompt 运行。

**7 个 cron 任务**:
| # | Job | Schedule | 职责 |
|---|-----|----------|------|
| 1 | `junshi-automerge` | 每 10min | auto-merge + 健康巡检 |
| 2 | `junshi-stale-watch` | 每 30min | 巡检 stale issue (>3天无进展) |
| 3 | `junshi-pattern-reflect` | 每天 2:00 | REJECT/HOLD 聚类分析，模板自修 |
| 4 | `junshi-daily-report` | 每天 9:00 | 日报生成 |
| 5 | `junshi-health-check` | 每 15min | Agent 心跳监控 |
| 6 | `junshi-coverage-track` | 每天 6:00 | 覆盖率追踪，qa-growth 子 issue |
| 7 | `junshi-learn-archive` | 每周日 3:00 | learn 归档 |

**军师 automege 判定标准**:
- ✅ CI 全绿
- ✅ 有 `Fixes/Closes #xxx`
- ✅ 无敏感文件
- ✅ 无前端/Controller 变更（或 E2E spec 存在）
- → auto-merge (squash)

**军师不可控项**: Git push approval、Review required（需人工 approve）。

## 研发 Agent (dev-agent)

**指令文件**: `.claude/agents/dev-agent.md`

**工作流程**:
```
Phase 1: Review (硬 gate — 不过不写码)
  1. 读 CONTRACT_JSON → 业务真值
  2. 读 DRAFT_JSON → L2/L3/L4 case 草稿
  3. 逐条比对: 真值 → case 覆盖
  4. 判定: accept / reject / supplement

Phase 2: TDD 写码
  严格遵守 CLAUDE.md + tdd-iron-law.md CP-1~CP-7
  测试先行 → 全量单测 → 增量集测 → E2E → 自检

Phase 3: 开 PR
  分支由 agent-poll 创建
  PR body 含测试结果 + Closes #xxx
```

**处理信号**:
| 信号 | 来源 | 动作 |
|------|------|------|
| `needs-draft` | CI (case-draft) | 生成 DRAFT_JSON |
| `needs-draft` + REJECT | CI (redraft) | 读 REJECT 原因 → 重新 draft |
| 已 accept 的 issue | agent-poll | TDD 写码 → 开 PR |
| `junshi-review/needs-changes` | CI (PR Check) | 读 CI 失败原因 → 修复 → push |

**硬约束**:
- 禁止跳过 TDD 检查点
- 禁止自己 merge PR
- 禁止手写 E2E mock (用 Record-Replay)
- 超时 30min
- 熔断: `block_depth >= 3`
- Token 控制: ≤200k/issue

## 验收 Agent (verify-agent)

**指令文件**: `.claude/agents/verify-agent.md`

**工作流程**:
```
1. gh issue view → 提取 business_truths
2. 逐条执行:
   - api 类 → curl | check_assert
   - db 类 → psql | check_assert
   - e2e 类 → vitest run (不靠 ls)
3. 每条输出 check_assert JSON trace
4. 置信度 = passed / total
5. 判定: 1.0→close, ≥0.8→hold, <0.8→block
6. 贴 VERDICT_JSON
```

**独立验收三原则**:
1. verify-agent 不知道自己怎么写代码的（与 dev-agent 完全隔离）
2. check_assert 说 fail 就是 fail（LLM 不判断 pass/fail）
3. 弱断言降级：全 status/error.code 无业务数据 → 自动 fail

## 调度工人

### agent-poll.sh
- **触发**: Linux crontab `*/5 * * * *`
- **扫描**: `needs-draft` issue / `junshi-review/needs-changes` PR
- **执行**: 调用 `claude --agent dev-agent`
- **自愈**: ERR trap 捕获崩溃 + 健康指标写入 + 熔断检测
- **文件**: `scripts/agent-poll.sh` (214 行)

### verify-poll.sh  
- **触发**: Linux crontab `*/5 * * * *`
- **扫描**: `ai-verify/pending` issue (open + closed)
- **执行**: 启动服务 → `claude --agent verify-agent` → 停止服务
- **保护**: 死循环检测 (3+ HOLD) / 超时跳过 (7天无 VERDICT)
- **文件**: `scripts/verify-poll.sh` (169 行)

## CI (GitHub Actions)

13 个 workflow，全是事件驱动。详见 [03-ci-workflows.md](03-ci-workflows.md)。

**核心 CI**:
- `pr-check.yml` — 5 个 job: .env 检查 + admin-api 单测 + admin-web 单测 + QA Growth Gate + E2E Web
- `junshi/verify-trigger` — PR merge → 贴 VERIFY_TRIGGER
- `junshi/case-draft` — issue label → needs-draft
- `issue-contract-check` — issue open → 检查 CONTRACT_JSON
