#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 米高研发 Agent 轮询触发器（单实例版，适配 4C8G）
#
# cron 每 5 分钟执行。一次只处理一个 issue。
# 优先抢修复 issue，其次抢新功能 issue。
# 不直接处理 block/dual-mismatch 标签的原始 issue（那是军师的状态标记）。
#
# 注意：验收由 verify-poll.sh 独立执行（claude --agent verify-agent），本脚本只负责写码。
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
    git reset --hard HEAD 2>/dev/null
    git clean -fd 2>/dev/null
    git fetch origin "$PR_BRANCH" && git checkout "$PR_BRANCH" 2>/dev/null
    git pull origin main 2>/dev/null

    claude --print \
        --agent dev-agent \
        "PR #$PR_NUM (关联 issue #$ISSUE_ID) 被军师标记 needs-changes。读 PR 评论 → 修复 → 遵守项目铁律 (CLAUDE.md + tdd-iron-law.md) → push 到当前分支 $PR_BRANCH。" \
        2>&1 | tee -a /var/log/migao-agent-coding.log | tail -10

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

    # 找模板补充类 issue（有 qa 标签的不需要 case_draft）
    local TEMPLATE=$(gh issue list --label "needs-verification,qa" --state open --limit 10 \
        --json number,assignees --jq '.[] | select(.assignees | length == 0) | .number' 2>/dev/null | head -1)
    if [ -n "$TEMPLATE" ]; then
        echo "$TEMPLATE"
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
    log "😴 无待处理 issue，跳过"
else

# ── 启动服务前先拉最新代码 ──
log "📥 同步最新代码..."
git reset --hard HEAD 2>/dev/null
git clean -fd 2>/dev/null
git checkout main 2>/dev/null
git pull origin main 2>&1 | tail -1

# 创建 issue 专用分支
ISSUE_TITLE=$(gh issue view "$ISSUE_ID" --json title --jq '.title' 2>/dev/null | sed 's/[^a-zA-Z0-9一-鿿 -]//g' | tr ' ' '-' | head -c 40)
BRANCH="feat/issue-${ISSUE_ID}-${ISSUE_TITLE}"
git checkout -B "$BRANCH" 2>/dev/null
log "🌿 分支: $BRANCH"

# ── 按需启动服务，任务结束后自动关闭 ──

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
        --agent dev-agent \
        "issue #$ISSUE_ID 验收被阻。读 BLOCK_LOG 评论理解失败原因 → 查 SLS 日志定位根因 → 修复代码 → 遵守项目铁律 (CLAUDE.md + tdd-iron-law.md) → 推送到当前分支 $BRANCH → 创建 PR (Closes #$ISSUE_ID)。" \
        2>&1 | tee -a /var/log/migao-agent-coding.log | tail -10
	else
	    log "📝 新功能 issue #$ISSUE_ID"
	    # 检查是否为模板补充任务（不需要 case review）
	    IS_TEMPLATE=$(gh issue view "$ISSUE_ID" --json labels --jq '.labels[].name' 2>/dev/null | grep -c "qa" || true)
	    if [ "${IS_TEMPLATE:-0}" -gt 0 ]; then
	        PROMPT="处理 issue #$ISSUE_ID（模板补充任务）。读 CONTRACT_JSON → 按铁律 (CLAUDE.md) 修改模板 YAML → 推送到 $BRANCH → 创建 PR (Closes #$ISSUE_ID)。"
	        claude --print \
	            --agent dev-agent \
	            "$PROMPT" \
	            2>&1 | tee -a /var/log/migao-agent-coding.log | tail -10
	    else
	        # ══ Phase 0: bash 客观 gate（客观标准，不靠 LLM 自觉）══
	        DRAFT=$(gh issue view "$ISSUE_ID" --comments --json comments \
	            --jq '[.comments[] | select(.body | contains("DRAFT_JSON"))] | last | .body' 2>/dev/null)
	        TRUTHS_COUNT=$(echo "$DRAFT" | grep -oP '"truths_count"\s*:\s*\K\d+' | head -1)
	        AUTO_ASSERTS=$(echo "$DRAFT" | grep -oP '"auto_asserts"\s*:\s*\K\d+' | head -1)
	        TEMPLATE_NAME=$(echo "$DRAFT" | grep -oP '"template"\s*:\s*"\K[^"]+' | head -1)

	        if [ "${TRUTHS_COUNT:-0}" -eq 0 ]; then
	            log "❌ 业务真值为空 — bash gate reject"
	            exit 0
	        fi
	        if [ "$TEMPLATE_NAME" = "unknown" ] || [ -z "$TEMPLATE_NAME" ]; then
	            log "❌ 未匹配模板(${TEMPLATE_NAME:-none}) — bash gate reject"
	            exit 0
	        fi
	        if [ "${AUTO_ASSERTS:-0}" -lt "${TRUTHS_COUNT:-1}" ]; then
	            log "❌ 自动断言(${AUTO_ASSERTS:-0}) < 真值(${TRUTHS_COUNT:-0}) — bash gate reject"
	            exit 0
	        fi
	        log "✅ bash gate pass: ${AUTO_ASSERTS:-0} asserts >= ${TRUTHS_COUNT:-0} truths, template=$TEMPLATE_NAME"

	        # ══ Phase 1: LLM Review（bash gate 通过后才到 LLM）══
	        log "🔍 Phase 1: LLM Review case 草稿..."
	        claude --print \
	            --agent dev-agent \
	            "Review issue #$ISSUE_ID。只做 Review，不写代码。

