# 11 — 可观测性

## 监控矩阵

| 维度 | 指标 | 来源 | 告警方式 |
|------|------|------|---------|
| Agent 心跳 | `/var/log/migao-agent.log` 最后修改时间 | heartbeat.sh | cron 邮件 |
| Verify 心跳 | `/var/log/migao-verify.log` 最后修改时间 | heartbeat.sh | cron 邮件 |
| Agent 健康 | `/tmp/migao-agent-health.json` | agent-poll ERR trap | health-check |
| Agent 崩溃 | `exit: "crash"` in health.json | agent-poll | health-check |
| Agent 错误率 | `errors > 5` in health.json | agent-poll | health-check |
| 死循环 | HOLD×3 | verify-poll | block/need-human |
| 熔断 | needs-changes×3 | agent-poll | block/need-human |
| 超时检查 | VERIFY_TRIGGER >7天 | verify-poll | auto-skip + comment |
| 锁超时 | lock age >30min | agent/verify-poll | auto-clear |
| 服务不可达 | curl 8081 失败 | verify-poll | auto-start |

## 日志文件

| 文件 | 内容 | 轮转 |
|------|------|------|
| `/var/log/migao-agent.log` | agent-poll 运行日志 | 保留 30 天 |
| `/var/log/migao-verify.log` | verify-poll 运行日志 | 保留 30 天 |
| `/var/log/migao-agent-coding.log` | dev-agent 写码详细日志 | 保留 7 天 |
| `/var/log/migao-verify-agent.log` | verify-agent 验收详细日志 | 保留 7 天 |
| `/var/log/migao-admin-api.log` | admin-api 启动日志 | 保留 3 天 |
| `/var/log/migao-ai-agent.log` | ai-agent-service 启动日志 | 保留 3 天 |
| `/var/log/migao-admin-web.log` | admin-web 启动日志 | 保留 3 天 |

## 健康指标文件

`/tmp/migao-agent-health.json`:
```json
{
  "last_run": "2026-06-21T20:00:00+08:00",
  "exit": "ok|crash",
  "line": 115,
  "errors": 0,
  "duration_s": 12
}
```

## 告警规则

### heartbeat.sh (每 15min)

```bash
# Agent 心跳
AGENT_LOG_AGE=$(($(date +%s) - $(stat -c %Y /var/log/migao-agent.log)))
[ "$AGENT_LOG_AGE" -gt 900 ] && echo "⚠️ agent-poll 超过 15 分钟无输出"

# Verify 心跳
VERIFY_LOG_AGE=$(($(date +%s) - $(stat -c %Y /var/log/migao-verify.log)))
[ "$VERIFY_LOG_AGE" -gt 900 ] && echo "⚠️ verify-poll 超过 15 分钟无输出"
```

### health-check (OpenClaw, 每 15min)

读取 health.json → 检测 crash → 通知。

## 日报 (junshi-daily-report)

OpenClaw cron 每天 9:00，创建 `[二郎神日报 YYYY-MM-DD]` issue。

**内容**:
- 昨日验收统计: close N / hold N / block N
- Agent 运行时间 / 崩溃次数
- PR 合并数
- E2E 失败数
- 当前待处理队列

## 巡检

由 `junshi-automerge` (每 10min) 和 `junshi-stale-watch` (每 30min) 执行:

### automerge 巡检
- 扫描 open PR 的 CI 状态
- CI 失败 → 确认已打 needs-changes 标签
- 无 needs-changes 标签的失败 PR → 补打

### stale-watch 巡检
- needs-verification >5天 → escalate
- needs-draft >2天 → 重新触发
- ai-verify/pending >7天 → 判定异常
- issue 无任何更新 >3天 → 标记 stale

## 排查流程

```
1. Agent 不工作?
   → 看 /var/log/migao-agent.log 最后几行
   → 看 /tmp/migao-agent-health.json
   → 检查 crontab: crontab -l | grep agent

2. 验收不触发?
   → 看 /var/log/migao-verify.log
   → 看 issue 是否有 ai-verify/pending 标签
   → 看 issue 是否有 VERIFY_TRIGGER comment

3. CI 标签加不上?
   → 查 workflow 日志 → gh pr edit 权限?
   → 确认 workflow 有 pull-requests: write

4. Push 失败?
   → 检查 .git/refs/heads/feat/ 权限 (chown admin:admin)
   → 检查 git remote (应为 zhaokai-mgzn/migao)

5. 死循环?
   → 看 issue 的 VERDICT_JSON 数量
   → ≥3 且都是 hold → 手动 block/need-human
```
