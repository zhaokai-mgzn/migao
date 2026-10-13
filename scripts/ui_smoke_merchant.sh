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
# 变量一律用 ${var} 显式包裹（同 scripts/dev-worktree.sh、scripts/sync-main.sh 的既有约定）；
# 同一版本下**空数组**的 `"${arr[@]}"` 也报 unbound variable（issue #6777）⇒ 一律写成
# `${arr[@]+"${arr[@]}"}`（同 scripts/preset-anchor-check.sh 的既有约定）；
# 判据 = tests/unit_ci_workflows/test_ui_smoke_worktree_deps.py 的类级回归锁（含这两条）。
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

# ── 1.5 云 dev DB 预检：把**症状**接到**处置**（issue #6789）──
# 本机公网 IP 不在 RDS 白名单时，下游 admin-api 会吐 7403 行 Spring 栈、第一现场是
# `PSQLException 尝试连线已失败` / `SocketTimeoutException` —— 那**不是**根因现场。
# ⇒ 起 admin-api **之前**先 TCP 探一次；不可达就打**一行**可行动提示 + 非零退出。
# ⚠️ 顺序即价值：这段必须在「启动 admin-api」之前（判据 = MC-092 的接线检查）。
if [ -f "$REPO_ROOT/backend/admin-api/.env" ]; then
  RDS_HOST_PRE="$(sed -n 's/^RDS_HOST=//p' "$REPO_ROOT/backend/admin-api/.env" | head -1)"
  RDS_PORT_PRE="$(sed -n 's/^RDS_PORT=//p' "$REPO_ROOT/backend/admin-api/.env" | head -1)"
  if [ -n "$RDS_HOST_PRE" ] && ! nc -G 5 -z "$RDS_HOST_PRE" "${RDS_PORT_PRE:-5432}" >/dev/null 2>&1; then
    echo "✗ 连不上云 dev DB（${RDS_HOST_PRE}:${RDS_PORT_PRE:-5432}）：本机公网 IP 可能在 RDS 白名单之外"
    echo "  ⇒ 处置：./scripts/dev-db-whitelist.sh（诊断）/ ./scripts/dev-db-whitelist.sh --yes（追加）"
    echo "     —— 不修白名单就起栈，只会把 Spring 启动失败的下游噪音甩给人当第一现场"
    exit 1
  fi
fi

# ── 1b. ai-agent 配置显式化（issue #6790 判据 ③ / AGENTS.md 铁律「环境」节）──
# 🔴 `application.yml` 的两个默认值都是**坏的**：`AI_AGENT_BASE_URL=http://localhost:8000`
#    （容器内端口，本机 ai-agent 在 :8001）、`AI_AGENT_SERVICE_TOKEN` 默认空。
#    不给 ⇒ api 侧真实链路**静默 fail-closed**，而 ai-agent 看着是健康的；实测 api 日志逐字：
#    `[CRAFT_CALC_UNAVAILABLE] 算料服务（ai-agent）不可用…未配置 ai-agent.service-token（当前服务地址 http://localhost:8000/…）`。
#    ⇒ 启动 admin-api 时**显式传**这两个变量（判据：本脚本的启动命令里必须出现，见判据 U）。
# 取值优先级：环境变量 → 本仓 ai-agent .env → 主仓 ai-agent .env / 根 .env。
# ⚠️ **绝不打印凭据本身**（只打印「取到 / 没取到」与长度）。
AI_AGENT_BASE_URL="${AI_AGENT_BASE_URL:-http://localhost:8001}"

