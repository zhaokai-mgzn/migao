#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# 「线上就是本次构建」的**版本自证**（issue #6951；同族先例 #6611 / #6746 / #6554）
#
# ## 病（现取读数，不是推断）
#
# 1. **判据停在「推没推」**：`deploy-admin-api.yml` 的 `Skip if already built` 只看
#    「镜像在不在 ACR / 同 sha 的 run 结论是不是 success」⇒ 亮的是
#    「**产物存在**」，不是「**线上是它**」（issue #6746 实测：只跑 22 秒也报 success）。
# 2. **探活面 ≠ 探版本面**：`https://api.migaozn.com/actuator/health` 与 `/actuator/info`
#    都是 **nginx 404**（`deploy/swas/nginx.conf` 的 `location ~ ^/(actuator|…)` ⇒ `return 404`）
#    ⇒ 线上只能探到「服务活着」（实测 `POST /api/auth/sms/send` 空体 ⇒ 422），
#    **探不到「跑的是哪个 build」**（issue #6951 逐字）。
# 3. **跨版本可能相同**：`index.html` 字节哈希那类判据**只证 chunk 图、不证部署了哪份代码**
#    （issue #6611 实测：应用代码变了、`index.html` 的 sha256 前后都是 `b1f3a2ef2929ec66`）。
# 4. **实测假绿**：issue #6554 —— 自证说「在跑 tag==046298d」，而线上前端实际停在 `03b1132`。
#
# ## 判据形态（照抄同族 `deploy/scripts/worker-h5-verify-served.sh` 已有的判别力口径）
#
# 探**线上真正响应的那个端点**（`GET {BASE_URL}/api/version`，nginx 已放行的 `/api/` 前缀
# ⇒ 不新增任何放行面），把它的 `sha` 与**本次部署的 sha** 逐字符比（比前 7 位 —— 镜像 tag
# 是 `sha-<7hex>`，端点报的是完整 40 位；7 位已是本仓全链路既有口径）：
#
# | 情形 | 退出码 | 语义 |
# |---|---|---|
# | 线上 `sha` 前 7 位 == 期望 sha 前 7 位 | **0** | 线上**就是**这次构建 ⇒ 放行 |
# | 线上 `sha` 与期望**不一致** | **1** | **判红**（具名：服务 / 期望 / 实测 / 可复制命令），并落 `SERVED_VERSION=mismatch` |
# | 线上 `sha` 一致、但 `builtAt` 为**空串**（且调用方要求判它） | **1** | **判红**（具名：**取值源未接** issue #7015）—— 「探到了、值是空」≠「探不到」 |
# | 取不到（连不上 / 非 200 / 429 / body 不是 JSON / `sha` 为空 / `app` 不是目标服务 / 期望 sha 形态不合法） | **3** | **fail-closed**（`SERVED_VERSION=unknown`）|
#
# ⚠️ **为什么「取不到」是 3 而不是 0**：老镜像没有注入面（`sha` 为空）时，判据**一个字节都证不了**
#    —— 把它当绿就是 issue #6294 的同款假绿（「没跑」必须长得像「没跑」）。同时它**不是红**：
#    红与「探不到」是两种东西，混桶会让真缺陷淹没在噪声里（同族三态口径见
#    `deploy/scripts/swas_deploy_running_tag.sh`）。
#
# ⚠️ **它证什么、不证什么**（照实登记，§19.1）：
#    · **证**：**服务端真正响应的**那份产物自报的构建 sha 与本次部署目标一致
#      （`sha` 由构建期经 `docker build --build-arg` 烘焙进镜像 —— 见 `backend/admin-api/Dockerfile`
#      与 `deploy/swas/deploy.sh` 的 C′ 构建段；**不是**运行时现算：部署形态下容器里没有 `.git`）。
#    · **不证**：前端那几条静态落地面腿（`frontend/*` 的 `index.html` / bundle 身份）——
#      它们的构建期注入面**不在本单**（issue #6611 是它们的修法）；`deploy-frontend.yml` 本轮
#      **未接线**（如实登记在 PR body 的「未固化项」）。
#    · **不证**：`servedAt` / `builtAt` 的时钟精度，也不证「镜像里的代码等于该 sha 的源码树」
#      —— 后者由构建期注入面与 `sha` 的**不可变性**保证（同一个 sha 只会被造出一份产物）。
#
# ⚠️ **类级残余（issue #7015，照实登记，配合 tests/unit_ci_workflows/test_served_version_verify.py 的
#    类级守卫 `test_workflow_run_bodies_never_expand_undefined_github_env_literals`）**：
#    这类「run 正文里当默认值用/直接展开的 `GITHUB_*` 字面量**不是** GitHub 注入的环境变量 ⇒ shell
#    展开恒为空（而没有任何东西会红）」的形态，**在 shell 里是防御不了的** —— `${GITHUB_X:-}` 对
#    未定义变量只给空串、`$GITHUB_X` 只在 `set -u` 下才炸（且本仓多处 run 正文只有 `set -uo pipefail`）。
#    ⇒ 承载体**不在脚本里**，而是上面那条**编辑期**守卫（静态扫 `.github/workflows/**.yml` 的正文，
#    编造的名字 ⇒ 具名判红）。⬜ 未固化边界：YAML 里的**其它**动态取值面（`matrix.*` / `needs.*` /
#    `inputs.*` 的编造字段）不在其射程内 —— 它们要另立判据（本单不假装已覆盖）。
#
# 用法:
#   served-version-verify.sh [<BASE_URL>] [<EXPECTED_SHA>]
#     BASE_URL      默认 `https://api.migaozn.com`
#     EXPECTED_SHA  默认 `$GITHUB_SHA`（CI 里就是本次运行的 commit）
# 环境变量（可选）:
#   SERVED_VERSION_APP   期望的 `app` 字段（默认空 = 不判；非空且不符 ⇒ 判「探不到」，不许当绿）
#   SERVED_VERSION_PATH  端点路径（默认 `/api/version`；**只为本地桩测试而存在**，生产不许改）
#   SERVED_VERSION_RETRIES       就绪重试次数（默认 3）
#   SERVED_VERSION_RETRY_DELAY   每次间隔秒（默认 5）
#   SERVED_VERSION_REQUIRE_BUILT_AT  非空（CI 部署腿传 1）⇒ **探到 `builtAt` 为空即判红**（退出码 1）
#
# 🔴 **`builtAt` 面（issue #7015）**：`builtAt` 是 #6951 身份面三个字段之一，而改前它**恒空**
#    且**没有任何东西会红** —— 「空串」既不是「探到非空」、也不是「探不到 ⇒ 退 3」，是一条
#    **恒真的空断言**。⇒ 本脚本给它一条**具名判据**（只在调用方显式要求时生效）：
#      · **探到 `builtAt` 为空** ⇒ **判红（退 1）+ 点名「取值源未接（issue #7015）」**；
#      · 「探不到」（连不上 / 非 200 / body 不是 JSON）仍是 **退 3**，**与上面那条是两种语义**
#        （`builtAt` 字段缺席 ⇒ 本脚本读到空串 ⇒ 走退 1 那条：`/api/version` 的消费面里
#          「字段在但值是空串」与「字段压根不在」同形，本仓刻意不为此加第二种形态）。
#
# 退出码：0 = 线上就是本次构建；1 = 不一致 / `builtAt` 为空（判红）；3 = 探不到（fail-closed）。
# 判据 = tests/unit_ci_workflows/test_served_version_verify.py
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

