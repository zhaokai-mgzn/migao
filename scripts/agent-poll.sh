#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 米高研发 Agent 轮询触发器（单实例版，适配 4C8G）
#
# cron 每 5 分钟执行。一次只处理一个 issue。
# 优先抢修复 issue（parent_issue 不为空），其次抢新功能 issue。
# 不直接处理 block/dual-mismatch 标签的原始 issue（那是军师的状态标记）。
# ═══════════════════════════════════════════════════════════════
set -e

# ── cron 环境保护（PATH 不含 /usr/local/bin，HOME 可能为空）──
export HOME="${HOME:-/root}"
export PATH="/usr/local/bin:/usr/bin:/bin${PATH:+:$PATH}"

# venv Python 3.11（系统 python3 可能是 3.6）
PYTHON="${WORK_DIR:-/opt/youke}/backend/ai-agent-service/.venv/bin/python3"
[ -x "$PYTHON" ] || PYTHON="python3.11"
[ -x "$(command -v "$PYTHON" 2>/dev/null)" ] || PYTHON="python3"

# ═══════════════════════════════════════════════════════
# 按需启停服务 — 任务开始前启动，任务结束后关闭
# ═══════════════════════════════════════════════════════
start_services() {
    log "🚀 启动服务..."
    cd /opt/youke/backend/admin-api && nohup ./mvnw spring-boot:run -q -Dspring-boot.run.arguments='--server.port=8081' > /var/log/migao-admin-api.log 2>&1 &
    cd /opt/youke/backend/ai-agent-service && nohup .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 > /var/log/migao-ai-agent.log 2>&1 &
    cd /opt/youke/frontend/admin-web && nohup npm run dev > /var/log/migao-admin-web.log 2>&1 &
    sleep 30
}

stop_services() {
    log "🛑 关闭服务..."
    fuser -k 8081/tcp 2>/dev/null || true
    fuser -k 8001/tcp 2>/dev/null || true
    fuser -k 3001/tcp 2>/dev/null || true
}

WORK_DIR="${WORK_DIR:-/opt/youke}"
LOCK_FILE="/tmp/migao-agent.lock"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }

if [ -f "$LOCK_FILE" ]; then
    LOCK_AGE=$(($(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0)))
    if [ "${LOCK_AGE:-0}" -gt 1800 ]; then
        log "⚠️ 锁文件超过30分钟，强制清除"
        rm -f "$LOCK_FILE"
    else
        log "⚠️ 上一个任务还在跑 (${LOCK_AGE}s)，跳过"
        exit 0
    fi
fi
trap "rm -f $LOCK_FILE" EXIT
touch "$LOCK_FILE"

cd "$WORK_DIR"

if ! gh auth status 2>/dev/null; then
    log "❌ gh 未认证"
    exit 1
fi

# ── 0. 最高优先：PR 被军师打回 needs-changes → 立即修复 ──
NEEDS_CHANGE_PR=$(gh pr list --label "junshi-review/needs-changes" --state open --limit 5 \
    --json number,headRefName,body --jq '.[] | select(.body | contains("Closes")) | "\(.number) \(.headRefName)"' 2>/dev/null | head -1)
if [ -n "$NEEDS_CHANGE_PR" ]; then
    PR_NUM=$(echo "$NEEDS_CHANGE_PR" | awk '{print $1}')
    PR_BRANCH=$(echo "$NEEDS_CHANGE_PR" | awk '{print $2}')
    PR_BODY=$(gh pr view "$PR_NUM" --json body --jq '.body' 2>/dev/null)
    ISSUE_ID=$(echo "$PR_BODY" | grep -oP 'Closes #\K\d+' | head -1)

    log "🔧 PR #$PR_NUM 被军师打回 needs-changes → 修复"
    git fetch origin "$PR_BRANCH" && git checkout "$PR_BRANCH" 2>/dev/null

    claude --print \
        --custom-instructions ".claude/agents/dev-agent.md" \
        "PR #$PR_NUM (关联 issue #$ISSUE_ID) 被军师标记 needs-changes。读 PR 评论理解要改什么，修复代码，跑测试，push 到同分支。" \
        2>&1 | tail -10

    log "✅ PR #$PR_NUM 修复完成"
    exit 0
fi

# ── 抢一个 issue：优先被阻的（同 issue 内 block 后重新抢）──
pick_issue() {
    local BLOCKED=$(gh issue list --label "block/dual-mismatch,needs-verification" --state open --limit 10 \
        --json number,assignees --jq '.[] | select(.assignees | length == 0) | .number' 2>/dev/null | head -1)
    if [ -n "$BLOCKED" ]; then
        echo "$BLOCKED"
        return
    fi

    # 再找普通 needs-verification（军师已出 case 的）
    local NEW=$(gh issue list --label needs-verification --state open --limit 15 \
        --json number,assignees --jq '.[] | select(.assignees | length == 0) | .number' 2>/dev/null | head -1)
    if [ -n "$NEW" ]; then
        local HAS_DRAFT=$(gh issue view "$NEW" --comments --json comments \
            --jq '.comments[] | select(.body | contains("DRAFT_JSON")) | .body' 2>/dev/null | head -1)
        if [ -n "$HAS_DRAFT" ]; then echo "$NEW"; return; fi
        log "⏳ issue #$NEW 军师还未出 case"
    fi
}

