#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 米高二郎神验收轮询触发器 v3.3（独立于 agent-poll.sh）
#
# cron 每 5 分钟执行。一次处理一个待验收 issue。
# 职责单一：扫 VERIFY_TRIGGER → 死循环检测 → claude --agent verify-agent
# 不与 agent-poll.sh 互斥（独立锁文件），确保验收不被写码阻塞。
#
# v3.3 新增：死循环检测 — 同一 issue 连续 3 次相同 HOLD → auto-escalate
# ═══════════════════════════════════════════════════════════════
set -e

# ── cron 环境保护（PATH 不含 /usr/local/bin，HOME 可能为空）──
export HOME="${HOME:-/root}"
export PATH="/usr/local/bin:/usr/bin:/bin${PATH:+:$PATH}"

# venv Python 3.11（系统 python3 可能是 3.6）
PYTHON="${WORK_DIR:-/opt/youke}/backend/ai-agent-service/.venv/bin/python3"
[ -x "$PYTHON" ] || PYTHON="python3.11"
[ -x "$(command -v "$PYTHON" 2>/dev/null)" ] || PYTHON="python3"

# ═══════════════════════════════════════════════════════════
# 按需启停服务
# ═══════════════════════════════════════════════════════════
start_services() {
    log "🚀 启动服务..."
    # 加载 .env 中的 RDS/REDIS 变量（Spring Boot 不自读 .env）
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
    # 只杀自己启动的进程，不误杀 agent-poll 启动的服务
    for pid_file in /tmp/migao-verify-admin-api.pid /tmp/migao-verify-ai-agent.pid /tmp/migao-verify-admin-web.pid; do
        if [ -f "$pid_file" ]; then
            kill $(cat "$pid_file") 2>/dev/null || true
            rm -f "$pid_file"
        fi
    done
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

# 拉取最新代码
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

# ═══════════════════════════════════════════════════════════════
# v3.3 死循环检测：同一 issue 连续 N 次相同 HOLD → auto-escalate
# ═══════════════════════════════════════════════════════════════
STUCK_THRESHOLD=3
MATCHING_HOLD_COUNT=0

# 取最近非 VERIFY_TRIGGER 的非军师评论中的 VERDICT_JSON 判定
PREV_DECISIONS=$(gh issue view "$VERIFY_ISSUE" --comments --json comments \
    --jq '[.comments[] | select(.body | contains("VERDICT_JSON")) | .body] | .[-3:] | .[]' 2>/dev/null || true)

if [ -n "$PREV_DECISIONS" ]; then
    # 检查最后一条 VERDICT_JSON 的 decision
    LAST_DECISION=$(echo "$PREV_DECISIONS" | tail -1 | python3 -c "
import sys, json, re
txt = sys.stdin.read()
m = re.search(r'\"decision\"\s*:\s*\"(hold|block)\"', txt)
print(m.group(1) if m else '')
" 2>/dev/null || true)

    if [ "$LAST_DECISION" = "hold" ]; then
        # 统计连续 hold 次数
        MATCHING_HOLD_COUNT=$(echo "$PREV_DECISIONS" | grep -c '"decision".*"hold"' 2>/dev/null || echo 0)
    fi
fi

if [ "$MATCHING_HOLD_COUNT" -ge "$STUCK_THRESHOLD" ]; then
    log "🚨 死循环检测：issue #$VERIFY_ISSUE 已连续 $MATCHING_HOLD_COUNT 次 HOLD，自动升级为 BLOCK"

    gh issue comment "$VERIFY_ISSUE" --body "## 🚨 二郎神死循环检测 — 自动升级为 BLOCK

**原因**: 连续 $MATCHING_HOLD_COUNT 次验收返回 HOLD，判定死循环。
**行动**: 自动升级为 `block/need-human`。请人工介入。

上一轮判定:
\`\`\`
$(echo "$PREV_DECISIONS" | tail -1 | head -c 500)
\`\`\`"

    if ! gh issue edit "$VERIFY_ISSUE" --add-label "block/need-human" 2>/dev/null; then
        # label 可能不存在，尝试创建
        gh label create "block/need-human" --color "B60205" --description "二郎神死循环自动升级 — 需人工介入" 2>/dev/null || true
        gh issue edit "$VERIFY_ISSUE" --add-label "block/need-human" 2>/dev/null || true
    fi

    rm -f "$LOCK_FILE"
    exit 0
fi

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
export PGPASSWORD=$(grep '^RDS_PASSWORD=' /opt/youke/backend/admin-api/.env 2>/dev/null | cut -d= -f2)
export DB_HOST=$(grep '^RDS_HOST=' /opt/youke/backend/admin-api/.env 2>/dev/null | cut -d= -f2)
export DB_USER=$(grep '^RDS_USER=' /opt/youke/backend/admin-api/.env 2>/dev/null | cut -d= -f2)
export DB_NAME=$(grep '^RDS_DB=' /opt/youke/backend/admin-api/.env 2>/dev/null | cut -d= -f2)
export ADMIN_API=http://localhost:8081

log "  → LLM 自主验收 v3.3 (调 API + 查 DB + check_assert 管道校验)..."

cd /opt/youke && claude --print \
    --agent verify-agent \
    "验收 issue #$VERIFY_ISSUE。你是执行机器，不是代码审查员。

## ⛔ 禁止读源码文件（.java/.py/.ts/.tsx/.vue）
API 路径用约定的 REST 路径表（verify-agent.md 中有完整映射表），不要翻 Controller 源码。

## 环境（已注入，直接用）
- admin-api: \$ADMIN_API
- X-Service-Token: \$SERVICE_TOKEN
- DB: psql -h \$DB_HOST -U \$DB_USER -d \$DB_NAME (PGPASSWORD 已设)

## 强制要求
1. gh issue view $VERIFY_ISSUE --json body,comments → 提取 business_truths
2. **每条 api 真值必须走 curl | check_assert 管道**（不跳过、不替代）
3. **置信度 = passed / total**（公式强制，pass 不含待人工/手动检查）
4. VERDICT_JSON 必须贴每条真值的 check_assert 原始 JSON 输出
	5. 完成后必须用 gh issue comment 贴 VERDICT_JSON + gh issue close/hold
5. 不超过 10 分钟

## 判定
全部 check_assert all_pass → close
部分 fail → hold（列出失败项 + check_assert 证据）
全部 API_UNREACHABLE → hold（不 block）" 2>&1 | tee -a /var/log/migao-verify-agent.log | tail -5

# Agent 没贴 VERDICT_JSON → 从日志自动贴
HAS_VERDICT=
if [ "0" -eq 0 ]; then
    VERDICT_BLOCK=
    if [ -n "" ]; then
        echo "" | gh issue comment "" --body-file - 2>/dev/null
        log "✅ VERDICT_JSON 已从日志自动贴到 issue"
    fi
fi

log "✅ LLM 验收完成 #$VERIFY_ISSUE"