# 读某个 .env 的一行值（只回显值供变量赋值；不打印到日志）
env_value() { # $1=文件 $2=键
  [ -f "$1" ] || return 1
  sed -n "s/^[[:space:]]*$2[[:space:]]*=[[:space:]]*//p" "$1" | head -1 | tr -d '\r'
}
AI_AGENT_SERVICE_TOKEN="${AI_AGENT_SERVICE_TOKEN:-}"
AI_AGENT_TOKEN_SOURCE="环境变量 AI_AGENT_SERVICE_TOKEN"
if [ -z "$AI_AGENT_SERVICE_TOKEN" ]; then
  for f in "$REPO_ROOT/backend/ai-agent-service/.env" "$MAIN_REPO/backend/ai-agent-service/.env" "$MAIN_REPO/.env" "$REPO_ROOT/.env"; do
    v="$(env_value "$f" AI_AGENT_SERVICE_TOKEN || true)"
    [ -z "$v" ] && v="$(env_value "$f" SERVICE_TOKEN || true)"
    if [ -n "$v" ]; then AI_AGENT_SERVICE_TOKEN="$v"; AI_AGENT_TOKEN_SOURCE="$f 的 SERVICE_TOKEN"; break; fi
  done
fi
export AI_AGENT_BASE_URL AI_AGENT_SERVICE_TOKEN
# ai-agent 自身要 .env 才起得来（worktree 形态缺件，与 admin-api 的 .env / rsa 同法补齐）
if [ ! -f "$REPO_ROOT/backend/ai-agent-service/.env" ] && [ -f "$MAIN_REPO/backend/ai-agent-service/.env" ]; then
  cp "$MAIN_REPO/backend/ai-agent-service/.env" "$REPO_ROOT/backend/ai-agent-service/.env"
  echo "  [prep] 补齐 ai-agent .env（worktree 缺件，来自主仓）"
fi
SMOKE_UNCONFIGURED=0
if [ -z "$AI_AGENT_SERVICE_TOKEN" ]; then
  SMOKE_UNCONFIGURED=1
  echo "  ⚠️ [未配置] 未取到 ai-agent service token（查了环境变量 / 本仓与主仓 ai-agent .env / 根 .env）"
  echo "      ⇒ base-url=${AI_AGENT_BASE_URL}、token **空** ⇒ 算料 / 会话面会 fail-closed（api 日志打 CRAFT_CALC_UNAVAILABLE）。"
  echo "      这类旅程在本轮汇总里记为「➖ 未配置」，**不与真实失败混在一张表里**。"
else
  echo "  [prep] ai-agent 配置：base-url=${AI_AGENT_BASE_URL}、token 已取到（长度 ${#AI_AGENT_SERVICE_TOKEN}，来源：${AI_AGENT_TOKEN_SOURCE}）"
fi
export SMOKE_UNCONFIGURED
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
  # 复用形态下「这轮到底带没带 ai-agent 配置」**取决于那个实例的启动参数**（脚本看不见）
  # ⇒ 如实说明，避免把复用实例的配置缺口读成「本脚本没传」（判据 U 的边界，issue #6790 判据 ③）
  if [ "${SMOKE_UNCONFIGURED:-0}" = "0" ]; then
    echo "      ⚠️ 复用实例：本轮 ai-agent 配置是否生效取决于**该实例**的启动参数；"
    echo "         若汇总出现 CRAFT_CALC_UNAVAILABLE / 未配置，先杀掉旧实例再跑以取得单变量读数。"
  fi
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

# ── 2.5 业务路由自检：防「陈旧 .next 缓存」被读成产品大面积故障 ──
# 实测（2026-10-13，worktree 形态）：admin-api / admin-web 都 ready，`curl :3001/login` = 200，
# 而 `(dashboard)` 组每个路由 **404**（dev 日志 `GET /dashboard 404` / `/products 404`）⇒ 34 条旅程全灭，
# 看着像产品挂了；真因 = **worktree 里的 `.next` 是别处/旧上下文留下的**（Turbopack 拿着陈旧路由清单）
# ⇒ `rm -rf frontend/admin-web/.next` 后重启 dev，全部恢复（/dashboard /products /employees = 200）。
# ⚠️ `/login` 不在那一组里 ⇒ **健康检查看不出来**，所以这里必须探**业务组**路由。
# 只报不动手：删缓存是有副作用的动作（默认交给人/上层决定），本脚本**不自动**清。
ROUTE_CHECK_404=""
for route in /employees /dashboard; do
  code="$(curl -s -m 5 -o /dev/null -w "%{http_code}" "http://127.0.0.1:$WEB_PORT$route" 2>/dev/null || echo 000)"
  if [ "$code" = "404" ]; then ROUTE_CHECK_404="$route"; break; fi
