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
#      ④⑤ `/w/machine.html` 与 `/w/src/machine.mjs`（一体机机台页，母单 #5161）；
#      ⑥ **module script 的 MIME**（issue #6293）：`frontend/worker-h5/src/**` 的**每个** `.mjs` 的
#         Content-Type 必须 ∈ **JS MIME 白名单** —— 身份与字节全对时页面**仍可能白屏**：
#         `.mjs` 被 nginx 发成 `application/octet-stream` ⇒ 浏览器按 HTML 规范拒绝执行 module script。
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
LOCAL_MACHINE="$ROOT/frontend/worker-h5/machine.html"
LOCAL_MACHINE_APP="$ROOT/frontend/worker-h5/src/machine.mjs"

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

# ── JS MIME 白名单判据（issue #6293）────────────────────────────────────────────
# 病灶（云测试环境实测 2026-10-04）：`.mjs` **不在** nginx 的 `mime.types` 里 ⇒ 落到 `default_type`
# （本镜像 = application/octet-stream）⇒ 浏览器按 HTML 规范**拒绝执行 module script**
# （Strict MIME type checking is enforced for module scripts）⇒ 工人端 H5 / 一体机页**整页白屏**。
# 🔴 而**状态码 200 与字节哈希全部正确** ⇒ 本脚本 ①~⑤ 全绿（它们只判身份与字节，**一条都不判 MIME**）。
# 判据形态 = 「Content-Type **属于 JS MIME 白名单**」，**不是**等于某个字面量：
#   `text/javascript` 与 `application/javascript` 都是 WHATWG 认可的 JS MIME（不同 nginx / 发行版
#   给哪个都合法）⇒ 写死其一会在**正确**的部署上误红，逼人改判据而不是改配置（那是降门禁，不是修缺陷）。
JS_MIME_RE='^(application|text)/(x-)?(java|ecma)script([0-9.]+)?$'
js_mime_ok() {   # $1 = Content-Type 原文（可带 `; charset=…`）
  local ct
  ct="$(printf '%s' "${1%%;*}" | tr 'A-Z' 'a-z' | tr -d '[:space:]')"
  [[ "$ct" =~ $JS_MIME_RE ]]
}
# 取一个 URL 的 Content-Type（与 issue #6293 的复现命令同形：GET + 丢弃 body；HEAD 不是同一回事）
content_type_of() {
  curl -sS -m 20 -H 'Cache-Control: no-cache' -o /dev/null -w '%{content_type}' "$1" 2>"$TMPDIR_RUN/curl.err" || true
}

echo "== worker-h5 落地面身份断言 =="
echo "   BASE_URL=$BASE"
[ -f "$LOCAL_INDEX" ] || { echo "❌ 本仓库缺少 ${LOCAL_INDEX}（无法比对身份）" >&2; exit 2; }
[ -f "$LOCAL_APP" ]   || { echo "❌ 本仓库缺少 ${LOCAL_APP}（无法比对身份）" >&2; exit 2; }
[ -f "$LOCAL_MACHINE" ] || { echo "❌ 本仓库缺少 ${LOCAL_MACHINE}（无法比对身份）" >&2; exit 2; }
[ -f "$LOCAL_MACHINE_APP" ] || { echo "❌ 本仓库缺少 ${LOCAL_MACHINE_APP}（无法比对身份）" >&2; exit 2; }

EXPECTED_INDEX_SHA="$(file_sha256 "$LOCAL_INDEX")"
EXPECTED_APP_SHA="$(file_sha256 "$LOCAL_APP")"
EXPECTED_MACHINE_SHA="$(file_sha256 "$LOCAL_MACHINE")"
EXPECTED_MACHINE_APP_SHA="$(file_sha256 "$LOCAL_MACHINE_APP")"
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


