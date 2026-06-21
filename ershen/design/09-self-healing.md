# 09 — 自愈机制

二郎神体系有 8 种自愈机制，覆盖 Agent 崩溃、CI 失败、死循环、权限异常、脏状态。

## 1. Agent 崩溃自愈 (agent-poll Fix1)

```bash
trap 'err "脚本异常退出"; 写健康指标; 释放锁' ERR
```

- ERR trap 捕获任何非零退出
- 写入 `/tmp/migao-agent-health.json` (exit=crash, line=N)
- 释放锁文件 (防止死锁)
- OpenClaw health-check 检测到 crash → 告警

## 2. 熔断自愈 (agent-poll Fix2)

```
needs-changes 修复尝试次数 ≥ 3
  → block/need-human
  → 评论: "已达熔断阈值"
  → 移除 needs-changes
```

防止 Agent 反复尝试修复同一个无法解决的问题。

## 3. 锁超时自愈 (agent-poll + verify-poll)

```bash
LOCK_AGE=$(($(date +%s) - $(stat -c %Y "$LOCK_FILE")))
if [ "$LOCK_AGE" -gt 1800 ]; then  # 30min
    rm -f "$LOCK_FILE"
fi
```

上次运行异常退出未释放锁 → 30 分钟后自动清除。

## 4. 死循环自愈 (verify-poll)

```
≥3 条 VERDICT_JSON + 最后一条 decision = hold
  → block/need-human
  → 评论: "连续 3+ 次 HOLD → 死循环"
  → 移除 ai-verify/pending
```

## 5. 超时跳过 (verify-poll v6.1)

```
VERIFY_TRIGGER 超过 7 天无 VERDICT_JSON
  → 历史异常 (PR body typo 误触发)
  → 移除 ai-verify/pending
  → comment: "超过 7 天无 VERDICT_JSON，判定为历史异常"
```

## 6. CI 失败自愈

```
任一 CI job 失败
  → pr-check.yml "Label needs-changes on any failure"
  → gh pr edit --add-label "junshi-review/needs-changes"
  → agent-poll 每 5min 扫描 → dev-agent 修复 → push
```

**关键依赖**: `pull-requests: write` 权限 (已修复于 PR #677)。

## 7. 权限自愈 (手动 + 巡检)

**已知问题**: `.git/refs/heads/feat/` 被 root 独占 (agent 以 root 运行 git 操作后)。

**自愈方案** (巡检检测到后):
```bash
chown -R admin:admin .git/refs/heads/feat/
```

由 OpenClaw `junshi-health-check` 或巡检 cron 检测并自动修复。

## 8. 脏工作区自愈 (agent-poll)

每次启动时:
```bash
git checkout main
git reset --hard HEAD
git clean -fd
git pull origin main
```

强制还原工作区到干净状态。

## Agent 健康指标

`/tmp/migao-agent-health.json`:
```json
{
  "last_run": "2026-06-21T20:00:00+08:00",
  "exit": "ok",
  "errors": 0,
  "duration_s": 12
}
```

异常值:
- `exit: "crash"` → Agent 崩溃
- `errors > 5` → 多次 gh 命令失败
- 文件不存在 >15min → Agent 停止运行

## VERDICT 兜底

verify-agent 未贴 VERDICT → 自动从日志提取:
```bash
VERDICT_BLOCK=$(grep -A30 "<!-- VERDICT_JSON" /var/log/migao-verify-agent.log | tail -31)
[ -n "$VERDICT_BLOCK" ] && echo "$VERDICT_BLOCK" | gh issue comment "$VERIFY_ISSUE" --body-file -
```

## 服务自启

verify-poll 验收前:
```bash
# 检查 admin-api 是否响应
curl -s -o /dev/null -w '%{http_code}' http://localhost:8081/api/admin/dashboard/stats
# 不响应 → start_services()
```

验收完成后 trap 自动停服务。
