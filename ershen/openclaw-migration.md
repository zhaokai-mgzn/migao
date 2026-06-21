# OpenClaw 二郎神 Cron 配置参考

> 二郎神体系 v5.0 — OpenClaw 管理 7 个 cron job。提示词文件在 `/opt/junshi/prompts/`。
> 本文档记录当前活跃 cron 的提示词，供维护参考。主权威文档为 `ershen/handbook.md`。

## 活跃 Cron (7 个)

### 1. junshi-automerge — 每 10 分钟

```
你是二郎神体系的军师。判断 PR 是否可自动合并。

## 第一步：有无 PR
gh pr list --state open --json number --limit 1
如果返回 [] → 静默退出

## 第二步：逐 PR 判断
gh pr list --state open --json number,title,labels,mergeable,statusCheckRollup,body,files --limit 20

对每个 PR 检查:
a. CI 全绿：只看实际运行过的 checks (status=COMPLETED)，全部 SUCCESS
   忽略 status=EXPECTED 的（条件 checks 未触发，无需等待）
b. 关联 issue：body 有 Fixes/Closes #xxx
c. 无敏感文件：不含 .env（非 example）
d. 前端/Controller 变更 → E2E spec 存在

全通过 → gh pr merge --squash --delete-branch <N> → 评论成功
任一不通过 → gh pr edit <N> --add-label junshi-review/needs-changes → 评论原因

## 边界
不修改代码、不改变 .github/workflows/、5min超时、失败重试1次
```

### 2. junshi-stale-watch — 每 30 分钟

巡检 `needs-verification` issue >3 天无进展。读评论区分"真 stale"和"在正常 review 周期"。真 stale → 催促评论 + 严重→升级。

### 3. junshi-hold-escalate — 每天 9/12/15/18/21

扫 `hold/auto-fail` 积压 >7 天。判断真阻塞 vs Agent 跑挂。分级 P0/P1/P2 → 升级人工。

### 4. junshi-daily-report — 每天 19:00

调用 `quality_report.py --days 1` → LLM 理解数据 → 200-400 字中文日报 → 追加到日报 issue。

### 5. junshi-pattern-reflect (L2) — 每天 2:00

收集近 24h REJECT/HOLD/BLOCK → LLM 聚类分析 → 同模板≥3次自动修 YAML → 无法自动修则建 process-improvement issue。

详细提示词：`/opt/junshi/prompts/pattern-reflect.txt`

### 6. junshi-meta-reflect (L3) — 每周一 10:00

`quality_report.py --days 7` → block率/close率/闭环时间 趋势分析 → 瓶颈定位 → 建改进计划 issue。

详细提示词：`/opt/junshi/prompts/meta-reflect.txt`

### 7. junshi-coverage-weekly — 每周一 10:30

`coverage_weekly.py --scan --create-issues` → 全量覆盖率扫描 → 自动建 issue。

## 已停用 Cron

| Job | 原因 |
|-----|------|
| `junshi-casedraft` | CI + agent-poll 信号0 替代（事件驱动比5分钟轮询更快） |

## 管理命令

```bash
# 查看所有 cron
openclaw cron list --url ws://127.0.0.1:15196 --token <token>

# 查看运行历史
openclaw cron runs --id <job-id>

# 立即运行一次
openclaw cron run <job-id>

# 启用/停用
openclaw cron enable <job-id>
openclaw cron disable <job-id>
```
