# 04 — 执行脚本

## agent-poll.sh (214 行)

研发工人脚本，每 5 分钟由 crontab 触发。

### 启动流程
1. **锁检查**: `/tmp/migao-agent.lock` (超时 30min 强制清除)
2. **ERR trap**: 崩溃捕获 → 写健康指标 → 释放锁
3. **git**: `checkout main → reset --hard → clean -fd → pull origin main`
4. **gh auth**: 验证认证状态

### 信号扫描 (按优先级)

```
信号 0: needs-draft → 生成 DRAFT_JSON
  ├─ 扫描: gh issue list --label needs-draft --state open
  ├─ 已有有效 DRAFT? → 移除 needs-draft
  ├─ REJECT 后重 draft? → 读 REVIEW_JSON reject 原因
  └─ 执行: claude --print --agent dev-agent
      步骤: gh issue view → 读 CONTRACT_JSON → 理解 → 生成 DRAFT_JSON
      验收: gh issue comment 贴 DRAFT_JSON → 移除 needs-draft

信号 1: junshi-review/needs-changes → 修复 PR
  ├─ 扫描: gh pr list --label "junshi-review/needs-changes"
  ├─ 无关联 issue? → 移除标签 + skip
  ├─ 检查修复次数 (基于 comments 中 needs-changes 出现次数)
  │   ├─ ≥3 次 → 熔断: block/need-human
  │   └─ <3 次 → 继续
  ├─ git fetch origin -- <branch> && git checkout <branch>
  ├─ git pull origin main
  └─ 执行: claude --print --agent dev-agent
      "读 CI 失败原因 → 修复 → 遵守项目铁律 → push"

信号 2: needs-verification → Phase 1 Review + TDD (原始流程)
  (v6.0 后此信号主要由 OpenClaw 驱动)
```

### 自愈机制 (Fix1~Fix4)

| Fix | 机制 | 说明 |
|-----|------|------|
| Fix1 | ERR trap | 脚本异常崩溃时写健康指标 + 释放锁 |
| Fix2 | 熔断 | needs-changes 修复尝试 ≥3 次 → block/need-human |
| Fix3 | 健康指标 | 每次运行写 `/tmp/migao-agent-health.json` |
| Fix4 | assignee 释放 | Phase2 无 PR → 释放 assignee + 2 次后 escalate |

### gh_exec 包装
所有 `gh` 命令通过 `gh_exec` 执行：
```bash
gh_exec() {
    local output
    output=$("$@" 2>&1) || { err "gh $1 失败: ${output:0:200}"; return 1; }
    echo "$output"
}
```

---

## verify-poll.sh (169 行)

验收工人脚本，每 5 分钟由 crontab 触发。

### 启动流程
1. **锁检查**: `/tmp/migao-verify.lock` (超时 30min)
2. **git pull** origin main
3. **扫描**: `ai-verify/pending` 标签的 issue (open + closed)

### 扫描逻辑

```bash
for iid in $SCAN_IDS; do
    HAS_TRIGGER=$(检查是否有 VERIFY_TRIGGER comment)
    HAS_VERDICT=$(检查是否有 VERDICT_JSON comment)

    # 死循环检测
    if HAS_VERDICT >= 3 && 最后一条 decision = hold → block/need-human

    # 超时跳过 (v6.1)
    if HAS_TRIGGER && 无 VERDICT:
        TRIGGER_AGE = VERIFY_TRIGGER comment 的 createdAt
        if TRIGGER_AGE >= 7 天 → 移除 ai-verify/pending + skip

    # 待验收
    if HAS_TRIGGER && 无 VERDICT → VERIFY_ISSUE=$iid; break
done
```

### 验收执行

```bash
# 1. 确保服务启动
start_services() {
    admin-api (:8081) + ai-agent-service (:8001) + admin-web (:3001)
    sleep 30
}

# 2. 凭据注入
export SERVICE_TOKEN / PGPASSWORD / DB_HOST / DB_USER / DB_NAME

# 3. 调用 verify-agent
claude --print --agent verify-agent "
  验收 issue #$VERIFY_ISSUE
  环境: curl http://localhost:8081 + psql + check_assert
  步骤: 提取 business_truths → 逐条执行 → 判定 → 贴 VERDICT_JSON
"
```

### 兜底机制

Agent 没贴 VERDICT → 自动从 `/var/log/migao-verify-agent.log` 提取并贴评论。

### 服务管理
- **启动**: nohup 后台启动 3 个服务 → sleep 30 → 验证 lsof
- **关闭**: `trap "stop_services; rm -f $LOCK_FILE" EXIT`

---

## agent-setup.sh

一键初始化脚本，在云服务器上运行一次。

### 步骤
1. Clone 仓库 (`zhaokai-mgzn/migao`)
2. 配置 git user (`junshi` / `junshi@youke.local`)
3. 安装依赖: Python venv + Java mvn + Node npm + Playwright
4. 配置 `.env` (手动)
5. 配置 Claude Code agent (`dev-agent.md` + `verify-agent.md` + `settings.json`)
6. 验证 `gh auth`
7. 启动服务 (admin-api :8081 / ai-agent :8001 / admin-web :3001)
8. 环境锁死 (Java/Python/Node 版本)
9. 安装 crontab: agent-poll + verify-poll (各每 5 分钟)

---

## heartbeat.sh

Agent 心跳脚本，OpenClaw `junshi-health-check` 调用。

**检查项**:
- `/var/log/migao-agent.log` 最后修改时间 >15min → 告警
- `/var/log/migao-verify.log` 最后修改时间 >15min → 告警
- `/tmp/migao-agent-health.json` 读取失败次数
- stdout 输出 = cron 邮件通知
