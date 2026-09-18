#!/usr/bin/env bash
# =============================================================================
# issue #4299 端到端验证（真库 + 真栈）—— 受控 A/B：同一真库、同一时刻、两个代码版本
#
#   RED   （未修代码）：main 工作区已在跑的 admin-api :8080（classpath = main/target/classes）
#   GREEN （已修代码）：从分支 worktree 另起 admin-api :8090
#   ai-agent :8001 两侧共用（本单不改 ai-agent，故不构成变量）
#
# 断言（判据见 issue #4299 修正章节 + acceptance/.../FINDINGS.md）：
#   米类工序 qty == 该单订单数量，且 qty_source != "fallback"        ← 修复前必红
#   折/幅/套 类 qty == 1 且 qty_source == "fallback"（#4208 更正口径，不得回归）
#
# 用法：./run-e2e.sh            # 起分支栈 + 跑 A/B + 出报告
#       ./run-e2e.sh --no-boot  # 分支栈已在跑，只跑 A/B
# =============================================================================
set -euo pipefail

WT="/Users/guangzhen.zk/ai native/migao-wt/4299-qty-meter-mapping"
MAIN="/Users/guangzhen.zk/ai native/migao"
OUT_DIR="$(cd "$(dirname "$0")" && pwd)"
API_MAIN="http://localhost:8080"
API_BRANCH="http://localhost:8090"
BRANCH_PORT=8090
LOG="/tmp/e2e-4299-branch-api.log"

# RED 侧订单（confirmed / bulk_cut / 订单数量 2 / 加工项 per_meter / 无既有加工单）
RED_ORDER="78d207ac2d30c609d5f68cbc9128ccb6"
# GREEN 侧订单（confirmed / bulk_cut / 订单数量 3 / 加工项 per_meter / 无既有加工单）
GREEN_ORDER="8614224ecd54374e0cbf33c1cb564958"

BOOT=1
[ "${1:-}" = "--no-boot" ] && BOOT=0

# ---------------------------------------------------------------- 起分支栈
boot_branch_api() {
  echo "▶️  启动分支 admin-api :${BRANCH_PORT}（worktree=${WT}）"
  # 注意顺序：先 ai-agent 的 .env 取 SERVICE_TOKEN，**最后** source admin-api 的 .env
  # （两份都含 JWT_PUBLIC_KEY，admin-api 的必须最后生效，否则签名/验签口径可能不一致）
  # worktree 缺 gitignored 的 rsa/private.pem（`.gitignore` 的 `**/rsa/private.pem`）⇒
  # `JWT_PRIVATE_KEY=classpath:rsa/private.pem` 加载失败、应用起不来（首次实测踩到）。
  # 从主工作区补齐（gitignored ⇒ 不会被提交）。
  local rsa="$WT/backend/admin-api/src/main/resources/rsa"
  mkdir -p "$rsa"
  [ -f "$rsa/private.pem" ] || cp "$MAIN/backend/admin-api/src/main/resources/rsa/private.pem" "$rsa/private.pem"
  [ -f "$rsa/public.pem" ] || cp "$MAIN/backend/admin-api/src/main/resources/rsa/public.pem" "$rsa/public.pem"

  local agent_token
  agent_token="$(grep '^SERVICE_TOKEN=' "$MAIN/backend/ai-agent-service/.env" | cut -d= -f2-)"
  # shellcheck disable=SC1090
  set -a; . "$MAIN/backend/admin-api/.env"; set +a
  export AI_AGENT_BASE_URL="http://127.0.0.1:8001"
  export AI_AGENT_SERVICE_TOKEN="$agent_token"
  export SERVER_PORT="$BRANCH_PORT"
  export SMS_BYPASS_CODE="123456"
  ( cd "$WT/backend/admin-api" && exec ./mvnw -q spring-boot:run ) >"$LOG" 2>&1 &
  echo "   pid=$! log=$LOG"

  for i in $(seq 1 90); do
    code="$(curl -s -o /dev/null -w '%{http_code}' -m 3 "$API_BRANCH/api/auth/sms/login" || true)"
    [ "$code" != "000" ] && { echo "   ✅ 分支栈就绪（第 ${i} 次探测，HTTP ${code}）"; return 0; }
    sleep 3
  done
  echo "   ❌ 分支栈 90 次探测未就绪，见 $LOG" >&2
  tail -30 "$LOG" >&2
  return 1
}

# ---------------------------------------------------------------- 工具
login() {
  curl -s -m 10 -X POST "$1/api/auth/sms/login" \
    -H 'Content-Type: application/json' \
    -d '{"phone":"13800138000","code":"123456"}' | jq -r '.data.accessToken // .data.token // empty'
}

gen() { # gen <api> <token> <orderId>
  curl -s -m 60 -X POST "$1/api/admin/processing-orders/generate" \
    -H "Authorization: Bearer $2" -H 'Content-Type: application/json' \
    -d "{\"orderIds\":[\"$3\"]}"
}

ops() { # ops <api> <token> <orderId>
  curl -s -m 30 "$1/api/admin/production/orders/$3/operations" -H "Authorization: Bearer $2"
}

# 从 operations 响应里算断言（米类/折/幅/套 的 qty 与 qty_source 集合）
verdict() { # verdict <json-file> —— 口径落在 verdict-summary.jq（单点，避免行内转义踩坑）
  jq -r -f "$(dirname "$0")/verdict-summary.jq" "$1"
}

run_side() { # run_side <label> <api> <orderId>
  local label="$1" api="$2" order="$3"
  local tok; tok="$(login "$api")"
  [ -n "$tok" ] || { echo "❌ $label 登录失败（${api}）"; return 1; }
  echo "── $label 侧：$api  订单 $order"
  local g; g="$(gen "$api" "$tok" "$order")"
  echo "   generate ⇒ $(echo "$g" | jq -c '.data[0] // .' 2>/dev/null | head -c 400)"
  local o; o="$(ops "$api" "$tok" "$order")"
  echo "   operations ⇒ $(verdict /dev/stdin <<<"$o")"
  echo "$o" > "$OUT_DIR/e2e-$label-operations.json"
  echo "$g" > "$OUT_DIR/e2e-$label-generate.json"
}

mkdir -p "$OUT_DIR"
[ "$BOOT" = "1" ] && boot_branch_api

{
  echo "### RED（未修代码 main :8080）"
  run_side red "$API_MAIN" "$RED_ORDER"
  echo
  echo "### GREEN（已修代码 branch :8090）"
  run_side green "$API_BRANCH" "$GREEN_ORDER"
} 2>&1 | tee "$OUT_DIR/e2e-ab-output.txt"
