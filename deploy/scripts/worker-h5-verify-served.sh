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
#      ⑦ **module 闭包加载**（issue #6306）：起点 = **发布集内每个 `*.html` 入口**（`index.html` →
#         `src/app.mjs`；`machine.html` → `src/machine-app.mjs`），沿**静态 `import` + 动态 `import()`
#         字面量**递归取每个依赖，要求 `200` + Content-Type ∈ JS MIME 白名单；空集判红；
#         另断入口引用的 `<link rel="stylesheet" href>` = 200。
#         —— ⑥ 只走**本仓**文件清单，看不见「仓里存在、线上不存在」的依赖（#6306 的坏点正是它：
#         `/shared/operation-display.mjs` 被 SPA 兜底接成 `200 text/html` ⇒ 整页白屏，而 ①~⑥ 全绿）。
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
# 本腿**依赖的** fail-closed 空集分支声明（issue #6306 订正）：MIME 判据的「取不到就判红」必须
# 锚在**它自己的**那些变量上 —— 否则同一条腿里**别的**判据的空集分支会把它喂绿（红证会失败）。
# 判据 = tests/unit_ci_workflows/test_served_leg_mime_guard.py（`leg_problems` 逐变量核）。
#   MJS_LOCAL  = 本仓 `src/**` 的 `.mjs` 文件清单（取不到 ⇒ MIME 判据会空跑）
#   ENTRY_HTML = 发布集内的 `*.html` 入口清单（取不到 ⇒ 闭包判据会空跑）
FAIL_CLOSED_VARS="MJS_LOCAL ENTRY_HTML"
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

# ── ⑦ module 闭包加载判据（issue #6306）────────────────────────────────────────
# 病（实测 2026-10-04，真浏览器）：修好 ⑥ 的 `.mjs` MIME 之后页面**仍整页白屏** ——
#   真浏览器读数 `bodyText=""` / `rootChildren=0` / console 逐字
#   `Failed to load module script: … MIME type of "text/html"`。
#   坏点 = `/shared/operation-display.mjs` → **`200 text/html`**：`render.mjs` / `machine.mjs` 的
#   静态 import 写的是 `'../../shared/operation-display.mjs'`，而共享模块住在**仓根**
#   `frontend/shared/`、**不在发布集**（发布集 = index.html + machine.html + `src/**`）⇒ 线上没有
#   这个文件、由 nginx 的 `location /` 的 `try_files … /index.html` 接成 `200 + C 端 index.html`。
# 🔴 ①~⑥ **一条都判不到它**：⑥ 只走**本仓** `src/**` 的文件清单 ⇒ 一个仓里存在、线上不存在的
#   依赖天然在它的面之外；而「字节全对 + MIME 全对 + 页面白屏」正是本单的形态。
#
# 判据形态（**类级**：从发布集导出，不从「谁能被 import 到」导出）：
#   起点 = **发布集内每一个 `*.html` 入口** —— worker 有**两个**入口
#          （`index.html` → `src/app.mjs`；`machine.html` → `src/machine-app.mjs`），而
#          `machine.mjs` 恰是坏点导入者之一 ⇒ **只从 index.html 出发会漏掉那条链**；
#   解析面 = **静态 `import … from '…'` + 动态 `import('…')` 字面量**（`app.mjs` 有真实的 `await import('./api.mjs')`）；
#   规格化 = **发布集内**的相对说明符 + `.js` / `.mjs` / `.cjs` 后缀（`src/shipment.mjs` 是孤儿模块：
#            仓内无人 import 它，但它是**发布集成员** ⇒ 由 ⑥ 的现取文件清单兜，不进本闭包）；
#   每个模块 = `200` **且** Content-Type ∈ JS MIME 白名单；**空集判红**（「没跑」必须长得像「没跑」）；
#   另收集入口的 `<link rel="stylesheet" href>` 并断 `200`（**正向盲区**：`.css` 404 时页面无样式
#           而 module 闭包仍全绿）。
# 为什么这条只能**活体**判（离线判不了）：坏点的本质是「线上那个 URL 上**是什么**」——
#   本地仓里再怎么写断言都看不见它。
echo "⑦ module 闭包加载判据（起点 = 发布集内每个 *.html 入口；静态 import + 动态 import() 字面量）"
ENTRY_HTML="$(find "$ROOT/frontend/worker-h5" -maxdepth 1 -name '*.html' -type f 2>/dev/null | sort)"
if [ -z "$ENTRY_HTML" ]; then
  bad "本仓库 frontend/worker-h5 下取不到任何 *.html 入口 —— 闭包判据会空跑（不许当通过）"
