#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# 线上落地面**身份 + 不串端**断言（issue #5668 的验收判据；CI 发布后必跑，也可本地单跑）
#
# 🔴 为什么不能只看 `/b/` = 200、也不能只看「页面标题/文案」：
#    · 修复**前** `/b/` 就已经是 200 —— nginx 的 `location /` 是 `try_files $uri $uri/ /index.html`，
#      `/b/` 不存在时**静默回落**到根 index.html（C 端小布）；
#    · 更隐蔽的是：bmini 与 C 端**同为 Taro h5 产物**，实测两者 `dist/index.html` 的
#      `<title>` 都是「米高窗帘 · 小布智能助手」、都带 `window.TARO_ENV = 'h5'`，连资源名
#      （`js/app.js` / `css/app.css`）都一样 ⇒ **标记法区分不了这两端**。
#    ⇒ 可判的只有两样：**字节哈希**（线上 body == 本仓库 `frontend/bmini-app/dist/index.html`）
#      与**资源命名空间**（index.html 的引用必须落在 `/b/` 内，不许引用根级 `/js/…`）。
#
# 判据（每条都能单独变红，红证见表）：
#   ① `GET /b/` 与 `GET /b/index.html` == 200 且 body 哈希 == 本仓库 `dist/index.html`；
#   ② **不串端**：`GET /b/<任意子路由>` 也返回 **bmini 的 index.html**（去掉 nginx 里 `/b/` 的
#      自己的 fallback ⇒ 它会回落到根 index.html = C 端 ⇒ 本条红）；
#   ③ **不劫持根**：`GET /` 与 `GET /<根级子路由>` 仍是 **C 端**页面（不得等于 bmini 产物）；
#   ④ **worker-h5 零回归**：直接复用 `deploy/scripts/worker-h5-verify-served.sh`（**不复制**一份
#      判定，避免两套真相源）；另加 `/s/<短码面>` 仍被代理（不是静态页）。
#
# 用法: bmini-h5-verify-served.sh [BASE_URL] [DIST_DIR]
#   默认 https://app.migaozn.com 与 frontend/bmini-app/dist
# 环境变量: BMINI_NGINX_WAIT_SECONDS —— ② 的**等待窗口**（默认 900s，见下方 §为什么会有等待）
# 退出码：0 = 线上确实是本仓库的 bmini 产物、不串端、根仍是 C 端、worker-h5 零回归；非零 = 逐条打印哪条不成立。
#
# §为什么会有等待（不是「重试到绿」）
#   `/b/<子路由>` 的判定依赖 **nginx 配置里 `location /b/` 的 fallback**，而 nginx 配置由
#   `deploy/swas/deploy.sh` 的「`cp nginx.conf` + reload」随**下一次 deploy 腿**生效 ——
#   与本 job 是**两个并发 run**（同一次 push 触发）。因此首次探测若发现回落，本脚本在
#   **显式窗口内**等待配置生效，并把每次探测打印出来；窗口用完仍回落 ⇒ **判红并给出可行动原因**。
#   窗口内**只有这一条判据**会等：身份 / 根 / worker-h5 三条**立刻**判定（它们不依赖 nginx 改动）。
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