ISSUE_ID=$(pick_issue)

if [ -z "$ISSUE_ID" ]; then
    log "😴 无待处理 issue"
    exit 0
fi

# ── 按需启动服务，任务结束后自动关闭 ──
start_services
trap 'stop_services' EXIT

# ── 熔断检查 ──
BLOCK_COMMENT=$(gh issue view "$ISSUE_ID" --comments --json comments \
    --jq '.comments[] | select(.body | contains("BLOCK_LOG")) | .body' 2>/dev/null | tail -1)
DEPTH=$(echo "$BLOCK_COMMENT" | grep -oP '"block_depth"\s*:\s*\K\d+' | head -1)
if [ "${DEPTH:-0}" -ge 3 ]; then
    log "🛑 issue #$ISSUE_ID block_depth=$DEPTH，已达熔断阈值"
    gh issue edit "$ISSUE_ID" --add-label "block/need-human" 2>/dev/null || true
    exit 0
fi

# ── 判断是新功能还是 re-fix ──
IS_BLOCKED=$(gh issue view "$ISSUE_ID" --json labels --jq '.labels[].name' 2>/dev/null | grep -c "block/dual-mismatch" || true)
gh issue edit "$ISSUE_ID" --add-assignee "@me" 2>/dev/null || true

if [ "${IS_BLOCKED:-0}" -gt 0 ]; then
    log "🔧 被阻 issue #$ISSUE_ID (第${DEPTH:-1}次打回) → 修复"
    claude --print \
        --custom-instructions ".claude/agents/dev-agent.md" \
        "issue #$ISSUE_ID 验收被阻。读最新 BLOCK_LOG 评论理解失败原因，修复代码，跑涉及模块的全量单测，创建新 PR。PR body 关联同一个 issue (Closes #$ISSUE_ID)。" \
        2>&1 | tail -10
else
    log "📝 新功能 issue #$ISSUE_ID"
    claude --print \
        --custom-instructions ".claude/agents/dev-agent.md" \
        "处理 issue #$ISSUE_ID。读 CONTRACT_JSON 和 DRAFT_JSON，review case 草稿，按 TDD 写码，跑全量单测，创建 PR。" \
        2>&1 | tail -10
fi

log "✅ issue #$ISSUE_ID 完成"
exit 0

# ── 3. 扫验收触发（军师发 VERIFY_TRIGGER → Agent 跑验收脚本）──
log "🔍 扫描验收触发..."

VERIFY_ISSUE=""
while read iid; do
    HAS_TRIGGER=$(gh issue view "$iid" --comments --json comments \
        --jq '.comments[] | select(.body | contains("VERIFY_TRIGGER")) | .body' 2>/dev/null | head -1)
    HAS_RESULT=$(gh issue view "$iid" --comments --json comments \
        --jq '.comments[] | select(.body | contains("VERIFY_RESULT")) | .body' 2>/dev/null | head -1)

    if [ -n "$HAS_TRIGGER" ] && [ -z "$HAS_RESULT" ]; then
        VERIFY_ISSUE="$iid"
        break
    fi
done < <(gh issue list --state open --limit 20 --json number --jq '.[].number' 2>/dev/null)

if [ -n "$VERIFY_ISSUE" ]; then
    log "🧪 验收 issue #$VERIFY_ISSUE"

    if ! lsof -i :8081 -sTCP:LISTEN >/dev/null 2>&1 || ! lsof -i :8001 -sTCP:LISTEN >/dev/null 2>&1 || ! lsof -i :3001 -sTCP:LISTEN >/dev/null 2>&1; then
        log "⚠️ 服务未全部就绪，跳过验收"
    else
        log "  → primary.py (E2E + 真实集测)..."
        cd /opt/youke && $PYTHON scripts/dual_verify/primary.py "$VERIFY_ISSUE" 2>&1 | tail -3
        log "  → reviewer.py (独立 DB+API)..."
        cd /opt/youke && $PYTHON scripts/dual_verify/reviewer.py "$VERIFY_ISSUE" 2>&1 | tail -3
        log "  → merge.py (自动判定+执行)..."
        cd /opt/youke && $PYTHON scripts/dual_verify/merge.py "$VERIFY_ISSUE" 2>&1 | tail -3
        log "✅ 验收完成 #$VERIFY_ISSUE"
    fi
else
    log "😴 无待处理任务"
fi
