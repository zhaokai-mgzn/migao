#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════
# 线上安全响应头判据（**只读**；issue #8218 P1-08 / P1-09，2026-10-31 上线审计）
#
# ## 病（逐条都是线上读数，不是推断）
#
# 1. **P1-08「声明存在 ≠ 可达」**：`backend/admin-api/.../SecurityConfig` 里明明白白声明了
#    HSTS（`maxAgeInSeconds(31536000).includeSubDomains(true)`），而线上
#    `curl -sI https://api.migaozn.com/api/version | grep -i strict-transport` **无输出**。
#    机制：nginx 终止 TLS 后以 **http** 回源（真实协议放在 `X-Forwarded-Proto: https`），
#    Spring 默认**不看**这个头 ⇒ `request.isSecure()` 为假 ⇒ Spring Security 的 HSTS
#    **一个字节都不发**。修法 = `server.forward-headers-strategy: framework`（同一单里改）。
# 2. **P1-09 静态域零安全头**：`/w/`（工人端）、`/b/`（商家端）、`/download`（官网下载页）
#    三条面**都没有** nosniff / HSTS / CSP。两个前端都把会话摆在 localStorage ⇒ 一次 XSS
#    即可冒用**工人身份**报工 / 入库（涉钱）。
#
# ## 判据（逐面；**线上真的 200 的面**才配当判据 —— 这条本身就是 P1-05 的教训）
#
# | 面 | URL | 期望 |
# |---|---|---|
# | api 版本面（Spring 发 HSTS） | `{api}/api/version` | 200 + HSTS + nosniff |
# | 商家后台登录页 | `{merchant}/login` | 200 + HSTS + nosniff |
# | 官网下载页（审计点名的 `/download`） | `{site}/download` | 200 + HSTS + nosniff |
# | 工人报工页 | `{app}/w/` | 200 + HSTS + nosniff + **CSP** |
# | 商家端 h5 | `{app}/b/` | 200 + HSTS + nosniff + **CSP** |
# | 终端下载面（issue #8195） | `{app}/terminal/` | 301/404（面还没发布也算合格）**但头必须齐** |
# | ai-agent 健康面（FastAPI，nginx 补头） | `{ai_api}/health` | 200 + HSTS + nosniff |
#
# CSP 的「最小」是**可判定**的三条：① 必须含 `default-src 'self'` ② 必须含 `script-src`
# ③ 不得出现 `*` 通配来源、不得出现 `unsafe-eval`（宽松到那一步就等于没 CSP）。
#
# ## 三态退出码（**3 不得当 0 读**）
#
# | 码 | 含义 |
# |---|---|
# | 0 | 全部面**都**带齐了必需的头 |
# | 1 | 有**确定**的缺陷：缺头 / `max-age` 太小 / CSP 形态不合规 / 该 200 的面不是 200 |
# | 3 | **无法判定**：连不上 / 拿不到响应头（既不是通过，也不归因成缺陷）|
#
# 1 优先于 3：**已经确定的缺陷不该被「另一面探不到」稀释成「不可判定」**。
#
# ## 注入点（判据用；沿用 `TLS_*` / `SERVED_VERSION_*` 先例）
#
#   PROD_HEADERS_API_BASE / _MERCHANT_BASE / _SITE_BASE / _APP_BASE / _AI_BASE  各面基址
#   PROD_HEADERS_CURL_BIN   curl 路径（默认 PATH 里的 curl）
#   PROD_HEADERS_TIMEOUT    单次超时秒（默认 15）
#   PROD_HEADERS_MAX_AGE_MIN  HSTS max-age 下限（默认 15552000 = 180 天）
#
# 判据 = tests/unit_ci_workflows/test_prod_security_headers.py（真起一个本地 stub server 喂
# 两种响应：缺头 ⇒ 1、带齐 ⇒ 0；接线 = `.github/workflows/deploy-admin-api.yml` 的那个 step）
# ══════════════════════════════════════════════════════════════════════════
set -uo pipefail