done
if [ -n "$ROUTE_CHECK_404" ]; then
  echo "✗ admin-web 业务路由 404（${ROUTE_CHECK_404}）：疑似 **陈旧 .next 缓存**（非产品故障 —— /login 仍 200）"
  echo "  ⇒ 处置：rm -rf $REPO_ROOT/frontend/admin-web/.next 后重启 admin-web dev，再跑本脚本"
  echo "     —— 不修缓存就跑 spec，只会产出 N 条假故障读数（每旅程一条）"
  exit 1
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

# ── 2.6 验签公钥对齐预检（issue #6801）──
# 病（2026-10-13 真栈实测，两次复跑一致）：同一浏览器会话里其余旅程全 ✅，只有
# `06-agent-sessions` / `07-chat` 报 console `401 (Unauthorized)` ×3，读起来像**产品鉴权缺陷**。
# 真因在**环境**：ai-agent 校验 JWT 用的 `JWT_PUBLIC_KEY` 与 admin-api 签发所用的私钥**不是同一对**
# —— ai-agent 日志逐字 `JWT verification failed: invalid token - Signature verification failed`。
# 两个键**各自独立下发**（admin-api 用 `classpath:rsa/public.pem`；ai-agent 用 `.env` 的 `JWT_PUBLIC_KEY`），
# 而本机 `backend/ai-agent-service/.env` 是 **gitignored** 的 ⇒ 仓库里换过密钥对之后，本地这份会**静默陈旧**
# （2026-08-13 的 #360 换过密钥对；.env 停在更早那对）。
# ⇒ 判据：起栈后**立即**比指纹（比对的是公钥内容，**不涉及任何私钥 / 凭据**）。
#   不齐 ⇒ 命名两个指纹 + 给一条可行动处置，并把会话类旅程按「未配置」单列
#   （**不许**让它继续伪装成产品失败 —— #6790 判据 ③ 的同族）。
# 边界（照实登记）：只裁「admin-api 的 classpath 公钥 vs ai-agent 生效公钥」这一对；
#   admin-api 用 `JWT_PUBLIC_KEY_PEM`/`JWT_PRIVATE_KEY_PEM` 注入**其余对**时本预检不覆盖。
# 严格档（默认关）：`SMOKE_STRICT_KEY_ALIGNMENT=1` ⇒ 不齐即非零退出，防「静默降级成未配置」被当绿。
# 单一真值源 = `scripts/align_agent_jwt_key.py --state`（同一份逻辑既供人修、又供本预检读；
# 不在这里再抄一份解析 —— 抄第二份就会漂，而漂了没有任何东西会红）。
# ⚠️ 本块**自成一体**（`REPO_ROOT` / `MAIN_REPO` / `SCRIPT_DIR` 都带 `:-` 兜底）：它会被判据在沙箱里
#    整块 `source` 真跑（tests/unit_ci_workflows/test_agent_jwt_key_alignment.py）——
#    依赖外部恰好赋过值，会让「整块当单元跑」炸在 unbound variable 上。
REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)}"
MAIN_REPO="${MAIN_REPO:-$(dirname "$REPO_ROOT")/migao}"
[ -d "$MAIN_REPO" ] || MAIN_REPO="$REPO_ROOT"
SCRIPT_DIR="${SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)}"
AGENT_KEY_ALIGN="$(ALIGN_ENV="$REPO_ROOT/backend/ai-agent-service/.env" \
  ALIGN_ENV_FALLBACK="$MAIN_REPO/backend/ai-agent-service/.env" \
  ALIGN_PEM="$REPO_ROOT/backend/admin-api/src/main/resources/rsa/public.pem" \
  ALIGN_PEM_FALLBACK="$MAIN_REPO/backend/admin-api/src/main/resources/rsa/public.pem" \
  "${PYTHON_BIN:-python3}" "$SCRIPT_DIR/align_agent_jwt_key.py" --state 2>/dev/null || echo 'unknown:na:na')"
