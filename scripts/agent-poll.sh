#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 米高研发 Agent 轮询 v6 — 自愈 + 可观测性
#
# Fix1: ERR trap 捕获崩溃 + gh_exec 记录失败
# Fix2: needs-changes 最多3次 → auto-release
# Fix3: 健康指标写入 /tmp/migao-agent-health.json
# Fix4: Phase2 无 PR → 释放 assignee + escalate after 2 tries
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

export HOME="${HOME:-/root}"
export PATH="/usr/local/bin:/usr/bin:/bin${PATH:+:$PATH}"

WORK_DIR="${WORK_DIR:-/opt/youke}"
LOCK_FILE="/tmp/migao-agent.lock"
HEALTH_FILE="/tmp/migao-agent-health.json"
START_TS=$(date +%s)
ERRORS=0

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }
err() { ERRORS=$((ERRORS+1)); log "❌ $1"; }

# ── Fix1: 崩溃捕获 ──
trap 'err "脚本异常退出 line=$LINENO exit=$?";
      echo "{\"last_run\":\"$(date -Iseconds)\",\"exit\":\"crash\",\"line\":$LINENO,\"errors\":$ERRORS,\"duration_s\":$(($(date +%s)-START_TS))}" > $HEALTH_FILE
      rm -f $LOCK_FILE' ERR
trap 'rm -f $LOCK_FILE
      echo "{\"last_run\":\"$(date -Iseconds)\",\"exit\":\"ok\",\"errors\":$ERRORS,\"duration_s\":$(($(date +%s)-START_TS))}" > $HEALTH_FILE' EXIT

# ── Fix1: gh_exec — 执行 gh 命令，失败时记日志 ──
gh_exec() {
    local output
    output=$("$@" 2>&1) || { err "gh $1 失败: ${output:0:200}"; return 1; }
    echo "$output"
}

if [ -f "$LOCK_FILE" ]; then
    LOCK_AGE=$(($(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0)))
    if [ "${LOCK_AGE:-0}" -gt 1800 ]; then
        log "⚠️ 锁超时 强制清除 (${LOCK_AGE}s)"; rm -f "$LOCK_FILE"
    else
        exit 0
    fi
fi
touch "$LOCK_FILE"

cd "$WORK_DIR"
gh auth status 2>/dev/null || { err "gh 未认证"; exit 1; }

git checkout main 2>/dev/null
git reset --hard HEAD 2>/dev/null
git clean -fd 2>/dev/null
git pull origin main 2>&1 | tail -1

# ═══════════════════════════════════════════════════════════
# 信号 0: needs-draft → 生成 DRAFT_JSON
# ═══════════════════════════════════════════════════════════
NEEDS_DRAFT=$(gh_exec gh issue list --label needs-draft --state open --limit 1 --json number --jq '.[0].number' || echo "")
if [ -n "$NEEDS_DRAFT" ] && [ "$NEEDS_DRAFT" != "null" ]; then
    [[ "$NEEDS_DRAFT" =~ ^[0-9]+$ ]] || { err "非法 NEEDS_DRAFT: $NEEDS_DRAFT"; exit 1; }

    VALID_DRAFT=$(gh_exec gh issue view "$NEEDS_DRAFT" --comments --json comments --jq '[.comments[] | select(.body | contains("<!-- DRAFT_JSON") and (contains("OUTDATED") | not))] | length' || echo "0")
    if [ "${VALID_DRAFT:-0}" -gt 0 ]; then
        log "⏭️ #$NEEDS_DRAFT 已有有效 DRAFT，移除 needs-draft"
        gh_exec gh issue edit "$NEEDS_DRAFT" --remove-label "needs-draft" || true
    else
        FEEDBACK=$(gh_exec gh issue view "$NEEDS_DRAFT" --comments --json comments --jq '[.comments[] | select(.body | contains("<!-- REVIEW_JSON") and contains("\"reject\""))] | last | .body' || echo "")
        if [ -n "$FEEDBACK" ]; then
            log "🔄 REJECT 重 draft for #$NEEDS_DRAFT"
            CONTEXT="这是 REJECT 后重新生成。上次被拒原因: $FEEDBACK。修正 L2/L3/L4。"
        else
            log "📝 初始 DRAFT for #$NEEDS_DRAFT"
            CONTEXT="这是新 issue 的初始 case draft。读 issue → 理解业务 → 生成。"
        fi
        claude --print --agent dev-agent \
            "任务：为 issue #$NEEDS_DRAFT 生成 case draft。$CONTEXT
