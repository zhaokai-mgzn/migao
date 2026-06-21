# 05 — 定时任务

## 调度矩阵

二郎神有两个调度层，共 9 个定时任务：

| 层级 | 调度器 | 任务数 | 最小间隔 |
|------|--------|--------|---------|
| **LLM 层** | OpenClaw gateway | 7 | 10min |
| **机械层** | Linux crontab | 2 | 5min |

## Linux Crontab (机械执行工人层)

由 `agent-setup.sh` 在第 9 步安装。

```crontab
*/5 * * * * cd /opt/youke && bash scripts/agent-poll.sh >> /var/log/migao-agent.log 2>&1
*/5 * * * * cd /opt/youke && bash scripts/verify-poll.sh >> /var/log/migao-verify.log 2>&1
```

**特性**:
- 两个脚本独立锁文件，可并行运行
- agent-poll 负责写码，verify-poll 负责验收
- 日志文件: `/var/log/migao-agent.log` / `/var/log/migao-verify.log`

## OpenClaw 原生 Cron (军师调度层)

由 OpenClaw gateway 管理，prompt 文件在 `/opt/junshi/prompts/`。

| # | Job Name | Schedule | 职责 | 类型 |
|---|----------|----------|------|------|
| 1 | `junshi-automerge` | 每 10min | auto-merge + 健康巡检 (Agent心跳/流水线卡点) | 操作+监控 |
| 2 | `junshi-stale-watch` | 每 30min | 巡检 stale issue (>3天无进展)，标记或 escalate | 监控 |
| 3 | `junshi-pattern-reflect` | 每天 2:00 | REJECT/HOLD 聚类分析，同模板≥3次→自动修 YAML | 进化 |
| 4 | `junshi-daily-report` | 每天 9:00 | 日报生成 (#648 等) | 报告 |
| 5 | `junshi-health-check` | 每 15min | Agent 心跳监控 (调 heartbeat.sh) | 监控 |
| 6 | `junshi-coverage-track` | 每天 6:00 | 覆盖率追踪，创建 qa-growth 子 issue | 进化 |
| 7 | `junshi-learn-archive` | 每周日 3:00 | learn 归档，清理过期数据 | 维护 |

### junshi-automerge 详细逻辑

```
for each open PR (not draft, CI green):
    1. 检查 PR body 含 Fixes/Closes #xxx
    2. 检查无敏感文件 (.env, 密钥)
    3. 检查 E2E/Growth Gate 通过
    4. 全部通过 → gh pr merge --squash --delete-branch
    5. 有问题 → add-label junshi-review/needs-changes + comment
```

### junshi-pattern-reflect 详细逻辑

```
1. 扫描最近的 REVIEW_JSON reject 和 VERDICT_JSON block/hold
2. 聚类: 相同模板 + 相同失败原因 ≥3 次
3. 自动修: 更新对应的 verification template YAML
4. 无法自动修: 创建 process-improvement issue
```

### junshi-stale-watch 详细逻辑

```
1. 扫描 open issue updated >3 天
2. needs-verification 超过 5 天 → escalate
3. needs-draft 超过 2 天 → 重新触发
4. ai-verify/pending 超过 7 天 → 判定异常
```

## 运行时序

```
时间轴 (分钟):
:00  CI 事件可能触发
:05  agent-poll 扫描 + verify-poll 扫描
:10  junshi-automerge 扫描
:10  agent-poll 扫描 + verify-poll 扫描
:15  junshi-health-check 心跳
:15  agent-poll 扫描 + verify-poll 扫描
:20  agent-poll 扫描 + verify-poll 扫描
:25  agent-poll 扫描 + verify-poll 扫描
:30  junshi-stale-watch 巡检
:30  agent-poll 扫描 + verify-poll 扫描
...
2:00 junshi-pattern-reflect 模式反思
6:00 junshi-coverage-track 覆盖率追踪
9:00 junshi-daily-report 日报
```

## 启停操作

```bash
# 查看 crontab
crontab -l | grep -E 'agent-poll|verify-poll'

# 临时停止
crontab -l | grep -v 'agent-poll\|verify-poll' | crontab -

# 恢复
(crontab -l | grep -v 'agent-poll\|verify-poll'; echo "*/5 * * * * cd /opt/youke && bash scripts/agent-poll.sh >> /var/log/migao-agent.log 2>&1"; echo "*/5 * * * * cd /opt/youke && bash scripts/verify-poll.sh >> /var/log/migao-verify.log 2>&1") | crontab -

# 手动触发
cd /opt/youke && bash scripts/agent-poll.sh
cd /opt/youke && bash scripts/verify-poll.sh
```