AGENT_KEY_STATE="${AGENT_KEY_ALIGN%%:*}"
AGENT_KEY_API_FP="$(printf '%s' "$AGENT_KEY_ALIGN" | cut -d: -f2)"
AGENT_KEY_AGENT_FP="$(printf '%s' "$AGENT_KEY_ALIGN" | cut -d: -f3)"
if [ "$AGENT_KEY_STATE" = "mismatch" ]; then
  echo "  ⚠️ [未配置] admin-api 签发密钥与 ai-agent 校验公钥**不是同一对**（issue #6801）"
  echo "      admin-api classpath 公钥指纹: ${AGENT_KEY_API_FP}"
  echo "      ai-agent .env 生效公钥指纹 : ${AGENT_KEY_AGENT_FP}"
  echo "      ⇒ 06-agent-sessions / 07-chat 会收到 401（ai-agent 日志：Signature verification failed）；"
  echo "        这是**环境**失配，不是产品缺陷。处置（step1 复原 .env 该键 → step2 重启 ai-agent）："
  echo "        step1: python3 scripts/align_agent_jwt_key.py   （就地重写 ai-agent .env 的该键）"
  echo "        step2: 杀 :$AGENT_PORT 后重起 ai-agent（.env 不热加载）"
  echo "        复算: 本脚本的「[prep] 验签公钥对齐」一行必须印 aligned 指纹"
  SMOKE_UNCONFIGURED=1
  SMOKE_UNCONFIGURED_WHY="admin-api 签发密钥与 ai-agent 校验公钥不是同一对（#6801）：${AGENT_KEY_API_FP} vs ${AGENT_KEY_AGENT_FP}"
  export SMOKE_UNCONFIGURED SMOKE_UNCONFIGURED_WHY
  if [ "${SMOKE_STRICT_KEY_ALIGNMENT:-0}" = "1" ]; then
    echo "  ✗ SMOKE_STRICT_KEY_ALIGNMENT=1：验签密钥不齐 ⇒ 非零退出（不跑 spec，避免 401 被读成产品失败）"
    exit 1
  fi
elif [ "$AGENT_KEY_STATE" = "unknown" ]; then
  echo "  [prep] 验签公钥对齐：**判不了**（取不到 admin-api classpath 公钥或 ai-agent .env）—— 不当通过读"
else
  echo "  [prep] 验签公钥对齐：admin-api 与 ai-agent 同一对（指纹 ${AGENT_KEY_API_FP}）"
fi

# ── 3. SMS 限流清理 + 防刷窗口（登录旅程需要发码）──
"${PYTHON_BIN:-python3}" - "$REPO_ROOT/backend/admin-api/.env" << 'EOF' >/dev/null 2>&1 || true
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
# 「没跑」必须长得像「没跑」（issue #6777；§19.1）：入口不可用 / spec 没产出汇总时**不得**印
# 「spec 退出码: N」—— 那会把「一行旅程都没跑」说成「有旅程失败」，并把人指向**不存在**的
# smoke-summary.md / smoke-results.json。判据 = tests/unit_ci_workflows/test_ui_smoke_worktree_deps.py
# （含 `EXTRA_ARGS` 的空数组护栏，防 #6777 的 bash 3.2 形态再回来）。
SPEC="$SCRIPT_DIR/ui-smoke-merchant/spec.mjs"
LOG="$OUT_DIR/smoke.log"
SPEC_NOT_RUN_WHY=""
if [ ! -f "$SPEC" ]; then
  SPEC_NOT_RUN_WHY="找不到 spec 文件：${SPEC}"
elif ! command -v node >/dev/null 2>&1; then
  SPEC_NOT_RUN_WHY="PATH 里没有 node（spec 是 .mjs，没有 node 跑不起来）"
