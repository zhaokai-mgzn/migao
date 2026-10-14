#!/usr/bin/env bash
# ============================================================================
# 2026-10-14 环境重建轮 —— 本地三件套启停（一条命令，铁律 10）
# ============================================================================
# 口径：本地三件套 + 云 dev 库
#   · ai-agent-service  :8001（主检出 backend/ai-agent-service，DEBUG=true，无 LLM key ⇒ 规则层）
#   · admin-api         :8080（两条 AI 接线显式给：AI_AGENT_BASE_URL=http://localhost:8001 +
#                                AI_AGENT_SERVICE_TOKEN ← ai-agent 的 SERVICE_TOKEN，否则真实入驻静默「系统繁忙」）
#   · admin-web         :3001（Next dev）
# 用法：
#   bash acceptance/2026-10-14/tools/start-stack.sh up       # 起三件套（幂等：已在跑的端口不重复起）
#   bash acceptance/2026-10-14/tools/start-stack.sh down     # 停三件套
#   bash acceptance/2026-10-14/tools/start-stack.sh status   # 只读探活
# 日志：/tmp/migao-20261014-{ai-agent,admin-api,admin-web}.log
# ============================================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
LOG_PREFIX="/tmp/migao-20261014"
AI_DIR="$REPO_ROOT/backend/ai-agent-service"
API_DIR="$REPO_ROOT/backend/admin-api"
WEB_DIR="$REPO_ROOT/frontend/admin-web"

port_pid() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1; }

wait_http() { # url, 秒
  local url="$1" secs="${2:-60}" i=0
  while [ "$i" -lt "$secs" ]; do
    if curl -s -o /dev/null --max-time 3 "$url"; then return 0; fi
    sleep 2; i=$((i + 2))
  done
  return 1
}

cmd_down() {
  for p in 8001 8080 3001; do
    local pid; pid="$(port_pid "$p")"
    if [ -n "$pid" ]; then echo "停止 :$p (pid $pid)"; kill "$pid" 2>/dev/null; fi
  done
  sleep 3
  for p in 8001 8080 3001; do
    local pid; pid="$(port_pid "$p")"
    [ -n "$pid" ] && { echo "强杀 :$p (pid $pid)"; kill -9 "$pid" 2>/dev/null; }
  done
  echo "已停。"
}

cmd_status() {
  printf '%-8s %-8s %s\n' 端口 PID 探活
  for spec in "8001 http://127.0.0.1:8001/health" "8080 http://127.0.0.1:8080/api/health" "3001 http://127.0.0.1:3001/login"; do
    set -- $spec
    local p="$1" url="$2" pid code
    pid="$(port_pid "$p")"
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null || echo '-')"
    printf '%-8s %-8s %s\n' ":$p" "${pid:--}" "HTTP $code"
  done
}

cmd_up() {
  # 1) ai-agent
  if [ -n "$(port_pid 8001)" ]; then
    echo "· ai-agent :8001 已在跑，跳过"
  else
    echo "· 起 ai-agent :8001"
    ( cd "$AI_DIR" && nohup .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 \
        > "$LOG_PREFIX-ai-agent.log" 2>&1 & )
    wait_http http://127.0.0.1:8001/health 60 || { echo "❌ ai-agent 未就绪，见 $LOG_PREFIX-ai-agent.log"; tail -5 "$LOG_PREFIX-ai-agent.log"; return 1; }
  fi

  # 2) admin-api（两条 AI 接线必须显式给）
  if [ -n "$(port_pid 8080)" ]; then
    echo "· admin-api :8080 已在跑，跳过"
  else
    echo "· 起 admin-api :8080"
    (
      cd "$API_DIR"
      set -a; . ./.env; set +a
      export AI_AGENT_BASE_URL="http://localhost:8001"
      export AI_AGENT_SERVICE_TOKEN="$(grep -E '^SERVICE_TOKEN=' "$AI_DIR/.env" | cut -d= -f2- | tr -d '\"')"
      nohup ./mvnw -q spring-boot:run > "$LOG_PREFIX-admin-api.log" 2>&1 &
    )
    wait_http http://127.0.0.1:8080/api/health 300 || { echo "❌ admin-api 未就绪，见 $LOG_PREFIX-admin-api.log"; tail -20 "$LOG_PREFIX-admin-api.log"; return 1; }
  fi

  # 3) admin-web（依赖变更后需先装）
  if [ -n "$(port_pid 3001)" ]; then
    echo "· admin-web :3001 已在跑，跳过"
  else
    echo "· 装前端依赖（package.json 本轮有 dep bump）"
    ( cd "$WEB_DIR" && npm install --prefer-offline --no-audit --no-fund > "$LOG_PREFIX-web-install.log" 2>&1 ) \
      || { echo "❌ npm install 失败，见 $LOG_PREFIX-web-install.log"; tail -10 "$LOG_PREFIX-web-install.log"; return 1; }
    echo "· 起 admin-web :3001"
    ( cd "$WEB_DIR" && nohup npm run dev > "$LOG_PREFIX-admin-web.log" 2>&1 & )
    wait_http http://127.0.0.1:3001/login 240 || { echo "❌ admin-web 未就绪，见 $LOG_PREFIX-admin-web.log"; tail -20 "$LOG_PREFIX-admin-web.log"; return 1; }
  fi

  cmd_status
}

case "${1:-up}" in
  up) cmd_up ;;
  down) cmd_down ;;
  status) cmd_status ;;
  *) echo "用法: $0 {up|down|status}"; exit 2 ;;
esac
