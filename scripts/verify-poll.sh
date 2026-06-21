#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 米高二郎神验收轮询 v4 — LLM 调度，bash 仅执行
#
# bash 职责：lock / service start-stop / 执行 LLM 决策
# LLM 职责：扫描待验收 issue / 判定 / 贴 VERDICT
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

export HOME="${HOME:-/root}"
export PATH="/usr/local/bin:/usr/bin:/bin${PATH:+:$PATH}"

WORK_DIR="${WORK_DIR:-/opt/youke}"
LOCK_FILE="/tmp/migao-verify.lock"
log() { echo "[verify $(date '+%Y-%m-%d %H:%M:%S')] $1"; }

# ── 锁文件（独立于 agent-poll，30 分钟超时）──
if [ -f "$LOCK_FILE" ]; then
    LOCK_AGE=$(($(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0)))
    if [ "${LOCK_AGE:-0}" -gt 1800 ]; then
        log "⚠️ 锁文件超过30分钟，强制清除"; rm -f "$LOCK_FILE"
    else
        log "⚠️ 上一个验收任务还在跑 (${LOCK_AGE}s)，跳过"; exit 0
    fi
fi
trap "rm -f $LOCK_FILE" EXIT
touch "$LOCK_FILE"

cd "$WORK_DIR"

if ! gh auth status 2>/dev/null; then
    log "❌ gh 未认证"; exit 1
fi

git pull origin main 2>&1 | tail -1 || true

# ── 服务启停 ──
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
    for pid_file in /tmp/migao-verify-admin-api.pid /tmp/migao-verify-ai-agent.pid /tmp/migao-verify-admin-web.pid; do
        if [ -f "$pid_file" ]; then
            kill $(cat "$pid_file") 2>/dev/null || true
            rm -f "$pid_file"
        fi
    done
}

# ── Step 1: LLM 调度（扫描待验收 issue）──
log "🔍 扫描验收触发..."

SCAN_IDS=$(gh issue list --label ai-verify/pending --state open --limit 20 --json number --jq '.[].number' 2>/dev/null | tr '\n' ' ')
# Also scan closed + ai-verify/pending (bypassed by PR auto-close)
SCAN_IDS="$SCAN_IDS $(gh issue list --label ai-verify/pending --state closed --limit 20 --json number --jq '.[].number' 2>/dev/null | tr '\n' ' ')"

