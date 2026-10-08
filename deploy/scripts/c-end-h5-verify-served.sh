#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# 线上落地面**身份 + 不串端**断言（issue #4184 的验收判据；CI 发布后必跑，也可本地单跑）
#
# 🔴 为什么不能只看 `GET /` = 200：
#    `GET /` **修复前后都是 200**（根上一直有 C 端产物，只是陈旧）⇒ 200 是**恒真的空断言**。
#    本脚本断言的是**身份**（线上字节 == **本仓库这次构建**的 `dist/index.html`）与**边界**
#    （根级子路由仍回 C 端自己的 index；`w/` `b/` 两个别的应用的子树仍在、且**不是** C 端产物）。
#
# 判据（每条都能单独变红，红证见 `tests/unit_ci_workflows/test_c_end_h5_hosting.py`）：
#   ① `GET /` 与 `GET /index.html` == 200 且 body 哈希 == 本仓库 `frontend/mini-app/dist/index.html`
#      —— 这一条同时是「**发布真的生效了**」的判据（陈旧产物 ⇒ 哈希不符 ⇒ 红）；
#   ② **不串端（引用面）**：`GET /index.html` 里**不得**出现 `"/w/` 或 `"/b/` 开头的资源引用
#      （那种产物会让 C 端页面加载别的应用的包）；
#   ③ **不串端（路由面）**：`GET /<根级不存在的深层路径>` 仍返回**根 index.html**
#      （= C 端自己的 SPA fallback 还在；若被别的应用的 fallback 吃掉 ⇒ 红）；
#   ④ **零回归（另外两条腿）**：`GET /w/` 与 `GET /b/` 都仍是 200，且**两者的 body 都不等于**
#      本仓库这次构建的 `dist/index.html`（= 根发布没有把别的应用覆盖成 C 端）。
#      ⚠️ 逐字节比对它们的身份由各自那条腿的 `*-verify-served.sh` 承担（**不复制**一份判定，
#      避免两套真相源）；本脚本只判「还在、且不是 C 端」这一条**与本次发布直接相关**的边界。
#   ⑤ **入口脚本的 MIME**（issue #6293）：`dist/index.html` 引用的入口脚本的 Content-Type 必须 ∈
#      **JS MIME 白名单**（`.mjs` 被发成 `application/octet-stream` ⇒ 浏览器拒绝执行 module script ⇒
#      白屏，而身份 / 串端 / 字节全对 ⇒ ①~④ 会全绿）。判据 = 「属于白名单」而**不是**等于某个字面量。
#
# 用法: c-end-h5-verify-served.sh [BASE_URL] [DIST_DIR]
#   默认 https://app.migaozn.com 与 frontend/mini-app/dist
# ⚠️ **没有等待窗口**（与 `/b/` 那条腿不同）：本腿写的是**静态文件**，不依赖 nginx 配置 reload
#    ⇒ 没有任何「配置还没生效」的中间态可等。判据要么立刻成立，要么就是真红（不把等待当判据）。
# 退出码：0 = 线上确实是本仓库的 C 端产物、不串端、另两条腿未被覆盖；非零 = 逐条打印哪条不成立。
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

