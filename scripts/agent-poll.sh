#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 米高研发 Agent 轮询触发器（单实例版，适配 4C8G）
#
# cron 每 5 分钟执行。一次只处理一个 issue，完成后退出。
# 优先级: block/dual-mismatch > needs-verification
# ═══════════════════════════════════════════════════════════════
set -e

WORK_DIR="${WORK_DIR:-/opt/youke}"
LOCK_FILE="/tmp/migao-agent.lock"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }

# 防并发
if [ -f "$LOCK_FILE" ]; then
    log "⚠️ 上一个任务还在跑，跳过"
    exit 0
fi
trap "rm -f $LOCK_FILE" EXIT
touch "$LOCK_FILE"

cd "$WORK_DIR"

if ! gh auth status 2>/dev/null; then
    log "❌ gh 未认证"
    exit 1
fi

# ── 1. 优先抢 block issue ──
ISSUE_ID=$(gh issue list --label block/dual-mismatch --state open --limit 5 \
    --json number,assignees --jq '.[] | select(.assignees | length == 0) | .number' 2>/dev/null | head -1)

if [ -n "$ISSUE_ID" ]; then
    # 熔断检查：block_depth >= 3 跳过
    BODY=$(gh issue view "$ISSUE_ID" --json body --jq '.body' 2>/dev/null)
    DEPTH=$(echo "$BODY" | grep -oP '"block_depth"\s*:\s*\K\d+' | head -1)
    if [ "${DEPTH:-0}" -ge 3 ]; then
        log "🛑 issue #$ISSUE_ID block_depth=$DEPTH，已达熔断阈值，跳过"
        gh issue edit "$ISSUE_ID" --add-label "block/need-human" 2>/dev/null || true
        exit 0
    fi

    log "🔴 抢到 block issue #$ISSUE_ID"
    gh issue edit "$ISSUE_ID" --add-assignee "@me" 2>/dev/null || true

    claude --print \
        --custom-instructions ".claude/agents/dev-agent.md" \
        "修复验收被阻的 issue #$ISSUE_ID。读 VERDICT_JSON 理解失败原因，修复代码，跑涉及模块的全量单测，创建 PR（PR_CONTRACT 标 parent_issue=$ISSUE_ID）。" \
        2>&1 | tail -10

    log "✅ issue #$ISSUE_ID 修复完成"
    exit 0
fi

# ── 2. 没有 block → 抢待开发 issue ──
ISSUE_ID=$(gh issue list --label needs-verification --state open --limit 10 \
    --json number,title,assignees --jq '.[] | select(.assignees | length == 0) | .number' 2>/dev/null | head -1)

if [ -n "$ISSUE_ID" ]; then
    # 确认军师已出 case
    HAS_DRAFT=$(gh issue view "$ISSUE_ID" --comments --json comments \
        --jq '.comments[] | select(.body | contains("DRAFT_JSON")) | .body' 2>/dev/null | head -1)
    if [ -z "$HAS_DRAFT" ]; then
        log "⏳ issue #$ISSUE_ID 军师还未出 case，跳过"
        exit 0
    fi

    log "📝 抢到待开发 issue #$ISSUE_ID"
    gh issue edit "$ISSUE_ID" --add-assignee "@me" 2>/dev/null || true

    claude --print \
        --custom-instructions ".claude/agents/dev-agent.md" \
        "处理 issue #$ISSUE_ID。读 CONTRACT_JSON 和 DRAFT_JSON，review case 草稿，按 TDD 写码，跑全量单测，创建 PR。" \
        2>&1 | tail -10

    log "✅ issue #$ISSUE_ID 开发完成"
    exit 0
fi

log "😴 无待处理 issue"
