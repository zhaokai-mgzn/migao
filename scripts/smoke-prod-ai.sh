#!/usr/bin/env bash
# 冒烟「双档」入口（issue #9082）：**日常 → 测试机完整档；发版前 → 生产只读档一次**。
#
# 用户裁定（2026-11-23，逐字）：
#   「我们是 ai native 公司，冒烟都需要 AI 跑」
#   「以后还是需要先在测试机器上做充分验证，只有要发布生产的时候才在发布前走一次生产环境的冒烟」
#
# 两个档，时机不同、跑的东西不同（时机是**判据**，不是建议）：
#
#   --env test（默认档，AI 天天跑，一起提交后就应该跑）
#     目标 = 测试机（api.migaozn.com / ai-api.migaozn.com）
#     内容 = `tests/smoke/` **完整档**（含写类用例、AI 会话、建单、删会话 —— 测试机可以随便写）
#     凭据 = ① 已注入 SMOKE_ADMIN_TOKEN ⇒ 直接用
#            ② 给了 MIGAO_SMOKE_IDENTIFIER + MIGAO_SMOKE_PASSWORD ⇒ 员工登录换 token 注入
#            ③ 都没给 ⇒ 测试机固定码（SMS_BYPASS_CODE=123456 **只在测试环境**成立；生产禁止开 bypass）
#
#   --env prod（发版闸门档，**只在「即将发生产」时跑一次**，不许当日常回归）
#     目标 = 生产（api.cytda.com / ai-api.cytda.com）
#     内容 = `tests/smoke/prod_readonly_profile.json` 的**只读子集**（单点来源，不跑 `-m p0` 整档：
#            `test_04_ai_chat` 写会话、`test_09_order_lifecycle` 建单、AI 面还烧 LLM 成本）
#     凭据 = **必须**给 MIGAO_SMOKE_IDENTIFIER + MIGAO_SMOKE_PASSWORD（secret / 本机 export）
#            ⇒ 员工账号密码登录（`POST /api/auth/employee/login`，identifier = <用户名>@<企业编码>）
#              换 access token 注入 SMOKE_ADMIN_TOKEN ⇒ 不发短信、不用 bypass
#
# ⛔ **禁止**给本脚本挂 cron / schedule / 部署腿自动触发：`--env prod` 只能由人（或发版流程）显式调用。
#    判据 = `tests/unit_ci_workflows/test_smoke_prod_readonly_profile.py`（静态扫 `.github/workflows/**`）。
#
# 退出码（三态；`3` 不是 `0`）：
#   0 = 全过（failed=0 **且** passed>0 —— 0 条通过的绿是假绿，判不了）
#   1 = 有真红（登录被拒 / 有用例失败）
#   3 = 判不了（缺凭据 / 连不上目标 / 只读档解析不了 / pytest 自身出错 / 收集不到用例）
#
# 用法：
#   ./scripts/smoke-prod-ai.sh                 # = --env test（日常档）
#   ./scripts/smoke-prod-ai.sh --env prod      # 发版闸门档（只读子集，发版前一次）
#
# 可选环境变量（都有安全默认，见函数体）：
#   MIGAO_SMOKE_IDENTIFIER / MIGAO_SMOKE_PASSWORD   员工账号（**secret**，绝不写进任何文件）
#   MIGAO_SMOKE_SMS_CODE                            测试机固定码（仅 --env test 用；默认 123456）
#   MIGAO_TEST_API_URL / MIGAO_TEST_AI_URL          覆盖测试机地址
#   MIGAO_PROD_API_URL / MIGAO_PROD_AI_URL          覆盖生产地址
#   MIGAO_SMOKE_MARKERS                             测试档的 -m 过滤（默认 "not performance"）
#   MIGAO_SMOKE_PYTHON                              解释器（默认 python3）
#   MIGAO_SMOKE_LOG                                 日志落盘路径（默认 mktemp）
set -uo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SMOKE_DIR="$REPO_ROOT/tests/smoke"
PROFILE="$SMOKE_DIR/prod_readonly_profile.json"
PYTHON_BIN="${MIGAO_SMOKE_PYTHON:-python3}"

