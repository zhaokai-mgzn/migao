#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════
# B 端上线值守 —— 一条**只读**命令，把「B 端线上是否健康 / 是否落后本仓库」看全
#
# 用户 2026-11-23 逐字：「不碰C端，先把B端做夯实」。v1.0.2 已上线（2026-11-23 10:49:54），
# 而判断「B 端线上是否健康 / 是否落后本仓库」原先要分别跑 3~4 个东西（冒烟 / 版本身份 /
# 域名泄漏 / 包体台账），**漏一面就会以为「没事」**。本脚本把它们编排成**一屏读数**：
# 每行 `PASS` / `FAIL` / `SKIP`（不可判定），最后一行机读汇总 + 三态退出码。
#
# ## 五个面（**一个 C 端面都没有**：`app.*` 的 h5 根与 `/w/` 都**不在**射程）
#
# | # | 面 | 判据 | 判据本体（**复用，不重写**） |
# |---|---|---|---|
# | ① | 健康 | 五个 B 端面 **200**（单次超时上限 `-m`） | 本脚本（只用 `curl`；见下「为什么不复用冒烟段的健康面」） |
# | ② | 版本身份 | 线上 `sha` == **`origin/release`**（发布线，**不是** main） | `deploy/scripts/served-version-verify.sh` + `deploy/scripts/admin-web-version-probe.sh` |
# | ③ | 域名泄漏 | B 端相关面响应体里 `migaozn` 命中 **== 0** | `deploy/scripts/prod-smoke.sh` 的泄漏段（`SMOKE_ONLY=leak` 只跑它） |
# | ④ | 小程序包体 | 最近一次实测 dist 读数 ≤ 主包预算（够不够下一次发版） | `deploy/scripts/bmini-dist-budget.json` 的预算常量 + `measurements`（**单一来源**，本脚本不写死任何上限） |
# | ⑤ | 客户端错误 | 拉 Top-N | **载体缺失** ⇒ 恒 `SKIP` + 写「重启条件」（**不**为凑一条而新建上报通道） |
#
# ## 为什么不复用 `prod-smoke.sh` 的健康段（①）
#
# `deploy/scripts/prod-smoke.sh` 是**部署腿**的冒烟（`deploy-prod.yml` 每次都跑），它的面清单是
# 「本次部署**应该**全在」：8 个面里含 `https://app.<域>/`（h5 根）与 `/w/`（工人端）——`/` 这一面
# 正是本命令**明令不探**的 C 端根；而且它对「连不上」判 **红**（部署后连不上确实是缺陷）。
# 本命令是**人工值守读数**：本机离线 / 网络抖动不该被读成「B 端坏了」⇒ 连不上是 `SKIP`。
# 两条语义相反 ⇒ 健康段由本脚本自己发 `curl`（判据就是一个 `200` 比对）；其余三段**必须**复用既有实现。
#
# ## 三态退出码（`3` **不得当 0 读**；本仓既有约定）
#
# | 码 | 含义 | 怎么读 |
# |---|---|---|
# | 0 | 每个面都 `PASS` | 通过 |
# | 1 | 至少一个 `FAIL`（**1 优先于 3**：已确定的缺陷不该被「另一面探不到」稀释） | 判红，具名到面 |
# | 3 | 无 `FAIL` 但有 `SKIP`（探不到 / 载体缺失） | **不是通过**：有面判不了 |
# | 2 | 用法错误（未知参数） | 命令没跑成 |
#
# 🔴 **常态是 `rc=3`，不是故障**：⑤ 客户端错误面的只读载体**今天不存在** ⇒ 缺省全跑时必然有 1 个
# `SKIP`。把它折成 `0` 就是本仓反复踩过的「探不到当通过」。子集模式（`BMINI_GOLIVE_FACES=…`）
# 只用于**定位/演练**，**不代表上线健康** —— 汇报请贴缺省全跑的那一行 `BMINI-GOLIVE-SUMMARY`。
#
# ## 注入点（判据用；沿用 `SERVED_VERSION_*` / `PROD_HEADERS_*` / `SMOKE_*` 先例）
#
#   BMINI_GOLIVE_APP_BASE / _API_BASE / _AI_BASE / _MERCHANT_BASE / _SITE_BASE  各面基址
#   BMINI_GOLIVE_TIMEOUT      单次 curl 超时秒（默认 15）
#   BMINI_GOLIVE_CURL_BIN     curl 路径（默认 PATH 里的 `curl`；判据用桩替身）
#   BMINI_GOLIVE_FACES        逗号分隔的面子集（默认五面全跑）；**空/未知 ⇒ rc=3，绝不当绿**
#   BMINI_GOLIVE_RELEASE_REF  发布线 ref（默认 `origin/release`）
#   BMINI_GOLIVE_RELEASE_SHA  直接给发布身份（默认从上面的 ref 现取；给空串 = 回落到 ref）
#   BMINI_GOLIVE_BUDGET_FILE  包体预算台账（默认 `deploy/scripts/bmini-dist-budget.json`）
#   BMINI_GOLIVE_REPO         仓库根（默认按脚本位置推）
#
# ## 只读（结构性保证）
#
# 不写任何文件（不落盘 / 不建临时目录）、不改 git（不拉取 / 不切分支 / 不推送）、
# 不触发部署或发布、**不引定时排程**（用户 2026-09-21 裁定：不新增无人值守的周期任务）。
# 委托的两个身份探针内部各自建临时目录取响应体（**既有实现**的行为，不在本脚本内），
# 本脚本自己不产生任何写面。判据 = 本文件的「只读 / 无排程 / 无 C 端面」三条静态守卫。
#
# 用法:
#   bash scripts/bmini-golive-watch.sh                # 五面全跑（常态 rc=3，见上）
#   bash scripts/bmini-golive-watch.sh --help
#
# 判据 = tests/unit_ci_workflows/test_bmini_golive_watch.py（case BM-069）
# ══════════════════════════════════════════════════════════════════════════
set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=${BMINI_GOLIVE_REPO:-$(git -C "$SCRIPT_DIR/.." rev-parse --show-toplevel 2>/dev/null || printf '%s' "$SCRIPT_DIR/..")}