BASE=${1:-https://api.migaozn.com}
BASE=${BASE%/}
EXPECTED=${2:-${GITHUB_SHA:-}}
APP=${SERVED_VERSION_APP:-}
PATH_SUFFIX=${SERVED_VERSION_PATH:-/api/version}
RETRIES=${SERVED_VERSION_RETRIES:-3}
RETRY_DELAY=${SERVED_VERSION_RETRY_DELAY:-5}
REQUIRE_BUILT_AT=${SERVED_VERSION_REQUIRE_BUILT_AT:-}

URL="$BASE$PATH_SUFFIX"
TMPDIR_RUN="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_RUN"' EXIT

# 期望 sha 的形态前置断言（fail-closed）：拿不到/形态不对的**期望值** = 判据的前置没成立
# ⇒ 当场报「探不到」，**绝不**退化成「比了个空串」（那会让判据恒红或恒绿，两种都是坏形态）。
# ⚠️ 这条出口也要落机读读数（`SERVED_VERSION=unknown`）：下游按它分三态，
#    缺了它就把「探不到」和「不一致」混桶（红与探不到是两种东西）。
EXPECTED=$(printf '%s' "$EXPECTED" | tr 'A-Z' 'a-z')
case "$EXPECTED" in
  *[!0-9a-f]*|"")
    echo "::error::本次部署的 sha 形态不合法（'$EXPECTED'）⇒ 无法判定（fail-closed）"
    echo "  · 期望值来源 = 部署腿的 \`GITHUB_SHA\` / 调用方第二个参数；形态必须是 ≥7 位 hex"
    echo "SERVED_VERSION=unknown"
    exit 3 ;;
