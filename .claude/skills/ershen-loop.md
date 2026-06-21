# 二郎神速查卡 — 军师操作手册

> 本文档是 `ershen/handbook.md` 的派生速查版。主权威在 handbook。
> 日常操作看这里，完整设计看 handbook。

## 调度体系（三层兜底）

```
OpenClaw cron (主) → 每5min casedraft / 每10min verify-trigger/automerge / 每日报告
GitHub Actions (事件即时) → issue open → 立即跑 case_draft
Linux crontab (Agent轮询) → */5 agent-poll + verify-poll
```

## 常用命令

```bash
# Cron 管理
openclaw cron list                          # 查看全部
openclaw cron run <id>                      # 手动触发
openclaw cron runs --id <id> --limit 5      # 运行历史

# Case Draft
python3 scripts/dual_verify/case_draft.py <issue_number>
python3 scripts/dual_verify/case_draft.py <issue_number> --dry-run

# 质量报告
python3 scripts/dual_verify/quality_report.py --days 7
```

## 生命周期速查

```
Issue (CONTRACT_JSON + needs-verification)
  → 军师 case_draft → DRAFT_JSON
  → Agent 抢 → REVIEW_JSON → TDD → PR (Fixes #xxx)
  → CI 全绿 → 军师 automerge
  → Deploy → VERIFY_TRIGGER
  → verify-agent → close/block/hold
```

## 关键文件

| 文件 | 用途 |
|------|------|
| `ershen/handbook.md` | 主权威 doc |
| `ershen/contracts/AI-Contracts.md` | 契约格式 + 标签状态机 |
| `scripts/dual_verify/case_draft.py` | Case 反推 |
| `scripts/dual_verify/quality_report.py` | 质量报告 |
| `.github/workflows/junshi-case-draft.yml` | GA 即时 draft |
| `.github/workflows/junshi-verify-trigger.yml` | GA 即时 verify |

## 标签速查

| 标签 | 含义 |
|------|------|
| `needs-verification` | 等军师出 case / Agent 开发 |
| `ai-verify/pending` | 验收进行中 |
| `verified/auto` | 验收通过 |
| `block/dual-mismatch` | 验收不一致 |
| `block/need-human` | 熔断需人工 |
