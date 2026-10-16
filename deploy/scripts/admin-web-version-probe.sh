#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# ⚠️ **命名空间**：本腿**不是**静态落地面腿（`*-verify-served.sh` 那个命名空间，它们由 nginx
#    发静态文件，`.mjs` 的 MIME 面归 issue #6293），而是**版本身份探针**（`/version.json` 由
#    admin-web 的 Next 服务器应答）⇒ 与 admin-api 腿的 `served-version-verify.sh` 同族命名。
#    两条类级守卫（`tests/unit_ci_workflows/test_served_leg_mime_guard.py` /
#    `test_worker_h5_module_closure_guard.py`）按 `deploy/scripts/*-verify-served.sh` **现取**腿集合、
#    要求每条腿带静态面的判据 ⇒ 名字落进那个命名空间会把它们判红（名不副实）。
# admin-web 发布腿的**身份自证**（issue #6611 / #6746；同族范式 = `deploy/scripts/served-version-verify.sh`）
#
# ## 病（现取读数，不是推断）
#
# 1. **身份判据不具判别力**（issue #6611 逐字）：「`index.html` 字节哈希**跨版本相同**
#    （只证 chunk 图，不证部署了哪份代码）」—— 实测应用代码变了、`index.html` 的 sha256
#    前后都是 `b1f3a2ef2929ec66`。同一形态在另外三条静态落地面腿上也在
#    （`worker-h5` / `bmini-h5` / `c-end-h5` 的 `*-verify-served.sh`）—— 见本文件末尾的类级清单。
# 2. **HTTP 200 不能证明任何东西**（同族，`worker-h5-verify-served.sh` 自己写下的）：
#    「200 是**恒真**的（空断言）」—— nginx `try_files … /index.html` 对某些路径会**静默回落**
#    到 index.html（`deploy/swas/nginx.conf` 的 `location /` 就是 `try_files $uri $uri/ /index.html`）
#    ⇒ **200 + HTML 恰恰是「探不到身份面」的形态**，不是「通过」。
# 3. **schedule 兜底报 success 却零交付**（issue #6746 逐字）：兜底判据是「**镜像存在**」而非
#    「**线上是它**」⇒ 实测 schedule run 只跑 22 秒、`conclusion=success`，而线上产物逐字节未变
#    （CSS 仍是旧的、内容级判据 `primary-50-lit` 0 命中）。镜像存在 ≠ 线上是它。
# 4. **实测假绿**（issue #6554）：自证说「在跑 tag == 046298d」，而线上前端实际停在 `03b1132`。
#
# ## 判据形态
#
# 探**线上真正响应的那个端点** = `GET {BASE_URL}/version.json`
# （admin-web 容器里由构建期烘焙的 `public/version.json` 应答 —— 见 `frontend/admin-web/Dockerfile`），
# 把它的 `sha` 与**本次部署的 sha** 逐字符比（比前 7 位 —— 镜像 tag 是 `sha-<7hex>`，
# 身份面报的是完整 40 位；7 位已是本仓全链路既有口径）：
#
# | 情形 | 退出码 | 语义 |
# |---|---|---|
# | 线上 `sha` 前 7 位 == 期望 sha 前 7 位 | **0** | 线上**就是**这次构建 ⇒ 放行 |
# | 线上 `sha` 与期望**不一致** | **1** | **判红**（具名：期望 / 实测 / 可复制命令），并落 `SERVED_VERSION=mismatch` |
# | 探不到（连不上 / 非 200 / body 不是 JSON / **是 HTML（回落）** / `sha` 为空或 `unknown` 或非 hex / `app` 不是目标服务 / 期望 sha 形态不合法） | **3** | **fail-closed**（`SERVED_VERSION=unknown`）|
#
# 🔴 **为什么「探不到」是 3 而不是 0**：老镜像没有注入面（`sha` 为空 / `unknown`）时，
#    判据**一个字节都证不了** —— 把它当绿就是 issue #6294 的同款假绿（「没跑」必须长得像「没跑」）。
#    同时它**不是红**：红与「探不到」是两种东西，混桶会让真缺陷淹没在噪声里
#    （同族三态口径见 `deploy/scripts/swas_deploy_running_tag.sh`）。
# 🔴 **回落必须显式处理**：拿到 HTML（`<!doctype html` / `<html`）⇒ 判**探不到（3）**，
#    **绝不许**「200 就通过」。两处都钉住：Content-Type 是 `text/html` ⇒ 判探不到；
#    body 以 `<` 开头 ⇒ 即使 Content-Type 撒谎也判探不到。
#
# ## 它证什么、不证什么（照实登记，§19.1）
#
# · **证**：admin-web 容器**真正响应的**那份产物自报的构建 sha 与本次部署目标一致
#   （`sha` 由构建期经 `docker build --build-arg` 烘焙进镜像 —— 见 `frontend/admin-web/Dockerfile`
#    与 `deploy/swas/deploy.sh` 的 C′ 构建段；**不是**运行时现算：部署形态下容器里没有 `.git`）。
# · **不证**：① 「容器里那份 `public/version.json` 一定来自该 sha 的源码树」—— 由构建期注入面
#   与 sha 的**不可变性**保证（同一个 sha 只会被造出一份产物）；② 页面**行为**对不对
#   （身份对 ≠ 功能对，那是 e2e / 冒烟的射程）；③ 另三条静态落地面腿（`worker-h5` / `bmini-h5` /
#   `c-end-h5`）的身份面 —— 它们各有自己的 `*-verify-served.sh`，本判据**不**替它们背书。
#
# 用法:
#   admin-web-version-probe.sh [<BASE_URL>] [<EXPECTED_SHA>]
#     BASE_URL      默认 `https://merchant.migaozn.com`
#     EXPECTED_SHA  默认 `$GITHUB_SHA`（CI 里就是本次运行的 commit）
# 环境变量（可选）:
#   ADMIN_WEB_SERVED_APP   期望的身份面 `app` 字段（默认 `admin-web`；不符 ⇒ 判「探不到」）
#   ADMIN_WEB_SERVED_PATH  身份面路径（默认 `/version.json`；**只为本地桩测试而存在**，生产不许改）
#   ADMIN_WEB_SERVED_RETRIES       就绪重试次数（默认 3）
#   ADMIN_WEB_SERVED_RETRY_DELAY   每次间隔秒（默认 5）
#
# 退出码：0 = 线上就是本次构建；1 = 不一致（判红）；3 = 探不到（fail-closed）。
# 判据 = tests/unit_ci_workflows/test_admin_web_served_version.py
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