esac
if [ "${#EXPECTED}" -lt 7 ]; then
  echo "::error::本次部署的 sha 太短（'$EXPECTED'，需 ≥ 7 位 hex）⇒ 无法判定（fail-closed）"
  echo "  · 说明：判据按前 7 位比对（镜像 tag 是 \`sha-<7hex>\`）⇒ 期望值短于 7 位时判不了任何东西"
  echo "SERVED_VERSION=unknown"
  exit 3
fi
EXPECTED7=${EXPECTED:0:7}

echo "== 现场版本自证（issue #6951）=="
echo "   端点：$URL"
echo "   期望 sha（本次部署）：${EXPECTED}（前 7 位 ${EXPECTED7}）${APP:+ · 期望 app=$APP}"

# `json_field <file> <key>`：只取**顶层字符串字段**（唯一消费面 = 本仓自有的 `/api/version`）。
# ⚠️ 解析失败 / 字段不存在 / 字段不是字符串 ⇒ **空串**，由调用方按「探不到」判（fail-closed）。
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
CODE=""; FETCHED_SHA=""; FETCHED_APP=""; FETCHED_BUILT_AT=""; ATTEMPT=0
while :; do
  ATTEMPT=$((ATTEMPT + 1))
  CODE=$(curl -sS -m 15 -H 'Cache-Control: no-cache' -o "$TMPDIR_RUN/version.json" \
           -w '%{http_code}' "$URL" 2>"$TMPDIR_RUN/curl.err" || true)
  FETCHED_SHA=""; FETCHED_APP=""; FETCHED_BUILT_AT=""
  if [ "$CODE" = "200" ] && [ -s "$TMPDIR_RUN/version.json" ]; then
    FETCHED_SHA=$(json_field "$TMPDIR_RUN/version.json" sha)
    FETCHED_APP=$(json_field "$TMPDIR_RUN/version.json" app)
    FETCHED_BUILT_AT=$(json_field "$TMPDIR_RUN/version.json" builtAt)
  fi
  # 判定「这一次读数是否已经可用」——只有它可用才停（`sha` 非空且形态合规）
  case "$FETCHED_SHA" in
    ""|*[!0-9a-fA-F]*) : ;;
    *) if [ "${#FETCHED_SHA}" -ge 7 ]; then break; fi ;;
  esac
  if [ "$ATTEMPT" -ge "$RETRIES" ]; then break; fi
  sleep "$RETRY_DELAY"
done

echo "   HTTP $CODE · 尝试 $ATTEMPT/$RETRIES"
echo "   线上读数：sha='${FETCHED_SHA:-}' app='${FETCHED_APP:-}' builtAt='${FETCHED_BUILT_AT:-}'"
if [ -s "$TMPDIR_RUN/version.json" ]; then
  echo "   原始 body：$(head -c 400 "$TMPDIR_RUN/version.json")"
fi