DEFAULT_TEST_API="https://api.migaozn.com"
DEFAULT_TEST_AI="https://ai-api.migaozn.com"
DEFAULT_PROD_API="https://api.cytda.com"
DEFAULT_PROD_AI="https://ai-api.cytda.com"

say() { printf '%s\n' "$*"; }

finish() {
  # finish <rc> <passed> <skipped> <failed> [附加 k=v ...]
  local rc="$1" passed="${2:-0}" skipped="${3:-0}" failed="${4:-0}"
  shift 4 2>/dev/null || true
  local extra=""
  if [ "$#" -gt 0 ]; then extra=" $*"; fi
  say "${SUMMARY_TAG} rc=${rc} passed=${passed} skipped=${skipped} failed=${failed} target=${TARGET} env=${ENV_KIND}${extra}"
  exit "$rc"
}

undecidable() {
  say "⛔ 判不了：$*"
  finish 3 0 0 0
}

usage() {
  say "用法：$0 [--env test|prod]"
  say "  --env test  （默认）测试机完整档：日常 / 每次合并后跑这个"
  say "  --env prod  发版闸门档：只读子集，**只在「即将发生产」时跑一次**"
}

# ── 员工账号密码登录 ⇒ EMPLOYEE_TOKEN（成功）/ 打印状态与 message 后退出（失败）───────────
# 只打印 HTTP 状态与响应里的 message：**不打印密码、不打印 token、不回显完整响应体**。
employee_login() {
  local login_rc=0 login_out="" detail=""
  login_out=$(
    MIGAO_SMOKE_LOGIN_URL="${BASE_URL}/api/auth/employee/login" "$PYTHON_BIN" - <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

url = os.environ["MIGAO_SMOKE_LOGIN_URL"]
payload = json.dumps({
    "identifier": os.environ.get("MIGAO_SMOKE_IDENTIFIER", ""),
    "password": os.environ.get("MIGAO_SMOKE_PASSWORD", ""),
}).encode("utf-8")
request = urllib.request.Request(
    url, data=payload, method="POST",
    headers={"Content-Type": "application/json", "Accept": "application/json"},
)


def message_of(raw):
    """只取服务端的 message 文案（反枚举的统一文案），截断到 120 字符。

    形态可能是 `{"message": "…"}`，也可能套一层 `{"message": {"code": …, "message": "…"}}`
    —— 2026-11-23 生产实测命中了后者，原样打成 Python repr（读起来像脚本崩了）⇒ 递归取文案。
    """
    try:
        body = json.loads(raw)
    except ValueError:
        return raw.strip()[:120]
    for _ in range(3):  # 最多剥三层，避免病态响应把这里变成死循环
        if not isinstance(body, dict):
            break
        nxt = None
        for key in ("message", "msg", "error", "detail"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:120]
            if isinstance(value, dict):
                nxt = value
                break
        if nxt is None:
            break
        body = nxt
    return ""


def fail(status, message):
    print(json.dumps({"status": status, "message": message}, ensure_ascii=False))
    sys.exit(10)


try:
    with urllib.request.urlopen(request, timeout=20) as response:
        status = response.status
        raw = response.read().decode("utf-8", "replace")
except urllib.error.HTTPError as exc:
    fail(exc.code, message_of(exc.read().decode("utf-8", "replace")))
except Exception as exc:  # DNS / TLS / 连接被拒 / 超时 ⇒ 判不了（没有 HTTP 状态可报）
    print(json.dumps({"status": 0, "message": type(exc).__name__}, ensure_ascii=False))
    sys.exit(12)

if status != 200:
    fail(status, message_of(raw))

try:
    body = json.loads(raw)
except ValueError:
    fail(status, "响应不是 JSON")

node = body.get("data", body) if isinstance(body, dict) else {}
token = ""
if isinstance(node, dict):
    token = node.get("accessToken") or node.get("access_token") or node.get("token") or ""
if not token:
    fail(status, message_of(raw) or "响应里没有 accessToken")
print(token)
PY
  ) || login_rc=$?

  case "$login_rc" in
    0)
      EMPLOYEE_TOKEN=$(printf '%s' "$login_out" | tr -d '\r\n')
      [ -n "$EMPLOYEE_TOKEN" ] || undecidable "登录返回 200 但取不到 accessToken（响应形态变了？）"
      ;;
    10)
      detail=$(printf '%s' "$login_out" | "$PYTHON_BIN" -c 'import json, sys
try:
    body = json.load(sys.stdin)
    print("HTTP %s message=%s" % (body.get("status") or "?", body.get("message") or "<无>"))
except Exception:
    print("HTTP ? message=<响应不可解析>")' 2>/dev/null || true)
      say "⛔ 登录失败：${detail:-HTTP ? message=<响应不可解析>}"
      say "   · 只打印了状态与文案：密码与 token **都不打印**（也不会写进任何文件）"
      say "   · 出口：核对 MIGAO_SMOKE_IDENTIFIER（= <用户名>@<企业编码>）与 MIGAO_SMOKE_PASSWORD（secret 过期 / 账号被禁用 / 需先改密）"
      finish 1 0 0 0
      ;;
    *)
      say "⛔ 登录请求没有得到可判定的结果（传输层错误：DNS / TLS / 连接被拒 / 超时）⇒ 判不了"
      say "   · 目标：${BASE_URL}/api/auth/employee/login"
      finish 3 0 0 0
      ;;
  esac
}

