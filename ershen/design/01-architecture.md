# 01 — 架构总览

## 设计原则

```
机械层 (CI + crontab)            LLM 层 (Claude Code + OpenClaw)
─────────────────────────       ─────────────────────────────
确定性操作：标签、模板评论、      理解和判断：DRAFT生成、Review、
git、语法检查、心跳告警           TDD写码、验收判定、模式反思

CI 做闹钟（事件驱动，瞬时）        LLM 做大脑（理解上下文，推理）
bash 做手臂（机械执行）            Agent 做手（写码+验收）
```

**铁律**：LLM 收益 > 机械才用 AI。标签操作、模板评论、git 同步等纯机械操作由 CI/脚本完成。

## 三层架构

```
┌──────────────────────────────────────────────────────────┐
│                    OpenClaw (军师调度层)                    │
│  7 个原生 cron: automerge / stale-watch / pattern-reflect │
│              / daily-report / health-check / ...          │
│              决策：merge / 巡检 / 模式反思                  │
└──────────────┬───────────────────────────────┬────────────┘
               │                               │
          gh CLI 操作                      cron prompt
               │                               │
┌──────────────▼───────────┐    ┌──────────────▼────────────┐
│   GitHub Actions (CI 层)  │    │   Linux crontab (工人层)    │
│                           │    │                            │
│  事件驱动 (瞬时响应):       │    │  轮询驱动 (每 5 分钟):       │
│  • pr-check               │    │  • agent-poll.sh           │
│  • e2e-web                │    │  • verify-poll.sh          │
│  • junshi/verify-trigger  │    │                            │
│  • junshi/case-draft      │    │  调用 Claude Code Agent:    │
│  • junshi/redraft         │    │  • dev-agent (写码)         │
│  • issue-contract-check   │    │  • verify-agent (验收)      │
│  • smoke-test             │    │                            │
│  • deploy-*               │    │                            │
└──────────┬────────────────┘    └──────────────┬─────────────┘
           │                                    │
           │  gh issue/pr 操作                   │ gh + claude CLI
           │                                    │
┌──────────▼────────────────────────────────────▼────────────┐
│                    GitHub (数据层 + 协作层)                   │
│  Issues / PRs / Labels / Comments / Actions / Projects      │
└─────────────────────────────────────────────────────────────┘
```

## 组件拓扑

```
                      ┌─────────────┐
                      │   GitHub     │
                      │  Issue/PR    │
                      └──────┬──────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
   ┌────▼─────┐       ┌──────▼──────┐      ┌─────▼──────┐
   │  CI (13个) │       │ agent-poll  │      │ verify-poll │
   │ 事件驱动   │       │  每 5min    │      │  每 5min    │
   └────┬─────┘       └──────┬──────┘      └─────┬──────┘
        │                    │                    │
        │ 标签/评论           │ claude --agent     │ claude --agent
        │                    │ dev-agent          │ verify-agent
        │               ┌────▼─────┐        ┌─────▼──────┐
        │               │ dev-agent │        │verify-agent│
        │               │  写码+TDD  │        │ 验收判定    │
        │               └──────────┘        └────────────┘
        │
   ┌────▼─────────────────────────────────────────────┐
   │              OpenClaw (军师)                        │
   │  automerge / stale-watch / pattern-reflect /       │
   │  daily-report / health-check / ...                 │
   └──────────────────────────────────────────────────┘
```

## 数据流

```
Issue 创建
  │
  ├─→ contract-check (CI)     → 缺真值? → needs-truths
  ├─→ case-draft (CI)         → 有真值? → needs-draft
  │
  ├─→ agent-poll 扫描 needs-draft
  │     └─→ dev-agent 生成 DRAFT_JSON → comment on issue
  │
  ├─→ 用户 review (accept/supplement/reject)
  │     └─→ redraft (CI) → needs-draft (重新 draft)
  │
  ├─→ agent-poll 扫描 needs-draft (accept 后)
  │     └─→ dev-agent TDD 写码 → git push → 开 PR
  │
  ├─→ PR Check (CI): 单测 + typecheck + Growth Gate + E2E
  │     ├─→ fail → auto-label needs-changes
  │     │         └─→ agent-poll 扫描 → dev-agent 修复
  │     └─→ pass → 军师 automerge
  │
  ├─→ verify-trigger (CI) → VERIFY_TRIGGER comment + ai-verify/pending
  │
  └─→ verify-poll 扫描 ai-verify/pending
        └─→ verify-agent 验收 → VERDICT_JSON
              ├─→ 1.0 → close + verified/auto
              ├─→ ≥0.8 → hold → ai-verify/hold
              └─→ <0.8 → block → block/dual-mismatch
```

## 服务器布局

```
/opt/youke/              ← migao 项目代码 (git 仓库, main 分支)
/opt/junshi/             ← 军师工作区 (prompts/ metrics/ archive.py)
/opt/junshi/prompts/     ← OpenClaw cron prompt 文件
/opt/qa-results/         ← 验收结果 ({issue_id}/verdict.json)
/var/log/migao-*.log     ← Agent/军师运行日志
/opt/openclaw/           ← OpenClaw gateway 安装目录
/tmp/migao-*.lock        ← 锁文件 (agent + verify)
/tmp/migao-agent-health.json ← 健康指标
```

## 权限模型

| 层级 | 用户 | 权限 |
|------|------|------|
| repo 文件 | `admin:admin` | rw |
| crontab | `root` | 以 root 执行脚本 |
| gh CLI | `root` (token: zhaokai-mgzn) | repo + workflow + project |
| .git/refs/heads/feat/ | `admin:admin` | rw (不能被 root 独占) |