BASE=${1:-https://app.migaozn.com}
BASE=${BASE%/}
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST_DIR=${2:-$ROOT/frontend/mini-app/dist}
LOCAL_INDEX="$DIST_DIR/index.html"

WORKER_PROBE="/w/"
SUBDIR_PROBE="/b/"
# 一个**不存在**的根级深层路径（C 端 SPA 路由不需要真实目录）：判据 ③ 的探针。
ROOT_PROBE="/__c_end_spa_probe__/deep/route"
TMPDIR_RUN="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_RUN"' EXIT

FAILURES=0
ok()  { echo "  ✅ $*"; }
bad() { echo "  ❌ $*"; FAILURES=$(( FAILURES + 1 )); }

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
# （Strict MIME type checking is enforced for module scripts）⇒ 页面**整页白屏**。
# 🔴 而**状态码 200 与字节哈希全部正确** ⇒ 本脚本 ①~④ 全绿（它们只判身份与串端，**一条都不判 MIME**）。
# 判据形态 = 「Content-Type **属于 JS MIME 白名单**」，**不是**等于某个字面量：
#   `text/javascript` 与 `application/javascript` 都是 WHATWG 认可的 JS MIME（不同 nginx / 发行版
#   给哪个都合法）⇒ 写死其一会在**正确**的部署上误红，逼人改判据而不是改配置（那是降门禁，不是修缺陷）。
JS_MIME_RE='^(application|text)/(x-)?(java|ecma)script([0-9.]+)?$'
# 本腿**依赖的** fail-closed 空集分支声明（issue #6306）：MIME 判据的「取不到就判红」锚在
# `ENTRY_REFS` 上（`REFS` 是 ② 那条判据的变量；判据 = tests/unit_ci_workflows/test_served_leg_mime_guard.py）。
FAIL_CLOSED_VARS="ENTRY_REFS"
js_mime_ok() {   # $1 = Content-Type 原文（可带 `; charset=…`）
  local ct
  ct="$(printf '%s' "${1%%;*}" | tr 'A-Z' 'a-z' | tr -d '[:space:]')"
  [[ "$ct" =~ $JS_MIME_RE ]]
}
# 取一个 URL 的 Content-Type（与 issue #6293 的复现命令同形：GET + 丢弃 body；HEAD 不是同一回事）
content_type_of() {
  curl -sS -m 20 -H 'Cache-Control: no-cache' -o /dev/null -w '%{content_type}' "$1" 2>"$TMPDIR_RUN/curl.err" || true
}

echo "== C 端元元 h5 落地面断言（issue #4184）=="
echo "   BASE_URL=$BASE"
[ -f "$LOCAL_INDEX" ] || { echo "❌ 本仓库缺少 ${LOCAL_INDEX}（无法比对身份）" >&2; exit 2; }
EXPECTED_SHA="$(file_sha256 "$LOCAL_INDEX")"
echo "   仓库 dist/index.html 哈希=$EXPECTED_SHA"
echo ""

# ── ① 身份（含「发布真的生效」）──────────────────────────────────────────────
echo "① 身份：线上 = 本仓库这次构建的 dist/index.html"
CODE_ROOT=$(fetch "${BASE}/" "$TMPDIR_RUN/root.html")
if [ "$CODE_ROOT" = "200" ]; then
  GOT=$(file_sha256 "$TMPDIR_RUN/root.html")
  if [ "$GOT" = "$EXPECTED_SHA" ]; then
    ok "GET / 200，哈希 $GOT == 本仓库产物"
  else
    bad "GET / 200，但哈希 $GOT ≠ 本仓库产物 $EXPECTED_SHA —— 线上**不是这次构建**（陈旧发布？发布没生效？）"
  fi
else
  bad "GET / 返回 ${CODE_ROOT}（期望 200）"
fi
CODE_IDX=$(fetch "${BASE}/index.html" "$TMPDIR_RUN/index.html")
if [ "$CODE_IDX" = "200" ] && [ "$(file_sha256 "$TMPDIR_RUN/index.html")" = "$EXPECTED_SHA" ]; then
  ok "GET /index.html 200，哈希 == 本仓库产物"
else
  bad "GET /index.html 返回 $CODE_IDX 或哈希 ≠ 本仓库产物（$(file_sha256 "$TMPDIR_RUN/index.html" 2>/dev/null || echo '-')）"
fi

# ── ② 引用面不串端 ──────────────────────────────────────────────────────────
echo "② 引用面：根 index.html 不得引用 /w/ 或 /b/ 的命名空间"
REFS=$(grep -oE '(src|href)="[^"]*"' "$TMPDIR_RUN/index.html" 2>/dev/null | sed -E 's/^(src|href)="//; s/"$//' || true)
if [ -z "$REFS" ]; then
  bad "线上 index.html 里没有任何 src/href（取不到或产物异常）"
else
  STRAY=$(printf '%s\n' "$REFS" | grep -E '^/(w|b)(/|$)' || true)
  if [ -z "$STRAY" ]; then
    ok "引用只落在根级（$(printf '%s\n' "$REFS" | tr '\n' ' ')）"
  else
    bad "线上 index.html 引用了别的应用的命名空间：$(printf '%s' "$STRAY" | tr '\n' ' ') —— C 端页面会加载那个应用的包（串端）"
  fi
fi

# ── ③ 路由面不串端 ──────────────────────────────────────────────────────────
echo "③ 路由面：根级深层路径仍回 C 端自己的 index.html"
CODE_PROBE=$(fetch "${BASE}${ROOT_PROBE}" "$TMPDIR_RUN/probe.html")
if [ "$CODE_PROBE" = "200" ] && [ "$(file_sha256 "$TMPDIR_RUN/probe.html")" = "$EXPECTED_SHA" ]; then
  ok "GET ${ROOT_PROBE} 回到根 index.html（C 端 SPA fallback 在位）"
else
  bad "GET ${ROOT_PROBE} 得 $CODE_PROBE / 哈希 $(file_sha256 "$TMPDIR_RUN/probe.html" 2>/dev/null || echo '-') —— 期望回落到**根 index.html**（被别的应用的 fallback 吃掉了？）"
fi

# ── ④ 零回归：另两条腿还在，且没被覆盖成 C 端 ────────────────────────────────
echo "④ 零回归：/w/ 与 /b/ 仍在，且都不是 C 端产物"
for p in "$WORKER_PROBE" "$SUBDIR_PROBE"; do
  code=$(fetch "${BASE}${p}" "$TMPDIR_RUN/sub.html")
  if [ "$code" != "200" ]; then
    bad "GET ${p} 返回 ${code}（期望 200）—— 本腿不该影响别的发布腿"
    continue
  fi
  h=$(file_sha256 "$TMPDIR_RUN/sub.html")
  if [ "$h" = "$EXPECTED_SHA" ]; then
    bad "GET ${p} 返回的是**本仓库这次构建的 C 端产物**（哈希 ${h}）—— 根发布把别的应用覆盖成了 C 端（红线）"
  else
    ok "GET ${p} 200，哈希 ${h} ≠ C 端产物（是它自己的产物）"
  fi
done
if [ -x "$ROOT/deploy/scripts/worker-h5-verify-served.sh" ] && [ "${C_END_SKIP_NEIGHBOUR_VERIFY:-}" != "1" ]; then
  echo "   ℹ️ /w/ 的逐字节身份由 deploy/scripts/worker-h5-verify-served.sh 承担；/b/ 由 bmini-h5-verify-served.sh 承担（本脚本不复制那份判定）"
fi

# ── ⑤ 入口脚本的 MIME（issue #6293）────────────────────────────────────────────
# 判据对象 = 本地产物 `dist/index.html` 里 `<script src=…>` 引用的**入口脚本**（现取 ⇒ 产物从 `.js`
# 换成 `.mjs` 时判据自动跟上，不写死路径）。为什么必须单列一条：①~④ 判的是身份与串端，
# 而**字节全对也照样白屏** —— 浏览器对 module script 先做 MIME 检查（octet-stream ⇒ 拒绝执行）。
# 取不到任何入口引用 ⇒ 判红（fail-closed）：「没跑」必须长得像「没跑」，不许当通过。
echo "⑤ 入口脚本的 MIME（Content-Type 必须 ∈ JS MIME 白名单）"
ENTRY_REFS="$(grep -oE '<script[^>]*src="[^"]+"' "$LOCAL_INDEX" 2>/dev/null | sed -E 's/.*src="([^"]+)".*/\1/' | sort -u)"
if [ -z "$ENTRY_REFS" ]; then
  bad "本地产物 ${LOCAL_INDEX} 里取不到 <script src=…> —— MIME 判据会空跑（不许当通过）"
fi
while IFS= read -r ref; do
  [ -n "$ref" ] || continue
  case "$ref" in
    http*://*) url="$ref" ;;
    /*)        url="$BASE$ref" ;;
    *)         url="$BASE/${ref#./}" ;;
  esac
  ct="$(content_type_of "$url")"
  if js_mime_ok "$ct"; then
    ok "GET $url → Content-Type ${ct}（∈ JS MIME 白名单）"
  else
    bad "GET $url → Content-Type ${ct:-（空）} 【∉ JS MIME 白名单】—— 浏览器会拒绝执行 module script ⇒ 页面整页白屏（HTTP 200 / 字节哈希一致都救不了）"
  fi
done <<< "$ENTRY_REFS"
echo ""
if [ "$FAILURES" -eq 0 ]; then
  echo "✅ 全部通过：线上 = 本仓库这次构建的 C 端产物、不串端、另两条腿未被覆盖、入口脚本 Content-Type ∈ JS MIME 白名单"
  exit 0
fi
echo "❌ ${FAILURES} 条判据不成立（逐条见上）"
exit 1