CURL_BIN=${BMINI_GOLIVE_CURL_BIN:-curl}
TIMEOUT=${BMINI_GOLIVE_TIMEOUT:-15}
APP_BASE=${BMINI_GOLIVE_APP_BASE:-https://app.cytda.com}
API_BASE=${BMINI_GOLIVE_API_BASE:-https://api.cytda.com}
AI_BASE=${BMINI_GOLIVE_AI_BASE:-https://ai-api.cytda.com}
MERCHANT_BASE=${BMINI_GOLIVE_MERCHANT_BASE:-https://merchant.cytda.com}
SITE_BASE=${BMINI_GOLIVE_SITE_BASE:-https://cytda.com}
RELEASE_REF=${BMINI_GOLIVE_RELEASE_REF:-origin/release}
RELEASE_SHA=${BMINI_GOLIVE_RELEASE_SHA:-}
BUDGET_FILE=${BMINI_GOLIVE_BUDGET_FILE:-$REPO_ROOT/deploy/scripts/bmini-dist-budget.json}
FACES_RAW=${BMINI_GOLIVE_FACES:-health,identity,leak,budget,client-errors}
FACE_ORDER='health identity leak budget client-errors'

while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help) sed -n '2,70p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "::error::未知参数：$1（--help 看用法）"; exit 2 ;;
  esac
done

PASS_N=0
FAIL_N=0
SKIP_N=0
ST_health=PASS
ST_identity=PASS
ST_leak=PASS
ST_budget=PASS
ST_client_errors=PASS
SHA7=''

status_line() { printf '   %-5s %-42s %s\n' "$1" "$2" "$3"; }
detail() { printf '          %s\n' "$*"; }
pass() { PASS_N=$((PASS_N + 1)); status_line PASS "$@"; }
fail() { FAIL_N=$((FAIL_N + 1)); status_line FAIL "$@"; }
skip() { SKIP_N=$((SKIP_N + 1)); status_line SKIP "$@"; }

#: 逗号分隔的面子集筛选
wanted() {
  case ",${FACES_RAW}," in
    *",$1,"*) return 0 ;;
  esac
  return 1
}

#: 起址 → 裸域（`https://cytda.com/x` ⇒ `cytda.com`）；`prod-smoke.sh` 的 `SMOKE_BASE` 要裸域
host_of() {
  printf '%s' "$1" | sed -E 's#^[a-zA-Z]+://##; s#/.*$##'
}

#: 探针输出里的第一条 `::error::`（去掉前缀；过长截断）—— 判红/不可判定时用于**具名归因**
first_error() {
  printf '%s\n' "$1" | sed -n 's/^::error:://p' | head -1 | cut -c1-220
}

#: 千分位（只用于读数可读性；逐位拼，不依赖 locale / BSD sed 的标签循环）
commas() {
  local n=$1 out='' i=0
  while [ -n "$n" ]; do
    out="${n: -1}${out}"
    n=${n:0:${#n}-1}
    i=$((i + 1))
    if [ $((i % 3)) -eq 0 ] && [ -n "$n" ]; then
      out=",${out}"
    fi
  done
  printf '%s' "$out"
}

#: 面状态（FAIL > SKIP > PASS；由该面内计数变化推出，不靠人记）
set_face_status() {
  case "$1" in
    health) ST_health=$2 ;;
    identity) ST_identity=$2 ;;
    leak) ST_leak=$2 ;;
    budget) ST_budget=$2 ;;
    client-errors) ST_client_errors=$2 ;;
  esac
}