## 步骤
1. 读 CONTRACT_JSON 中的 business_truths
2. 读 DRAFT_JSON → 理解 L2/L3/L4 case
3. 逐条比对：每条真值是否有 case 覆盖
4. 判定 accept/reject/supplement
5. 贴 REVIEW_JSON + 停止

## REVIEW_JSON 格式
\`\`\`
<!-- REVIEW_JSON {\"action\":\"accept|reject|supplement\",\"issue_id\":$ISSUE_ID,\"reason\":\"...\"} -->
\`\`\`

边界：不写代码、不跑测试、不建 PR。这是硬 gate。" \
	            2>&1 | tee -a /var/log/migao-agent-review.log | tail -10

	        # ══ 检查 REVIEW_JSON 结果 ══
	        REVIEW_BODY=$(gh issue view "$ISSUE_ID" --comments --json comments \
	            --jq '[.comments[] | select(.body | contains("<!-- REVIEW_JSON"))] | last | .body' 2>/dev/null)
	        REVIEW_ACTION=$(echo "$REVIEW_BODY" | grep -oP '"action"\s*:\s*"\K\w+' | head -1)

		        # Agent 没贴 REVIEW_JSON comment → 从日志提取 action
		        if [ -z "$REVIEW_ACTION" ]; then
		            REVIEW_ACTION=$(grep -oP '"action"\\s*:\\s*"\\K\\w+' /var/log/migao-agent-review.log 2>/dev/null | tail -1)
		            log "⚠️ Agent 未贴 REVIEW_JSON comment，从日志提取: action=$REVIEW_ACTION"
		        fi

	        if [ "$REVIEW_ACTION" = "accept" ]; then
	            log "✅ Review accept → Phase 2: TDD 写码"
	            claude --print \
	                --agent dev-agent \
	                "处理 issue #$ISSUE_ID。REVIEW_JSON 已 accept，直接 TDD 写码。
	                读 CONTRACT_JSON 和 DRAFT_JSON → 遵守项目铁律 (CLAUDE.md + tdd-iron-law.md) → 推送到 $BRANCH → 创建 PR (Closes #$ISSUE_ID)。" \
	                2>&1 | tee -a /var/log/migao-agent-coding.log | tail -10
	        elif [ "$REVIEW_ACTION" = "supplement" ]; then
	            log "⚠️ Review supplement — 跳过，等军师补 case"
	            exit 0
	        else
	            log "❌ Review reject — 跳过写码"
	            exit 0
	        fi
	    fi
	fi
fi