BASE=${1:-https://merchant.migaozn.com}
BASE=${BASE%/}
EXPECTED=${2:-${GITHUB_SHA:-}}
APP=${ADMIN_WEB_SERVED_APP-admin-web}
PATH_SUFFIX=${ADMIN_WEB_SERVED_PATH:-/version.json}
RETRIES=${ADMIN_WEB_SERVED_RETRIES:-3}
RETRY_DELAY=${ADMIN_WEB_SERVED_RETRY_DELAY:-5}

URL="$BASE$PATH_SUFFIX"
TMPDIR_RUN="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_RUN"' EXIT

# 期望 sha 的形态前置断言（fail-closed）：拿不到 / 形态不对的**期望值** = 判据的前置没成立
# ⇒ 当场报「探不到」，**绝不**退化成「比了个空串」（那会让判据恒红或恒绿，两种都是坏形态）。
EXPECTED=$(printf '%s' "$EXPECTED" | tr 'A-Z' 'a-z')
case "$EXPECTED" in
  *[!0-9a-f]*|"")
    echo "::error::本次部署的 sha 形态不合法（'$EXPECTED'）⇒ 无法判定（fail-closed）"
    echo "  · 期望值来源 = 部署腿的 \`GITHUB_SHA\` / 调用方第二个参数；形态必须是 >=7 位 hex"
    echo "SERVED_VERSION=unknown"
    exit 3 ;;
esac
if [ "${#EXPECTED}" -lt 7 ]; then
  echo "::error::本次部署的 sha 太短（'$EXPECTED'，需 >= 7 位 hex）⇒ 无法判定（fail-closed）"
  echo "  · 说明：判据按前 7 位比对（镜像 tag 是 \`sha-<7hex>\`）⇒ 期望值短于 7 位时判不了任何东西"
  echo "SERVED_VERSION=unknown"
  exit 3
fi
EXPECTED7=${EXPECTED:0:7}

echo "== admin-web 现场版本自证（issue #6611）=="
echo "   端点：$URL"
echo "   期望 sha（本次部署）：${EXPECTED}（前 7 位 ${EXPECTED7}）${APP:+ · 期望 app=$APP}"

