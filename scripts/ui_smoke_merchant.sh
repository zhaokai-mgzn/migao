#!/usr/bin/env bash
# ============================================================================
# MIGAO 商家后端（admin-web）全面功能冒烟 —— 一键可复跑
# ============================================================================
# 用途：今日大改动后的集成层验证（issue #3660）。真浏览器 + 真后端 + 商家 persona，
#       穷举 admin-web 全部页面（31 旅程，含加工单生成确认门禁/门幅口径/上下架/售后关闭原因等）。
# 用法：
#   ./scripts/ui_smoke_merchant.sh            # 起栈 → 跑 31 旅程 → 停栈（默认清理）
#   ./scripts/ui_smoke_merchant.sh --keep     # 跑完保留服务（排查用）
#   ./scripts/ui_smoke_merchant.sh --group 0  # 只跑指定前缀旅程（如 --group 16-）
# 环境：
#   REPO_ROOT   仓库根（默认本仓库）；MAIN_REPO  主仓库（提供 .venv/.env/rsa 等 worktree 缺件，默认 ../migao）
#   OUT_DIR     截图/报告输出（默认 <repo>/acceptance/2026-09-14/merchant-ui-smoke/out）
#   PHONE/SMS_CODE  登录手机号/万能码（默认 13800138000/123456）
# 服务：admin-api(:8090) + admin-web(:3001) + ai-agent(:8001，可选) —— 端口与 §2.3 隔离
# 注意：本脚本需兼容 macOS 自带 bash 3.2 —— `$var` 后紧跟非 ASCII 字符会被并入变量名
# （如 `$path（` → `path<0xE3>` 报 unbound variable，本机实测 exit 127），因此所有后跟中文的
# 变量一律用 ${var} 显式包裹（同 scripts/dev-worktree.sh、scripts/sync-main.sh 的既有约定；
# 判据 = tests/unit_ci_workflows/test_ui_smoke_worktree_deps.py 的类级回归锁）。
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
# 主仓库（有 .venv、gitignored 的 .env/rsa 等）：默认取兄弟目录 migao（worktree 部署形态）
MAIN_REPO="${MAIN_REPO:-$(dirname "$REPO_ROOT")/migao}"
[ -d "$MAIN_REPO" ] || MAIN_REPO="$REPO_ROOT"

API_PORT=8090
WEB_PORT=3001
AGENT_PORT=8001
PHONE="${PHONE:-13800138000}"
SMS_CODE="${SMS_CODE:-123456}"
KEEP=0
EXTRA_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --keep) KEEP=1; shift ;;
    --group) EXTRA_ARGS+=(--group "$2"); shift 2 ;;
    *) EXTRA_ARGS+=("$1"); shift ;;
  esac
done

OUT_DIR="${OUT_DIR:-$REPO_ROOT/acceptance/2026-09-14/merchant-ui-smoke/out}"
mkdir -p "$OUT_DIR"

echo "==> MIGAO 商家后端冒烟（31 旅程）"
echo "    repo=$REPO_ROOT main=$MAIN_REPO out=$OUT_DIR"

# ── 1. 依赖准备：worktree 形态下 node_modules/.venv 不在本仓库 → 真装（禁止软链）──
# ⚠️ 不得把主仓库的 node_modules 软链进来（issue #5241）：Next 16 的 dev 默认走 Turbopack，
#    它拒绝指向**项目根之外**的 node_modules 软链 ⇒ `next dev` 先打印 `✓ Ready` 再 FATAL：
#      Error [TurbopackInternalError]: Symlink [project]/node_modules is invalid,
#      it points out of the filesystem root
#    而下面的健康检查是 curl :3001/login（45×2s）⇒ 90s 后才报「admin-web 启动失败（见日志）」：
#    文案把人指向日志，根因却在 bundler。⇒ worktree 形态**真装**（复用 npm 全局缓存：--prefer-offline），
#    与 CI / 生产同一条 Turbopack 路径 —— 不用 `--webpack` 绕（那是另一条 bundler，保真度不同）。
NPM_BIN="${NPM_BIN:-npm}"
ADMIN_WEB_DIR="$REPO_ROOT/frontend/admin-web"
# 旧版脚本留在存量 worktree 里的根外软链：Turbopack 照样判死 ⇒ 先摘掉（自愈）再真装。
# `rm -f` 只摘软链本身、不跟随目标（主仓库 node_modules 不受影响）。
if [ -L "$ADMIN_WEB_DIR/node_modules" ]; then
  echo "  [prep] 摘除 node_modules 软链（-> $(readlink "$ADMIN_WEB_DIR/node_modules")；Turbopack 拒绝根外软链）"
  rm -f "$ADMIN_WEB_DIR/node_modules"