# ── 只读档 ⇒ 空格分隔的 node id（相对 tests/smoke）─────────────────────────────────
profile_node_ids() {
  [ -f "$PROFILE" ] || undecidable "找不到只读档 ${PROFILE}（tests/smoke/prod_readonly_profile.json 是唯一来源）"
  "$PYTHON_BIN" - "$PROFILE" <<'PY'
import json
import sys

PREFIX = "tests/smoke/"
try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        entries = json.load(handle)["tests"]
except Exception as exc:  # 解析失败 ⇒ 判不了，不许静默跑空档
    sys.stderr.write("只读档解析失败: %s\n" % exc)
    raise SystemExit(2)
ids = []
for entry in entries:
    node = str(entry.get("id", "")).strip()
    if not node:
        sys.stderr.write("只读档有缺 id 的条目: %r\n" % (entry,))
        raise SystemExit(2)
    ids.append(node[len(PREFIX):] if node.startswith(PREFIX) else node)
if not ids:
    sys.stderr.write("只读档是空的（空档 = 什么都没跑，不是绿）\n")
    raise SystemExit(2)
sys.stdout.write("\n".join(ids))
PY
}

# ── 跑 pytest 并给出三态读数（0 / 1 / 3；passed=0 一律判不了）────────────────────────
run_pytest() {
  local label="$1"
  shift
  local log_file counts passed skipped failed pytest_rc rc
  log_file="${MIGAO_SMOKE_LOG:-$(mktemp "${TMPDIR:-/tmp}/migao-smoke.XXXXXX.log")}"
  say "ℹ️ 档=${label} SMOKE_ENV=${SMOKE_ENV_VALUE} target=${TARGET}（凭据只从环境变量读，不入库）"
  ( cd "$SMOKE_DIR" && "$PYTHON_BIN" -m pytest "$@" -q --tb=short --timeout=120 -p no:cacheprovider ) 2>&1 | tee "$log_file"
  pytest_rc=${PIPESTATUS[0]}

  counts=$("$PYTHON_BIN" - "$log_file" <<'PY'
import re
import sys

text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
summary = ""
for line in text.splitlines():
    if re.search(r"\b\d+ (passed|failed|error)", line):
        summary = line


def num(word):
    found = re.search(r"(\d+) " + word, summary)
    return int(found.group(1)) if found else 0


# errors 并入 failed：fixture 级错误也是红，不许读成 failed=0
print(num("passed"), num("skipped"), num("failed") + num("error"))
PY
  ) || counts="0 0 0"
  passed=$(printf '%s' "$counts" | cut -d' ' -f1); passed=${passed:-0}
  skipped=$(printf '%s' "$counts" | cut -d' ' -f2); skipped=${skipped:-0}
  failed=$(printf '%s' "$counts" | cut -d' ' -f3); failed=${failed:-0}

  case "$pytest_rc" in
    0)
      if [ "$passed" -gt 0 ]; then
        rc=0
      else
        rc=3
        say "⛔ 0 条通过 ⇒ 判不了（收集到 0 条 / 全被跳过，这种绿是假绿）"
      fi
      ;;
    1)
      rc=1
      ;;
    5)
      rc=3
      say "⛔ pytest 收集不到用例（rc=5）⇒ 判不了（只读档或路径改名了？先跑元守卫）"
      ;;
    *)
      rc=3
      say "⛔ pytest 自身出错（rc=${pytest_rc}）⇒ 判不了"
      ;;
  esac

  if [ "$rc" -ne 0 ]; then
    say "─── 失败尾部 40 行（完整日志：${log_file}）───"
    tail -n 40 "$log_file"
  else
    say "ℹ️ 完整日志：${log_file}"
  fi
  finish "$rc" "$passed" "$skipped" "$failed" "档=${label}"
}