# `json_field <file> <key>`：只取**顶层字符串字段**（唯一消费面 = 本仓自有的 version.json）。
# 解析失败 / 字段不存在 / 字段不是字符串 ⇒ **空串**，由调用方按「探不到」判（fail-closed）。
JSON_FIELD_PY='import json,sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    print(""); raise SystemExit(0)
val = data.get(sys.argv[2]) if isinstance(data, dict) else None
print(val if isinstance(val, str) else "")'
json_field() { python3 -c "$JSON_FIELD_PY" "$1" "$2" 2>/dev/null || echo ""; }

# ── 取读数（就绪重试：滚动重启期间会有瞬态 502/503/504 与连接失败）─────────────────
CODE=""; CTYPE=""; FETCHED_SHA=""; FETCHED_APP=""; ATTEMPT=0
while :; do
  ATTEMPT=$((ATTEMPT + 1))
  # 一次请求取两个读数（`%{content_type}` + `%{http_code}` 各一行）：分两次 curl 会在
  # 「两次之间容器被换掉」时把两个不同代的读数拼在一起（判据自己引入的不确定性）。
  META=$(curl -sS -m 15 -H 'Cache-Control: no-cache' -o "$TMPDIR_RUN/version.json" \
           -w '%{content_type}\n%{http_code}' "$URL" 2>"$TMPDIR_RUN/curl.err" || true)
  CTYPE=${META%%$'\n'*}
  CODE=${META##*$'\n'}
  CTYPE=${CTYPE%%;*}
  FETCHED_SHA=""; FETCHED_APP=""
  if [ "$CODE" = "200" ] && [ -s "$TMPDIR_RUN/version.json" ]; then
    # 回落形态（HTML）**不当读数**取：它的 `sha` 字段必然是空的，但先判出来的话
    # 「探不到」的理由会写成「sha 为空」而不是「拿到了 HTML（回落）」—— 排查方向完全不同。
    case "$(head -c 200 "$TMPDIR_RUN/version.json" | tr -d '[:space:]' | tr 'A-Z' 'a-z')" in
      '<!doctypehtml'*|'<html'*|'<'*) CTYPE="text/html" ;;
    esac
    if [ "$CTYPE" != "text/html" ]; then
      FETCHED_SHA=$(json_field "$TMPDIR_RUN/version.json" sha)
      FETCHED_APP=$(json_field "$TMPDIR_RUN/version.json" app)
    fi
  fi
  # 判定「这一次读数是否已经可用」——只有它可用才停（`sha` 非空且形态合规）
  case "$FETCHED_SHA" in
    ""|*[!0-9a-fA-F]*) : ;;
    *) if [ "${#FETCHED_SHA}" -ge 7 ]; then break; fi ;;
  esac
  if [ "$ATTEMPT" -ge "$RETRIES" ]; then break; fi
  sleep "$RETRY_DELAY"
done

echo "   HTTP ${CODE:-（取不到）} · Content-Type '${CTYPE:-（取不到）}' · 尝试 $ATTEMPT/$RETRIES"
echo "   线上读数：sha='${FETCHED_SHA:-}' app='${FETCHED_APP:-}'"
if [ -s "$TMPDIR_RUN/version.json" ]; then
  echo "   原始 body：$(head -c 400 "$TMPDIR_RUN/version.json")"
fi

# ── 「探不到」出口（退出码 3）────────────────────────────────────────────────
# 每一条都必须**具名**（哪一步取不到），因为它们的处置不同：连不上 = 网络/容器；
# 非 200 = 路径不存在或服务没起；**HTML = 回落**（要的就是「身份面不存在」这个事实）；
# sha 空 / `unknown` = 镜像没有注入面（老镜像，或 `--build-arg` 没过边界）。
unknown() {
  local reason=$1
  echo "::error::admin-web 版本自证**无法判定**（探不到）：$reason"
  echo "  · 语义：这是「**探不到**」，与「确认线上不是目标版本」是两种东西（后者退 1）；**不得**当通过"
  echo "  · 实测读数：HTTP ${CODE:-（取不到）} · Content-Type '${CTYPE:-（取不到）}' · sha='${FETCHED_SHA:-}' · app='${FETCHED_APP:-}' · 尝试 ${ATTEMPT}/${RETRIES}"
  echo "  · 可复制复算命令："
  echo "      curl -sS -m 15 -D - '$URL' | head -c 400"
  echo "      bash deploy/scripts/admin-web-version-probe.sh '$BASE' '$EXPECTED'"
  echo "  · 排查方向：① 身份面在不在（admin-web 容器是否真在服务；\`GET /version.json\` 是不是 404）"
  echo "     ② 镜像有没有构建期注入面（frontend/admin-web/Dockerfile 的 MIGAO_BUILD_SHA）"
  echo "     ③ 拿到了 HTML ⇒ 该路径**回落**到了页面（nginx try_files / 容器换成了别的应用）"
  echo "  · 出口：确认服务恢复后复跑本判据；老镜像（没有注入面）需要一次**带注入面的部署**"
  echo "SERVED_VERSION=unknown"
  exit 3
}