CURL_BIN=${PROD_HEADERS_CURL_BIN:-curl}
TIMEOUT=${PROD_HEADERS_TIMEOUT:-15}
MAX_AGE_MIN=${PROD_HEADERS_MAX_AGE_MIN:-15552000}

API_BASE=${PROD_HEADERS_API_BASE:-https://api.migaozn.com}
MERCHANT_BASE=${PROD_HEADERS_MERCHANT_BASE:-https://merchant.migaozn.com}
SITE_BASE=${PROD_HEADERS_SITE_BASE:-https://migaozn.com}
APP_BASE=${PROD_HEADERS_APP_BASE:-https://app.migaozn.com}
AI_BASE=${PROD_HEADERS_AI_BASE:-https://ai-api.migaozn.com}

FAILED=0
UNKNOWN=0
PROBED=0

# ── 面 → (url, 期望状态码集合, 是否要求 CSP) ────────────────────────────────────
# 期望状态码写成「逗号分隔的集合」：`/terminal/` 这一面**还没发布**是正常的（404 也是合格回答），
# 但**头必须齐** —— `add_header … always` 在 4xx 上也生效，所以「面没发布」不能当缺头的借口。
FACES="
api-version|${API_BASE}/api/version|200|no
merchant-login|${MERCHANT_BASE}/login|200|no
site-download|${SITE_BASE}/download|200|no
worker-h5|${APP_BASE}/w/|200|yes
bmini-h5|${APP_BASE}/b/|200|yes
terminal-download|${APP_BASE}/terminal/|200,301,404|no
ai-agent-health|${AI_BASE}/health|200|no
"

say() { printf '%s\n' "$*"; }

#: 取一个 URL 的状态码 + 响应头。`<headers>\n__CODE__<code>\n`（取不到时 code=000）
fetch() {
  local url=$1 out
  out=$("$CURL_BIN" -sS -o /dev/null -D - -m "$TIMEOUT" -w '\n__CODE__%{http_code}\n' "$url" 2>/dev/null) || true
  [ -n "$out" ] || out=$'\n__CODE__000\n'
  printf '%s\n' "$out"
}

#: 从响应头里取某个头的值（大小写不敏感；取不到 ⇒ 空串）。用 `awk` 而不是 `grep -i` 是为了
#: 避免「头 A 的值里恰好出现头 B 的名字」这类误命中（例如 CSP 里出现 `x-content-type` 字样）。
header_value() {
  local headers=$1 name=$2
  printf '%s\n' "$headers" \
    | tr -d '\r' \
    | awk -v want="$(printf '%s' "$name" | tr 'A-Z' 'a-z')" '
        { line = $0 }
        {
          pos = index(tolower(line), ":")
          if (pos > 0) {
            k = tolower(substr(line, 1, pos - 1))
            if (k == want) { v = substr(line, pos + 1); sub(/^[ \t]+/, "", v); print v; exit }
          }
        }'
}

#: HSTS 的 max-age（秒；取不到 / 非法 ⇒ 空串）
hsts_max_age() {
  local v
  v=$(header_value "$1" strict-transport-security)
  [ -n "$v" ] || { printf ''; return; }
  printf '%s\n' "$v" | sed -n 's/.*max-age=\([0-9][0-9]*\).*/\1/p' | head -1
}

csp_shape_violations() {
  local csp=$1 bad=''
  printf '%s' "$csp" | tr 'A-Z' 'a-z' | grep -q "default-src 'self'" || bad="${bad}default-src-'self'-missing "
  printf '%s' "$csp" | tr 'A-Z' 'a-z' | grep -q 'script-src' || bad="${bad}script-src-missing "
  printf '%s' "$csp" | grep -q '\*' && bad="${bad}wildcard-source "
  printf '%s' "$csp" | tr 'A-Z' 'a-z' | grep -q "'unsafe-eval'" && bad="${bad}unsafe-eval "
  printf '%s' "$bad"
}

say "== 线上安全响应头判据（issue #8218 P1-08/P1-09；只读）=="
say "   HSTS max-age 下限：${MAX_AGE_MIN}s（≥180 天）；单次超时 ${TIMEOUT}s"

while IFS='|' read -r face url want_codes want_csp; do
  [ -n "${face:-}" ] || continue
  PROBED=$((PROBED + 1))
  raw=$(fetch "$url")
  code=$(printf '%s\n' "$raw" | sed -n 's/^__CODE__\([0-9][0-9]*\)$/\1/p' | tail -1)
  code=${code:-000}
  headers=$(printf '%s\n' "$raw" | sed '/^__CODE__[0-9]*$/d')

  missing=''
  # ① 状态码（取不到 = 无法判定这一类面）
  if [ "$code" = "000" ]; then
    say "  ???? ${face} ${url} —— **取不到响应**（连不上 / DNS / TLS）⇒ 本面无法判定"
    UNKNOWN=$((UNKNOWN + 1))
    printf 'PROD-HEADERS face=%s code=000 ok=unknown\n' "$face"
    continue
  fi
  case ",${want_codes}," in
    *",${code},"*) : ;;
    *) missing="${missing}status=${code}(want ${want_codes}) " ;;
  esac

  # ② HSTS
  hsts=$(header_value "$headers" strict-transport-security)
  if [ -z "$hsts" ]; then
    missing="${missing}strict-transport-security "
  else
    age=$(hsts_max_age "$headers")
    if [ -z "$age" ]; then
      missing="${missing}hsts-max-age-missing "
    elif [ "$age" -lt "$MAX_AGE_MIN" ]; then
      missing="${missing}hsts-max-age=${age}s(<${MAX_AGE_MIN}s) "
    fi
  fi

  # ③ nosniff
  [ -n "$(header_value "$headers" x-content-type-options)" ] || missing="${missing}x-content-type-options "

  # ④ CSP（只有点名的两个静态面要求）
  if [ "$want_csp" = "yes" ]; then
    csp=$(header_value "$headers" content-security-policy)
    if [ -z "$csp" ]; then
      missing="${missing}content-security-policy "
    else
      shape=$(csp_shape_violations "$csp")
      [ -z "$shape" ] || missing="${missing}csp-${shape}"
    fi
  fi

  if [ -z "$missing" ]; then
    say "  ✅ ${face} ${url} code=${code}（HSTS=${hsts:-?} nosniff=ok csp=$([ "$want_csp" = yes ] && echo ok || echo n/a)）"
    printf 'PROD-HEADERS face=%s code=%s ok=1\n' "$face" "$code"
  else
    say "  ❌ ${face} ${url} code=${code} —— 缺/不合规：${missing}"
    FAILED=$((FAILED + 1))
    printf 'PROD-HEADERS face=%s code=%s ok=0 missing=%s\n' "$face" "$code" "${missing// /,}"
  fi
done <<EOF
$(printf '%s' "$FACES" | grep -v '^$')
EOF

if [ "$FAILED" -gt 0 ]; then
  say "PROD-HEADERS-SUMMARY rc=1 failed=${FAILED} unknown=${UNKNOWN} probed=${PROBED}"
  say "  处置：① api 域缺 HSTS ⇒ 核 backend/admin-api/src/main/resources/application.yml 的"
  say "          \`server.forward-headers-strategy: framework\` 是否随本次部署生效（deploy-admin-api）"
  say "        ② app / merchant 域缺头 ⇒ 核 deploy/swas/nginx.conf 的 add_header（随任一次 deploy 腿 cp+reload）"
  say "        ③ 复算：bash deploy/scripts/prod-security-headers.sh"
  exit 1
fi
if [ "$UNKNOWN" -gt 0 ]; then
  say "PROD-HEADERS-SUMMARY rc=3 unknown=${UNKNOWN} probed=${PROBED}"
  say "  ⚠️ **无法判定**不是通过：上面 \`????\` 那几面这次没探到（网络 / DNS / TLS），修好后复算。"
  exit 3
fi
say "PROD-HEADERS-SUMMARY rc=0 failed=0 unknown=0 probed=${PROBED}"
exit 0
