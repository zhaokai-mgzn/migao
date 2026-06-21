#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 米高二郎神验收轮询 v5 — AI First: 只看信号，不做决策
#
# OpenClaw 发 VERIFY_TRIGGER → verify-poll 执行验收
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

export HOME="${HOME:-/root}"
export PATH="/usr/local/bin:/usr/bin:/bin${PATH:+:$PATH}"

WORK_DIR="${WORK_DIR:-/opt/youke}"
LOCK_FILE="/tmp/migao-verify.lock"
log() { echo "[verify $(date '+%Y-%m-%d %H:%M:%S')] $1"; }

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
git pull origin main 2>&1 | tail -1 || true

# ── 服务管理 ──
start_services() {
    log "🚀 启动服务..."
    export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-21}"
    if [ -f /opt/youke/backend/admin-api/.env ]; then
        export $(grep -E '^(RDS_|REDIS_)' /opt/youke/backend/admin-api/.env | xargs)
    fi
    cd /opt/youke/backend/admin-api && nohup ./mvnw spring-boot:run -q -Dspring-boot.run.arguments='--server.port=8081' > /var/log/migao-admin-api.log 2>&1 & echo $! > /tmp/migao-verify-admin-api.pid
    cd /opt/youke/backend/ai-agent-service && nohup .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 > /var/log/migao-ai-agent.log 2>&1 & echo $! > /tmp/migao-verify-ai-agent.pid
    cd /opt/youke/frontend/admin-web && nohup npm run dev > /var/log/migao-admin-web.log 2>&1 & echo $! > /tmp/migao-verify-admin-web.pid
    sleep 30
}
stop_services() {
    log "🛑 关闭服务..."
    for f in /tmp/migao-verify-admin-api.pid /tmp/migao-verify-ai-agent.pid /tmp/migao-verify-admin-web.pid; do
        [ -f "$f" ] && { kill $(cat "$f") 2>/dev/null || true; rm -f "$f"; }
    done
}

# ═══════════════════════════════════════════════════════
# 扫描: 有 VERIFY_TRIGGER 无 VERDICT_JSON → 验收
# ═══════════════════════════════════════════════════════
log "🔍 扫描待验收..."

VERIFY_ISSUE=""
SCAN_IDS=$( {
    gh issue list --label ai-verify/pending --state open --limit 20 --json number --jq '.[].number' 2>/dev/null
    gh issue list --label ai-verify/pending --state closed --limit 20 --json number --jq '.[].number' 2>/dev/null
} | sort -u)
for iid in $SCAN_IDS; do
    HAS_TRIGGER=$(gh issue view "$iid" --comments --json comments \
        --jq '[.comments[] | select(.body | contains("VERIFY_TRIGGER"))] | length' 2>/dev/null)
    HAS_VERDICT=$(gh issue view "$iid" --comments --json comments \
        --jq '[.comments[] | select(.body | contains("<!-- VERDICT_JSON"))] | length' 2>/dev/null)

    # 死循环检测: >=3 条 VERDICT_JSON 且最后一条是 hold → escalate
    if [ "${HAS_VERDICT:-0}" -ge 3 ]; then
        LAST_DECISION=$(gh issue view "$iid" --comments --json comments \
            --jq '[.comments[] | select(.body | contains("<!-- VERDICT_JSON"))] | last | .body' 2>/dev/null)
        if echo "$LAST_DECISION" | grep -q '"decision".*"hold"'; then
            log "🚨 #$iid 连续 3+ 次 HOLD → 死循环，标记 block/need-human"
            gh issue comment "$iid" --body "## 🚨 二郎神死循环检测
连续 3+ 次验收返回 HOLD，自动升级为 block/need-human。请人工介入。"
            gh issue edit "$iid" --add-label "block/need-human" --remove-label "ai-verify/pending" 2>/dev/null || true
            continue
        fi
    fi

    if [ "${HAS_TRIGGER:-0}" -gt 0 ] && [ "${HAS_VERDICT:-0}" -eq 0 ]; then
        VERIFY_ISSUE="$iid"; break
    fi