[ -n "$CODE" ] || unknown "curl 取不到 \`$URL\`（连接失败 / DNS / TLS）"
case "$CODE" in
  200) ;;
  *)   unknown "HTTP ${CODE}（期望 200；404 = 身份面不存在或容器没起，502/503/504 = 容器未就绪）" ;;
esac
[ -s "$TMPDIR_RUN/version.json" ] || unknown "HTTP 200 但 body 为空（端点被别的东西接管？）"
if [ "$CTYPE" = "text/html" ]; then
  unknown "响应是 **HTML**（Content-Type '${CTYPE}' 或 body 以 '<' 开头）⇒ 该路径回落到页面了，**不是**身份面"
fi
[ -n "$FETCHED_SHA" ] || unknown "响应里取不到非空字符串字段 \`sha\`（body 不是本仓的 version.json 形态？）"
case "$FETCHED_SHA" in
  *[!0-9a-fA-F]*) unknown "线上 \`sha\`='${FETCHED_SHA}' 不是 hex（形态不符；\`unknown\` = 构建身份没过边界）" ;;
esac
if [ "${#FETCHED_SHA}" -lt 7 ]; then
  # 「空串」是**老镜像**的形态（没有构建期注入面）：它必须判「探不到」，**不许**当绿
  # —— 否则本判据会在每一次「镜像没换」的部署上悄悄变成空断言。
  unknown "线上 \`sha\`='${FETCHED_SHA}' 不足 7 位 hex（镜像没有构建期注入面？老镜像？）"
fi
if [ -n "$APP" ] && [ "$FETCHED_APP" != "$APP" ]; then
  unknown "线上 \`app\`='${FETCHED_APP}' != 期望 '${APP}'（这个端点后面不是 admin-web）"
fi

# ── 比较：**逐字符**比前 7 位（镜像 tag 是 `sha-<7hex>`，身份面报的是完整 40 位）─────────
FETCHED_LOWER=$(printf '%s' "$FETCHED_SHA" | tr 'A-Z' 'a-z')
if [ "${FETCHED_LOWER:0:7}" = "$EXPECTED7" ]; then
  echo "✅ 线上就是本次构建：served sha=${FETCHED_LOWER} == 期望 ${EXPECTED7}（前 7 位逐字符一致）"
  echo "   · 判据口径：只比前 7 位（与镜像 tag \`sha-<7hex>\` 同口径；更长的两端都照此截断）"
  echo "   · 与 issue #6611 的旧判据的区别：比的是**响应体里的身份字段**，不是 \`index.html\` 的字节哈希"
  echo "SERVED_VERSION=match"
  exit 0
fi

echo "::error::线上**不是**本次构建：served sha=${FETCHED_LOWER} != 期望 ${EXPECTED}（前 7 位 ${EXPECTED7}）"
echo "  · 服务：admin-web（${URL}）"
echo "  · 探到什么：sha=${FETCHED_SHA} · app=${FETCHED_APP:-（空）} · HTTP ${CODE}"
echo "  · 期望什么：sha=${EXPECTED}（本次部署的目标 commit）"
echo "  · 也就是说：这次部署的「产物存在 / run 结论 success」**不等于**「线上换成了它」"
echo "    —— 这正是 issue #6611 / #6746 / #6554 要治的形态（判据从「推没推」换成「线上是不是它」）"
echo "  · 可复制复算命令："
echo "      curl -sS -m 15 '$URL' | head -c 400"
echo "      bash deploy/scripts/admin-web-version-probe.sh '$BASE' '$EXPECTED'"
echo "  · 出口：① 容器没被替换（蓝绿残留 / compose 没重建）⇒ 在 run 页面 Re-run 本腿；"
echo "     ② 目标构建本身是旧的（镜像 tag 不是本次 commit）⇒ 用 \`gh workflow run deploy-frontend.yml -f image_tag=sha-<7>\` 显式重部署；"
echo "     ③ 根因不明 ⇒ **先不要**用「再跑一次」掩盖：把本读数和该 run 的 \`EFFECTIVE_TAG=\` 并排看"
echo "SERVED_VERSION=mismatch"
exit 1