fi
if [ ! -d "$ADMIN_WEB_DIR/node_modules" ]; then
  echo "  [prep] admin-web 依赖缺失 → 真装（$NPM_BIN ci --prefer-offline；首次几分钟，之后命中 npm 缓存）"
  if ! ( cd "$ADMIN_WEB_DIR" && "$NPM_BIN" ci --no-audit --no-fund --prefer-offline ); then
    echo "  ✗ admin-web 依赖安装失败：${ADMIN_WEB_DIR}（${NPM_BIN} ci）"
    echo "    ⇒ 不要退回「软链主仓库 node_modules」：Turbopack 必 FATAL（issue #5241）"
    echo "      Symlink [project]/node_modules is invalid, it points out of the filesystem root"
    exit 1
  fi
fi
# 注：本脚本不碰 frontend/mini-app 的依赖 —— 本冒烟只跑 admin-web 的 31 旅程（spec.mjs 无 mini-app
#     消费方），旧版这里也给 mini-app 软链主仓库 node_modules，属同形态的死代码（issue #5241）⇒ 删除。
#     将来真要在 worktree 里跑 mini-app，按上面 admin-web 同法真装（Taro 不走 Turbopack，但软链同样无收益）。
# admin-api 本地密钥/gitignored 文件补齐（worktree 形态）
if [ ! -f "$REPO_ROOT/backend/admin-api/.env" ] && [ -f "$MAIN_REPO/backend/admin-api/.env" ]; then
  cp "$MAIN_REPO/backend/admin-api/.env" "$REPO_ROOT/backend/admin-api/.env"
fi
if [ ! -f "$REPO_ROOT/backend/admin-api/src/main/resources/rsa/private.pem" ] && [ -f "$MAIN_REPO/backend/admin-api/src/main/resources/rsa/private.pem" ]; then
  cp "$MAIN_REPO/backend/admin-api/src/main/resources/rsa/private.pem" "$REPO_ROOT/backend/admin-api/src/main/resources/rsa/private.pem"
fi
PYTHON_BIN="${PYTHON_BIN:-$MAIN_REPO/backend/ai-agent-service/.venv/bin/python}"
[ -x "$PYTHON_BIN" ] || PYTHON_BIN="$(command -v python3)"

# ── 2. 起栈（已在跑则复用；端口检查 §2.3）──
started_api=0; started_web=0; started_agent=0
api_health() { curl -s -m 3 -o /dev/null -w "%{http_code}" "http://127.0.0.1:$API_PORT/actuator/health" 2>/dev/null || echo 000; }
web_health() { curl -s -m 3 -o /dev/null -w "%{http_code}" "http://127.0.0.1:$WEB_PORT/login" 2>/dev/null || echo 000; }

if [ "$(api_health)" != "200" ]; then
  echo "  [stack] 启动 admin-api(:$API_PORT, SMS bypass)..."
  ( cd "$REPO_ROOT/backend/admin-api" && SMS_BYPASS_CODE="$SMS_CODE" SERVER_PORT=$API_PORT ./mvnw spring-boot:run > /tmp/ui-smoke-admin-api.log 2>&1 & echo $! > /tmp/ui-smoke-admin-api.pid )
  started_api=1
  for i in $(seq 1 60); do
    [ "$(api_health)" = "200" ] && break
    sleep 2
  done
  [ "$(api_health)" = "200" ] || { echo "  ✗ admin-api 启动失败（见 /tmp/ui-smoke-admin-api.log）"; exit 1; }
  echo "  ✓ admin-api ready"
else
  echo "  [stack] admin-api 已在运行，复用"
fi