face_title() {
  case "$1" in
    health) printf '① 健康（5 个 B 端面 · 200 判定 · 超时上限 %ss）' "$TIMEOUT" ;;
    identity) printf '② 版本身份（线上 sha 必须 == %s）' "$RELEASE_REF" ;;
    leak) printf '③ 域名泄漏（B 端相关面 migaozn 命中必须 0）' ;;
    budget) printf '④ 小程序包体（最近实测 dist 读数 vs 主包预算）' ;;
    client-errors) printf '⑤ 客户端错误 Top-N（B 端）' ;;
  esac
}

run_face() {
  local name=$1 p0=$PASS_N f0=$FAIL_N s0=$SKIP_N st=PASS fn
  fn="face_${name//-/_}"   # 面名带连字符（`client-errors`），函数名只能是下划线
  printf '\n%s\n' "$(face_title "$name")"
  "$fn"
  if [ "$FAIL_N" -gt "$f0" ]; then
    st=FAIL
  elif [ "$SKIP_N" -gt "$s0" ]; then
    st=SKIP
  fi
  set_face_status "$name" "$st"
}

# ── ① 健康：五个 B 端面，200 通过；拿到非 200 的**响应** ⇒ FAIL；连不上 ⇒ SKIP ────────────
face_health() {
  local url code
  for url in "${APP_BASE}/b/" "${API_BASE}/api/version" "${AI_BASE}/version" \
             "${MERCHANT_BASE}/login" "${SITE_BASE}/"; do
    code=$("$CURL_BIN" -sL -o /dev/null -m "$TIMEOUT" -w '%{http_code}' "$url" 2>/dev/null)
    case "$code" in
      200) pass "$url" '200' ;;
      ''|000) skip "$url" '取不到（连接失败 / 超时 / DNS / TLS）—— 判不了，不当通过' ;;
      *) fail "$url" "HTTP ${code}（期望 200）" ;;
    esac
  done
}

# ── ② 版本身份：委托既有探针（0 == 一致 / 1 == 不一致 / 3 == 探不到）────────────────────
probe_identity() {
  local label=$1 script=$2 base=$3 out rc err served7
  if [ ! -r "$script" ]; then
    skip "$label" "缺载体（${script#"$REPO_ROOT"/} 不可读）—— 判不了"
    return
  fi
  # 单次尝试：值守读数要快；调用方仍可用既有 `*_RETRIES` 覆盖（显式给的优先）
  out=$(SERVED_VERSION_RETRIES=${SERVED_VERSION_RETRIES:-1} \
        SERVED_VERSION_RETRY_DELAY=${SERVED_VERSION_RETRY_DELAY:-0} \
        ADMIN_WEB_SERVED_RETRIES=${ADMIN_WEB_SERVED_RETRIES:-1} \
        ADMIN_WEB_SERVED_RETRY_DELAY=${ADMIN_WEB_SERVED_RETRY_DELAY:-0} \
        bash "$script" "$base" "$RELEASE_SHA" 2>&1)
  rc=$?
  err=$(first_error "$out")
  served7=$(printf '%s\n' "$out" | sed -n "s/.*线上读数：sha='\([0-9a-fA-F]\{7,40\}\)'.*/\1/p" | head -1 | tr 'A-Z' 'a-z' | cut -c1-7)
  case "$rc" in
    0) pass "$label" "线上 sha 前 7 位 == ${SHA7}（${RELEASE_REF}）" ;;
    1) fail "$label" "线上 sha ${served7:-（未知）} ≠ ${RELEASE_REF} ${SHA7} —— 线上落后发布线（该腿未随 release 重新部署）"
       detail "${err:-线上 sha 与 ${RELEASE_REF} 不一致}" ;;
    *) skip "$label" "探不到（rc=${rc}）—— 判不了，不当通过"
       detail "${err:-见探针输出}" ;;
  esac
}

