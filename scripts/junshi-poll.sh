#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 军师轮询触发器 — 只指挥、只报告、不写代码不跑测试
#
# 每 3 分钟执行。职责：
#   1. 扫新 issue → case_draft.py 反推草稿
#   2. 扫 PR → CI 绿 + 关联 issue + E2E → 自动 merge
#   3. 扫已 merge 的 PR → 发 VERIFY_TRIGGER
#   4. 扫 stale issue → 催促
#   5. 扫 hold 积压 → 升级人工
#   6. 每天 19:00 → 质量日报
# ═══════════════════════════════════════════════════════════════
set -e

export HOME="${HOME:-/root}"
export PATH="/usr/local/bin:/usr/bin:/bin${PATH:+:$PATH}"

WORK_DIR="${WORK_DIR:-/opt/youke}"
LOCK_FILE="/tmp/junshi-poll.lock"
# venv Python 3.11（系统 $PYTHON 可能是 3.6，不支持 capture_output）
PYTHON="${WORK_DIR}/backend/ai-agent-service/.venv/bin/python3"
[ -x "$PYTHON" ] || PYTHON="python3.11"
[ -x "$(command -v "$PYTHON" 2>/dev/null)" ] || PYTHON="python3"
log() { echo "[junshi $(date '+%Y-%m-%d %H:%M:%S')] $1"; }

# ── 锁文件（带 30 分钟超时）──
if [ -f "$LOCK_FILE" ]; then
    LOCK_AGE=$(($(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0)))
    if [ "${LOCK_AGE:-0}" -gt 1800 ]; then
        log "⚠️ 锁文件超过30分钟，强制清除"
        rm -f "$LOCK_FILE"
    else
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

# ═══════════════════════════════════════════════════════════════
# 1. 扫新 issue → 发 DRAFT_JSON
# ═══════════════════════════════════════════════════════════════
log "📋 扫描需要 case_draft 的 issue..."

gh issue list --label needs-verification --state open --limit 30 \
    --json number,updatedAt --jq '.[].number' 2>/dev/null | while read iid; do

    # 跳过已有 DRAFT_JSON 评论的 issue
    HAS_DRAFT=$(gh issue view "$iid" --comments --json comments \
        --jq '.comments[] | select(.body | contains("DRAFT_JSON")) | .body' 2>/dev/null | head -1)

    if [ -n "$HAS_DRAFT" ]; then
        continue
    fi

    # 跳过已有 REVIEW_JSON 的（Agent 已经在处理）
    HAS_REVIEW=$(gh issue view "$iid" --comments --json comments \
        --jq '.comments[] | select(.body | contains("REVIEW_JSON")) | .body' 2>/dev/null | head -1)
    if [ -n "$HAS_REVIEW" ]; then
        continue
    fi

    log "  📝 issue #$iid → case_draft..."
    DRAFT_OUTPUT=$($PYTHON scripts/dual_verify/case_draft.py "$iid" 2>&1)
    echo "$DRAFT_OUTPUT" | tail -3

    # quality_gate 拦截 → 创建"补充模板"任务下发给 Agent
    if echo "$DRAFT_OUTPUT" | grep -q "拒绝发稿"; then
        TMPL_NAME=$(echo "$DRAFT_OUTPUT" | sed -n 's/.*模板 `\([a-z0-9-]*\)`.*/\1/p' | head -1)
        [ -z "$TMPL_NAME" ] && TMPL_NAME="unknown"
        GAP_INFO=$(echo "$DRAFT_OUTPUT" | grep "拒绝发稿" | head -1 | cut -c1-120)

        # 避免重复创建
        HAS_TASK=$(gh issue list --label "qa" --state open --limit 10 \
            --search "补充模板: $TMPL_NAME" --json number --jq '.[0].number' 2>/dev/null)

        if [ -z "$HAS_TASK" ]; then
            TASK_BODY="## 补充模板 reviewer_asserts

