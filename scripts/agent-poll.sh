#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 米高研发 Agent 轮询触发器（单实例版，适配 4C8G）
#
# cron 每 5 分钟执行。一次只处理一个 issue。
# 优先抢修复 issue（parent_issue 不为空），其次抢新功能 issue。
# 不直接处理 block/dual-mismatch 标签的原始 issue（那是军师的状态标记）。
# ═══════════════════════════════════════════════════════════════
set -e

WORK_DIR="${WORK_DIR:-/opt/youke}"
LOCK_FILE="/tmp/migao-agent.lock"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }

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

# ── 抢一个 issue：优先修复 issue，其次新功能 ──
pick_issue() {
    # 先找修复 issue（CONTRACT_JSON 含 parent_issue 的）
    local FIX=$(gh issue list --label needs-verification --state open --limit 15 \
        --json number,body,assignees \
        --jq '.[] | select(.assignees | length == 0) | select(.body | contains("parent_issue")) | .number' 2>/dev/null | head -1)

    if [ -n "$FIX" ]; then
        echo "$FIX"
        return
    fi

    # 再找普通 issue（军师已出 case 的）
    local NEW=$(gh issue list --label needs-verification --state open --limit 15 \
        --json number,assignees --jq '.[] | select(.assignees | length == 0) | .number' 2>/dev/null | head -1)

    if [ -n "$NEW" ]; then
        # 确认军师已出 case（有 DRAFT_JSON 评论）
        local HAS_DRAFT=$(gh issue view "$NEW" --comments --json comments \
            --jq '.comments[] | select(.body | contains("DRAFT_JSON")) | .body' 2>/dev/null | head -1)
        if [ -n "$HAS_DRAFT" ]; then
            echo "$NEW"
            return
        fi
        log "⏳ issue #$NEW 军师还未出 case"
    fi
}

ISSUE_ID=$(pick_issue)

if [ -z "$ISSUE_ID" ]; then
    log "😴 无待处理 issue"
    exit 0
fi

# ── 熔断检查 ──
BODY=$(gh issue view "$ISSUE_ID" --json body --jq '.body' 2>/dev/null)
DEPTH=$(echo "$BODY" | grep -oP '"block_depth"\s*:\s*\K\d+' | head -1)
if [ "${DEPTH:-0}" -ge 3 ]; then
    log "🛑 issue #$ISSUE_ID block_depth=$DEPTH，已达熔断阈值"
    gh issue edit "$ISSUE_ID" --add-label "block/need-human" 2>/dev/null || true
    exit 0
fi

# ── 判断是修复还是新功能 ──
PARENT=$(echo "$BODY" | grep -oP '"parent_issue"\s*:\s*\K\d+' | head -1)
gh issue edit "$ISSUE_ID" --add-assignee "@me" 2>/dev/null || true

if [ -n "$PARENT" ]; then
    log "🔧 抢到修复 issue #$ISSUE_ID (父 issue #$PARENT, depth=$DEPTH)"
    claude --print \
        --custom-instructions ".claude/agents/dev-agent.md" \
        "修复验收被阻的 issue #$ISSUE_ID（父 issue #$PARENT）。读 VERDICT_JSON 理解失败原因，修复代码，跑涉及模块的全量单测，创建 PR（PR_CONTRACT 标 parent_issue=$PARENT）。" \
        2>&1 | tail -10
else
    log "📝 抢到新功能 issue #$ISSUE_ID"
    claude --print \
        --custom-instructions ".claude/agents/dev-agent.md" \
        "处理 issue #$ISSUE_ID。读 CONTRACT_JSON 和 DRAFT_JSON，review case 草稿，按 TDD 写码，跑全量单测，创建 PR。" \
        2>&1 | tail -10
fi

log "✅ issue #$ISSUE_ID 完成"
    exit 0
fi

# ── 3. 没有 dev 任务 → 扫验收触发 ──
log "🔍 扫描验收触发..."

# 找军师的 VERIFY_TRIGGER 评论（最近 20 个 issue）
VERIFY_ISSUE=$(gh issue list --state open --limit 20 --json number --jq '.[].number' 2>/dev/null | while read iid; do
    HAS_TRIGGER=$(gh issue view "$iid" --comments --json comments \
        --jq '.comments[] | select(.body | contains("VERIFY_TRIGGER")) | .body' 2>/dev/null | head -1)
    HAS_RESULT=$(gh issue view "$iid" --comments --json comments \
        --jq '.comments[] | select(.body | contains("VERIFY_RESULT")) | .body' 2>/dev/null | head -1)
    if [ -n "$HAS_TRIGGER" ] && [ -z "$HAS_RESULT" ]; then
        echo "$iid"
        break
    fi
done)

if [ -n "$VERIFY_ISSUE" ]; then
    # 解析 VERIFY_TRIGGER 获取 kind
    TRIGGER=$(gh issue view "$VERIFY_ISSUE" --comments --json comments \
        --jq '.comments[] | select(.body | contains("VERIFY_TRIGGER")) | .body' 2>/dev/null | head -1)
    KIND=$(echo "$TRIGGER" | grep -oP '"kind"\s*:\s*"\K\w+' | head -1)

    log "🧪 验收 issue #$VERIFY_ISSUE (kind=$KIND)"
    claude --print \
        --custom-instructions ".claude/agents/verify-agent.md" \
        "对 issue #$VERIFY_ISSUE 执行 $KIND 验收。跑对应脚本，贴 VERIFY_RESULT 评论。" \
        2>&1 | tail -10
    log "✅ 验收完成 #$VERIFY_ISSUE"
else
    log "😴 无待处理 issue / 验收任务"
fi