face_identity() {
  case "$RELEASE_SHA" in
    ''|*[!0-9a-fA-F]*)
      skip 'release 身份' "取不到 ${RELEASE_REF} 的 sha（本地没有该 ref / 离线）—— 判不了发布线身份"
      return
      ;;
  esac
  probe_identity "api（served-version-verify.sh）" \
    "$REPO_ROOT/deploy/scripts/served-version-verify.sh" "$API_BASE"
  probe_identity "merchant（admin-web-version-probe.sh）" \
    "$REPO_ROOT/deploy/scripts/admin-web-version-probe.sh" "$MERCHANT_BASE"
}

# ── ③ 域名泄漏：委托 `prod-smoke.sh` 的泄漏段（`SMOKE_ONLY=leak`）──────────────────────────
face_leak() {
  local smoke="$REPO_ROOT/deploy/scripts/prod-smoke.sh" out rc face_done
  if [ ! -r "$smoke" ]; then
    skip '域名泄漏' "缺载体（deploy/scripts/prod-smoke.sh 不可读）—— 判不了"
    return
  fi
  out=$(SMOKE_ONLY=leak SMOKE_BASE="$(host_of "$SITE_BASE")" bash "$smoke" 2>&1)
  rc=$?
  # 逐面读数原样带出（判据本体已经打印了 `<url> ✅ 0 处` / `❌ N 处 migaozn` / `⚠️ 不可判定`）
  printf '%s\n' "$out" | grep -E '^https://' | sed 's/^/          /' || true
  face_done=$(printf '%s\n' "$out" | grep -cE '^https://.*✅' || true)
  case "$rc" in
    0) pass 'migaozn 命中（B 端相关面）' "0 处（${face_done} 面通过）" ;;
    1) fail 'migaozn 命中（B 端相关面）' '有面命中 migaozn.com（逐面读数见上）—— 构建用了测试基址' ;;
    *) skip 'migaozn 命中（B 端相关面）' '有面拿不到内容（不可判定）—— 判不了，不当通过' ;;
  esac
}

# ── ④ 小程序包体：读预算台账与最近实测读数（**单一来源**；本脚本不写死任何上限）──────────
face_budget() {
  local out status bytes budget cand_n path margin
  if ! command -v python3 >/dev/null 2>&1; then
    skip '包体预算' '缺 python3 ⇒ 读不了预算台账（不可判定）'
    return
  fi
  if [ ! -r "$BUDGET_FILE" ]; then
    skip '包体预算' "缺台账（${BUDGET_FILE#"$REPO_ROOT"/} 不可读）—— 判不了"
    return
  fi
  out=$(python3 - "$BUDGET_FILE" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    print("bad_json|0|0|0|"); raise SystemExit(0)
if not isinstance(data, dict):
    print("bad_json|0|0|0|"); raise SystemExit(0)
cap = data.get("wechatPackageCapBytes")
reserve = data.get("mainPackageReserveBytes")
if not isinstance(cap, int) or not isinstance(reserve, int) or cap <= reserve:
    print("bad_budget|0|0|0|"); raise SystemExit(0)
cands = []
for m in data.get("measurements") or []:
    if not isinstance(m, dict):
        continue
    dom = str(m.get("domains") or "")
    # 只认**生产域**读数：`cytda=` 命中且 `migaozn=0` —— 测试域/混域/漂移包不许当发版读数
    if "cytda=" not in dom or "migaozn=0" not in dom:
        continue
    b = m.get("bytes")
    if isinstance(b, int) and b > 0:
        cands.append((b, str(m.get("path") or "?")))
if not cands:
    print("no_measurement|0|0|0|"); raise SystemExit(0)
bytes_, path = max(cands)          # 取**最坏**的一份生产域读数（保守方向）
print("OK|%d|%d|%d|%s" % (bytes_, cap - reserve, len(cands), path))
PY
)
  IFS='|' read -r status bytes budget cand_n path <<<"$out"
  case "${status:-ERR}" in
    OK) ;;
    bad_json) skip '包体预算' '台账不是合法 JSON（不可判定）'; return ;;
    bad_budget) skip '包体预算' '台账缺预算常量（wechatPackageCapBytes / mainPackageReserveBytes）'; return ;;
    no_measurement) skip '包体预算' '台账里没有**生产域**实测读数（migaozn=0 的 measurements）—— 判不了'; return ;;
    *) skip '包体预算' '读台账失败（不可判定）'; return ;;
  esac
  margin=$((budget - bytes))
  if [ "$margin" -ge 0 ]; then
    pass '最近实测 dist vs 主包预算' \
      "$(commas "$bytes") ≤ $(commas "$budget")（余量 $(commas "$margin") · ${cand_n} 份生产域读数）"
  else
    fail '最近实测 dist vs 主包预算' \
      "$(commas "$bytes") > $(commas "$budget")（超 $(commas "$((0 - margin))") 字节）—— 下一次发版会撞上限"
  fi
  detail "读数来源：${path}（deploy/scripts/bmini-dist-budget.json 的 measurements）"
}