done

if [ -z "$VERIFY_ISSUE" ]; then
    log "😴 无待验收 issue"; exit 0
fi

[[ "$VERIFY_ISSUE" =~ ^[0-9]+$ ]] || { log "❌ 非法 ID"; exit 1; }
log "🧪 验收 issue #$VERIFY_ISSUE"

# reopen if closed by PR
ISSUE_STATE=$(gh issue view "$VERIFY_ISSUE" --json state --jq '.state' 2>/dev/null)
[ "$ISSUE_STATE" = "CLOSED" ] && { gh issue reopen "$VERIFY_ISSUE" 2>/dev/null || true; }

# 凭据注入（服务检查前，curl 需要 auth）
export SERVICE_TOKEN=$(grep '^SERVICE_TOKEN=' /opt/youke/backend/admin-api/.env 2>/dev/null | cut -d= -f2)
export PGPASSWORD=$(grep '^RDS_PASSWORD=' /opt/youke/backend/admin-api/.env 2>/dev/null | cut -d= -f2)

# 确保服务
curl -s -o /dev/null -w '%{http_code}' -H "X-Service-Token: ${SERVICE_TOKEN:-}" http://localhost:8081/api/admin/dashboard/stats 2>/dev/null | grep -q 200 || start_services
trap "stop_services; rm -f $LOCK_FILE" EXIT
export DB_HOST=$(grep '^RDS_HOST=' /opt/youke/backend/admin-api/.env 2>/dev/null | cut -d= -f2)
export DB_USER=$(grep '^RDS_USER=' /opt/youke/backend/admin-api/.env 2>/dev/null | cut -d= -f2)
export DB_NAME=$(grep '^RDS_DB=' /opt/youke/backend/admin-api/.env 2>/dev/null | cut -d= -f2)
export ADMIN_API=http://localhost:8081
export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-21}"

# ── LLM 验收 ──
log "→ verify-agent 验收..."
claude --print --agent verify-agent \
    "验收 issue #$VERIFY_ISSUE。

## 环境（已 export，直接用 shell 变量）
- curl http://localhost:8081 调 admin-api（X-Service-Token: \$SERVICE_TOKEN）
- psql -h \$DB_HOST -U \$DB_USER -d \$DB_NAME 查 DB（PGPASSWORD 已设）
- check_assert: python3 /opt/youke/scripts/dual_verify/check_assert.py

## 步骤
1. gh issue view $VERIFY_ISSUE --json body,comments → 提取所有 business_truths
2. 逐条执行：api 类 → curl | check_assert；db 类 → psql；e2e 类 → ls spec 文件
3. 每条输出 check_assert 完整 JSON 作为 trace
4. 置信度 = passed / total（公式强制，API_UNREACHABLE = fail）
5. 判定：1.0=close, >=0.8=hold, <0.8=block（全部 UNREACHABLE=hold）
6. **用 gh issue comment 贴完整报告 + <!-- VERDICT_JSON {issue_id,decision,confidence,passed_truths,total_truths,traces} -->**
7. close/hold/block 用 gh issue close/edit" \
    2>&1 | tee /var/log/migao-verify-agent.log | tail -10

# 兜底: Agent 没贴 VERDICT → 自动从日志提取
HAS_VERDICT=$(gh issue view "$VERIFY_ISSUE" --comments --json comments \
    --jq '[.comments[] | select(.body | contains("<!-- VERDICT_JSON"))] | length' 2>/dev/null)
if [ "${HAS_VERDICT:-0}" -eq 0 ]; then
    VERDICT_BLOCK=$(grep -A30 "<!-- VERDICT_JSON" /var/log/migao-verify-agent.log 2>/dev/null | tail -31)
    [ -n "$VERDICT_BLOCK" ] && echo "$VERDICT_BLOCK" | gh issue comment "$VERIFY_ISSUE" --body-file - 2>/dev/null
fi

log "✅ 验收完成 #$VERIFY_ISSUE"
