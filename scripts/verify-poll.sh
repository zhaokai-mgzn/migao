#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 米高二郎神验收轮询触发器（独立于 agent-poll.sh）
#
# cron 每 5 分钟执行。一次处理一个待验收 issue。
# 职责单一：扫 VERIFY_TRIGGER → primary.py → reviewer.py → merge.py
# 不与 agent-poll.sh 互斥（独立锁文件），确保验收不被写码阻塞。
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
# 按需启停服务
# ═══════════════════════════════════════════════════════
start_services() {
    log "🚀 启动服务..."
    # 加载 .env 中的 RDS/REDIS 变量（Spring Boot 不自读 .env）
    if [ -f /opt/youke/backend/admin-api/.env ]; then
        export $(grep -E '^(RDS_|REDIS_)' /opt/youke/backend/admin-api/.env | xargs)
    fi
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
LOCK_FILE="/tmp/migao-verify.lock"
log() { echo "[verify $(date '+%Y-%m-%d %H:%M:%S')] $1"; }

# ── 锁文件（独立于 agent-poll，30 分钟超时）──
if [ -f "$LOCK_FILE" ]; then
    LOCK_AGE=$(($(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0)))
    if [ "${LOCK_AGE:-0}" -gt 1800 ]; then
        log "⚠️ 锁文件超过30分钟，强制清除"
        rm -f "$LOCK_FILE"
    else
        log "⚠️ 上一个验收任务还在跑 (${LOCK_AGE}s)，跳过"
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

# 拉取最新代码（确保 primary.py / reviewer.py / merge.py 最新）
git pull origin main 2>&1 | tail -1 || true

# ═══════════════════════════════════════════════════════════════
# 扫验收触发（军师发 VERIFY_TRIGGER → 跑验收脚本）
# ═══════════════════════════════════════════════════════════════
log "🔍 扫描验收触发..."

VERIFY_ISSUE=""
while read iid; do
    HAS_TRIGGER=$(gh issue view "$iid" --comments --json comments \
        --jq '.comments[] | select(.body | contains("VERIFY_TRIGGER")) | .body' 2>/dev/null | head -1)
    HAS_RESULT=$(gh issue view "$iid" --comments --json comments \
        --jq '.comments[] | select(.body | contains("VERDICT_JSON")) | .body' 2>/dev/null | head -1)

    if [ -n "$HAS_TRIGGER" ] && [ -z "$HAS_RESULT" ]; then
        VERIFY_ISSUE="$iid"
        break
    fi
done < <({
  # 优先 OPEN issue（验收被打回或新触发）
  gh issue list --state open --limit 20 --json number --jq '.[].number' 2>/dev/null
  # 也扫 CLOSED 但 pending 的（被 PR "Closes #xxx" auto-close 绕过验收的）
  gh issue list --state closed --label ai-verify/pending --limit 20 --json number --jq '.[].number' 2>/dev/null
})

if [ -z "$VERIFY_ISSUE" ]; then
    log "😴 无待验收 issue"
    exit 0
fi

log "🧪 验收 issue #$VERIFY_ISSUE"

# 如果 issue 被 PR "Closes #xxx" auto-close，先 reopen 再验收
ISSUE_STATE=$(gh issue view "$VERIFY_ISSUE" --json state --jq '.state' 2>/dev/null)
if [ "$ISSUE_STATE" = "CLOSED" ]; then
    log "  🔓 issue 已关闭（可能是 PR auto-close），重新打开..."
    gh issue reopen "$VERIFY_ISSUE" 2>/dev/null || true
fi

# 确保服务起来（agent-poll 可能在跑，服务可能已在运行）
if ! lsof -i :8081 -sTCP:LISTEN >/dev/null 2>&1 || ! lsof -i :8001 -sTCP:LISTEN >/dev/null 2>&1 || ! lsof -i :3001 -sTCP:LISTEN >/dev/null 2>&1; then
    log "  ⚠️ 服务未就绪，启动中..."
    start_services
fi
trap "stop_services; rm -f $LOCK_FILE" EXIT

# 凭据通过环境变量传递，不写入 prompt 文本
export SERVICE_TOKEN=$(grep '^SERVICE_TOKEN=' /opt/youke/backend/admin-api/.env 2>/dev/null | cut -d= -f2)
export PGPASSWORD=Migao2026!
export DB_HOST=pgm-bp1p7w92k81ob5to-pub.pg.rds.aliyuncs.com
export DB_USER=migao_admin
export DB_NAME=ai_customer_service
export ADMIN_API=http://localhost:8081

log "  → LLM 自主验收 (调 API + 查 DB + 判定)..."
cd /opt/youke && claude --print \
    --agent verify-agent \
    "验收 issue #$VERIFY_ISSUE。独立验证每条业务真值。

## 环境（已通过环境变量注入，直接使用）
- admin-api: \$ADMIN_API
- X-Service-Token: \$SERVICE_TOKEN
- DB: psql -h \$DB_HOST -U \$DB_USER -d \$DB_NAME（密码已在 PGPASSWORD 环境变量）

## 步骤
1. gh issue view $VERIFY_ISSUE --json body,comments → 提取 business_truths
2. 对每条真值调 API 或查 DB 验证
3. 判定：全部通过→close / 关键失败→hold / 严重→block
4. 贴 VERDICT_JSON 评论：
<!-- VERDICT_JSON {\"issue_id\":$VERIFY_ISSUE,\"decision\":\"close|hold|block\",\"verdict\":\"...\",\"verifier\":\"dev-agent-llm\"} -->

## 边界
- 不跑 primary.py/reviewer.py/merge.py
- 不依赖模板 reviewer_asserts（自己推理 API path）
- 真实 API path 参考：after-sales（有连字符），orders, products, customers
- API 调不通→先 curl localhost:8081/actuator/health → 仍不行则hold
- 不超过 10 分钟" 2>&1 | tail -5

log "✅ LLM 验收完成 #$VERIFY_ISSUE"