fi
CLOSURE_QUEUE="$TMPDIR_RUN/closure.queue"
: > "$CLOSURE_QUEUE"
# 入口清单（`<本地落盘文件><TAB><线上 URL>`）：HTML 只取一次，闭包起点与样式表判据共用同一份读数。
ENTRIES="$TMPDIR_RUN/closure.entries"
: > "$ENTRIES"
ENTRY_COUNT=0
while IFS= read -r hf; do
  [ -n "$hf" ] || continue
  ENTRY_COUNT=$(( ENTRY_COUNT + 1 ))
  rel="${hf#"$ROOT/frontend/worker-h5/"}"
  hd="$BASE/w/$rel"
  hbody="$TMPDIR_RUN/closure-entry-${ENTRY_COUNT}.html"
  hcode=$(fetch "$hd" "$hbody" || true)
  if [ "$hcode" != "200" ] || [ ! -s "$hbody" ]; then
    bad "入口 $hd → HTTP ${hcode:-（取不到）}（期望 200 且 body 非空）—— 闭包判据的起点取不到 ⇒ 这条链判不了"
    continue
  fi
  printf '%s\t%s\n' "$hbody" "$hd" >> "$ENTRIES"
  # ① 入口里的 module script / 静态 import 说明符入队（`.html` 里是 `<script type="module" src=…>`）
  while IFS=$'\t' read -r spec dir; do
    [ -n "$spec" ] || continue
    printf '%s\t%s\n' "$spec" "$hd" >> "$CLOSURE_QUEUE"
  done < <(python3 -c '
import re, sys
base, path = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8", errors="replace").read()
# `<script type="module" src="…">`（入口脚本）—— 只认 module script，普通 script 不是模块面
for m in re.finditer(r"""<script[^>]*type=["'"'"']module["'"'"'][^>]*>""", text, re.I):
    src = re.search(r"""src=["'"'"']([^"'"'"']+)["'"'"']""", m.group(0), re.I)
    if src and src.group(1).endswith((".js", ".mjs", ".cjs")):
        print(f"{src.group(1)}\t{base}")
' "$hd" "$hbody" || true)
done <<< "$ENTRY_HTML"

SEEN="$TMPDIR_RUN/closure.seen"
: > "$SEEN"
CLOSURE_MJS=0
while IFS=$'\t' read -r spec from_dir; do
  [ -n "$spec" ] || continue
  # 说明符**一律在 Python 侧规格化**（`urljoin`）：HTML 里的 `src="…"` 相对的是**文档 URL**，
# 而模块里的 `import "…"` 相对的是**该模块自己** —— 两套基准不同，混用会把
# `/w/index.html` 当目录 ⇒ 解析出 `/w/index.html/src/app.mjs`（实测踩过）。
  url=$(python3 -c "import sys,urllib.parse; print(urllib.parse.urljoin(sys.argv[1], sys.argv[2]))" "$from_dir" "$spec" 2>/dev/null || true)
  if [ -z "$url" ]; then
    # 解析器本身就是判据的**前置**：它空转（Python 不在 / 提前退出）而只打印一行「解析不了」，
    # 会让 ⑦ 在「闭包集合非空」的假象下继续跑 ⇒ 这里直接判红（fail-closed，不静默）。
    bad "解析不了模块说明符 '$spec'（from $from_dir）—— 闭包判据的解析器没跑起来（fail-closed）"
    continue
  fi
  grep -qxF -- "$url" "$SEEN" && continue
  printf '%s\n' "$url" >> "$SEEN"
  CLOSURE_MJS=$(( CLOSURE_MJS + 1 ))
  fname="$TMPDIR_RUN/closure.$CLOSURE_MJS"
  mcode=$(fetch "$url" "$fname" || true)
  if [ "$mcode" != "200" ]; then
    bad "GET $url → HTTP ${mcode:-（取不到）} 【模块闭包内的依赖取不到】—— 浏览器会拒绝加载 module graph ⇒ 整页白屏（#6306 的形态：该 URL 被 SPA 兜底接成 200 text/html，或根本就是 404）"
    continue
  fi
  if [ ! -s "$fname" ]; then
    bad "GET $url → HTTP 200 但 body 为空（期望非空模块）"
    continue
  fi
  # 🔴 MIME 判据在这里**不重复实现**：紧邻上方的 ⑥ 已经对**本仓** `src/**` 的每个 `.mjs` 判过一遍
  # （同一个 `js_mime_ok`），而**闭包新增的那些 URL 全部落在 `src/**` 内**（说明符是相对的）
  # ⇒ ⑥ 的覆盖面已经包含它们。本段只补 ⑥ 看不见的那一面：**这些 URL 存不存在**（#6306）。
  # 若将来闭包引用了 `src/**` 之外的模块（例如 `../vendor/x.mjs`），⑥ 就盖不到它 ——
  # 那时把 MIME 判据补到这里（`js_mime_ok` 就在上方可用）。
  ok "GET $url → 200 ${ct}（模块闭包）"
  # 继续把这条链上的**相对说明符**（静态 / 动态 import 与 CSS url()/@import）解出来入队
  while IFS=$'\t' read -r spec2 dir2; do
    [ -n "$spec2" ] || continue
    printf '%s\t%s\n' "$spec2" "$dir2" >> "$CLOSURE_QUEUE"
  done < <(python3 -c '
import re, sys
base, path = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8", errors="replace").read()
# 静态 `import … from "…"` / `export … from "…"` / 动态 `import("…")` / 裸 `import "…"`
pat = re.compile(r"""(?:@import\s+|\bfrom\s+|\bimport\s*\(?\s*|url\(\s*)["'"'"']?([^"'"'"')\s]+)""")
for m in pat.finditer(text):
    t = m.group(1)
    if not (t.startswith(("./", "../", "/")) and t.endswith((".js", ".mjs", ".cjs", ".css"))):
        continue
    print(f"{t}\t{base}")
' "$url" "$fname" || true)
done < "$CLOSURE_QUEUE"

if [ "$CLOSURE_MJS" -eq 0 ]; then
  bad "module 闭包集合为空 —— 起点（发布集内每个 *.html 入口）里一个模块说明符都没解析出来 ⇒ 闭包判据空跑（不许当通过）"
fi
echo "   ℹ️ module 闭包解析到 ${CLOSURE_MJS} 个不同模块（入口 ${ENTRY_COUNT} 个）"

# `<link rel="stylesheet" href>` 断 200（不必限 MIME 白名单）：CSS 404 时页面无样式，
# 而 module 闭包**照样全绿**（复核补的正向盲区）。两个入口共用同一个 `styles.css` ⇒ 先按
# `(文档 URL 目录 + href 原文)` 去重再判（否则同一个 URL 会被报两次）。
SHEET_QUEUE="$TMPDIR_RUN/closure.sheets"
: > "$SHEET_QUEUE"
while IFS=$'\t' read -r hbody hd; do
  [ -n "$hd" ] || continue
  while IFS=$'\t' read -r spec dir; do
    [ -n "$spec" ] || continue
    printf '%s\t%s\n' "$spec" "$dir" >> "$SHEET_QUEUE"
  done < <(python3 -c '
import re, sys
base, path = sys.argv[1], sys.argv[2]
try:
    text = open(path, encoding="utf-8", errors="replace").read()
except OSError:
    raise SystemExit(0)
for m in re.finditer(r"""<link[^>]*rel=["'"'"']stylesheet["'"'"'][^>]*>""", text, re.I):
    h = re.search(r"""href=["'"'"']([^"'"'"']+)["'"'"']""", m.group(0), re.I)
    if h:
        print(f"{h.group(1)}\t{base}")
' "$hd" "$hbody" || true)
done < "$ENTRIES"

# 去重（键 = 规格化后的 URL）：`awk` 一次扫完，不做逐行子串匹配（那是 O(n²) 且可读性差）。
cut -f1,2 "$SHEET_QUEUE" | while IFS=$'\t' read -r spec dir; do
  [ -n "$spec" ] || continue
  rurl=$(python3 -c "import sys,urllib.parse; print(urllib.parse.urljoin(sys.argv[1], sys.argv[2]))" "$dir" "$spec" 2>/dev/null || true)
  [ -n "$rurl" ] && printf '%s\n' "$rurl"
done | sort -u > "$TMPDIR_RUN/closure.sheet-urls"

if [ ! -s "$TMPDIR_RUN/closure.sheet-urls" ]; then
  bad "发布集内每个 *.html 入口都取不到 <link rel=\"stylesheet\" href> —— 样式表判据会空跑（不许当通过）"
fi
while IFS= read -r url; do
  [ -n "$url" ] || continue
  scode=$(fetch "$url" "$TMPDIR_RUN/closure-sheet.css" || true)
  if [ "$scode" = "200" ] && [ -s "$TMPDIR_RUN/closure-sheet.css" ]; then
    ok "GET $url → 200（样式表）"
  else
    bad "GET $url → HTTP ${scode:-（取不到）}/ body$( [ -s "$TMPDIR_RUN/closure-sheet.css" ] && echo 非空 || echo 空 )【入口引用的样式表取不到】—— 页面会无样式（module 闭包照样全绿，所以必须单列这一条）"
  fi
done < "$TMPDIR_RUN/closure.sheet-urls"
echo ""

if [ "$FAILURES" -gt 0 ]; then
  echo "❌ 落地面身份断言**失败 $FAILURES 条**：$BASE/w/ 返回的不是本仓库的工人端 H5"
  exit 1
fi
echo "✅ 落地面身份断言全过：$BASE/w/ = 本仓库 frontend/worker-h5/（index.html / machine.html / src/**.mjs 哈希逐字节一致 + 每个 .mjs 的 Content-Type ∈ JS MIME 白名单 + module 闭包 ${CLOSURE_MJS} 个模块全部 200 且 MIME 达标 + 入口样式表 200，无 C 端标识）"
