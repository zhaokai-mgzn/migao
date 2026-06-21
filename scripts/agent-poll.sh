#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 米高研发 Agent 轮询 v4 — LLM 调度，bash 仅执行
#
# bash 职责：lock / git / 收集状态 / 执行 LLM 决策
# LLM 职责：抢 issue / 判定 / 决定下一步
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

export HOME="${HOME:-/root}"
export PATH="/usr/local/bin:/usr/bin:/bin${PATH:+:$PATH}"

WORK_DIR="${WORK_DIR:-/opt/youke}"
LOCK_FILE="/tmp/migao-agent.lock"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }

# ── 锁文件（30 分钟超时）──
if [ -f "$LOCK_FILE" ]; then
    LOCK_AGE=$(($(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0)))
    if [ "${LOCK_AGE:-0}" -gt 1800 ]; then
        log "⚠️ 锁文件超过30分钟，强制清除"; rm -f "$LOCK_FILE"
    else
        log "⚠️ 上一个任务还在跑 (${LOCK_AGE}s)，跳过"; exit 0
    fi
fi
trap "rm -f $LOCK_FILE" EXIT
touch "$LOCK_FILE"

cd "$WORK_DIR"

if ! gh auth status 2>/dev/null; then
    log "❌ gh 未认证"; exit 1
fi

# ── 同步代码 ──
git checkout main 2>/dev/null
git reset --hard HEAD 2>/dev/null
git clean -fd 2>/dev/null
git pull origin main 2>&1 | tail -1

# ── Step 1: 收集状态（纯机械，无判断逻辑）──
log "🔍 扫描..."

ISSUE_STATE=$(gh issue list --label needs-verification --state open --limit 10 \
    --json number,title,labels,assignees 2>/dev/null || echo "[]")
PR_STATE=$(gh pr list --label "junshi-review/needs-changes" --state open --limit 5 \
    --json number,title,headRefName,body 2>/dev/null || echo "[]")

# 为候选 issue 抓取最新评论（DRAFT_JSON + REVIEW_JSON）
COMMENTS_JSON="{}"
for iid in $(echo "$ISSUE_STATE" | python3 -c "import sys,json; [print(i['number']) for i in json.load(sys.stdin)]" 2>/dev/null); do
    CISSUE=$(gh issue view "$iid" --comments --json comments 2>/dev/null || echo "{}")
    COMMENTS_JSON=$(echo "$COMMENTS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); d['$iid']=json.loads('$CISSUE'); print(json.dumps(d))" 2>/dev/null || echo "$COMMENTS_JSON")
done

# ── Step 2: LLM 调度（所有判断逻辑）──
DECISION=$(claude --print --agent orchestrator \
    "决定下一步动作。返回纯 JSON。

     ISSUE_STATE: $ISSUE_STATE
     PR_STATE: $PR_STATE
     COMMENTS: $COMMENTS_JSON

     优先级:
     1. fix_pr — PR 有 junshi-review/needs-changes
     2. write_code — DRAFT_JSON.skip_template=true
     3. review_draft — 有 DRAFT_JSON 无 REVIEW_JSON
     4. skip" 2>/dev/null || echo '{"action":"skip"}')

ACTION=$(echo "$DECISION" | python3 -c "import sys,json; print(json.load(sys.stdin).get('action','skip'))" 2>/dev/null || echo "skip")
ISSUE_ID=$(echo "$DECISION" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('issue_id',''))" 2>/dev/null || echo "")
PR_NUMBER=$(echo "$DECISION" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('pr_number',''))" 2>/dev/null || echo "")

log "📋 LLM: action=$ACTION issue=$ISSUE_ID"

# ── Step 3: 执行 LLM 决策（bash 只做机械操作）──
case "$ACTION" in

fix_pr)
    PR_BRANCH=$(gh pr view "$PR_NUMBER" --json headRefName --jq '.headRefName' 2>/dev/null)
    log "🔧 PR #$PR_NUMBER needs-changes → 修复"
    git fetch origin "$PR_BRANCH" && git checkout "$PR_BRANCH" 2>/dev/null
    git pull origin main 2>/dev/null || true
    claude --print --agent dev-agent \
        "PR #$PR_NUMBER (关联 issue #$ISSUE_ID) 被标记 needs-changes。读 PR 评论和 CI 失败原因 → 修复 → 遵守项目铁律 → push $PR_BRANCH。" \
        2>&1 | tee -a /var/log/migao-agent-coding.log | tail -10
    log "✅ PR #$PR_NUMBER 修复完成"
    ;;