# ── 参数 ─────────────────────────────────────────────────────────────────────────────
ENV_KIND="test"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --env)
      ENV_KIND="${2:-}"
      shift
      [ "$#" -gt 0 ] && shift
      ;;
    --env=*)
      ENV_KIND="${1#--env=}"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      say "⛔ 判不了：未知参数 $1"
      usage
      exit 3
      ;;
  esac
done

case "$ENV_KIND" in
  test)
    SUMMARY_TAG="TEST-SMOKE"
    BASE_URL="${MIGAO_TEST_API_URL:-$DEFAULT_TEST_API}"
    AI_URL="${MIGAO_TEST_AI_URL:-$DEFAULT_TEST_AI}"
    SMOKE_ENV_VALUE="staging"   # tests/smoke/config.py 的 staging 档 = api.migaozn.com
    ;;
  prod|production)
    ENV_KIND="prod"
    SUMMARY_TAG="PROD-SMOKE"
    BASE_URL="${MIGAO_PROD_API_URL:-$DEFAULT_PROD_API}"
    AI_URL="${MIGAO_PROD_AI_URL:-$DEFAULT_PROD_AI}"
    SMOKE_ENV_VALUE="production"
    ;;
  *)
    say "⛔ 判不了：--env 只能是 test / prod，收到 '${ENV_KIND}'"
    usage
    exit 3
    ;;
esac

BASE_URL="${BASE_URL%/}"
TARGET="${BASE_URL#*://}"
TARGET="${TARGET%%/*}"