fi
if [ -n "$SPEC_NOT_RUN_WHY" ]; then
  echo "==> ✗ spec **未执行**（${SPEC_NOT_RUN_WHY}）"
  echo "    ⇒ 一行旅程都没跑 —— 这不是「31 旅程里某几条失败」，本轮的 UI 验收**没有发生**。"
  EXIT=1
else
  echo "==> 执行冒烟 spec（31 旅程）..."
  set +e
  # `${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}` 的花括号与 `+` **不能省**：macOS bash 3.2 在 `set -u` 下把
  # **空数组**的 `"${EXTRA_ARGS[@]}"` 判成 unbound variable ⇒ spec 一行都没跑（issue #6777；
  # 实测 `bash -c 'set -u; A=(); echo "${A[@]}"'` ⇒ exit 127）。非空时逐字转发，语义不变。
  BASE_URL="http://localhost:$WEB_PORT" \
  REPO_ROOT="$MAIN_REPO" \
  OUT_DIR="$OUT_DIR" \
  PHONE="$PHONE" SMS_CODE="$SMS_CODE" \
  SMOKE_UNCONFIGURED="${SMOKE_UNCONFIGURED:-0}" \
  SMOKE_UNCONFIGURED_WHY="${SMOKE_UNCONFIGURED_WHY:-}" \
  node "$SPEC" ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} 2>&1 | tee "$LOG"
  EXIT=${PIPESTATUS[0]}
  set -e
  if [ -f "$OUT_DIR/smoke-summary.md" ] && [ -f "$OUT_DIR/smoke-results.json" ]; then
    echo "==> spec 退出码: ${EXIT}（0=无真实失败；见 $OUT_DIR/smoke-summary.md / smoke-results.json）"
    # 汇总里**单独标一类**（issue #6790 判据 ③）：未配置 / skip **不与真实失败混在一张表**
    summary_breakdown="$("${PYTHON_BIN:-python3}" - "$OUT_DIR/smoke-results.json" <<'PYEOF' 2>/dev/null || true
import json, sys
try:
    rows = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    sys.exit(0)
unc = [r["journey"] for r in rows if r.get("unconfigured")]
skip = [r["journey"] for r in rows if r.get("skipped")]
fail = [r["journey"] for r in rows if not r.get("pass") and not r.get("unconfigured") and not r.get("skipped")]
print(f"通过 {sum(1 for r in rows if r.get('pass'))} / 失败 {len(fail)} / 未配置 {len(unc)} / skip {len(skip)}")
if fail:
    print("  真实失败: " + " ".join(fail))
if unc:
    print("  ➖ 未配置（ai-agent 未配置，不是产品失败）: " + " ".join(unc))
if skip:
    print("  ⏭️  skip（前置/依赖不满足，未跑）: " + " ".join(skip))
PYEOF
)"
    [ -n "$summary_breakdown" ] && printf '    分类: %s\n' "$summary_breakdown"
    if [ "${SMOKE_UNCONFIGURED:-0}" = "1" ]; then
      echo "    ⚠️ 本轮 ai-agent **未配置**：「➖ 未配置」那几条的成因不在产品；"
      echo "       判据 U（.github/cases 的 UI-AI-AGENT-CONFIG）要求汇总把它们单列，本轮已单列。"
      if [ -n "${SMOKE_UNCONFIGURED_WHY:-}" ]; then
        echo "       形态: ${SMOKE_UNCONFIGURED_WHY}"
        echo "       （#6801 起：这类**环境**失配必须与产品失败分开看 —— 401 不是产品缺陷）"
      fi
    fi
  else
    echo "==> ✗ spec **未执行**（node 退出码 ${EXIT}，但没产出 smoke-summary.md / smoke-results.json）"
    echo "    ⇒ 一行旅程都没跑（0 字节的 ${LOG} = 连 spec 启动都没走到）；这不是「有旅程失败」。"
    EXIT=1
  fi
fi

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
