# 二郎神 (Erlang Shen) — Quality Loop Engineering 设计方案

> 版本 v6.0 | 2026-06-21 | 米高项目 (migao)
>
> **原则**: AI First — LLM 收益 > 机械操作时用 AI，机械更快更省时用 CI/脚本。
> **机械层** (CI + crontab) 做闹钟和手臂，**LLM 层** (Claude Code + OpenClaw) 做大脑和手。

## 目录

| # | 文档 | 内容 |
|---|------|------|
| 1 | [架构总览](01-architecture.md) | 整体架构、组件拓扑、数据流、设计原则 |
| 2 | [角色体系](02-roles.md) | 军师/dev-agent/verify-agent/OpenClaw/CI — 分工与协作契约 |
| 3 | [CI 工作流](03-ci-workflows.md) | 13 个 GitHub Actions workflow 的触发条件、输入输出、标签操作 |
| 4 | [执行脚本](04-scripts.md) | agent-poll.sh / verify-poll.sh / agent-setup.sh / heartbeat.sh 完整逻辑 |
| 5 | [定时任务](05-cron-jobs.md) | Linux crontab (2) + OpenClaw 原生 cron (7) — 调度矩阵 |
| 6 | [Agent Prompt](06-agent-prompts.md) | dev-agent.md / verify-agent.md — 指令结构、契约、铁律 |
| 7 | [信号与标签体系](07-signals-and-labels.md) | 18 个标签、5 种 JSN 信号、组件间通信协议 |
| 8 | [QA Growth Gate](08-qa-growth-gate.md) | 事前测试覆盖门禁 — 规则矩阵、豁免机制、自愈闭环 |
| 9 | [自愈机制](09-self-healing.md) | 熔断、超时跳过、死循环检测、权限修复、脏状态恢复 |
| 10 | [进化体系](10-evolution.md) | L2 模式反思、模板自修、learn 归档、覆盖率追踪 |
| 11 | [可观测性](11-observability.md) | 心跳、健康指标、日志、告警、日报 |
| 12 | [部署指南](12-setup-guide.md) | 从零搭建军师服务器的完整步骤 |
| 13 | [与 Loop Engineering 对比](13-loop-engineering-comparison.md) | 设计理念、角色模型、质量闭环、自愈能力对比 |

## 快速导航

- **故障排查** → [自愈机制](09-self-healing.md) + [可观测性](11-observability.md)
- **新增 CI 检查** → [CI 工作流](03-ci-workflows.md) + [QA Growth Gate](08-qa-growth-gate.md)
- **Agent 行为异常** → [角色体系](02-roles.md) + [Agent Prompt](06-agent-prompts.md)
- **初始化服务器** → [部署指南](12-setup-guide.md)

## 核心闭环

```
Issue 创建
  → CI: contract-check → needs-truths
  → 用户补真值 → needs-verification
  → CI: case-draft → needs-draft
  → agent-poll → dev-agent 生成 DRAFT_JSON
  → 用户 review (accept/supplement/reject)
  → agent-poll → dev-agent TDD 写码 → 开 PR
  → CI: PR Check (单测/typecheck/Growth Gate/E2E)
  → CI fail → auto-label needs-changes → agent-poll 修复
  → CI pass → 军师 automerge → merge
  → CI: verify-trigger → ai-verify/pending
  → verify-poll → verify-agent 验收 → close/hold/block
```