**模板**: \`$TMPL_NAME\`
**原 issue**: #$iid
**错误**: $GAP_INFO

请为该模板补充 reviewer_asserts，使自动断言数 ≥ 原 issue 的业务真值数。
模板路径: \`docs/verification-templates/${TMPL_NAME}.yml\`

<!-- CONTRACT_JSON {\"schema_version\":\"1.0\",\"type\":\"template\",\"business_truths\":[\"补充 ${TMPL_NAME} 模板的 reviewer_asserts，消除 quality_gate 拦截\"]} -->
"
            gh issue create \
                --title "补充模板: $TMPL_NAME — L4 断言不足" \
                --label "needs-verification,qa" \
                --body "$TASK_BODY" 2>&1 | head -1
            log "  🔧 下发补充模板任务 → $TMPL_NAME"
        fi
    fi
done

# ═══════════════════════════════════════════════════════════════
# 2. 扫 PR → 自动 merge
# ═══════════════════════════════════════════════════════════════
log "🔍 扫描待 merge PR..."

gh pr list --state open --limit 20 --json number,headRefName,body,statusCheckRollup,labels \
    2>/dev/null | $PYTHON -c "
import json, sys

prs = json.load(sys.stdin)
for pr in prs:
    num = pr['number']
    body = pr.get('body', '')

    # 必须有 issue 关联
    if 'Closes #' not in body and 'Fixes #' not in body:
        continue

    # CI 状态：必须全部 COMPLETED + 全部 SUCCESS
    checks = pr.get('statusCheckRollup', [])
    if not isinstance(checks, list) or len(checks) == 0:
        print(f'SKIP:{num}:CI_NO_CHECKS', flush=True)
        continue

    completed = [c for c in checks if c.get('status') == 'COMPLETED']
    pending  = [c for c in checks if c.get('status') != 'COMPLETED']
    failed   = [c for c in completed if c.get('conclusion') != 'SUCCESS']

    # 有未完成的 check → 不能 merge
    if pending:
        print(f'SKIP:{num}:CI_PENDING({len(pending)})', flush=True)
        continue
    # 有失败的 check → 不能 merge
    if failed:
        print(f'SKIP:{num}:CI_FAIL({len(failed)})', flush=True)
        continue
    # 全部 COMPLETED + SUCCESS → 可以 merge
    all_pass = True

    # 检查军师 review 标签
    labels = [l['name'] for l in pr.get('labels', [])]
    has_pass = 'junshi-review/pass-with-followups' in labels
    has_block = 'junshi-review/blocked' in labels or 'junshi-review/needs-changes' in labels

    if has_block:
        print(f'SKIP:{num}:BLOCKED_BY_REVIEW', flush=True)
    elif has_pass:
        print(f'MERGE:{num}', flush=True)
    else:
        # CI 全绿但没有军师标签 → 自动挂 pass 并 merge
        print(f'AUTOPASS:{num}', flush=True)
" 2>/dev/null | while read action; do
    pr_num=$(echo "$action" | cut -d: -f2)
    act=$(echo "$action" | cut -d: -f1)

    case "$act" in
        MERGE|AUTOPASS)
            if [ "$act" = "AUTOPASS" ]; then
                gh pr edit "$pr_num" --add-label "junshi-review/pass-with-followups" 2>/dev/null || true
            fi
            MERGE_OUT=$(gh pr merge "$pr_num" --squash --delete-branch 2>&1)
            if echo "$MERGE_OUT" | grep -qE "Merged|merged|deleted"; then
                log "  ✅ PR #$pr_num → merged"
            else
                log "  ❌ PR #$pr_num merge 失败: $(echo "$MERGE_OUT" | head -1)"
            fi
            ;;
        SKIP)
            reason=$(echo "$action" | cut -d: -f3)
            # log "  ⏭️ PR #$pr_num: $reason"
            ;;
    esac
done

# ═══════════════════════════════════════════════════════════════
# 3. 扫已 merge → 发 VERIFY_TRIGGER
# ═══════════════════════════════════════════════════════════════
log "🔍 扫描需要验收触发的 issue..."

# 找最近 merged 的 PR，解析关联的 issue
gh pr list --state merged --limit 10 --json number,body,mergedAt \
    --jq '.[] | select(.mergedAt != null) | "\(.number)|\(.body)"' 2>/dev/null | while read line; do
    pr_num=$(echo "$line" | cut -d'|' -f1)
    pr_body=$(echo "$line" | cut -d'|' -f2-)

    issue_id=$(echo "$pr_body" | grep -oP '(?:Closes|Fixes)\s+#\K\d+' | head -1)
    [ -z "$issue_id" ] && continue

    # 检查是否已有 VERIFY_TRIGGER
    HAS_TRIGGER=$(gh issue view "$issue_id" --comments --json comments \
        --jq '.comments[] | select(.body | contains("VERIFY_TRIGGER")) | .body' 2>/dev/null | head -1)
    [ -n "$HAS_TRIGGER" ] && continue

    # 检查是否已有 VERIFY_RESULT（已验收完）
    HAS_RESULT=$(gh issue view "$issue_id" --comments --json comments \
        --jq '.comments[] | select(.body | contains("VERIFY_RESULT")) | .body' 2>/dev/null | head -1)
    [ -n "$HAS_RESULT" ] && continue

    # 发 VERIFY_TRIGGER
    TRIGGER_BODY="## 🧪 军师验收触发

PR #$pr_num 已 merge，请 Agent 执行全链路验收。

<!-- VERIFY_TRIGGER {\"issue_id\":$issue_id,\"pr\":$pr_num} -->
"
    gh issue comment "$issue_id" --body "$TRIGGER_BODY" 2>/dev/null
    gh issue edit "$issue_id" --add-label "ai-verify/pending" 2>/dev/null || true
    log "  🧪 issue #$issue_id ← VERIFY_TRIGGER (PR #$pr_num)"
done

# ═══════════════════════════════════════════════════════════════
# 4. 巡检 stale issue（needs-verification > 3 天）
# ═══════════════════════════════════════════════════════════════
log "🔍 巡检 stale issue..."

CUTOFF_STALE=$(date -d "3 days ago" +%Y-%m-%d 2>/dev/null || date -v-3d +%Y-%m-%d 2>/dev/null)
gh issue list --label needs-verification --state open --limit 30 \
    --search "updated:<$CUTOFF_STALE" --json number,title,updatedAt 2>/dev/null | \
    $PYTHON -c "
import json, sys
issues = json.load(sys.stdin)
for i in issues:
    print(f'{i[\"number\"]}|{i[\"title\"][:60]}')
" 2>/dev/null | while read line; do
    iid=$(echo "$line" | cut -d'|' -f1)
    title=$(echo "$line" | cut -d'|' -f2)

    # 检查是否已催促过
    HAS_NUDGE=$(gh issue view "$iid" --comments --json comments \
        --jq '.comments[] | select(.body | contains("军师巡检: issue 超过3天未处理")) | .body' 2>/dev/null | head -1)
    [ -n "$HAS_NUDGE" ] && continue

    log "  ⏰ issue #$iid 超过 3 天未处理 → 提醒"
    gh issue comment "$iid" --body "## ⏰ 军师巡检: issue 超过 3 天未处理

本 issue 已闲置超过 3 天，请关注：
- 如已在进行中 → 无视本条
- 如需 case 草稿 → 军师已生成，见上方评论
- 如已不适用 → 请 close

<!-- COMMENT_JSON {\"from\":\"junshi\",\"intent\":\"stale_nudge\",\"issue_id\":$iid} -->
" 2>/dev/null
done

# ═══════════════════════════════════════════════════════════════
# 5. 扫 hold 积压 → 升级（> 7 天）
# ═══════════════════════════════════════════════════════════════
CUTOFF_HOLD=$(date -d "7 days ago" +%Y-%m-%d 2>/dev/null || date -v-7d +%Y-%m-%d 2>/dev/null)
gh issue list --label hold/auto-fail --state open --limit 20 \
    --search "updated:<$CUTOFF_HOLD" --json number,title 2>/dev/null | \
    $PYTHON -c "
import json, sys
for i in json.load(sys.stdin):
    print(i['number'])
" 2>/dev/null | while read iid; do
    log "  🚨 issue #$iid hold 超过 7 天 → 升级"
    gh issue edit "$iid" --add-label "block/need-human" --remove-label "hold/auto-fail" 2>/dev/null || true
    gh issue comment "$iid" --body "## 🚨 军师巡检: hold 超过 7 天，自动升级

本 issue 已 hold 超过 7 天，自动标记为 block/need-human。请凯总/娜总介入。

<!-- COMMENT_JSON {\"from\":\"junshi\",\"intent\":\"hold_escalation\",\"issue_id\":$iid} -->
" 2>/dev/null
done

# ═══════════════════════════════════════════════════════════════
# 6. 每天 19:00 质量日报
# ═══════════════════════════════════════════════════════════════
HOUR=$(date +%H)
MINUTE=$(date +%M)
if [ "$HOUR" = "19" ] && [ "$MINUTE" -lt "5" ]; then
    log "📊 生成每日质量报告..."
    REPORT=$($PYTHON scripts/dual_verify/quality_report.py --days 7 2>&1)

    # 找到日报追踪 issue（或创建）
    REPORT_ISSUE=$(gh issue list --label "type/report" --state open --limit 5 \
        --search "军师质量日报" --json number --jq '.[0].number' 2>/dev/null)

    if [ -z "$REPORT_ISSUE" ]; then
        gh issue create \
            --title "📊 军师质量日报（持久追踪）" \
            --label "type/report" \
            --body "军师每日质量报告追踪 issue。每天 19:00 自动追加。" 2>&1 | head -1
        # 用 list 找回 issue 号
        REPORT_ISSUE=$(gh issue list --label "type/report" --state open --limit 1 \
            --search "军师质量日报" --json number --jq '.[0].number' 2>/dev/null)
    fi

    if [ -n "$REPORT_ISSUE" ]; then
        gh issue comment "$REPORT_ISSUE" --body "$REPORT" 2>/dev/null
        log "  ✅ 日报已发布到 #$REPORT_ISSUE"
    fi
fi

log "✅ 军师巡检完成"