if [ "$(web_health)" != "200" ]; then
  echo "  [stack] 启动 admin-web(:$WEB_PORT, API→:$API_PORT)..."
  ( cd "$REPO_ROOT/frontend/admin-web" && NEXT_PUBLIC_API_BASE_URL="http://localhost:$API_PORT" npm run dev > /tmp/ui-smoke-admin-web.log 2>&1 & echo $! > /tmp/ui-smoke-admin-web.pid )
  started_web=1
  for i in $(seq 1 45); do
    [ "$(web_health)" = "200" ] && break
    sleep 2
  done
  [ "$(web_health)" = "200" ] || { echo "  ✗ admin-web 启动失败（见 /tmp/ui-smoke-admin-web.log）"; exit 1; }
  echo "  ✓ admin-web ready"
else
  echo "  [stack] admin-web 已在运行，复用"
fi

# ai-agent（可选，session/chat 旅程需要；缺省自动起，失败不阻塞商家页面旅程）
if ! curl -s -m 2 -o /dev/null "http://127.0.0.1:$AGENT_PORT/health" 2>/dev/null; then
  if [ -f "$REPO_ROOT/backend/ai-agent-service/.env" ]; then
    echo "  [stack] 启动 ai-agent(:$AGENT_PORT, DEBUG 模式)..."
    ( cd "$REPO_ROOT/backend/ai-agent-service" && "$PYTHON_BIN" -m uvicorn app.main:app --port $AGENT_PORT > /tmp/ui-smoke-ai-agent.log 2>&1 & echo $! > /tmp/ui-smoke-ai-agent.pid )
    started_agent=1
    sleep 8
  else
    echo "  [stack] ⚠️ 未找到 ai-agent .env（生成方式见 REPORT.md），会话类旅程将标记 UI-only"
  fi
fi

# ── 3. SMS 限流清理 + 防刷窗口（登录旅程需要发码）──
"$PYTHON_BIN" - "$REPO_ROOT/backend/admin-api/.env" << 'EOF' >/dev/null 2>&1 || true
import sys, redis
env = open(sys.argv[1]).read()
pw = [l for l in env.split('\n') if l.startswith('REDIS_PASSWORD=')][0].split('=',1)[1]
host = [l for l in env.split('\n') if l.startswith('REDIS_HOST=')][0].split('=',1)[1]
port = [l for l in env.split('\n') if l.startswith('REDIS_PORT=')][0].split('=',1)[1]
r = redis.Redis(host=host, port=int(port), password=pw, decode_responses=True)
for phone in ['13800138000']:
    for k in [f'sms:limit:{phone}', f'sms:daily:{phone}', f'sms:fail:{phone}']:
        r.delete(k)
EOF
# 60s 防刷窗口（若距上次发码 <60s，登录旅程会 400）——简化：等 62s
echo "  [stack] 等待 SMS 防刷窗口 62s…"
sleep 62

# ── 4. 跑冒烟 spec ──
echo "==> 执行冒烟 spec（31 旅程）..."
LOG="$OUT_DIR/smoke.log"
set +e
BASE_URL="http://localhost:$WEB_PORT" \
REPO_ROOT="$MAIN_REPO" \
OUT_DIR="$OUT_DIR" \
PHONE="$PHONE" SMS_CODE="$SMS_CODE" \
node "$SCRIPT_DIR/ui-smoke-merchant/spec.mjs" "${EXTRA_ARGS[@]}" 2>&1 | tee "$LOG"
EXIT=${PIPESTATUS[0]}
set -e
echo "==> spec 退出码: ${EXIT}（0=全绿；见 $OUT_DIR/smoke-summary.md / smoke-results.json）"

# ── 5. 停栈（默认）──
if [ "$KEEP" = "1" ]; then
  echo "==> --keep：保留服务（admin-api pid=$(cat /tmp/ui-smoke-admin-api.pid 2>/dev/null || echo '-')）"
else
  echo "==> 停栈..."
  [ "$started_api" = "1" ] && kill "$(cat /tmp/ui-smoke-admin-api.pid 2>/dev/null)" 2>/dev/null || true
  [ "$started_web" = "1" ] && kill "$(cat /tmp/ui-smoke-admin-web.pid 2>/dev/null)" 2>/dev/null || true
  [ "$started_agent" = "1" ] && kill "$(cat /tmp/ui-smoke-ai-agent.pid 2>/dev/null)" 2>/dev/null || true
  sleep 3
  echo "==> 服务已停止"
fi

exit "$EXIT"
