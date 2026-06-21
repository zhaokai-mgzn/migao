#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 米高研发 Agent 轮询 v5 — AI First: OpenClaw 调度，agent 纯执行
#
# OpenClaw 决策 → 标签/评论 → agent-poll 读信号执行
# agent-poll 不做任何判断，只找第一个可执行任务并干活
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

export HOME="${HOME:-/root}"
export PATH="/usr/local/bin:/usr/bin:/bin${PATH:+:$PATH}"

WORK_DIR="${WORK_DIR:-/opt/youke}"
LOCK_FILE="/tmp/migao-agent.lock"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }

if [ -f "$LOCK_FILE" ]; then
    LOCK_AGE=$(($(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0)))
    if [ "${LOCK_AGE:-0}" -gt 1800 ]; then
        log "⚠️ 锁超时，强制清除"; rm -f "$LOCK_FILE"
    else
        exit 0
    fi
fi
trap "rm -f $LOCK_FILE" EXIT
touch "$LOCK_FILE"

cd "$WORK_DIR"
gh auth status 2>/dev/null || { log "❌ gh 未认证"; exit 1; }

git checkout main 2>/dev/null
git reset --hard HEAD 2>/dev/null
git clean -fd 2>/dev/null
git pull origin main 2>&1 | tail -1

# ═══════════════════════════════════════════════════════
# 信号 0: needs-draft → 生成 DRAFT_JSON（最高优先）
# 新 issue 初始 draft + REJECT 后重新 draft 都走这里
# ═══════════════════════════════════════════════════════
NEEDS_DRAFT=$(gh issue list --label needs-draft --state open --limit 1 \
    --json number --jq '.[0].number' 2>/dev/null)
if [ -n "$NEEDS_DRAFT" ]; then
    [[ "$NEEDS_DRAFT" =~ ^[0-9]+$ ]] || { log "❌ 非法 ID"; exit 1; }

    # 已有有效 DRAFT_JSON 则跳过（CI 重复打标签的情况）
    VALID_DRAFT=$(gh issue view "$NEEDS_DRAFT" --comments --json comments \
        --jq '[.comments[] | select(.body | contains("DRAFT_JSON") and (contains("OUTDATED") | not))] | length' 2>/dev/null)
    if [ "${VALID_DRAFT:-0}" -gt 0 ]; then
        log "⏭️  #$NEEDS_DRAFT 已有有效 DRAFT，移除冗余 needs-draft"
        gh issue edit "$NEEDS_DRAFT" --remove-label "needs-draft" 2>/dev/null || true
    else
        # 判断是初始 draft 还是 REJECT 重 draft
        FEEDBACK=$(gh issue view "$NEEDS_DRAFT" --comments --json comments \
            --jq '[.comments[] | select(.body | contains("<!-- REVIEW_JSON") and contains("\"reject\""))] | last | .body' 2>/dev/null || echo "")
        if [ -n "$FEEDBACK" ]; then
            log "🔄 REJECT 重 draft for #$NEEDS_DRAFT"
            CONTEXT="这是 REJECT 后重新生成。上次被拒原因: $FEEDBACK。请基于此修正 L2/L3/L4。"
        else
            log "📝 初始 DRAFT for #$NEEDS_DRAFT"
            CONTEXT="这是新 issue 的初始 case draft。读 issue → 理解业务 → 生成。"
        fi

        claude --print --agent dev-agent \
            "为 issue #$NEEDS_DRAFT 生成 DRAFT_JSON。$CONTEXT
             1. 读 issue body + CONTRACT_JSON → 提取 business_truths
             2. 理解业务领域和变更范围
             3. 生成 L2/L3/L4 case（前端 issue 用 skip_template=true）
             4. 用 gh issue comment 贴完整的 <!-- DRAFT_JSON -->" \
            2>&1 | tail -5

        gh issue edit "$NEEDS_DRAFT" --remove-label "needs-draft" 2>/dev/null || true
        log "✅ DRAFT 已生成"
    fi
    exit 0
fi

# ═══════════════════════════════════════════════════════
# 信号 1: needs-changes PR → 修复
# ═══════════════════════════════════════════════════════
NEEDS_FIX=$(gh pr list --label "junshi-review/needs-changes" --state open --limit 1 \
    --json number,headRefName,body --jq '.[0] | "\(.number) \(.headRefName)"' 2>/dev/null)
if [ -n "$NEEDS_FIX" ]; then
    PR_NUM=$(echo "$NEEDS_FIX" | awk '{print $1}')
    PR_BRANCH=$(echo "$NEEDS_FIX" | awk '{print $2}')
    ISSUE_ID=$(gh pr view "$PR_NUM" --json body --jq '.body' 2>/dev/null | grep -oP '(Closes|Fixes)\s+#\K\d+' | head -1)
    log "🔧 PR #$PR_NUM needs-changes → 修复"
    git fetch origin -- "$PR_BRANCH" && git checkout -- "$PR_BRANCH" 2>/dev/null
    git pull origin main 2>/dev/null || true
    claude --print --agent dev-agent \
        "PR #$PR_NUM (关联 issue #$ISSUE_ID) 被标记 needs-changes。读 CI 失败原因 → 修复 → 遵守项目铁律 → push $PR_BRANCH。" \
        2>&1 | tee -a /var/log/migao-agent-coding.log | tail -10
    log "✅ PR #$PR_NUM 修复完成"
    exit 0