# ── ④ /w/machine.html + /w/src/machine.mjs（一体机机台页；母单 #5161）──────────
# 背景：2026-09-29 前 `machine.html` **不在发布集**（远端脚本只拷 index.html + src/**）⇒ 线上打不开、
# 还会被 nginx `try_files` 静默回落成 C 端 H5（HTTP 200 不报错）。本段是该缺口的**绊线**。
echo "④ GET $BASE/w/machine.html"
CODE=$(fetch "$BASE/w/machine.html" "$TMPDIR_RUN/machine.html")
echo "   HTTP $CODE"
if [ "$CODE" = "200" ]; then ok "状态码 200"; else bad "状态码 ${CODE}（期望 200 —— machine.html 没进发布集？）"; fi
if [ -s "$TMPDIR_RUN/machine.html" ]; then
  GOT="$(file_sha256 "$TMPDIR_RUN/machine.html")"
  if [ "$GOT" = "$EXPECTED_MACHINE_SHA" ]; then
    ok "body 哈希 = 仓库 frontend/worker-h5/machine.html（${GOT}）"
  else
    bad "body 哈希 $GOT ≠ 仓库 ${EXPECTED_MACHINE_SHA}（回落成了别的东西？）"
  fi
fi
echo ""

echo "⑤ GET $BASE/w/src/machine.mjs"
CODE=$(fetch "$BASE/w/src/machine.mjs" "$TMPDIR_RUN/machine.mjs")
echo "   HTTP $CODE"
if [ "$CODE" = "200" ]; then ok "状态码 200"; else bad "状态码 ${CODE}（期望 200 —— 机台页脚本没落上去？）"; fi
if [ -s "$TMPDIR_RUN/machine.mjs" ]; then
  GOT="$(file_sha256 "$TMPDIR_RUN/machine.mjs")"
  if [ "$GOT" = "$EXPECTED_MACHINE_APP_SHA" ]; then
    ok "body 哈希 = 仓库 frontend/worker-h5/src/machine.mjs（${GOT}）"
  else
    bad "body 哈希 $GOT ≠ 仓库 $EXPECTED_MACHINE_APP_SHA"
  fi
fi
echo ""

# ── ⑥ module script 的 MIME（issue #6293）──────────────────────────────────────
# 判据对象 = 本仓库 `frontend/worker-h5/src/**` 的**每一个** `.mjs`（现取）：发布集 = index.html +
# machine.html + `src/**`（见 deploy/swas/h5-publish-remote.sh）⇒ 这些文件浏览器全都会当 module script 取。
# 为什么必须单列一段：①~⑤ 判的是「字节对不对」，而**字节全对也照样白屏** —— 浏览器先做 MIME 检查。
# 取不到任何 .mjs ⇒ 判红（fail-closed）：「没跑」必须长得像「没跑」，不许当通过。
echo "⑥ module script 的 MIME（Content-Type 必须 ∈ JS MIME 白名单）"
MJS_LOCAL="$(find "$ROOT/frontend/worker-h5/src" -name '*.mjs' -type f 2>/dev/null | sort)"
if [ -z "$MJS_LOCAL" ]; then
  bad "本仓库 frontend/worker-h5/src 下取不到任何 .mjs —— MIME 判据会空跑（不许当通过）"
fi
while IFS= read -r f; do
  [ -n "$f" ] || continue
  rel="${f#"$ROOT/frontend/worker-h5/"}"
  url="$BASE/w/$rel"
  ct="$(content_type_of "$url")"
  if js_mime_ok "$ct"; then
    ok "GET $url → Content-Type ${ct}（∈ JS MIME 白名单）"
  else
    bad "GET $url → Content-Type ${ct:-（空）} 【∉ JS MIME 白名单】—— 浏览器会拒绝执行 module script ⇒ 工人端整页白屏（HTTP 200 / 字节哈希一致都救不了）"
  fi
done <<< "$MJS_LOCAL"
echo ""

if [ "$FAILURES" -gt 0 ]; then
  echo "❌ 落地面身份断言**失败 $FAILURES 条**：$BASE/w/ 返回的不是本仓库的工人端 H5"
  exit 1
fi
echo "✅ 落地面身份断言全过：$BASE/w/ = 本仓库 frontend/worker-h5/（index.html / machine.html / src/**.mjs 哈希逐字节一致 + 每个 .mjs 的 Content-Type ∈ JS MIME 白名单，无 C 端标识）"