## 步骤 1. gh issue view $NEEDS_DRAFT --json body,comments → 读 CONTRACT_JSON.business_truths 2. 理解业务领域 3. 参考 docs/verification-templates/ 选模板（前端UI→frontend-fix,skip_template=true）4. 用 gh issue comment 贴 DRAFT_JSON
## 格式 见 .claude/agents/dev-agent.md" \
            2>&1 | tail -5
        gh_exec gh issue edit "$NEEDS_DRAFT" --remove-label "needs-draft" || true
        log "✅ DRAFT 已生成"
    fi
    exit 0
fi

# ═══════════════════════════════════════════════════════════
# 信号 1: needs-changes PR → 修复（最多3次）
# Fix2: 超过3次 → auto-release + comment
# ═══════════════════════════════════════════════════════════
NEEDS_FIX=$(gh_exec gh pr list --label "junshi-review/needs-changes" --state open --limit 1 --json number,headRefName --jq '.[0] | "\(.number) \(.headRefName)"' || echo "")
if [ -n "$NEEDS_FIX" ] && [ "$NEEDS_FIX" != "null null" ]; then
    PR_NUM=$(echo "$NEEDS_FIX" | awk '{print $1}')
    PR_BRANCH=$(echo "$NEEDS_FIX" | awk '{print $2}')
    ISSUE_ID=$(gh_exec gh pr view "$PR_NUM" --json body --jq '.body' | grep -oP '(Closes|Fixes)\s+#\K\d+' | head -1 || echo "")

    if [ -z "$ISSUE_ID" ]; then
        log "⚠️ PR #$PR_NUM 无关联 issue，移除 needs-changes"
        gh_exec gh pr edit "$PR_NUM" --remove-label "junshi-review/needs-changes" || true
    else
        # Fix2: 检查修复尝试次数（通过 PR 上的 needs-changes 添加/移除次数）
        FIX_ATTEMPTS=$(gh_exec gh pr view "$PR_NUM" --json timelineItems --jq '[.timelineItems[] | select(.__typename=="LabeledEvent" and .label.name=="junshi-review/needs-changes")] | length' 2>/dev/null || echo "1")
        if [ "${FIX_ATTEMPTS:-1}" -ge 3 ]; then
            log "🛑 PR #$PR_NUM needs-changes 已达3次上限 → block/need-human"
            gh_exec gh pr comment "$PR_NUM" --body "## 🛑 二郎神熔断
PR 被标记 needs-changes ${FIX_ATTEMPTS} 次，agent 无法自动修复。请人工介入。
关联 issue: #$ISSUE_ID"
            gh_exec gh pr edit "$PR_NUM" --remove-label "junshi-review/needs-changes" || true
            gh_exec gh issue edit "$ISSUE_ID" --add-label "block/need-human" || true
        else
            log "🔧 PR #$PR_NUM needs-changes → 修复 (第${FIX_ATTEMPTS}次)"
            git fetch origin -- "$PR_BRANCH" 2>/dev/null && git checkout "$PR_BRANCH" 2>/dev/null
            git pull origin main 2>/dev/null || true
            claude --print --agent dev-agent \
                "PR #$PR_NUM (关联 issue #$ISSUE_ID) 被标记 needs-changes。读 CI 失败原因 → 修复 → 遵守项目铁律 → push $PR_BRANCH。" \
                2>&1 | tee -a /var/log/migao-agent-coding.log | tail -10
            log "✅ PR #$PR_NUM 修复完成 (尝试 ${FIX_ATTEMPTS}/3)"
        fi
    fi
    exit 0
fi

# ═══════════════════════════════════════════════════════════
# 信号 2: needs-verification → Review → TDD
# Fix4: Phase2 无 PR → 释放 assignee; 2次无PR → escalate
# ═══════════════════════════════════════════════════════════
ISSUE_ID=""
for iid in $(gh_exec gh issue list --label needs-verification --state open --limit 15 --json number,assignees --jq '.[] | select(.assignees | length == 0) | .number' || echo ""); do
    HAS_DRAFT=$(gh_exec gh issue view "$iid" --comments --json comments --jq '[.comments[] | select(.body | contains("DRAFT_JSON"))] | length' || echo "0")
    if [ "${HAS_DRAFT:-0}" -eq 0 ]; then continue; fi
    REDRAFT_COUNT=$(gh_exec gh issue view "$iid" --comments --json comments --jq '[.comments[] | select(.body | contains("REVIEW_JSON") and contains("\"reject\""))] | length' || echo "0")
    if [ "${REDRAFT_COUNT:-0}" -ge 3 ]; then
        gh_exec gh issue edit "$iid" --add-label "block/need-human" --remove-label "needs-verification" || true
        log "🛑 #$iid reject $REDRAFT_COUNT 次 → block/need-human"
        continue
    fi
    ISSUE_ID="$iid"; break