BASE=${1:-https://app.migaozn.com}
BASE=${BASE%/}
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST_DIR=${2:-$ROOT/frontend/bmini-app/dist}
LOCAL_INDEX="$DIST_DIR/index.html"
WORKER_VERIFY="$ROOT/deploy/scripts/worker-h5-verify-served.sh"

SUBDIR=${H5_SUBDIR:-b}
# `/b/<子路由>`：刻意用一个**不存在**的深层路径（SPA 路由不需要真实目录；
# 若它返回根 index.html，说明 fallback 指向了别的应用）
SPA_PROBE="/${SUBDIR}/__bmini_spa_probe__/deep/route"
ROOT_PROBE="/__c_end_spa_probe__"
WAIT_SECONDS=${BMINI_NGINX_WAIT_SECONDS:-900}
POLL_SECONDS=${BMINI_NGINX_POLL_SECONDS:-20}

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

echo "== bmini h5 落地面身份 + 不串端断言 =="
echo "   BASE_URL=$BASE"
echo "   DIST_DIR=$DIST_DIR"
[ -f "$LOCAL_INDEX" ] || { echo "❌ 本仓库缺少 ${LOCAL_INDEX}（无法比对身份；请先 \`npm run build:h5\`）" >&2; exit 2; }
EXPECTED_INDEX_SHA="$(file_sha256 "$LOCAL_INDEX")"
echo "   本仓库 dist/index.html 哈希=$EXPECTED_INDEX_SHA"
echo ""

# ── ① /b/ 与 /b/index.html ──────────────────────────────────────────────────
echo "① GET $BASE/${SUBDIR}/ 与 /${SUBDIR}/index.html"
for path in "/${SUBDIR}/" "/${SUBDIR}/index.html"; do
  out="$TMPDIR_RUN/b-index.html"
  CODE=$(fetch "$BASE$path" "$out")
  if [ "$CODE" = "200" ] && [ -s "$out" ] && [ "$(file_sha256 "$out")" = "$EXPECTED_INDEX_SHA" ]; then
    ok "GET $path → 200，body 哈希 = 本仓库 dist/index.html"
  else
    bad "GET $path → HTTP ${CODE}，body 哈希 $( [ -s "$out" ] && file_sha256 "$out" || echo '(空)' ) ≠ 本仓库 ${EXPECTED_INDEX_SHA}（返回的不是这次构建的 bmini 产物）"
  fi
done
echo ""

# ── ② 不串端：/b/<子路由> 必须是 bmini 自己的 index.html ─────────────────────
echo "② GET $BASE${SPA_PROBE}（不存在的子路由 ⇒ 走 nginx 里 /${SUBDIR}/ 的 fallback）"
CODE=$(fetch "${BASE}${SPA_PROBE}" "$TMPDIR_RUN/spa.html")
if [ "$CODE" = "200" ] && [ -s "$TMPDIR_RUN/spa.html" ] && [ "$(file_sha256 "$TMPDIR_RUN/spa.html")" = "$EXPECTED_INDEX_SHA" ]; then
  ok "子路由返回 bmini 的 index.html（fallback 在自己的命名空间内，未串到别的应用）"
else
  GOT_SHA=$( [ -s "$TMPDIR_RUN/spa.html" ] && file_sha256 "$TMPDIR_RUN/spa.html" || echo '(空)' )
  if [ "$GOT_SHA" != "$EXPECTED_INDEX_SHA" ] && [ "$WAIT_SECONDS" -gt 0 ]; then
    echo "  ⏳ HTTP ${CODE}，body 哈希 $GOT_SHA ≠ bmini —— 可能是 nginx 配置（\`location /${SUBDIR}/\`）"
    echo "     还没随 deploy 腿生效（deploy.sh 会 \`cp nginx.conf\` + reload，与本次发布是两个并发 run）。"
    echo "     最多等待 ${WAIT_SECONDS}s（每 ${POLL_SECONDS}s 探测一次）："
    waited=0
    while [ "$waited" -lt "$WAIT_SECONDS" ]; do
      sleep "$POLL_SECONDS"
      waited=$(( waited + POLL_SECONDS ))
      CODE=$(fetch "${BASE}${SPA_PROBE}" "$TMPDIR_RUN/spa.html")
      GOT_SHA=$( [ -s "$TMPDIR_RUN/spa.html" ] && file_sha256 "$TMPDIR_RUN/spa.html" || echo '(空)' )
      if [ "$GOT_SHA" = "$EXPECTED_INDEX_SHA" ]; then
        ok "等 ${waited}s 后：子路由返回 bmini 的 index.html（nginx 配置已生效）"
        break
      fi
      echo "     … ${waited}s：HTTP ${CODE}，哈希 $GOT_SHA"
    done
  fi
  if [ "$( [ -s "$TMPDIR_RUN/spa.html" ] && file_sha256 "$TMPDIR_RUN/spa.html" || echo '(空)' )" != "$EXPECTED_INDEX_SHA" ]; then
    bad "GET $SPA_PROBE 没有返回 bmini 的 index.html（HTTP ${CODE}）—— nginx 的 \`location /${SUBDIR}/\` 缺少落在 /${SUBDIR}/index.html 的 fallback（会静默回落根 index.html = C 端小布）"
    echo "     处置：确认 \`deploy/swas/nginx.conf\` 的 \`location /${SUBDIR}/\` 已在**本次合并的 commit** 上；"
    echo "           等 deploy-* 跑完（它才会 cp nginx.conf + reload）后用 \`gh run rerun <run-id>\` 重跑本 job。"
  fi
fi
echo ""

# ── ③ 不劫持根：/ 与根级子路由仍是 C 端页面 ──────────────────────────────────
echo "③ GET $BASE/ 与 ${ROOT_PROBE}（根仍必须是 C 端小布，不能被 /${SUBDIR}/ 规则吃掉）"
for path in "/" "$ROOT_PROBE"; do
  out="$TMPDIR_RUN/root.html"
  CODE=$(fetch "$BASE$path" "$out")
  if [ "$CODE" != "200" ] || [ ! -s "$out" ]; then
    bad "GET $path → HTTP ${CODE}（期望 200：根是 C 端 SPA 的落地面）"
    continue
  fi
  GOT_SHA=$(file_sha256 "$out")
  if [ "$GOT_SHA" = "$EXPECTED_INDEX_SHA" ]; then
    bad "GET $path 返回的是 **bmini 产物**（哈希 = ${EXPECTED_INDEX_SHA}）—— 根被 /${SUBDIR}/ 规则劫持了"
  else
    ok "GET $path → 200，body 不是 bmini 产物（根仍是 C 端）"
  fi
done
echo ""

# ── ④ worker-h5 零回归（复用既有身份断言脚本，不复制第二份判定）─────────────
echo "④ worker-h5 零回归（/w/ 身份 + /s/ 代理面）"
if [ -f "$WORKER_VERIFY" ]; then
  if bash "$WORKER_VERIFY" "$BASE"; then
    ok "worker-h5 身份断言脚本判绿（/w/ 与本仓库 frontend/worker-h5/ 逐字节一致）"
  else
    bad "worker-h5 身份断言脚本判红 —— 本次改动把工人端落地面弄坏了（见上面它的逐条输出）"
  fi
else
  bad "缺少 $WORKER_VERIFY —— 无法证明 worker-h5 零回归（不许把「没有判据」当通过）"
fi
# `/s/<短码>` 必须仍由 admin-api 代理（不是静态面）。
# ⚠️ 边界（照实登记）：短码要查库、且真实短码是一次性的，本判据**只能**证明「这一面没有被静态化/
#    没被 /b/ 的规则吃掉」—— 它断言不了短码语义（那由 admin-api 的单测与线上日志负责）。
CODE=$(fetch "$BASE/s/__bmini_verify__" "$TMPDIR_RUN/s.html")
S_SHA=$( [ -s "$TMPDIR_RUN/s.html" ] && file_sha256 "$TMPDIR_RUN/s.html" || echo '(空)' )
if [ "$CODE" -ge 500 ] 2>/dev/null; then
  bad "GET /s/__bmini_verify__ → HTTP ${CODE}（5xx：代理面坏了，不是「短码不存在」）"
elif [ "$S_SHA" = "$EXPECTED_INDEX_SHA" ]; then
  bad "GET /s/__bmini_verify__ 返回了 bmini 产物 —— /s/ 面被静态化/被劫持了"
elif [ "$S_SHA" = "$(file_sha256 "$TMPDIR_RUN/root.html")" ]; then
  bad "GET /s/__bmini_verify__ 返回了根 C 端页面 —— /s/ 没有走到 admin-api 代理"
else
  ok "GET /s/__bmini_verify__ → HTTP ${CODE}（非静态页 ⇒ 仍由 admin-api 代理）"
fi
echo ""

if [ "$FAILURES" -gt 0 ]; then
  echo "❌ bmini h5 落地面断言**失败 ${FAILURES} 条**：$BASE/${SUBDIR}/ 的落地面不符合本仓库产物 / 或串了端"
  exit 1
fi
echo "✅ 全部通过：$BASE/${SUBDIR}/ = 本仓库 frontend/bmini-app/dist（含子路由 fallback）、根仍是 C 端、worker-h5 零回归"