# ── 「探不到」出口（退出码 3）────────────────────────────────────────────────
# 每一条都必须**具名**（哪一步取不到），因为它们的处置不同：连不上 = 网络/服务；非 200 = 面被挡；
# body 不是 JSON = 端点被别的东西接管；sha 空 = 镜像没有注入面（老镜像）。
unknown() {
  local reason=$1
  echo "::error::版本自证**无法判定**（探不到）：$reason"
  echo "  · 语义：这是「**探不到**」，与「确认线上不是目标版本」是两种东西（后者退 1）；**不得**当通过"
  echo "  · 实测读数：HTTP ${CODE:-（取不到）} · sha='${FETCHED_SHA:-}' · app='${FETCHED_APP:-}' · 尝试 ${ATTEMPT}/${RETRIES}"
  echo "  · 可复制复算命令："
  echo "      curl -sS -m 15 '$URL' | head -c 400"
  echo "      bash deploy/scripts/served-version-verify.sh '$BASE' '$EXPECTED'"
  echo "  · 排查方向：① 端点在不在（nginx 是否放行该路径 / 服务是否起来）"
  echo "     ② 镜像有没有构建期注入面（backend/admin-api/Dockerfile 的 MIGAO_BUILD_SHA）"
  echo "     ③ 是否撞上 429 限流（/api/ 前缀有 limit_req；重试可解）"
  echo "  · 出口：确认网络/服务恢复后复跑本判据；老镜像（没有注入面）需要一次**带注入面的部署**"
  echo "SERVED_VERSION=unknown"
  exit 3
}

[ -n "$CODE" ] || unknown "curl 取不到 \`$URL\`（连接失败 / DNS / TLS）"
case "$CODE" in
  200) ;;
  429) unknown "HTTP 429（nginx 的 /api/ 限流档拦了探针）—— 重试即解；若恒 429 需核对 limit_req 阈值" ;;
  *)   unknown "HTTP ${CODE}（期望 200；404 = 该路径没被放行或端点不存在，401/403 = 鉴权面没放行）" ;;
esac
[ -s "$TMPDIR_RUN/version.json" ] || unknown "HTTP 200 但 body 为空（端点被别的东西接管？）"
[ -n "$FETCHED_SHA" ] || unknown "响应里取不到非空字符串字段 \`sha\`（body 不是本仓的 /api/version 形态？）"
case "$FETCHED_SHA" in
  *[!0-9a-fA-F]*) unknown "线上 \`sha\`='${FETCHED_SHA}' 不是 hex（形态不符）" ;;
esac
if [ "${#FETCHED_SHA}" -lt 7 ]; then
  # 「空串」是**老镜像**的形态（没有构建期注入面）：它必须判「探不到」，**不许**当绿
  # —— 否则本判据会在每一次「镜像没换」的部署上悄悄变成空断言。
  unknown "线上 \`sha\`='${FETCHED_SHA}' 不足 7 位 hex（镜像没有构建期注入面？老镜像？）"
fi
if [ -n "$APP" ] && [ "$FETCHED_APP" != "$APP" ]; then
  unknown "线上 \`app\`='${FETCHED_APP}' ≠ 期望 '${APP}'（这个端点后面不是目标服务）"
fi