done

if [ -z "$ISSUE_ID" ]; then
    log "😴 无待处理任务"; exit 0
fi

[[ "$ISSUE_ID" =~ ^[0-9]+$ ]] || { err "非法 ID: $ISSUE_ID"; exit 1; }

ISSUE_TITLE=$(gh_exec gh issue view "$ISSUE_ID" --json title --jq '.title' | tr -cd '[:alnum:][:space:]-' | tr '[:space:]' '-' | tr -s '-' | head -c 40 || echo "issue")
BRANCH="feat/issue-${ISSUE_ID}-${ISSUE_TITLE}"
git checkout -B "$BRANCH" 2>/dev/null
gh_exec gh issue edit "$ISSUE_ID" --add-assignee "@me" || true
log "🌿 $BRANCH"

# Fix4: 记录 TDD 尝试次数
TDD_ATTEMPTS_FILE="/tmp/migao-tdd-attempts-$ISSUE_ID"
TDD_ATTEMPTS=$(cat "$TDD_ATTEMPTS_FILE" 2>/dev/null || echo "0")
TDD_ATTEMPTS=$((TDD_ATTEMPTS + 1))
echo "$TDD_ATTEMPTS" > "$TDD_ATTEMPTS_FILE"

DRAFT=$(gh_exec gh issue view "$ISSUE_ID" --comments --json comments --jq '[.comments[] | select(.body | contains("DRAFT_JSON"))] | last | .body' || echo "")
SKIP=$(echo "$DRAFT" | grep -oP '"skip_template"\s*:\s*\K\w+' | head -1)

if [ "$SKIP" = "true" ]; then
    log "⚡ skip_template → Phase 2 TDD"
    claude --print --agent dev-agent \
        "处理 issue #$ISSUE_ID。skip_template=true（前端简单改动），直接基于 CONTRACT_JSON.business_truths TDD 写码。读 CLAUDE.md + tdd-iron-law.md → Red→Green→Refactor → push $BRANCH → 创建 PR (Closes #$ISSUE_ID)。" \
        2>&1 | tee -a /var/log/migao-agent-coding.log | tail -10
else
    log "🔍 Phase 1 Review..."
    claude --print --agent dev-agent \
        "Review issue #$ISSUE_ID。只做 Review，不写代码。
1. 读 CONTRACT_JSON → business_truths
2. 读最新 DRAFT_JSON → L2/L3/L4 case
3. 逐条比对判定 accept/reject/supplement
4. **用 gh issue comment 贴 <!-- REVIEW_JSON {action,issue_id,reason} -->**
边界：不写代码、不跑测试、不建 PR。" \
        2>&1 | tee /var/log/migao-review-${ISSUE_ID}.log | tail -10

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
        gh_exec gh issue edit "$ISSUE_ID" --add-label "needs-redraft" --remove-assignee "@me" || true
        rm -f "$TDD_ATTEMPTS_FILE"
        exit 0
        ;;
    esac
fi

# Fix4: Phase2 后检查 PR 是否创建
HAS_PR=$(gh_exec gh pr list --head "$BRANCH" --state open --json number --jq '. | length' 2>/dev/null || echo "0")
if [ "${HAS_PR:-0}" -eq 0 ]; then
    if [ "$TDD_ATTEMPTS" -ge 2 ]; then
        log "🛑 #$ISSUE_ID TDD 失败 ${TDD_ATTEMPTS}次 → block/need-human"
        gh_exec gh issue edit "$ISSUE_ID" --add-label "block/need-human" --remove-assignee "@me" || true
        gh_exec gh issue comment "$ISSUE_ID" --body "## 🛑 二郎神熔断
Phase 2 TDD 尝试 ${TDD_ATTEMPTS} 次均未创建 PR。可能原因: 业务过于复杂需人工拆分、依赖环境缺失、或代码变更冲突。请人工介入。" || true
        rm -f "$TDD_ATTEMPTS_FILE"
    else
        log "⚠️ #$ISSUE_ID Phase2 未创建 PR (第${TDD_ATTEMPTS}次)，释放 assignee"
        gh_exec gh issue edit "$ISSUE_ID" --remove-assignee "@me" || true
    fi
else
    rm -f "$TDD_ATTEMPTS_FILE"
    log "✅ PR 已创建"
fi

log "✅ 调度完成"