# ── ⑤ 客户端错误：没有只读出口 ⇒ SKIP（载体缺失 + 重启条件，**不**新建上报通道）──────────
face_client_errors() {
  skip 'Top-N 读数' '载体缺失：拉不到 B 端客户端错误 Top-N'
  detail '现状：客户端错误只写一行服务端日志（backend/admin-api 的 ClientErrorController 只有'
  detail '      POST /api/client-errors，不落库 / 不打分 / 无查询端点），scripts/ 与 deploy/ 里'
  detail '      也没有日志查询（SLS）脚本 ⇒ 没有任何**只读**入口能拉到 Top-N。'
  detail '重启条件：接上只读出口后（SLS 日志查询，或新增只读聚合端点 + 一个只读脚本），'
  detail '      把该出口接进本面；在那之前不许把它读成 PASS（用户裁定：不为凑一条新建上报通道）。'
}

# ── 面子集校验（空 / 未知 ⇒ fail-closed，绝不当绿）──────────────────────────────────────────
bad_faces=''
for token in $(printf '%s' "$FACES_RAW" | tr ',' ' '); do
  case " $FACE_ORDER " in
    *" $token "*) ;;
    *) bad_faces="${bad_faces} ${token}" ;;
  esac
done
requested=0
for name in $FACE_ORDER; do wanted "$name" && requested=$((requested + 1)); done
if [ "$requested" -eq 0 ] || [ -n "$bad_faces" ]; then
  echo "::error::BMINI_GOLIVE_FACES='${FACES_RAW}' 没有命中已知面（未知：${bad_faces:-无}；已知面：${FACE_ORDER}）" >&2
  echo '  空跑 = 假绿：一个面都没判 ⇒ rc=3，绝不当 0 读'
  echo 'BMINI-GOLIVE-SUMMARY rc=3 pass=0 fail=0 skip=0 release=none faces=none'
  exit 3
fi

echo '=============================================================='
echo 'B 端上线值守（只读 · 一条命令看全 5 个面；不含任何 C 端面）'
# 发布身份**先解算**（表头就要显示它；面 ② 复用这个值 —— 两处读同一个，不许分叉）
if [ -z "$RELEASE_SHA" ]; then
  RELEASE_SHA=$(git -C "$REPO_ROOT" rev-parse --verify --quiet "$RELEASE_REF" 2>/dev/null || true)
fi
case "$RELEASE_SHA" in
  ''|*[!0-9a-fA-F]*) RELEASE_SHA='' ;;
  *) SHA7=$(printf '%s' "$RELEASE_SHA" | tr 'A-Z' 'a-z' | cut -c1-7) ;;
esac
echo "  发布线：${RELEASE_REF}=${SHA7:-（未取到）} · 超时 ${TIMEOUT}s · 面：${FACES_RAW}"
echo '=============================================================='

for name in $FACE_ORDER; do
  wanted "$name" && run_face "$name"
done

RC=0
if [ "$FAIL_N" -gt 0 ]; then
  RC=1
elif [ "$SKIP_N" -gt 0 ]; then
  RC=3
fi

echo
case "$RC" in
  0) printf '%s\n' "合计：PASS ${PASS_N} · FAIL 0 · SKIP 0 ⇒ rc=0（每一面都判过且都通过）" ;;
  1) printf '%s\n' "合计：PASS ${PASS_N} · FAIL ${FAIL_N} · SKIP ${SKIP_N} ⇒ rc=1（有面不成立，逐条见上）" ;;
  *) printf '%s\n' "合计：PASS ${PASS_N} · FAIL 0 · SKIP ${SKIP_N} ⇒ rc=3（有面判不了，**不当通过**）" ;;
esac
printf 'BMINI-GOLIVE-SUMMARY rc=%s pass=%s fail=%s skip=%s release=%s faces=health:%s,identity:%s,leak:%s,budget:%s,client-errors:%s\n' \
  "$RC" "$PASS_N" "$FAIL_N" "$SKIP_N" "${SHA7:-none}" \
  "$ST_health" "$ST_identity" "$ST_leak" "$ST_budget" "$ST_client_errors"
exit "$RC"