fi

# ═══════════════════════════════════════════════════════
# 信号 2: 有 DRAFT_JSON + needs-redraft 次数 < 3 → 干活
# ═══════════════════════════════════════════════════════
ISSUE_ID=""
for iid in $(gh issue list --label needs-verification --state open --limit 15 \
    --json number,assignees --jq '.[] | select(.assignees | length == 0) | .number' 2>/dev/null); do
    # 必须有 DRAFT_JSON（等 OpenClaw 生成完）
    HAS_DRAFT=$(gh issue view "$iid" --comments --json comments \
        --jq '[.comments[] | select(.body | contains("DRAFT_JSON"))] | length' 2>/dev/null)
    if [ "${HAS_DRAFT:-0}" -eq 0 ]; then continue; fi
    # 熔断: needs-redraft 被打了 >=3 次 → 跳过（等人工）
    REDRAFT_COUNT=$(gh issue view "$iid" --comments --json comments \
        --jq '[.comments[] | select(.body | contains("REVIEW_JSON") and contains("\"reject\""))] | length' 2>/dev/null)
    if [ "${REDRAFT_COUNT:-0}" -ge 3 ]; then
        gh issue edit "$iid" --add-label "block/need-human" --remove-label "needs-verification" 2>/dev/null || true
        log "🛑 #$iid 已 reject $REDRAFT_COUNT 次，标记 block/need-human"
        continue
    fi
    ISSUE_ID="$iid"; break
done

if [ -z "$ISSUE_ID" ]; then
    log "😴 无待处理任务"; exit 0
fi

[[ "$ISSUE_ID" =~ ^[0-9]+$ ]] || { log "❌ 非法 ID: $ISSUE_ID"; exit 1; }

ISSUE_TITLE=$(gh issue view "$ISSUE_ID" --json title --jq '.title' 2>/dev/null | sed 's/[^a-zA-Z0-9一-鿿 -]//g' | tr ' ' '-' | head -c 40)
BRANCH="feat/issue-${ISSUE_ID}-${ISSUE_TITLE}"
git checkout -B "$BRANCH" 2>/dev/null
gh issue edit "$ISSUE_ID" --add-assignee "@me" 2>/dev/null || true
log "🌿 $BRANCH"

# 检查是否 skip_template
DRAFT=$(gh issue view "$ISSUE_ID" --comments --json comments \
    --jq '[.comments[] | select(.body | contains("DRAFT_JSON"))] | last | .body' 2>/dev/null || echo "")
SKIP=$(echo "$DRAFT" | grep -oP '"skip_template"\s*:\s*\K\w+' | head -1)

if [ "$SKIP" = "true" ]; then
    # ══ skip_template: 直接写码 ══
    log "⚡ skip_template → Phase 2 TDD"
    claude --print --agent dev-agent \
        "处理 issue #$ISSUE_ID。skip_template 模式，直接 TDD 写码。读 CONTRACT_JSON → 遵守项目铁律 → push $BRANCH → 创建 PR (Closes #$ISSUE_ID)。" \
        2>&1 | tee -a /var/log/migao-agent-coding.log | tail -10
    log "✅ 完成"
else
    # ══ 标准流程: Phase 1 Review → Phase 2 TDD ══
    log "🔍 Phase 1 Review..."
    claude --print --agent dev-agent \
        "Review issue #$ISSUE_ID。只做 Review，不写代码。
         1. 读 CONTRACT_JSON → business_truths
         2. 读最新 DRAFT_JSON → L2/L3/L4 case
         3. 逐条比对判定 accept/reject/supplement
         4. **用 gh issue comment 贴 <!-- REVIEW_JSON {action,issue_id,reason} -->**
         边界：不写代码、不跑测试、不建 PR。" \
        2>&1 | tee /var/log/migao-review-${ISSUE_ID}.log | tail -10

    # 读 Review 结果（机械提取 action）
    REVIEW_ACTION=$(grep -oP '"action"\s*:\s*"\K\w+' /var/log/migao-review-${ISSUE_ID}.log 2>/dev/null | tail -1 | tr '[:upper:]' '[:lower:]')
    REVIEW_ACTION=${REVIEW_ACTION:-reject}

    case "$REVIEW_ACTION" in
    accept|supplement)
        log "✅ Review $REVIEW_ACTION → Phase 2 TDD"
        claude --print --agent dev-agent \
            "处理 issue #$ISSUE_ID。REVIEW_JSON=$REVIEW_ACTION。读 CONTRACT_JSON + DRAFT_JSON → 遵守项目铁律 → push $BRANCH → 创建 PR (Closes #$ISSUE_ID)。" \
            2>&1 | tee -a /var/log/migao-agent-coding.log | tail -10
        ;;
    reject)
        log "❌ Review reject → needs-redraft"
        gh issue edit "$ISSUE_ID" --add-label "needs-redraft" --remove-assignee "@me" 2>/dev/null || true
        ;;
    esac
fi

log "✅ 调度完成"