review_draft)
    ISSUE_TITLE=$(gh issue view "$ISSUE_ID" --json title --jq '.title' 2>/dev/null | sed 's/[^a-zA-Z0-9一-鿿 -]//g' | tr ' ' '-' | head -c 40)
    BRANCH="feat/issue-${ISSUE_ID}-${ISSUE_TITLE}"
    git checkout -B "$BRANCH" 2>/dev/null
    gh issue edit "$ISSUE_ID" --add-assignee "@me" 2>/dev/null || true
    log "🌿 $BRANCH"

    # Phase 1: Review
    log "🔍 Phase 1 Review..."
    claude --print --agent dev-agent \
        "Review issue #$ISSUE_ID。只做 Review，不写代码。
         1. 读 CONTRACT_JSON → business_truths
         2. 读最新 DRAFT_JSON comment → L2/L3/L4 case
         3. 逐条比对：每条 truth 是否有 case 覆盖
         4. 判定 accept/reject/supplement
         5. **必须用 gh issue comment 贴下面的块**：
         <!-- REVIEW_JSON {\"action\":\"accept|reject|supplement\",\"issue_id\":$ISSUE_ID,\"reason\":\"...\"} -->
         边界：不写代码、不跑测试、不建 PR。" \
        2>&1 | tee /var/log/migao-review-$ISSUE_ID.log | tail -10

    # LLM 读 review 输出，判定最终动作
    REVIEW_LOG=$(cat /var/log/migao-review-$ISSUE_ID.log 2>/dev/null || echo "")
    FOLLOWUP=$(claude --print --agent orchestrator \
        "读取 Phase 1 Review 输出，判定 accept/supplement/reject。
         REVIEW_LOG: $REVIEW_LOG
         返回纯 JSON: {\"action\":\"accept|supplement|reject\",\"issue_id\":$ISSUE_ID,\"reason\":\"...\"}" 2>/dev/null || echo '{"action":"reject"}')
    FOLLOWUP_ACTION=$(echo "$FOLLOWUP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('action','reject'))" 2>/dev/null || echo "reject")

    case "$FOLLOWUP_ACTION" in
    accept|supplement)
        log "✅ Review $FOLLOWUP_ACTION → Phase 2 TDD"
        claude --print --agent dev-agent \
            "处理 issue #$ISSUE_ID。REVIEW_JSON=$FOLLOWUP_ACTION。读 CONTRACT_JSON + DRAFT_JSON → 遵守项目铁律 → push $BRANCH → 创建 PR (Closes #$ISSUE_ID)。" \
            2>&1 | tee -a /var/log/migao-agent-coding.log | tail -10
        ;;
    reject)
        log "❌ Review reject → needs-redraft"
        gh issue edit "$ISSUE_ID" --add-label "needs-redraft" --remove-assignee "@me" 2>/dev/null || true
        ;;
    esac
    ;;

write_code)
    ISSUE_TITLE=$(gh issue view "$ISSUE_ID" --json title --jq '.title' 2>/dev/null | sed 's/[^a-zA-Z0-9一-鿿 -]//g' | tr ' ' '-' | head -c 40)
    BRANCH="feat/issue-${ISSUE_ID}-${ISSUE_TITLE}"
    git checkout -B "$BRANCH" 2>/dev/null
    gh issue edit "$ISSUE_ID" --add-assignee "@me" 2>/dev/null || true
    log "🌿 $BRANCH"
    log "⚡ skip_template → Phase 2 TDD"
    claude --print --agent dev-agent \
        "处理 issue #$ISSUE_ID。skip_template 模式，直接 TDD 写码。读 CONTRACT_JSON → 遵守项目铁律 → push $BRANCH → 创建 PR (Closes #$ISSUE_ID)。" \
        2>&1 | tee -a /var/log/migao-agent-coding.log | tail -10
    log "✅ skip_template Phase 2 完成"
    ;;

skip)
    log "😴 无待处理任务"
    ;;

esac

log "✅ 调度完成"