# ── 比较：**逐字符**比前 7 位（镜像 tag 是 `sha-<7hex>`，端点报的是完整 40 位）─────────
FETCHED_LOWER=$(printf '%s' "$FETCHED_SHA" | tr 'A-Z' 'a-z')
if [ "${FETCHED_LOWER:0:7}" = "$EXPECTED7" ]; then
  echo "✅ 线上就是本次构建：served sha=${FETCHED_LOWER} == 期望 ${EXPECTED7}（前 7 位逐字符一致）"
  echo "   · 判据口径：只比前 7 位（与镜像 tag \`sha-<7hex>\` 同口径；更长的两端都照此截断）"
  # ── `builtAt` 具名判据（issue #7015）─────────────────────────────────────────
  # 「`sha` 对」不等于「构建身份完整」：改前 `builtAt` 由 `${GITHUB_RUN_STARTED_AT:-}` 取值，
  # 而那不是 GitHub 注入的环境变量（run 开始时刻只在 context `github.run_started_at` 里）
  # ⇒ 恒空串 ⇒ 真机读数逐字 `{"app":"admin-api","sha":"b5d9315e…","builtAt":""}`。
  # ⚠️ 只在调用方**显式要求**时生效（`SERVED_VERSION_REQUIRE_BUILT_AT` 非空；CI 部署腿传 1）
  #    —— 默认不判，免得把没接这个面的调用方（如本地手动复探）误判红。
  # ⚠️ 与「探不到（退 3）」**语义不同、必须分别具名**：那条说的是「连不上 / 非 200 / body 不是
  #    JSON ⇒ 一个字节都证不了」；本条说的是「**探到了**，而值是空串 ⇒ 取值源没接上」。
  if [ -n "$REQUIRE_BUILT_AT" ] && [ -z "$FETCHED_BUILT_AT" ]; then
    echo "::error::\`builtAt\` 为空 ⇒ **取值源未接**（issue #7015）：线上自报的构建时刻是空串，而 \`sha\` 是有的 —— 两者不同源"
    echo "  · 服务：admin-api（${URL}）· HTTP ${CODE} · 尝试 ${ATTEMPT}/${RETRIES}"
    echo "  · 探到什么：sha=${FETCHED_SHA} · app=${FETCHED_APP:-（空）} · builtAt=''（**空串**，不是「探不到」）"
    echo "  · 语义区分：这是「**探到了、值是空**」（判红，退 1）≠「**探不到**」（连不上 / 非 200 / body 不是 JSON ⇒ 退 3）"
    echo "  · 根因形态：构建身份里的 \`BUILT_AT\` 取值源写成了**未定义变量**（issue #7015 实测 = \`\${GITHUB_RUN_STARTED_AT:-}\`，"
    echo "    而 run 的开始时刻只在 context \`github.run_started_at\` 里）⇒ shell 展开恒为空 ⇒ 镜像里烘焙进空串"
    echo "  · 可复制复算命令："
    echo "      curl -sS -m 15 '$URL' | head -c 400"
    echo "      bash deploy/scripts/served-version-verify.sh '$BASE' '$EXPECTED'"
    echo "  · 出口：① 确认部署腿的 \`Resolve build identity\` 步用 \`env: RUN_STARTED_AT: \${{ github.run_started_at }}\` 取值"
    echo "     ② 该值经 \`swas-deploy-ci.sh\` 第 10 位参数 ⇒ BOOTSTRAP 占位符 \`__BUILT_AT__\` ⇒ \`--build-arg MIGAO_BUILT_AT\`；"
    echo "     ③ 修好后需**一次带注入面的部署**（本次部署已把空值烘焙进镜像 ⇒ 光重跑本探针不会变好）"
    echo "SERVED_VERSION=mismatch"
    exit 1
  fi
  echo "   · builtAt='${FETCHED_BUILT_AT:-（未要求判定）}'"
  echo "SERVED_VERSION=match"
  exit 0
fi

echo "::error::线上**不是**本次构建：served sha=${FETCHED_LOWER} ≠ 期望 ${EXPECTED}（前 7 位 ${EXPECTED7}）"
echo "  · 服务：admin-api（${URL}）"
echo "  · 探到什么：sha=${FETCHED_SHA} · app=${FETCHED_APP:-（空）} · HTTP ${CODE}"
echo "  · 期望什么：sha=${EXPECTED}（本次部署的目标 commit）"
echo "  · 也就是说：这次部署的「产物存在 / run 结论 success」**不等于**「线上换成了它」"
echo "    —— 这正是 issue #6951 / #6746 / #6554 要治的形态（判据从「推没推」换成「线上是不是它」）"
echo "  · 可复制复算命令："
echo "      curl -sS -m 15 '$URL' | head -c 400"
echo "      bash deploy/scripts/served-version-verify.sh '$BASE' '$EXPECTED'"
echo "  · 出口：① 容器没被替换（蓝绿残留 / compose 没重建）⇒ 在 run 页面 Re-run 本腿；"
echo "     ② 目标构建本身是旧的（镜像 tag 不是本次 commit）⇒ 用 \`gh workflow run deploy-admin-api.yml -f image_tag=sha-<7>\` 显式重部署；"
echo "     ③ 根因不明 ⇒ **先不要**用「再跑一次」掩盖：把本读数和该 run 的 \`EFFECTIVE_TAG=\` 并排看"
echo "SERVED_VERSION=mismatch"
exit 1