case "$ENV_KIND" in
  prod)
    # ⚠️ 发版闸门档：只在「即将发生产」时跑一次 —— 横幅必须留在输出里，可 grep 可对账。
    say "════════════════════════════════════════════════════════════════════════"
    say "⚠️ 本档只在「即将发生产」时跑一次；日常验证请在测试机跑 --env test"
    say "════════════════════════════════════════════════════════════════════════"

    missing=""
    [ -n "${MIGAO_SMOKE_IDENTIFIER:-}" ] || missing="${missing} MIGAO_SMOKE_IDENTIFIER"
    [ -n "${MIGAO_SMOKE_PASSWORD:-}" ] || missing="${missing} MIGAO_SMOKE_PASSWORD"
    if [ -n "$missing" ]; then
      say "⛔ 判不了：缺少凭据环境变量:${missing}"
      say "   · 本机：export MIGAO_SMOKE_IDENTIFIER='<用户名>@<企业编码>'; export MIGAO_SMOKE_PASSWORD='<密码>'"
      say "   · CI  ：去配 secret（MIGAO_SMOKE_IDENTIFIER / MIGAO_SMOKE_PASSWORD）；仓库里没有默认值，也不许加"
      say "   · 为什么不用 bypass：生产禁止开 SMS_BYPASS_CODE（#8977 已否决弱化登录）"
      finish 3 0 0 0
    fi

    export SMOKE_ENV="$SMOKE_ENV_VALUE"
    export ADMIN_API_URL="$BASE_URL"
    export AI_AGENT_URL="$AI_URL"
    employee_login
    export SMOKE_ADMIN_TOKEN="$EMPLOYEE_TOKEN"
    unset EMPLOYEE_TOKEN

    NODE_IDS=$(profile_node_ids) || undecidable "只读档 ${PROFILE} 解析失败（判据：tests/unit_ci_workflows/test_smoke_prod_readonly_profile.py）"
    NODE_ID_COUNT=$(printf '%s\n' "$NODE_IDS" | wc -l | tr -d ' ')
    say "ℹ️ 只读档 ${NODE_ID_COUNT} 条（${PROFILE##*/}）；写类用例一律不跑：生产不打白工、不写脏数据、不烧 LLM"
    # shellcheck disable=SC2086  # node id 以换行分隔，必须分词
    run_pytest "prod-readonly" $NODE_IDS
    ;;
  *)
    export SMOKE_ENV="$SMOKE_ENV_VALUE"
    export ADMIN_API_URL="$BASE_URL"
    export AI_AGENT_URL="$AI_URL"

    if [ -n "${SMOKE_ADMIN_TOKEN:-}" ]; then
      say "ℹ️ 凭据路径 = 已注入的 SMOKE_ADMIN_TOKEN（不登录、不发码）"
    elif [ -n "${MIGAO_SMOKE_IDENTIFIER:-}" ] && [ -n "${MIGAO_SMOKE_PASSWORD:-}" ]; then
      say "ℹ️ 凭据路径 = 员工账号密码登录（identifier / password 只从环境变量读）"
      employee_login
      export SMOKE_ADMIN_TOKEN="$EMPLOYEE_TOKEN"
      unset EMPLOYEE_TOKEN
    elif [ -n "${MIGAO_SMOKE_IDENTIFIER:-}${MIGAO_SMOKE_PASSWORD:-}" ]; then
      say "⛔ 判不了：MIGAO_SMOKE_IDENTIFIER / MIGAO_SMOKE_PASSWORD 必须**成对**给（只给一半不猜）"
      finish 3 0 0 0
    else
      # 测试机的 bypass/固定码：**只在测试环境**允许（生产禁止开 bypass，见 README）
      export ADMIN_SMS_CODE="${MIGAO_SMOKE_SMS_CODE:-${ADMIN_SMS_CODE:-123456}}"
      export ADMIN_PHONE="${ADMIN_PHONE:-13900001025}"
      say "ℹ️ 凭据路径 = 测试机固定码（ADMIN_SMS_CODE，conftest 只登录一次）；"
      say "   要改用员工账号密码 ⇒ export MIGAO_SMOKE_IDENTIFIER / MIGAO_SMOKE_PASSWORD"
    fi

    MARKERS="${MIGAO_SMOKE_MARKERS:-not performance}"
    say "ℹ️ 完整档（-m '${MARKERS}'）：写类用例就该在测试机上写（建单 / 建会话 / 删会话 / 改价），生产不跑这些"
    # shellcheck disable=SC2086  # markers 表达式需要分词
    run_pytest "test-full" -m "$MARKERS"
    ;;
esac