DECISION=$(claude --print --agent orchestrator \
    "扫描待验收 issue。返回纯 JSON。你可以用 gh issue view <id> --comments --json comments 读评论。

    候选 issue IDs: $SCAN_IDS

    判定逻辑:
    - 有 VERIFY_TRIGGER 评论 且 无 VERDICT_JSON 评论 → action=verify
    - 死循环检测: 已有 >=3 条 VERDICT_JSON 且最后一条是 hold → action=escalate
    - 否则 → action=skip

    返回格式: {\"action\":\"verify|escalate|skip\",\"issue_id\":<id>}" 2>/dev/null || echo '{"action":"skip"}')

ACTION=$(echo "$DECISION" | python3 -c "import sys,json; print(json.load(sys.stdin).get('action','skip'))" 2>/dev/null || echo "skip")
VERIFY_ISSUE=$(echo "$DECISION" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('issue_id',''))" 2>/dev/null || echo "")

# 校验数字
if [ -n "$VERIFY_ISSUE" ] && ! [[ "$VERIFY_ISSUE" =~ ^[0-9]+$ ]]; then
    log "❌ 非法 issue ID: $VERIFY_ISSUE"; exit 1
fi

if [ "$ACTION" = "skip" ] || [ -z "$VERIFY_ISSUE" ]; then
    log "😴 无待验收 issue"; exit 0
fi

if [ "$ACTION" = "escalate" ]; then
    log "🚨 死循环检测 → 自动升级 BLOCK"
    gh issue comment "$VERIFY_ISSUE" --body "## 🚨 二郎神死循环检测 — 自动升级为 BLOCK
连续 3+ 次验收 HOLD。需人工介入。"
    gh issue edit "$VERIFY_ISSUE" --add-label "block/need-human" 2>/dev/null || true
    exit 0
fi

log "🧪 验收 issue #$VERIFY_ISSUE"

# reopen if closed by PR auto-close
ISSUE_STATE=$(gh issue view "$VERIFY_ISSUE" --json state --jq '.state' 2>/dev/null)
if [ "$ISSUE_STATE" = "CLOSED" ]; then
    log "🔓 issue 已关闭（PR auto-close），重新打开..."
    gh issue reopen "$VERIFY_ISSUE" 2>/dev/null || true
fi

# 确保服务就绪
if ! curl -s -o /dev/null -w '%{http_code}' http://localhost:8081 2>/dev/null | grep -q 200; then
    log "⚠️ 服务未就绪，启动中..."
    start_services
fi
trap "stop_services; rm -f $LOCK_FILE" EXIT

# 凭据注入
export SERVICE_TOKEN=$(grep '^SERVICE_TOKEN=' /opt/youke/backend/admin-api/.env 2>/dev/null | cut -d= -f2)
export PGPASSWORD=$(grep '^RDS_PASSWORD=' /opt/youke/backend/admin-api/.env 2>/dev/null | cut -d= -f2)
export DB_HOST=$(grep '^RDS_HOST=' /opt/youke/backend/admin-api/.env 2>/dev/null | cut -d= -f2)
export DB_USER=$(grep '^RDS_USER=' /opt/youke/backend/admin-api/.env 2>/dev/null | cut -d= -f2)
export DB_NAME=$(grep '^RDS_DB=' /opt/youke/backend/admin-api/.env 2>/dev/null | cut -d= -f2)
export ADMIN_API=http://localhost:8081
export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-21}"

# ── Step 2: LLM 验收 ──
log "→ LLM 自主验收 v4 (调 API + 查 DB + check_assert 管道)..."
claude --print --agent verify-agent \
    "验收 issue #$VERIFY_ISSUE。你是执行机器，不是代码审查员。

## ⛔ 禁止读源码文件（.java/.py/.ts/.tsx/.vue）
API 路径用约定的 REST 路径表（verify-agent.md 中有完整映射表）。

## 环境（已注入）
- admin-api: \$ADMIN_API
- X-Service-Token: \$SERVICE_TOKEN
- DB: psql -h \$DB_HOST -U \$DB_USER -d \$DB_NAME (PGPASSWORD 已设)

## 强制要求
1. gh issue view $VERIFY_ISSUE --json body,comments → 提取 business_truths
2. **每条 api 真值必须走 curl | check_assert 管道**（不跳过、不替代）
3. **置信度 = passed / total**（公式强制）
4. VERDICT_JSON 必须贴每条真值的 check_assert 原始 JSON 输出
5. **最后必须用 gh issue comment 贴 VERDICT_JSON + gh issue close/hold**" \
    2>&1 | tee /var/log/migao-verify-agent.log | tail -10

# 若 Agent 没贴 VERDICT_JSON，从日志自动提取
HAS_VERDICT=$(gh issue view "$VERIFY_ISSUE" --comments --json comments \
    --jq '[.comments[] | select(.body | contains("<!-- VERDICT_JSON"))] | length' 2>/dev/null)
if [ "${HAS_VERDICT:-0}" -eq 0 ]; then
    VERDICT_BLOCK=$(grep -A30 "<!-- VERDICT_JSON" /var/log/migao-verify-agent.log 2>/dev/null | tail -31)
    if [ -n "$VERDICT_BLOCK" ]; then
        echo "$VERDICT_BLOCK" | gh issue comment "$VERIFY_ISSUE" --body-file - 2>/dev/null
        log "✅ VERDICT_JSON 已从日志自动贴到 issue"
    fi
fi

log "✅ LLM 验收完成 #$VERIFY_ISSUE"
