#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# 线上落地面**身份断言**（issue #4837 的验收判据；CI 发布后必跑，也可本地单跑）
#
# 🔴 为什么不能只看 `curl -sI https://app.migaozn.com/w/` = 200：
#    修复**前**它就已经是 200 —— nginx 的 `location /` 是 `try_files $uri $uri/ /index.html`，
#    `/w/` 不存在时**静默回落**到 C 端 Taro H5 的 index.html（「米高窗帘 · 小布智能助手」）。
#    ⇒ 200 是**恒真**的（空断言）。本脚本断言的是**页面身份**：
#      ① `GET /w/` 与 `GET /w/index.html` 的 body 哈希 == **本仓库** `frontend/worker-h5/index.html`；
#      ② body 含工人端入口 `src/app.mjs`；**不含** C 端标识（`TARO_` / `小布智能助手`）；
#      ③ `GET /w/src/app.mjs` 200 且哈希 == 本仓库同名文件（证明 `src/**` 真的落了，不只是 index）。
#
# 用法: worker-h5-verify-served.sh [BASE_URL]      # 默认 https://app.migaozn.com
# 退出码：0 = 线上确实是工人端 H5 且与本仓库一致；非零 = 身份不符（**逐条打印到底哪一条不成立**）。
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

BASE=${1:-https://app.migaozn.com}
BASE=${BASE%/}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCAL_INDEX="$ROOT/frontend/worker-h5/index.html"
LOCAL_APP="$ROOT/frontend/worker-h5/src/app.mjs"

C_END_MARKERS=("TARO_" "小布智能助手")
WORKER_MARKERS=("src/app.mjs")

TMPDIR_RUN="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_RUN"' EXIT

FAILURES=0
ok()   { echo "  ✅ $*"; }
bad()  { echo "  ❌ $*"; FAILURES=$(( FAILURES + 1 )); }

file_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

# 拉一个 URL：写文件 + 回显 HTTP 码（不跟随重定向 —— 302 到别处本身就是失败信号）
fetch() {
  local url=$1 out=$2
  curl -sS -m 20 -H 'Cache-Control: no-cache' -o "$out" -w '%{http_code}' "$url" 2>"$TMPDIR_RUN/curl.err"
}

echo "== worker-h5 落地面身份断言 =="
echo "   BASE_URL=$BASE"
[ -f "$LOCAL_INDEX" ] || { echo "❌ 本仓库缺少 ${LOCAL_INDEX}（无法比对身份）" >&2; exit 2; }
[ -f "$LOCAL_APP" ]   || { echo "❌ 本仓库缺少 ${LOCAL_APP}（无法比对身份）" >&2; exit 2; }

EXPECTED_INDEX_SHA="$(file_sha256 "$LOCAL_INDEX")"
EXPECTED_APP_SHA="$(file_sha256 "$LOCAL_APP")"
echo "   仓库 index.html 哈希=$EXPECTED_INDEX_SHA"
echo "   仓库 src/app.mjs 哈希=$EXPECTED_APP_SHA"
echo ""

# ── ① /w/ ───────────────────────────────────────────────────────────────────
echo "① GET $BASE/w/"
CODE=$(fetch "$BASE/w/" "$TMPDIR_RUN/w.html")
echo "   HTTP $CODE"
if [ "$CODE" = "200" ]; then ok "状态码 200"; else bad "状态码 ${CODE}（期望 200；302/404 都不是落地面）"; fi
if [ -s "$TMPDIR_RUN/w.html" ]; then
  GOT="$(file_sha256 "$TMPDIR_RUN/w.html")"
  if [ "$GOT" = "$EXPECTED_INDEX_SHA" ]; then
    ok "body 哈希 = 仓库 frontend/worker-h5/index.html（${GOT}）"
  else
    bad "body 哈希 $GOT ≠ 仓库 $EXPECTED_INDEX_SHA —— **返回的不是这份工人端 H5**"
  fi
fi
for m in "${WORKER_MARKERS[@]}"; do
  if grep -qF -- "$m" "$TMPDIR_RUN/w.html"; then ok "body 含工人端入口标记 '$m'"; else bad "body 缺工人端入口标记 '$m'"; fi
done
for m in "${C_END_MARKERS[@]}"; do
  if grep -qF -- "$m" "$TMPDIR_RUN/w.html"; then bad "body 含 C 端标识 '$m'（= 静默回落到了 Taro C 端 H5）"; else ok "body 不含 C 端标识 '$m'"; fi
done
echo ""

# ── ② /w/index.html（显式文件路径，绕开目录索引处理）────────────────────────
echo "② GET $BASE/w/index.html"
CODE=$(fetch "$BASE/w/index.html" "$TMPDIR_RUN/w-index.html")
echo "   HTTP $CODE"
if [ "$CODE" = "200" ]; then ok "状态码 200"; else bad "状态码 ${CODE}（期望 200）"; fi
if [ -s "$TMPDIR_RUN/w-index.html" ]; then
  GOT="$(file_sha256 "$TMPDIR_RUN/w-index.html")"
  if [ "$GOT" = "$EXPECTED_INDEX_SHA" ]; then
    ok "body 哈希 = 仓库 frontend/worker-h5/index.html（${GOT}）"
  else
    bad "body 哈希 $GOT ≠ 仓库 $EXPECTED_INDEX_SHA"
  fi
fi
echo ""

# ── ③ /w/src/app.mjs（子资源真的落了 —— 「只落 index」这种半成品会被这条抓住）──
echo "③ GET $BASE/w/src/app.mjs"
CODE=$(fetch "$BASE/w/src/app.mjs" "$TMPDIR_RUN/app.mjs")
echo "   HTTP $CODE"
if [ "$CODE" = "200" ]; then ok "状态码 200"; else bad "状态码 ${CODE}（期望 200 —— src/** 没落上去？）"; fi
if [ -s "$TMPDIR_RUN/app.mjs" ]; then
  GOT="$(file_sha256 "$TMPDIR_RUN/app.mjs")"
  if [ "$GOT" = "$EXPECTED_APP_SHA" ]; then
    ok "body 哈希 = 仓库 frontend/worker-h5/src/app.mjs（${GOT}）"
  else
    bad "body 哈希 $GOT ≠ 仓库 $EXPECTED_APP_SHA"
  fi
fi
echo ""

if [ "$FAILURES" -gt 0 ]; then
  echo "❌ 落地面身份断言**失败 $FAILURES 条**：$BASE/w/ 返回的不是本仓库的工人端 H5"
  exit 1
fi
echo "✅ 落地面身份断言全过：$BASE/w/ = 本仓库 frontend/worker-h5/（index.html 与 src/app.mjs 哈希逐字节一致，无 C 端标识）"
