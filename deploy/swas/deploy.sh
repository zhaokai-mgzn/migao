#!/bin/bash
# migao 部署脚本：默认拉 CI 预构建镜像；**C′ 形态**下在服务器侧就地构建那一个服务（issue #5814）
#
# 流程：拉 repo 内 canonical compose/nginx（**与镜像 tag 同源**，见第 0 段 / issue #5083）
#       → [C′：docker build 本地构建该服务] → pull 镜像 → up -d → 健康检查
#
# ══════════════════════════════════════════════════════════════════════════════
# C′（服务器侧构建，issue #5814）—— **用户 2026-09-30 裁定**，推翻本仓旧铁律
# 「构建跑在 CI，服务器只拉预构建产物」（原文见 docs/deployment/swas-migration-lessons.md）
#
# 为什么推翻（**真机实测**，`swas-open run-command` 现取；详表见该文档与本 PR body）：
# | 场景 | 实测 |
# |---|---|
# | 冷构建（无缓存，国内 apt+pip 镜像） | 1782 s（29.7 min）= apt 1100 s + pip 675 s |
# | **改一个源码文件（日常部署真实路径）** | **2 s**（apt/pip 层全 CACHED） |
# | 改 requirements.txt | 592 s（9.9 min）（apt 仍 CACHED，只重建 pip 层） |
# | 内存峰值 | 1792 MB（可用从未低于 5669 MB）⇒ 内存不是问题 |
# ⇒ 旧铁律记的「服务器自己 build 3 个服务（10–30min）」是**冷构建**读数；**稳态只改代码是秒级**，
#    且**根本不推 ACR** ⇒ 「跨境推送 1.12GB 镜像挂住 40min」这个根因从结构上消失
#    （PR #5816 只是给它加上界止血，本形态才是治愈）。
#
# ⚠️ **构建在 flock 之内**（本脚本第 1 段就拿了锁并持有到 EXIT）⇒ 旧文档 §二.2 记的
#    「main 合并同刻触发 3 个 deploy ⇒ 单机并发 docker build ⇒ 容器互踩」被**同一把锁**串行化：
#    后到的 run 要么等到锁、要么等 `LOCK_WAIT_SECONDS`（1800s）超时退出（与既有部署等待语义**一致**，
#    未新增第二把锁；等待上限的取值依据见下方 `LOCK_WAIT_SECONDS` 的注释，issue #5896）。
# ⚠️ 不侵入既有路径：`BUILD_SERVICE` 为空（默认）⇒ 本段**完全不执行**，行为与改动前逐字相同。
# ══════════════════════════════════════════════════════════════════════════════
#
# 并发安全：flock 串行化（CI 可能并行触发）。
# 镜像 tag：`${1:-latest}`。⚠️ 配置（compose/nginx）按该 tag 对应的 commit 取 ⇒ 实际部署必须给
#           `sha-<7位hex>`（CI 的正常形态）；`latest` 这类**移动 tag** 追不到 commit ⇒ fail-closed。
# 镜像仓库登录：若存在 .env.registry（ACR_USERNAME/ACR_PASSWORD）则登录；
#               ACR 仓库设为公开读时无需登录；**C′ 本地构建时不需要 ACR 凭据**（见 registry_login）。
set -euo pipefail

LOCK=/tmp/migao-deploy.lock
# LOCK_WAIT_SECONDS：等待**兄弟部署**结束的上界（秒）—— 把三条部署腿串行化的是**同一把锁**，
# 而 CI 侧的 `concurrency` 组是按**服务**分的（`deploy-frontend` / `deploy-admin-api` /
# `deploy-ai-agent-service`）⇒ **跨服务不互斥**：同一次 push 同时改 admin-api 与 admin-web 时，
# 两条腿**同刻起跑**抢这把锁（issue #5896，2026-10-01 云测试环境一直停在旧版本的真因）。
# 取值依据（**真机实测**，非推断）：先到的那条腿跑了 **~28 分钟**（07:32:48Z → 08:00:22Z）
# ⇒ 旧的 600s 等待上限对后到者**必然不够**（当天两次如实复现 `deploy-frontend` failure，读数是
# 「等待部署锁超时」，不是构建/健康检查失败）。
# ⇒ 1800s（30min）= 覆盖实测最慢单次部署 + 余量。同期抬高的三处预算必须一致：
#   `deploy/scripts/swas-deploy-ci.sh` 的 `C_BUILD_DEPLOY_TIMEOUT_SECONDS`（= 锁等待 1800
#   + 冷构**上界** 2400 + 余量 300 = 4500）与三条 workflow 的 job `timeout-minutes`（90min > 该预算）。
# 判据 = tests/unit_ci_workflows/test_swas_deploy_ci_hardening.py（等待下限 / 等得起 / 文案不误诊）。
LOCK_WAIT_SECONDS=${SWAS_LOCK_WAIT_SECONDS:-1800}
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "== 检测到另一个部署正在进行，等待其完成（最多 $((LOCK_WAIT_SECONDS / 60)) 分钟）=="
  if ! flock -w "$LOCK_WAIT_SECONDS" 9; then
    echo "❌ 等待部署锁超时（$((LOCK_WAIT_SECONDS / 60)) 分钟）：$LOCK 仍被另一个部署持有 —— 那是**并发部署在排队**"
    echo "   真因是**排队**，不是「有进程挂住」：单次部署实测可达 ~28 分钟（比等待上限的旧值 600s 长得多）。"
    echo "   这把锁也不会被遗留：flock(2) 的锁挂在「打开文件描述」上 ⇒ 进程以**任何方式**终止（含 SIGKILL）"
    echo "   内核都会关闭 fd 并释放锁（见 https://github.com/zhaokai-mgzn/migao/wiki/CI-CD 的「远端 flock 与超时强杀的关系」）。"
    echo "   ⇒ 处置：**不要**手工清 $LOCK 后重试（它不会被遗留 ⇒ 清了也不会变快），也**不要** kill 占用者"
    echo "     （它多半正在**正常**部署，kill 只会留下半截环境）。等它跑完，下次部署会正常拿到锁。"
    echo "   次要核对（只想知道占用者是谁时）：fuser -v $LOCK"
    exit 1
  fi
fi
trap 'flock -u 9' EXIT

# ══════════════════════════════════════════════════════════════════════════
# 0.9 **运行面探测**（issue #6294）：`--probe-running-tag <服务…>` ⇒ 只读打印 `RUNNING_TAG=<svc>:<tag>`
#
# 病：`deploy-*.yml` 的 `Skip if already built (schedule reconcile)` 只凭 **run 结论**判「已部署」
# ⇒ 「跳过部署」的 run 也是 success ⇒ 环境停摆而台账全绿（issue #6294 现场：40 小时）。
# 出口 = 在**跳过**那条路径上加一条**运行面**读数（部署腿的 `Assert running tag == target` step
# 消费它，经 `deploy/scripts/swas_deploy_running_tag.sh`）。
#
# 🔴 位置**必须在 flock 之前**（两重理由）：① 它是**只读**的（不 build / 不 pull / 不 up），
#    不需要互斥；② 若放在锁之后，恰恰是「有兄弟部署在跑」时——也就是**最需要读到真实运行态**的
#    时候——探测会白等最多 `LOCK_WAIT_SECONDS`（1800s）⇒ 自证变成新的挂点。
# ⚠️ 取 tag 的**唯一实现**是下面的 `running_tag_of()`（本段按同一形态内联：探测要在函数定义之前跑）。
#    形态漂移由 `tests/unit_ci_workflows/test_deploy_skip_is_not_success.py` 钉住。
# ══════════════════════════════════════════════════════════════════════════
if [ "${1:-}" = "--probe-running-tag" ]; then
  shift
  cd /opt/migao-deploy 2>/dev/null || true
  for _s in "$@"; do
    _cid=$(docker compose -f deploy/swas/docker-compose.yml ps -q "$_s" 2>/dev/null || true)
    _cid=${_cid%%$'\n'*}
    _img=""
    if [ -n "$_cid" ]; then _img=$(docker inspect --format '{{.Config.Image}}' "$_cid" 2>/dev/null || true); fi
    echo "RUNNING_TAG=${_s}:${_img##*:}"
  done
  exit 0
fi

cd /opt/migao-deploy
# 发布线自检的**显式逃生口**（段内正文见 1.0.1 / issue #9086）：`--allow-unverified-release` ≡
# `ALLOW_UNVERIFIABLE_RELEASE=1`。放在这里（`$TAG` 之前的**唯一**参数解析点）⇒ 两种写法行为逐字相同。
ALLOW_UNVERIFIABLE_RELEASE=${ALLOW_UNVERIFIABLE_RELEASE:-0}
_rl_rest_args=""
for _a in "$@"; do
  if [ "$_a" = "--allow-unverified-release" ]; then
    ALLOW_UNVERIFIABLE_RELEASE=1
  else
    _rl_rest_args="${_rl_rest_args}${_rl_rest_args:+ }${_a}"
  fi
done
# ⚠️ 不用数组重建（bash 3.2 下 `set -u` + 空数组展开会报 unbound）：tag 形态**不含空格**（sha-<hex> /
#    版本 tag），所以这里按空格拆回是安全的；`set --` 无参也合法（⇒ 落到默认 `latest`）。
if [ -n "$_rl_rest_args" ]; then set -- $_rl_rest_args; else set --; fi
TAG=${1:-latest}
REGISTRY=${ACR_REGISTRY:-crpi-qdcgkzwx9p9zckga.cn-hangzhou.personal.cr.aliyuncs.com}

# ══════════════════════════════════════════════════════════════════════════════
# 站点对外域名（生产 cytda.com / 测试 migaozn.com）
#
# 唯一真值源仍是 `deploy/swas/nginx.conf`（560 行里 400+ 行是安全口径：限流五档 / 日志脱敏 /
# HSTS / CSP / 静态缓存）。生产**不再抄一份 nginx.conf**，只替换域名这一维：
#   盘上 `nginx/nginx.conf.canonical` = 仓库原文；`nginx/nginx.conf` = 渲染产物（挂进容器的那份）。
# 为什么不做 `deploy/prod/nginx.conf`：抄一份就多一处漂移面，而漂移的症状恰恰是「生产漏了
#   HSTS/限流」——静默且不可归因。渲染是纯替换 ⇒ 两边不可能只改一边。
#
# 配置来源（按顺序）：环境变量 > `/opt/migao-deploy/.env.site` > 默认 `migaozn.com`。
# 生产机写 `.env.site` 一行即可：`MIGAO_PUBLIC_DOMAIN=cytda.com`。
# 缺省值 = `migaozn.com` ⇒ 测试环境渲染结果与改前**逐字相同**（default 分支是纯 cp，不跑 sed）。
# 判据：tests/unit_ci_workflows/test_prod_domain_rendering.py
# ══════════════════════════════════════════════════════════════════════════════
MIGAO_SITE_ENV_FILE=${MIGAO_SITE_ENV_FILE:-.env.site}
if [ -f "$MIGAO_SITE_ENV_FILE" ]; then
  # shellcheck disable=SC1090
  set -a; . "./$MIGAO_SITE_ENV_FILE"; set +a
  echo "  ℹ️  已加载 ${MIGAO_SITE_ENV_FILE}（站点域名覆盖口）"
fi
MIGAO_PUBLIC_DOMAIN=${MIGAO_PUBLIC_DOMAIN:-migaozn.com}
# fail-closed：域名会进 sed 替换串与 server_name，畸形值必须在这里停住（而不是在 nginx -t）
case "$MIGAO_PUBLIC_DOMAIN" in
  '' | .* | *. | *[!a-z0-9.-]*)
    echo "❌ MIGAO_PUBLIC_DOMAIN 非法：'${MIGAO_PUBLIC_DOMAIN}'（只允许小写字母/数字/点/连字符，且不以点开头或结尾）" >&2
    exit 1
    ;;
esac

# ══════════════════════════════════════════════════════════════════════════════
# C′ 参数（issue #5814）：`BUILD_SERVICE=<admin-api|ai-agent|admin-web>`（空 = 走既有「拉镜像」路径）
#
# | 变量 | 默认 | 作用 |
# |---|---|---|
# | `BUILD_SERVICE` | **空** | 要**在服务器侧构建**的那个服务键（与 compose 服务名一致）⇒ 空 = 完全不走本段 |
# | `APT_MIRROR` | `deb.debian.org` | 传给 `--build-arg`；服务器侧传 `mirrors.aliyun.com`（否则 apt >1h，实测 4009s 仍未下完 189MB） |
# | `PIP_INDEX_URL` | 空（用 Dockerfile 默认） | 服务器侧传国内 PyPI 镜像（CI 传的是 `https://pypi.org/simple/` = 境外） |
# | `BUILD_TIMEOUT_SECS` | `2400` | **单次构建的显式上界**（秒）⇒ 冷构建实测 1782s，留 ~35% 余量；超时 rc=124 显式判红 |
# ⚠️ 上界的意义与 PR #5816 同族：**不许无上界地挂住**（挂住只会等 job 超时 ⇒ `cancelled` ⇒ 断路器不跳闸 ⇒ cron 自放大）。
# ══════════════════════════════════════════════════════════════════════════════
BUILD_SERVICE=${BUILD_SERVICE:-}
APT_MIRROR=${APT_MIRROR:-deb.debian.org}
PIP_INDEX_URL=${PIP_INDEX_URL:-}
BUILD_TIMEOUT_SECS=${BUILD_TIMEOUT_SECS:-2400}

# ══════════════════════════════════════════════════════════════════════════
# 构建身份注入面（issue #6951）：**线上跑的是哪个 build** 必须可判读
#
# 探针端点 = `GET /api/version`（消费方 `deploy/scripts/served-version-verify.sh`）。
# 下面三个值经 `--build-arg` 烘焙进镜像 ⇒ 探针读数 = **产物身份**，不是「这次想部署什么」。
# 🔴 为什么不在 `docker compose up` 时用 `environment:` 注入：那表达的是**部署意图**，
#    它与「容器里真的在跑哪份代码」可以脱钩（拉了旧镜像 / 容器没被替换）⇒ 探针会在跑着旧代码时
#    照样报出新 sha，变成**空断言**（issue #6951 要治的正是这个形态）。
# 🔴 为什么不运行时现算（`git rev-parse HEAD`）：部署形态的容器里**没有 `.git`**
#    （C′ 的构建上下文是 codeload 归档树，运行时镜像里也不带源码）⇒ 现算必然是错的。
# ⚠️ 构建期真值由 CI 注入（`deploy-admin-api.yml` 的 `Resolve build identity` 步，
#    来源 = `GITHUB_SHA` / `GITHUB_RUN_STARTED_AT` —— 都不是运行时现算）；
#    这里只管**把它交给 docker build**，并保证「忘了传」时在日志里可见（不静默空串）。
# 判据 = tests/unit_ci_workflows/test_served_version_verify.py
# ══════════════════════════════════════════════════════════════════════════
BUILD_SHA=${BUILD_SHA:-}
BUILD_TAG=${BUILD_TAG:-}
BUILT_AT=${BUILT_AT:-}
if [ -n "$BUILD_SERVICE" ] && [ -z "$BUILD_SHA" ]; then
  echo "  ::warning::BUILD_SHA 为空 ⇒ 本次构建的镜像**没有**版本注入面（/api/version 的 sha 会是空串）"
  echo "     ⇒ 线上版本自证（served-version-verify.sh）只能判「探不到」(exit 3)，**不会**判绿。"
  echo "     修法：让调用方（部署腿）导出 BUILD_SHA=<本次部署的 commit sha>（issue #6951）。"
fi

# 服务键 → (compose 服务名, 构建上下文, Dockerfile)。**唯一一处**映射，构建与拉取两侧共用 ⇒ 不会漂移。
service_name_of() {
  case "$1" in
    admin-api) echo "admin-api" ;;
    ai-agent)  echo "ai-agent" ;;
    admin-web) echo "admin-web" ;;
    *) echo "" ;;
  esac
}
service_context_of() {
  case "$1" in
    admin-api) echo "backend/admin-api" ;;
    ai-agent)  echo "backend/ai-agent-service" ;;
    admin-web) echo "frontend/admin-web" ;;
    *) echo "" ;;
  esac
}
# compose 里的镜像名由它自己插值（`${ACR_REGISTRY:-…}/<ns>/<compose 服务名>:${IMAGE_TAG}`）
# ⇒ **本地构建必须打逐字相同的 ref**（否则 compose 找不到本地镜像 ⇒ 转而去 ACR pull 一个
# **本次从未推送**的 tag ⇒ 拉到旧镜像或失败）。故下面第 1.4 段**不自己拼 ref**，而是让
# `docker compose config` 求值（唯一真相源）。
# ⚠️ compose 侧用 `${ACR_REGISTRY:-<默认>}` 插值 ⇒ 这里必须把同一个变量 export 出去才能同源。
export ACR_REGISTRY="$REGISTRY"
LOCAL_IMAGE_REF=""   # 非空 ⇒ 本次是 C′ 本地构建；下方 `pull` 段据此跳过该服务
if [ -n "$BUILD_SERVICE" ]; then
  _svc=$(service_name_of "$BUILD_SERVICE")
  if [ -z "$_svc" ]; then
    echo "❌ BUILD_SERVICE=\`$BUILD_SERVICE\` 不是已知服务（允许：admin-api / ai-agent / admin-web）⇒ 中止（拒绝猜）"
    exit 1
  fi
  echo "== C′ 参数：服务=${_svc} 上界=${BUILD_TIMEOUT_SECS}s apt=${APT_MIRROR} pip=${PIP_INDEX_URL:-<Dockerfile 默认>} =="
fi

# ══════════════════════════════════════════════════════════════════════════
# 0. 配置源与镜像 tag **同源**（issue #5083 / 无方向审计 P2-2.8）
#
# 病根（**审计实测**，非推断）：配置（compose / nginx）此前**无条件**取
# `refs/heads/main` 的最新版，而镜像 tag 是按 commit 固定的 ⇒ **回滚到旧 tag 时
# 配置仍是新版**（旧镜像 + 新配置 = 未定义行为，而且**不报错、不告警**）。
# 与本仓「部署结论以**容器真身**为唯一判据」同族：配置也是"真身"的一部分。
#
# 判据（**唯一一份推导**）：配置 ref 由镜像 tag 推导，**绝不**由 main 推导 ——
#   `sha-<hex>` ⇒ `<hex>`（**与镜像同一个 commit**，不可变引用）
#   其它形态    ⇒ `refs/tags/<tag>`（tag→commit 的解析；tag 不存在 ⇒ 404 ⇒ **fail-closed**）
# 取不到对应配置 ⇒ **非零退出 + 可行动报错**（**绝不**静默回落到 main 的配置）。
# ══════════════════════════════════════════════════════════════════════════
# 配置源（**唯一一处**）：codeload 归档。可被覆盖 ⇒ 守卫测试用桩打同一条码路。
CONFIG_TARBALL_BASE=${CONFIG_TARBALL_BASE:-https://codeload.github.com/zhaokai-mgzn/migao/tar.gz}

# `sha-<hex>` → 提交 sha；其它形态（latest / v1.2.3 / 空）⇒ 空串（= 没有提交可锚）
tag_to_sha() {
  local t=${1#sha-}
  case "$t" in
    *[!0-9a-f]*|"") echo ""; return 0 ;;
  esac
  if [ "${#t}" -ge 7 ]; then echo "$t"; else echo ""; fi
  return 0
}

# 配置 ref：与镜像 tag **同源** ⇒ 任何分支都不可能返回 `refs/heads/main`
config_ref_for_tag() {
  local t=$1 s
  s=$(tag_to_sha "$t")
  if [ -n "$s" ]; then echo "$s"; return 0; fi
  if [ -n "$t" ]; then echo "refs/tags/$t"; fi
  return 0
}

# ── 取配置的「可观测重试 + 现盘复用」（issue #6551）────────────────────────────
# 病根（**CI 现取**读数，run 37726977789）：
#   `curl: (28) Operation timed out after 120000 milliseconds with 41399245 out of 66570829 bytes received`
#   ⇒ 一次下载故障同时夺走「前进」与「后退」：主部署失败 → 自动重试失败 → **自动回滚也被同一步挡住**
#   （`❌ 取不到 tag=sha-03b1132 对应的配置（ref=03b1132）⇒ 中止部署`）。
#
# ⚠️ 预算（`--max-time` 的取值，900s）与「**不许加 `-C -`**」这两条**本单不动** —— 它们是 #6550 的实测结论，
#    逐字登记在下面的调用点（codeload 不支持 Range ⇒ 续传会把「慢」换成「永久卡死」）。
#    本单只在其上加两件事，**都不改那两条结论**：
#    ① **把不可见的重试换成可见的**：curl 自带的 `--retry 3` 在脚本日志里**没有痕迹**（事故的一部分
#       正是「参数面写了重试、到底有没有触发没人知道」）⇒ 换成显式轮次，每轮都打一行（含 `curl exit=`
#       与本轮**收到多少字节**）。预算口径与 #6550 逐字相同：3 轮 × 900s + 2×5s = **2710s** < CI 4500s。
#       ⚠️ 因此**去掉** curl 自带的 `--retry 3/--retry-delay 5`（它同样是「从 0 重下」，只是不可见）：
#          两者叠加会变成 3×4 次尝试 ⇒ 病态最坏 10800s，**打破 #6550 的预算契约**。
#    ② 现盘配置的 ref 与本次目标相同 ⇒ **跳过整仓下载**（回滚腿不再被下载闸门一起挡住）。
#    ⚠️ 每轮**先删残包**：既然不能续传，残包只会把下一次尝试拖进 `exit 33`（#6550 ② 的实测形态）。
CONFIG_FETCH_ATTEMPTS=${CONFIG_FETCH_ATTEMPTS:-3}
CONFIG_FETCH_DELAY_SECONDS=${CONFIG_FETCH_DELAY_SECONDS:-5}
CONFIG_TARBALL_BYTES=0
# 现盘配置的「物化 ref」标记（只在**真的把配置包落到盘上**之后写）。见 `config_reuse_on_disk()`。
CONFIG_REF_MARKER_FILE=${CONFIG_REF_MARKER_FILE:-/opt/migao-deploy/.config-ref}

# 盘上的 compose/nginx 是不是**本次目标 ref** 那一份（#6551 ②：回滚目标的配置通常就在盘上）。
# 🔴 只认「标记 == 目标 ref」⇒ 仍是「配置与镜像同源」（#5083 的护栏 fail-closed 语义一字不改）：
#    标记不匹配 / 三份 canonical 文件不齐 ⇒ 一律**降级为重新下载**（取不到仍 fail-closed）。
# ⚠️ 它与 `.last-good-tag` **不是**一回事：那个记「上次**部署成功**的 tag」，本标记只陈述
#    「**盘上这套配置**物化自哪个 ref」。用后者做复用判据，才不会在「新 tag 的配置已落盘、
#    部署在后续步骤才失败」时拿**旧镜像配新配置**（那正是 #5083 要治的形态）。
config_reuse_on_disk() {
  [ -n "$CONFIG_ON_DISK_REF" ] && [ "$CONFIG_ON_DISK_REF" = "$CONFIG_REF_RESOLVED" ] || return 1
  if [ -f docker-compose.yml ] && [ -f nginx/nginx.conf ] && [ -f docker-compose.bluegreen.yml ]; then
    return 0
  fi
  echo "  ::warning::盘上标记（${CONFIG_REF_MARKER_FILE}）说配置来自 ref=${CONFIG_REF_RESOLVED}，但三份 canonical 配置不齐 ⇒ **降级为重新下载**（同源语义不变）"
  return 1
}

# 取配置包：显式重试（每轮都在日志里出声）+ 每轮先删残包（#6551 ①）。
# ⚠️ **不续传**（codeload 不支持 Range，#6550 实测）⇒ 每轮都是**完整的**一次下载，从 0 开始。
# 成功 ⇒ 0；重试预算用尽 ⇒ 1（调用点 fail-closed，绝不回落 main 的配置）。
config_fetch_tarball() {
  local try=0 rc=0 have=0
  while [ "$try" -lt "$CONFIG_FETCH_ATTEMPTS" ]; do
    try=$((try + 1))
    # 残包不许跨轮留存：不能续传，留着只会让下一轮撞上 `Range:` ⇒ curl exit 33、零进展（#6550 ②）。
    rm -f src.tar.gz
    echo "  ⏱ 第 ${try}/${CONFIG_FETCH_ATTEMPTS} 次取配置：单次上界 900s（#6550 实测 66.5MB ÷ 118~345KB/s ⇒ 需 193~565s）"
    if curl -fsSL --connect-timeout 15 --max-time 900 -o src.tar.gz "$CONFIG_TARBALL_BASE/$CONFIG_REF_RESOLVED"; then
      CONFIG_TARBALL_BYTES=$(wc -c < src.tar.gz | tr -d ' ')
      return 0
    else
      rc=$?
    fi
    have=0
    if [ -f src.tar.gz ]; then have=$(wc -c < src.tar.gz | tr -d ' '); fi
    if [ "$try" -lt "$CONFIG_FETCH_ATTEMPTS" ]; then
      echo "  ⚠️ 第 ${try}/${CONFIG_FETCH_ATTEMPTS} 次失败（curl exit=${rc}，本轮收到 ${have} 字节）⇒ **第 $((try + 1)) 次重试**（${CONFIG_FETCH_DELAY_SECONDS}s 后，从 0 重下——codeload 无 Range，#6550 实测）"
      sleep "$CONFIG_FETCH_DELAY_SECONDS"
    else
      echo "  ⚠️ 第 ${try}/${CONFIG_FETCH_ATTEMPTS} 次失败（curl exit=${rc}，本轮收到 ${have} 字节）⇒ 重试预算用尽"
    fi
  done
  return 1
}

# ══════════════════════════════════════════════════════════════════════════
# 2.4 磁盘保留策略 × 回滚点对齐（issue #4808）
#
# 病根（**主会话实测**，非推断）：部署后那句 `docker image prune -f` **不带 `-a`**
# ⇒ 只清 dangling（无 tag）镜像 ⇒ 带 tag 的 `sha-*` 旧镜像**永远不被清** ⇒ 每次部署
# 堆积 ≈3.14GB（admin-web 1.72G + ai-agent 1.12G + admin-api 0.30G）⇒ 磁盘单调爬升；
# 到 >90% 才触发 `docker system prune -af --volumes`（深度清理）——**它会把带 tag 的也删**，
# 包括 `.last-good-tag` 指向的那一套 ⇒ **#4767 的「失败即回滚」在深度清理之后就没有回滚点了**
# ✗✗，而且**是静默的**（日志里只有一行「清理后磁盘: N%」）。
#
# 本段的两条约束（**清理策略必须与回滚策略一起设计**）：
#   ① 保留策略：部署成功后按 `sha-*` 保留「**当前在用** + **`.last-good-tag` 指向的（回滚点）**
#      + **最近 N 个**」⇒ 其余**按本项目前缀**删（**非本项目镜像一律不碰**）；
#   ② 回滚点**只许保留、不许静默丢** ⇒ **三道独立防线**：
#      ⓐ 回滚点在保留集里；ⓑ `cleanup_project_images` 里另有一条**不看保留集**的逐镜像护栏
#      （保留集算错/读不到/为空也删不掉它，fail-closed）；ⓒ 清理后**事后自检** + 每次部署
#      都报「回滚点 3/3 是否在本地」，缺失/不完整一律 `::warning::`。深度清理段同样先记
#      `RB_BEFORE`、清理后复核并从 ACR 补回（补回**必须在清理释放空间之后**）。
# ══════════════════════════════════════════════════════════════════════════

# 本项目镜像的**命名空间前缀**（只按它筛 ⇒ 不可能误删别的项目/公共镜像）。
# 默认值与 deploy/swas/docker-compose.yml 的 `image:` 一致；一致性由守卫测试钉住。
PROJECT_IMAGE_PREFIX=${PROJECT_IMAGE_PREFIX:-ai-customer-service/}
# 除「当前在用 + 回滚点」之外，额外保留的最近 `sha-*` tag 个数（0 = 只保留前两者）。
KEEP_RECENT_TAGS=${KEEP_RECENT_TAGS:-1}
# 磁盘水位告警阈值（**主动**告警，而不是只在 >90% 深度清理时说一句）
DISK_WARN_PCT=${DISK_WARN_PCT:-80}
LAST_GOOD_FILE=${LAST_GOOD_FILE:-/opt/migao-deploy/.last-good-tag}

disk_pct() { df / | awk 'NR==2 {gsub("%","",$5); print $5}'; }
# 已用空间（MB）：用于把「补回回滚点到底花了多少空间」**如实**打进部署日志（不猜、不算百分比估）
disk_used_mb() { df -Pk / | awk 'NR==2 {print int($3/1024)}'; }
# 可用空间（MB）：**唯一一份**口径 —— 构建前置门槛与缓存回收的水位判定共用它（两处不许各写各的）。
disk_free_mb() { df -Pk / | awk 'NR==2 {print int($4/1024)}'; }

# ── 容器日志上界（issue #8197 P1-02）──────────────────────────────────────────────
# 口径 = `deploy/swas/docker-compose.yml` 的 `x-logging` 锚点（max-size / max-file）。
# 🔴 这两条常量**不是**第二个真值源：它们是**同一份口径的读数侧**，判据
#    `tests/unit_ci_workflows/test_swas_container_runtime.py` 逐字比对两边（不一致即红）。
LOG_CAP_MB=${LOG_CAP_MB:-50}
LOG_MAX_FILES=${LOG_MAX_FILES:-3}

#: 单容器日志上界（MB）= max-size × max-file（compose 的 json-file 轮转语义）
log_cap_per_container_mb() { echo $((LOG_CAP_MB * LOG_MAX_FILES)); }

#: 本 compose 项目**容器 json-file 日志的实际占用**（MB）+ 计入的容器数：`<mb> <count>`
#: ⚠️ **只读**：只 `docker compose ps -q` + `docker inspect` + `du`，不删任何东西
#:    （铁律 10：本读数不新增任何无人值守的删除动作）。
#: ⚠️ 取不到（无 docker / 容器不是 json-file 驱动 / 无权限）⇒ 容器数与 MB 都照实给 0 ——
#:    `0` 在这里的含义是「本机没数到这个项目的容器」，**不是**「日志占用为零」；
#:    消费面（`::warning::` 门）只在**数到了容器**且超过上界时才响。
container_log_footprint_mb() {
  local total=0 count=0 cid path kb
  for cid in $(docker compose ps -q 2>/dev/null || true); do
    [ -n "$cid" ] || continue
    path=$(docker inspect -f '{{.LogPath}}' "$cid" 2>/dev/null || true)
    [ -n "$path" ] && [ -f "$path" ] || continue
    kb=$(du -k "$path" 2>/dev/null | awk '{print $1}')
    total=$((total + ${kb:-0}))
    count=$((count + 1))
  done
  echo "$((total / 1024)) $count"
}

# ══════════════════════════════════════════════════════════════════════════
# 构建缓存的**水位联动回收**（issue #6508）—— 只碰构建缓存，永不碰镜像/保留集
#
# 病（**真机实测 2026-10-07**）：脚本给运维的恢复出口是固定窗口
# `docker builder prune --filter until=168h`，而缓存条目**全是 72h 内建的** ⇒ 匹配 0 条、
# `Total: 0B`（同一时刻 `until=48h` 解出 **6.745GB**）⇒ **照提示敲解决不了问题**。
# 另一半：Build Cache 168h/184 条 / 100% RECLAIMABLE，**只增不减**，是磁盘单调爬升的主因。
#
# 落码（issue #6508 要的三件）：
#   ① 窗口**按磁盘可用量选**（`pick_cache_window`：水位越低窗口越紧，最紧档 = 兜底清空）；
#   ② 部署内**带阈值、幂等、失败可见**的自愈（`builder_cache_recover`：清到门槛以上为止；
#      铁律 10 口径 —— 不是新 schedule，也不做无人值守的删除）；
#   ③ 读数**真的打进部署日志**（`builder_cache_measure` ⇒ 消灭逐字的 `构建缓存：?`）。
#
# 🔴 铁律 10 / 保留集：本段**只发 `docker builder prune`**（构建缓存不是镜像、不是 tag、
#    不是回滚点）⇒ 结构上碰不到「当前在用 + `.last-good-tag` 回滚点 + 最近 N 个」。
#    由 tests/unit_ci_workflows/test_swas_deploy_disk_recovery.py 的判据 3/4 机械钉住
#    （缓存段里出现任何删镜像命令、或引用回滚点，当场判红）。
# ⚠️ `-af`（清空构建缓存）**只许**出现在本段的**兜底档**：它会把稳态 2s 打回冷构建 29.7min，
#    故只在「不腾空间这一趟就部署不下去」时才允许 —— 这正是「恢复出口必须真可行动」的代价。
# ══════════════════════════════════════════════════════════════════════════

#: 候选窗口阶梯（小时，逗号分隔，**从宽到紧**）：水位越低走到越后面；
#: 走完仍不够 ⇒ 兜底档 = `--keep-storage 0`（清空构建缓存 —— 真机实测缓存 100% RECLAIMABLE）。
BUILD_CACHE_LADDER=${BUILD_CACHE_LADDER:-168,72,48,24,6}
#: 「还值得回收」的下限（GB）：构建缓存**不足**这么多时，为它清缓存只是徒劳（日志里写清扫原因）
BUILD_CACHE_GATE_MB=${BUILD_CACHE_GATE_MB:-1}

#: 尺寸串 → MB（`1.9GB` / `512MB` / `0B` / `-` ⇒ 数；**读不出** ⇒ 空串 —— 绝不猜）
_size_to_mb() {
  LC_ALL=C awk -v s="$1" 'BEGIN {
    if (s == "" || s == "-") { print ""; exit }
    n = s + 0
    u = s; sub(/^[0-9.]+/, "", u); u = toupper(substr(u, 1, 2))
    if (u == "B") { printf "%d", (n < 1048576 ? (n > 0 ? 1 : 0) : n / 1048576) }
    else if (u == "KB") { printf "%d", (n < 1024 ? (n > 0 ? 1 : 0) : n / 1024) }
    else if (u == "MB") { printf "%d", n }
    else if (u == "GB") { printf "%d", n * 1024 }
    else if (u == "TB") { printf "%d", n * 1024 * 1024 }
    else if (s ~ /^[0-9.]+$/) { printf "%d", n }
    else { print "" }
  }'
}

#: 构建缓存当前占用（MB）。**读不出 ⇒ 空串**（调用方必须显式说「无法读数」，不许静默当 0）。
#: 两段实现（`--format` 取尺寸列；老版本 docker 用 `-v` 的 `Build cache usage:` 行）——
#: 实测本机 `docker system df --format` 可用；`-v` 是**可检出信号的**回落（缺它则 `-v` 环境读数为 `?`）。
cache_total_mb() {
  local out
  out=$(docker system df --format '{{.Type}} {{.Size}}' 2>/dev/null         | awk '$1=="Build" && $2=="Cache" {print $3}' | head -n 1 || true)
  if [ -z "$out" ]; then
    out=$(docker system df -v 2>/dev/null | sed -n 's/^Build cache usage: *//p' | head -n 1 || true)
  fi
  _size_to_mb "$out"
}

#: 缓存读数（MB；读不出 ⇒ `?`）。**读数与「有没有清到空间」是两件事** ⇒ 分开两个函数。
builder_cache_measure() {
  local mb
  mb=$(cache_total_mb || true)
  if [ -z "$mb" ]; then
    echo "?"
  else
    echo "$mb"
  fi
}

#: 按磁盘可用量选清理窗口（小时；**只读、幂等**，真跑函数本体的判据见测试文件的 §三）。
#: 契约：可用量越小 ⇒ 窗口越紧（单调，由 `BUILD_CACHE_LADDER` 从宽到紧的次序保证）；
#: 极端档（连 `BUILD_MIN_FREE_MB/2` 都不够）⇒ `-af`（由 `builder_cache_recover` 兜底）。
#: 为什么要「按水位」而不是固定窗口：真机实测 `until=168h` 在该场景匹配 **0 条**（缓存全是 72h 内建的）
#: ⇒ 固定窗口 = **空操作**；水位越低越要敢清更近的层 —— 那正是 issue #6508 的修法。
pick_cache_window() {
  local free=${1:-0} want=${BUILD_MIN_FREE_MB:-4096}
  if [ "$free" -ge "$((want * 4))" ]; then echo 168
  elif [ "$free" -ge "$((want * 2))" ]; then echo 72
  elif [ "$free" -ge "$want" ]; then echo 48
  elif [ "$free" -ge "$((want / 2))" ]; then echo 24
  else echo 6
  fi
  return 0
}

# ACR 登录（**唯一一份**）：1.9 的「回滚点补回」与第 2 步的常规拉取共用 ⇒ 判据/凭据读取不会漂移。
# ACR 是私有仓库（https://github.com/zhaokai-mgzn/migao/wiki/CI-CD：服务器需凭据拉私有镜像）⇒ 补回前必须先登录，否则必然失败。
# ⚠️ 本函数**在 C′ 本地构建时也照常登录**：虽然本次镜像本地构建、不推 ACR，但 1.9 的
#    「深度清理后从 ACR 补回回滚点」仍需凭据（回滚点是**上一次**推上去的 tag）⇒ 不能因为
#    本次走本地构建就跳过登录（那会把「失败即回滚」的能力悄悄砍掉）。
registry_login() {
  if [ -f .env.registry ]; then
    # shellcheck disable=SC1091
    . ./.env.registry
    if [ -n "${ACR_USERNAME:-}" ] && [ -n "${ACR_PASSWORD:-}" ]; then
      # ── issue #6526 C：**不再静默** —— 旧版把登录失败整层吞掉
      #    （`… --password-stdin >/dev/null 2>&1 || true`）⇒ 下游「拉取镜像失败」被错误归因
      #    （读日志的人只会看到「拉取失败」，看不到「那之前登录就失败了」）。
      #    语义**仍是非致命**（C′ 本地构建时可能不需要它；1.9 的「从 ACR 补回回滚点」需要）
      #    ⇒ 失败时具名 `::warning::` + 把 stderr 关键行打出来，**但函数仍返回 0**。
      # ⚠️ `2>&1 >/dev/null` 的**顺序不能反**：先把 stderr 复制到原 stdout（被 `$( )` 捕获）、
      #    再丢掉 stdout ⇒ 只捕获 stderr；反过来写会把 stderr 也丢掉（那正是旧版的病）。
      # ⚠️ 密码走 `--password-stdin`，**绝不回显**：打印的只有 docker 的 stderr 原文。
      _ok="no"; _i=1
      while [ "$_i" -le 3 ]; do
        _err="$(printf '%s\n' "$ACR_PASSWORD" | timeout "${ACR_LOGIN_ATTEMPT_TIMEOUT_SECONDS:-60}" \
                  docker login "$REGISTRY" -u "$ACR_USERNAME" --password-stdin 2>&1 >/dev/null)"
        _rc=$?
        if [ "$_rc" = "0" ]; then _ok="yes"; break; fi
        echo "⚠️ ACR 登录第 ${_i}/3 次失败（${REGISTRY}）："
        printf '%s\n' "$_err" | tail -n 3 | sed 's/^/    /'
        if [ "$_i" -lt 3 ]; then
          if [ "$_i" = "1" ]; then sleep 5; else sleep 10; fi
        fi
        _i=$(( _i + 1 ))
      done
      if [ "$_ok" != "yes" ]; then
        echo "::warning::ACR 登录失败（3 次尝试后仍失败，${REGISTRY}）—— 非致命（C′ 本地构建不需要凭据），但「拉镜像 / 从 ACR 补回回滚点」会跟着失败；下游报「拉取失败」时请先回到这里看读因"
      fi
    fi
  fi
  return 0
}

rollback_tag() { cat "$LAST_GOOD_FILE" 2>/dev/null || true; }

# 本项目全部镜像（`repo:tag` 逐行）；**只列本项目命名空间** ⇒ 非本项目镜像连候选都不是。
project_images() {
  docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null \
    | grep -F "$PROJECT_IMAGE_PREFIX" || true
}

# 本项目某个 tag 的镜像是否**真的在本地**（判据 = `docker image inspect`，不是「有没有容器引用」）
rollback_point_present() {
  local tag=$1 ref
  [ -n "$tag" ] || return 1
  while IFS= read -r ref; do
    [ -n "$ref" ] || continue
    if docker image inspect "$ref" >/dev/null 2>&1; then return 0; fi
  done < <(project_images | grep -E ":$tag\$" || true)
  return 1
}

# 保留集 = 当前 tag + 回滚点 + **除这两者之外**最近 N 个 `sha-*`
# （逐行、可重复：下游按整行匹配去重）。⚠️「最近 N 个」必须**先排除 cur/prev**，否则当前/
# 回滚点会白占配额 ⇒ `KEEP_RECENT_TAGS=2` 实际只剩 0 个额外缓冲（配额被静默吞掉）。
# 取舍：这里用 tag 排序（`sha-*` 的字典序）近似「最近」而非 `docker images` 的创建时间序 ——
# **回滚安全不依赖它**（回滚点由保留集 + 删除循环护栏独立保证），它只是"多留一代"的缓冲 ⇒
# 不值得为精确排序引入额外解析（最少代码）。
retained_tags() {
  local cur=$1 prev=$2 n=$3
  [ -n "$cur" ] && echo "$cur"
  [ -n "$prev" ] && echo "$prev"
  project_images | sed -n 's/.*:\(sha-[A-Za-z0-9._-]*\)$/\1/p' | sort -u \
    | grep -vxF -e "${cur:-__none__}" -e "${prev:-__none__}" | tail -n "$n" || true
  return 0
}

# 按保留策略清理**本项目**的 `sha-*` 旧镜像；非本项目镜像一律不碰。
cleanup_project_images() {
  local cur=$1 prev=$2 keep_file=$3 ref tag removed=0 kept=0
  while IFS= read -r ref; do
    [ -n "$ref" ] || continue
    tag=${ref##*:}
    case "$tag" in sha-*) ;; *) continue ;; esac
    # 🔴 issue #4808 ②「清理前先核回滚点」：回滚点**独立于保留集**永不删。
    # 这一条不看 `$keep_file` ⇒ 即使保留集算错/文件读不到/为空，回滚点也删不掉（fail-closed）。
    if [ -n "$prev" ] && [ "$tag" = "$prev" ]; then
      echo "  🛡️  保留回滚点 ${tag}（#4767 的「失败即回滚」依赖它，独立于保留集）"
      kept=$((kept + 1)); continue
    fi
    if grep -qxF "$tag" "$keep_file"; then kept=$((kept + 1)); continue; fi
    if docker image rm "$ref" >/dev/null 2>&1; then
      echo "  🗑️  删除旧镜像 ${tag}（不在保留集内）"
      removed=$((removed + 1))
    fi
  done < <(project_images)
  echo "  🧹 保留策略：保留 ${kept} 个本项目镜像（当前 ${cur} / 回滚点 ${prev:-无} / 最近 ${KEEP_RECENT_TAGS} 个），删除 ${removed} 个"
  return 0
}

# 回滚点**完整度**：该 tag 下本项目镜像有几个真的在本地（回滚要 3 个服务都在才算「能回滚」）
rollback_point_count() {
  local tag=$1 ref n=0
  [ -n "$tag" ] || { echo 0; return 0; }
  while IFS= read -r ref; do
    [ -n "$ref" ] || continue
    if docker image inspect "$ref" >/dev/null 2>&1; then n=$((n + 1)); fi
  done < <(project_images | grep -E ":$tag\$" || true)
  echo "$n"
  return 0
}

# 回滚点可观测：**部署日志里明确写出来**，缺失/不完整 ⇒ 告警 + 给恢复动作（不静默）
report_rollback_point() {
  local tag n
  tag=$(rollback_tag)
  if [ -z "$tag" ]; then
    echo "  ⚠️ 回滚点：$LAST_GOOD_FILE 为空（本改动上线后的首次部署前是正常的）"
    return 0
  fi
  n=$(rollback_point_count "$tag")
  if [ "$n" -ge 3 ]; then
    echo "  ✅ 回滚点 tag=${tag}：本项目 3/3 个服务镜像都在本地（#4767 的「失败即回滚」可用）"
  elif [ "$n" -gt 0 ]; then
    echo "  ::warning::回滚点 tag=${tag} 只剩 ${n}/3 个服务镜像 ⇒ #4767 的「失败即回滚」**只能回滚部分服务**"
    echo "     恢复：IMAGE_TAG=${tag} docker compose pull admin-api ai-agent admin-web"
  else
    echo "  ::warning::回滚点 tag=${tag} 的镜像**不在本地** ⇒ #4767 的「失败即回滚」**当前不可用**"
    echo "     恢复：docker pull 本项目三个服务的 :${tag}（或重跑一次该 tag 的部署 workflow）"
  fi
  return 0
}


#: 构建缓存回收（**清到门槛以上为止**）。铁律 10 口径：部署内、带阈值、幂等、失败可见。
#: 契约（判据 3/4 机械钉住）：**只发 `docker builder prune`** ⇒ 结构上碰不到镜像 / tag / 回滚点 / 保留集。
#: 副作用（供调用方读）：`CACHE_RECOVER_CANDIDATE`（是否值得清）/ `CACHE_RECOVER_DID`
#: （清了几次：0=没清 / 1=按窗口清 / 2=窗口 + 兜底清空）/ `CACHE_RECOVER_MSG`（人读原因）。
builder_cache_recover() {
  local want=$1 free window cache now_after cap_mb
  free=$(disk_free_mb || true)
  window=$(pick_cache_window "${free:-0}")
  cache=$(builder_cache_measure || true)
  CACHE_RECOVER_CANDIDATE=1
  CACHE_RECOVER_DID=0
  CACHE_RECOVER_MSG=""
  # 读数不可得且缓存为空 ⇒ 没有可清的东西（**明说**，不静默；失败可见）
  if [ "$cache" = "?" ] && [ "$window" != "6" ]; then
    CACHE_RECOVER_CANDIDATE=0
    CACHE_RECOVER_MSG="构建缓存读数不可得、且当前水位不需要兜底清理 ⇒ 跳过缓存回收"
    echo "  ℹ️ 缓存回收：${CACHE_RECOVER_MSG}"
    return 0
  fi
  cap_mb=${BUILD_CACHE_GATE_MB:-1}
  if [ "$cache" != "?" ] && [ "${cache:-0}" -lt "$cap_mb" ] && [ "$window" != "6" ]; then
    CACHE_RECOVER_CANDIDATE=0
    CACHE_RECOVER_MSG="构建缓存仅 ${cache}MB（< ${cap_mb}MB）⇒ 清它也只是徒劳，跳过（缓存读数非空故不是「?」）"
    echo "  ℹ️ 缓存回收：${CACHE_RECOVER_MSG}"
    return 0
  fi
  # ── 第 1 档：按水位选的窗口（真机上 168h 是空操作 ⇒ 所以窗口由 `pick_cache_window` 给）──────
  # 🔴 `RECOVER_TIER_1=1` 是**档位标记**（判据的锚点：证明这一档真的落码、不是只写在注释里）。
  RECOVER_TIER_1=1
  echo "  🧹 缓存回收：水位 ${free}MB ⇒ 选窗口 ${window}h（可用量经门槛 ${want}MB 判定；此档保留比 ${window}h 更新的层）"
  if docker builder prune -f --filter "until=${window}h" >/dev/null 2>&1; then
    CACHE_RECOVER_DID=1
  else
    echo "  ⚠️ docker builder prune --filter until=${window}h 失败（不影响本次部署；下面仍会复核水位）"
  fi
  now_after=$(disk_free_mb || true)
  # ── 第 2 档（兜底）：窗口清完仍不足门槛 ⇒ 清空构建缓存 ─────────────────────────────────
  # ⚠️ 这一档会把稳态 2s 打回冷构建 29.7min ⇒ **只在「不腾空间就部署不下去」时**才走到
  #    （水位已经低于门槛，即下面这个 `-lt` 为真）；正常路径永远不会碰到它。
  if [ "${now_after:-0}" -lt "$want" ]; then
    RECOVER_TIER_2=1
    echo "  🔴 窗口 ${window}h 清完仍不足门槛（${now_after}MB < ${want}MB）⇒ 兜底档：清空构建缓存（代价 = 下一次是冷构建）"
    CACHE_RECOVER_AF_CALL=1
    if docker builder prune -af >/dev/null 2>&1; then
      CACHE_RECOVER_DID=2
    else
      echo "  ⚠️ docker builder prune -af 失败（不影响本次部署；水位复核在下面）"
    fi
  fi
  return 0
}

CONFIG_REF_RESOLVED=$(config_ref_for_tag "$TAG")
if [ -z "$CONFIG_REF_RESOLVED" ]; then
  echo "❌ 无法把镜像 tag 追溯到具体 commit（tag=${TAG}）⇒ **拒绝用 main 的配置**（issue #5083）"
  echo "   配置（compose/nginx）必须与镜像**同一 commit**：否则回滚时是「旧镜像 + 新配置」（未定义行为、且不报错）"
  echo "   修法：改用 \`sha-<7位hex>\` 形态的 tag（= CI 部署的正常形态）"
  exit 1
fi

# ══════════════════════════════════════════════════════════════════════════
# 1.0.1 **发布线自检**（issue #9086）：手工敲 deploy.sh 也不许绕过「部署只认 release」
#
# 病根（**2026-11-23 生产实测**，人工路径）：上面第 0 段只保证「配置 ref 与镜像 tag **同源**」，
#   **不判断这个 tag 属不属于 `release`**。而发布线闸门此前只有一处：`deploy-prod.yml` 的
#   「发布线纪律（只认 release）」步骤（判据 = test_deploy_prod_release_discipline.py）
#   ⇒ 有人在主机上直接敲 `./deploy.sh sha-xxxxxxx` 就**完全绕过**它。2026-11-23 11:32–11:39
#   实测那次正是如此：只更新了 admin-api，admin-web 还是两天前的镜像（**发成半截**），
#   全程零报错 —— 脚本自己的结论是绿的。
# 口径（= AGENTS.md「发布线」一节；机械可查）：目标 commit 必须是 `origin/release` 的**祖先**。
#   否则「生产跑的代码在发布线上找不到」⇒ 回滚点 / `/api/version` 自证 / 发布记录三处同时失效。
# 位置**必须在这里**（已解析出 `$TAG` 与目标 commit，任何下载 / 构建 / 拉镜像 / 切流之前）：
#   检查晚于部署 = 没检查（那时容器已被换掉，日志里那句「拦住了」是假的）。
#   顺序判据 = tests/unit_ci_workflows/test_swas_deploy_release_line.py（行号比较）。
# 三态（**判不了也拒绝**，fail-closed —— 与 2.05 那条 #4852 闸门的 fail-open **有意不同**：
#   那条判的是「往不往回走」（判不了可以放行），这条判的是「该不该发」，判不了放行 = 闸门消失）：
#   祖先   ⇒ 打印 `RELEASE-LINE=OK target=<sha7> release=<sha7>` 后继续；
#   非祖先 ⇒ 打印两个 sha + 差多少提交 + 可行动指引，**exit 2**；
#   判不了 ⇒ **exit 3**（不是 git 仓 / fetch 三次都失败 / 拿不到 release ref / 追不到 target commit）。
#   ⚠️ 逃生口留在**明面上**：`ALLOW_UNVERIFIABLE_RELEASE=1`（或 `--allow-unverified-release`）⇒
#      `::warning::RELEASE-LINE=UNVERIFIED …` + 追加一行到 `release-ledger.jsonl` 后继续。
#      为什么必须有：生产机到 github.com:443 时通时不通（#4852 实测 `git clone --filter=tree:0`
#      超时 32s，而同一刻 `git ls-remote` 成功），**没有逃生口的 fail-closed 会被绕成「把这段删掉」**；
#      有逃生口 + 落账 ⇒ 绕过是**可见的**（谁在什么时候绕的，台账里有）。
# 🔴 段内**自包含**（不依赖第 0 段的 `tag_to_sha`：那条只验形态、不解析提交；这里要的是**提交图**）
#    ⇒ 判据可以只抽这一段字节、配桩化的 `git` 真跑，**不需要给脚本加测试专用钩子**。
# >>> release-line-assert
RELEASE_LINE_GIT_DIR=${RELEASE_LINE_GIT_DIR:-/opt/migao-deploy/.release-line.git}
RELEASE_LINE_REMOTE=${RELEASE_LINE_REMOTE:-https://github.com/zhaokai-mgzn/migao}
RELEASE_LINE_FETCH_ATTEMPTS=${RELEASE_LINE_FETCH_ATTEMPTS:-3}
RELEASE_LINE_FETCH_DELAY_SECONDS=${RELEASE_LINE_FETCH_DELAY_SECONDS:-5}
# 逃生口台账（**只在**走逃生口时追加一行；正常部署不写盘）
RELEASE_LEDGER_FILE=${RELEASE_LEDGER_FILE:-/opt/migao-deploy/release-ledger.jsonl}
RELEASE_LINE_TARGET=""
RELEASE_LINE_HEAD=""
RELEASE_LINE_WHY=""

# 所有 git 调用都打在**发布线专用的裸仓库**里：`/opt/migao-deploy` 本身**不是** git 仓
# （盘上是解包出来的源码树 `src/`，没有 `.git`）⇒ 不能指望 `git -C .` 能查到历史。
rl_git() { git --git-dir="$RELEASE_LINE_GIT_DIR" "$@"; }

# 取远端 ref 的**唯一形态**（三处调用共用 ⇒ 形态不会漂移）：
#   `GIT_TERMINAL_PROMPT=0` —— 生产机没有交互终端凭据，**缺了它就可能在 https 认证提示上永久挂住**
#     （挂住比失败更坏：部署锁被占着，别的部署只能等到 `LOCK_WAIT_SECONDS` 超时）；
#   `http.lowSpeedTime=60 / http.lowSpeedLimit=1000` —— 速率低于 1KB/s 持续 60s 就放弃本轮
#     （与脚本既有的「**不许无上界地挂住**」同族：`BUILD_TIMEOUT_SECS` 那段的口径）；
#   `--filter=tree:0` —— 只取**提交图**（merge-base 只看提交）。
rl_git_fetch() {
  GIT_TERMINAL_PROMPT=0 rl_git -c http.lowSpeedTime=60 -c http.lowSpeedLimit=1000 \
    fetch --quiet --force --no-tags --filter=tree:0 "$@"
}

# 建（一次性）发布线判据用的裸仓库。建不出来 ⇒ 判不了（fail-closed，原因具名）。
rl_ensure_repo() {
  [ -d "$RELEASE_LINE_GIT_DIR" ] && return 0
  if git init --quiet --bare "$RELEASE_LINE_GIT_DIR" >/dev/null 2>&1; then
    return 0
  fi
  RELEASE_LINE_WHY="建不出判据用的裸仓库（${RELEASE_LINE_GIT_DIR} 写不进去 / git 不可用）"
  return 1
}

# 取 `origin/release`：**显式重试 + 每轮出声**（沿用第 0 段 `config_fetch_tarball` 的既有风格：
# 事故里「参数面写了重试、到底有没有触发没人知道」本身就是病的一部分）。
# `--filter=tree:0` 只取**提交图**（merge-base 只看提交）⇒ 不拉 blob/tree：生产机磁盘
# （本脚本有水位阈值）+ 带宽都按最小量走；GitHub 支持 partial clone。
rl_fetch_release() {
  local try=0 rc=0
  while [ "$try" -lt "$RELEASE_LINE_FETCH_ATTEMPTS" ]; do
    try=$((try + 1))
    echo "  ⏱ 第 ${try}/${RELEASE_LINE_FETCH_ATTEMPTS} 次取 origin/release（只取提交图，--filter=tree:0）"
    if rl_git_fetch "$RELEASE_LINE_REMOTE" '+refs/heads/release:refs/remotes/origin/release' >/dev/null 2>&1; then
      return 0
    else
      rc=$?
    fi
    if [ "$try" -lt "$RELEASE_LINE_FETCH_ATTEMPTS" ]; then
      echo "  ⚠️ 第 ${try}/${RELEASE_LINE_FETCH_ATTEMPTS} 次取 origin/release 失败（git exit=${rc}）⇒ **马上重试（第 $((try + 1)) 轮）**（${RELEASE_LINE_FETCH_DELAY_SECONDS}s 后）"
      sleep "$RELEASE_LINE_FETCH_DELAY_SECONDS"
    else
      echo "  ⚠️ 第 ${try}/${RELEASE_LINE_FETCH_ATTEMPTS} 次取 origin/release 失败（git exit=${rc}）⇒ 重试预算用尽"
    fi
  done
  RELEASE_LINE_WHY="git fetch 连续 ${RELEASE_LINE_FETCH_ATTEMPTS} 次失败（${RELEASE_LINE_REMOTE} 不可达 / 无凭据）"
  return 1
}

# 解析 target（本次要部署的那个提交）：
#   `sha-<hex>`（≥7 位）⇒ 该提交；不在本地历史里 ⇒ **按 sha 补取一次**（GitHub 允许按 sha 取）；
#   其它形态（v1.2.3 / 非十六进制的 `sha-xxx` 这类）⇒ `refs/tags/<tag>`
#   —— **与第 0 段 `config_ref_for_tag` 同一口径**（配置那边已经把这类 tag 当 tag 解析，
#   这里若另立口径，同一个 tag 会在两处指向不同对象）。
# ⚠️ 取不到就**判不了**（不猜、不用字符串前缀凑）：短 sha 撞号与「提交不在 history 里」都不可当祖先。
rl_resolve_target() {
  local t=$1 short sha
  case "$t" in
    sha-*) short=${t#sha-} ;;
    *) short="" ;;
  esac
  case "$short" in
    *[!0-9a-f]*|"") short="" ;;
  esac
  if [ -n "$short" ] && [ "${#short}" -ge 7 ]; then
    sha=$(rl_git rev-parse --verify --quiet "${short}^{commit}" 2>/dev/null || true)
    if [ -z "$sha" ]; then
      rl_git_fetch "$RELEASE_LINE_REMOTE" "$short" >/dev/null 2>&1 || true
      sha=$(rl_git rev-parse --verify --quiet "${short}^{commit}" 2>/dev/null || true)
    fi
    if [ -z "$sha" ]; then
      RELEASE_LINE_WHY="追不到 tag=${t} 指向的提交（该 sha 不在 release 历史里，按 sha 补取也失败）"
      return 1
    fi
    RELEASE_LINE_TARGET=$sha
    return 0
  fi
  rl_git_fetch "$RELEASE_LINE_REMOTE" "+refs/tags/${t}:refs/tags/${t}" >/dev/null 2>&1 || true
  sha=$(rl_git rev-parse --verify --quiet "refs/tags/${t}^{commit}" 2>/dev/null || true)
  if [ -z "$sha" ]; then
    RELEASE_LINE_WHY="追不到 tag=${t} 指向的提交（仓库上没有这个 tag / 取不到）"
    return 1
  fi
  RELEASE_LINE_TARGET=$sha
  return 0
}

RELEASE_LINE_VERDICT=unverified
if rl_ensure_repo && rl_fetch_release; then
  RELEASE_LINE_HEAD=$(rl_git rev-parse --verify --quiet 'refs/remotes/origin/release^{commit}' 2>/dev/null || true)
  if [ -z "$RELEASE_LINE_HEAD" ]; then
    RELEASE_LINE_WHY="取不到 origin/release 的 ref（fetch 报成功但 rev-parse 为空）"
  elif rl_resolve_target "$TAG"; then
    if rl_git merge-base --is-ancestor "$RELEASE_LINE_TARGET" 'refs/remotes/origin/release'; then
      RELEASE_LINE_VERDICT=ancestor
    else
      _rl_rc=$?
      if [ "$_rl_rc" = "1" ]; then
        RELEASE_LINE_VERDICT=not-ancestor
      else
        RELEASE_LINE_WHY="git merge-base --is-ancestor 说不清（git exit=${_rl_rc}）"
      fi
    fi
  fi
fi

case "$RELEASE_LINE_VERDICT" in
  ancestor)
    echo "  ✅ RELEASE-LINE=OK target=${RELEASE_LINE_TARGET:0:7} release=${RELEASE_LINE_HEAD:0:7}（目标 commit 是 origin/release 的祖先）"
    ;;
  not-ancestor)
    _rl_ahead=$(rl_git rev-list --count 'refs/remotes/origin/release..'"$RELEASE_LINE_TARGET" 2>/dev/null || true)
    echo "  ❌ RELEASE-LINE=VIOLATION ⇒ **拒绝部署**（issue #9086）"
    echo "     · target  = ${RELEASE_LINE_TARGET}（本次要部署的提交）"
    echo "     · release = ${RELEASE_LINE_HEAD}（origin/release 的当前提交）"
    echo "     · 差 ${_rl_ahead:-?} 个提交（可复算：git rev-list --count origin/release..target）"
    echo "     · 为什么拦：「生产跑的代码在发布线上找不到」⇒ 回滚点 / /api/version 自证 / 发布记录同时失效"
    echo "     · 处置：先在任意工作区跑 ./scripts/cut-release.sh 把 release **快进**到该提交（它只允许快进，"
    echo "       并打出 REL_SHA=<40位>），再用那个 REL_SHA 部署（CI 走 prod-release；主机手工跑也用 REL_SHA）。"
    exit 2
    ;;
  *)
    if [ "${ALLOW_UNVERIFIABLE_RELEASE:-0}" = "1" ]; then
      echo "  ::warning::RELEASE-LINE=UNVERIFIED 判不了发布线归属，但**已显式放行**（ALLOW_UNVERIFIABLE_RELEASE=1）"
      echo "     · 原因：${RELEASE_LINE_WHY:-未知}"
      echo "     · target=${RELEASE_LINE_TARGET:-<未解析>} release=${RELEASE_LINE_HEAD:-<未取到>}"
      _rl_ledger=$(_rl_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
        printf '{"at":"%s","decision":"unverified-release","target":"%s","reason":"%s"}' \
          "$_rl_at" "${TAG:-}" "${RELEASE_LINE_WHY:-unknown}")
      if printf '%s\n' "$_rl_ledger" >> "$RELEASE_LEDGER_FILE" 2>/dev/null; then
        echo "     · 已记账：${RELEASE_LEDGER_FILE}（decision=unverified-release，谁绕过都留痕）"
      else
        echo "  ::warning::RELEASE-LINE=UNVERIFIED 的台账写不进去（${RELEASE_LEDGER_FILE}）⇒ 本次绕过**没有留痕**，请人工补记"
      fi
    else
      echo "  ❌ RELEASE-LINE=UNVERIFIED ⇒ **拒绝部署**（fail-closed，issue #9086）"
      echo "     · 原因：${RELEASE_LINE_WHY:-未知}"
      echo "     · target=${RELEASE_LINE_TARGET:-<未解析>} release=${RELEASE_LINE_HEAD:-<未取到>}"
      echo "     · 处置：① 到 github.com 不通 ⇒ 修网络/凭据后重跑（本段已重试 ${RELEASE_LINE_FETCH_ATTEMPTS} 次）；"
      echo "       ② tag 不是 sha-<7位hex> ⇒ 改用 CI 给的 sha tag；"
      echo "       ③ **确认本次就该发**、且判据确实取不到 ⇒ 显式带逃生口重跑："
      echo "          ALLOW_UNVERIFIABLE_RELEASE=1 ./deploy.sh ${TAG}（会打 ::warning:: 并记 ${RELEASE_LEDGER_FILE}）"
      exit 3
    fi
    ;;
esac
# <<< release-line-assert

# 本腿那个服务的**本地镜像 ref**（唯一一份推导，issue #5814）：让 compose 自己求值，不在脚本里重抄
# `${ACR_REGISTRY}/ai-customer-service/<svc>:${IMAGE_TAG}`（后者会在有人改 compose 时**静默漂移**）。
# 两个消费点：1.4 的构建，以及 #6551 ② 的「源码树不在盘上 ⇒ 能否改用本地已有的镜像」。
# ⚠️ `|| true`：本脚本是 `set -euo pipefail` ⇒ 命令替换里任一环失败会**当场静默退出**
#    （连调用点那句 ❌ 都打不出来）⇒ 显式吞掉非零，交由调用点的 `-z` 判定给出可行动报错。
local_image_ref_of() {
  local svc=$1
  docker compose config --format json 2>/dev/null \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["services"][sys.argv[1]].get("image",""))' "$svc" 2>/dev/null || true
}
echo "== 1. 同步 repo 内 canonical compose + nginx 配置（ref=${CONFIG_REF_RESOLVED}，与镜像 tag=${TAG} 同源）=="
# ⚠️ 这一段是「配置与镜像同源」的**唯一**落点（issue #5083）：URL 的 ref 来自 `$CONFIG_REF_RESOLVED`，
#    它由 `config_ref_for_tag "$TAG"` 推导 ⇒ 脚本里**不存在**「无条件取 main 配置」的路径。
#
# ── 整体超时预算 120s → 900s（issue #6550：测试环境三条部署腿全线失败）──────────────────────
# **为什么是 900s**（把实测速率算进去，不是拍脑袋）：四次失败 run 的远端逐字读数为
#   服务器→codeload **118~345 KB/s**（03:42Z ~217、04:06Z ~118、04:31Z ~201、04:56Z ~345），
#   而整仓 tar.gz **66.5MB** ⇒ 需要 **565s(118KB/s) ~ 193s(345KB/s)**；
#   120s 上限下**一次都没下完**（最好的一次 41.4MB/66.57MB，`curl: (28) … out of 66570829 bytes received`）
#   ⇒ 部署中止，**连回滚腿也失败**（回滚同样要下这份归档）。
#   900s 对实测最慢速率（565s）有 **1.6× 余量**，且必须 **< CI 侧单次尝试预算 4500s**
#   （deploy/scripts/swas-deploy-ci.sh::C_BUILD_DEPLOY_TIMEOUT_SECONDS = 锁等待上界 1800 + 冷构建上界 2400 + 余量 300）。
#   `--max-time` 是**每一次**尝试（含 `--retry` 的重试）的预算 ⇒ 病态最坏 3×900s+2×5s=2710s，仍在 4500s 之内。
#   **佐证「瓶颈是 120s 上限、不是带宽不可用」**：同一份 66MB 在 bootstrap 段
#   （deploy/scripts/swas-deploy-ci.sh::BOOTSTRAP，**不带 `--max-time`**）**实测下载成功** ——
#   否则 `deploy.sh` 根本不会被执行、也就不会有下面这条报错。
#
# ⚠️ **为什么不加 `-C -` 断点续传**（issue #6550 方向 1 曾建议加；实测**不可行且有害**，**勿再引入**）：
#   ① **codeload 不支持 Range**（本机实测 2026-10-08：`curl -r 0-1023 <tarball>` ⇒ **HTTP 200** + 整份 body
#      流式返回，响应头**没有** `content-range` / `accept-ranges`）；
#   ② 一旦本地留下半份 `src.tar.gz`，`-C -` 会发 `Range:`，服务器回 200 ⇒ curl **exit 33**
#      「HTTP server doesn't seem to support byte ranges. Cannot resume.」（本地桩实测：文件停在 204800 字节、
#      第二/第三次调用均 rc=33、**零进展**）；
#      而**半份文件确实会留下**：非 C′ 路径（`BUILD_SERVICE` 为空）不会执行末尾那句 `rm -rf src src.tar.gz`
#      （那句在 `if [ -n "$BUILD_SERVICE" ]` 之内）⇒ 加了 `-C -` 等于让**下一次部署**在 exit 33 上秒失败，
#      把「慢」换成「永久卡死」（要人工删文件才恢复）。
#   ③ curl 自己的 `--retry` **也不续传**：实测三次请求都不带 `Range`、且半份文件被截断回原尺寸
#      （⇒ 重试仍从 0 重下，但**不会**写出「前后拼接」的坏包）⇒ 正确姿势是让**单次尝试**在预算内下完，
#      而不是指望重试累积进度。本次修复即如此。
CONFIG_ON_DISK_REF=$(cat "$CONFIG_REF_MARKER_FILE" 2>/dev/null || true)
CONFIG_REUSED=0
if config_reuse_on_disk; then
  CONFIG_REUSED=1
  # ── 本腿还要构建吗（issue #6551 ②）──────────────────────────────────────────
  # C′ 形态下 `src/` 是**构建上下文**，而 #5814 在构建成功后按磁盘策略把它删掉（实测常驻 ~84MB）
  # ⇒ 回滚到「上一次成功部署」那个 tag 时，盘上**有配置、没有源码树**。此时若本地已有该 tag 的镜像
  # （回滚点镜像由第 0 段的保留策略保证在本地）⇒ **无物可建** ⇒ 直接用本地镜像：不下载、不构建。
  # 判据只认「同名 tag 的镜像确实在本地」；不在本地 ⇒ 照旧取源码树（fail-closed，不静默降级）。
  _bctx=$(service_context_of "$BUILD_SERVICE")
  if [ -n "$BUILD_SERVICE" ] && [ -n "$_bctx" ] && [ ! -f "src/$_bctx/Dockerfile" ]; then
    export IMAGE_TAG="$TAG"
    _reuse_img_ref=$(local_image_ref_of "$_svc")
    if [ -n "$_reuse_img_ref" ] && docker image inspect "$_reuse_img_ref" >/dev/null 2>&1; then
      LOCAL_IMAGE_REF="$_reuse_img_ref"
      echo "  ♻️ 源码树不在盘上（C′ 构建成功后按磁盘策略删除），但本地已有该 tag 的镜像（${LOCAL_IMAGE_REF}）⇒ **跳过服务器侧构建**（也就不需要源码树）"
    else
      CONFIG_REUSED=0
      echo "  ℹ️ 源码树不在盘上，且本地没有该 tag 的镜像 ⇒ 仍需取源码树（照旧下载，fail-closed 不变）"
    fi
  fi
fi
if [ "$CONFIG_REUSED" = "1" ]; then
  echo "  ♻️ 现盘配置就是 ref=${CONFIG_REF_RESOLVED} 那份（标记 ${CONFIG_REF_MARKER_FILE}）⇒ **跳过整仓下载**"
  echo "     （issue #6551 ②：下载故障不再同时夺走「前进」与「后退」；复用只认 ref 相同 ⇒ 同源护栏不变）"
else
  # 一旦走下载路径，先废掉「物化 ref」标记（它只在**整段同步成功**之后才重写）⇒ 复用判据永不基于
  # 「上一次跑到一半」的盘面（例如解包失败留下的半棵树）：fail-closed。
  rm -f "$CONFIG_REF_MARKER_FILE"
  if config_fetch_tarball; then
    echo "  ✅ 配置包已取到（ref=${CONFIG_REF_RESOLVED}，${CONFIG_TARBALL_BYTES} 字节）"
  else
    echo "  ❌ 取不到 tag=${TAG} 对应的配置（ref=${CONFIG_REF_RESOLVED}）⇒ **中止部署**（绝不回落到 main 的配置）"
    echo "     · 若 tag 是 latest 这类**移动 tag**（追不到具体 commit）⇒ 改用 sha-<7位hex> 形态的 tag"
    echo "     · 否则核对：该 commit/tag 在 zhaokai-mgzn/migao 上存在且可达"
    exit 1
  fi
  rm -rf src && mkdir -p src
  if ! tar xzf src.tar.gz -C src --strip-components=1; then
    echo "  ❌ ref=${CONFIG_REF_RESOLVED} 的源码包**解不开**（下载不完整 / 不是 gzip tar）⇒ **中止部署**"
    echo "     · 残包**不被信任**，也不会去下第二份凑数：删掉 src.tar.gz 后重跑即可"
    exit 1
  fi
  # 包内容自检（fail-closed）：旧 commit（早于 #4785）没有蓝绿 override，被劫持的 200 响应也不是仓库树
  # ⇒ 一律**中止**，绝不「main 的同名文件补上」（那正是本单要修的「旧镜像 + 新配置」）。
  if [ ! -f src/deploy/swas/docker-compose.yml ] || [ ! -f src/deploy/swas/nginx.conf ] \
     || [ ! -f src/deploy/swas/docker-compose.bluegreen.yml ]; then
    echo "  ❌ ref=${CONFIG_REF_RESOLVED} 的源码包里找不到 canonical 配置（deploy/swas/docker-compose.yml|nginx.conf|docker-compose.bluegreen.yml）"
    echo "     · 该 commit 早于 #4785（没有蓝绿 override）⇒ 回滚到它需要配套更早的部署脚本"
    echo "     · 若整包都不是 migao 仓库树 ⇒ 核对 $CONFIG_TARBALL_BASE 与网络（代理/门户劫持）"
    exit 1
  fi
  mkdir -p nginx certbot-www
  cp src/deploy/swas/docker-compose.yml ./docker-compose.yml
  # nginx.conf 的**原文**（渲染输入；容器挂的是下面渲染出来的 `nginx.conf`）
  cp src/deploy/swas/nginx.conf ./nginx/nginx.conf.canonical
  # 蓝绿 override（issue #4785）：**只新增** green 探针服务，不改既有服务定义
  cp src/deploy/swas/docker-compose.bluegreen.yml ./docker-compose.bluegreen.yml
  # TLS 自动续期脚本（issue #8201）：与配置同批落盘，供宿主 cron（/etc/cron.d/migao-tls-renew）调用。
  # ⚠️ 存在性守卫不是修饰：回滚到本单之前的 tag 时 tarball 里**没有**这个文件，
  #    无条件 `cp` 会让**回滚部署**当场 abort（本脚本 set -e）。
  if [ -f src/deploy/scripts/tls-renew.sh ]; then
    cp src/deploy/scripts/tls-renew.sh ./tls-renew.sh
    chmod +x ./tls-renew.sh
  fi
  # 记下「盘上这套配置物化自哪个 ref」（#6551 ②）：下次目标 ref 相同（含**回滚回同一 tag**）
  # ⇒ 直接复用、不再下一次 66.5MB 整仓。三份文件**都落到盘上之后**才写标记 ⇒ 标记不会先于配置落地。
  printf '%s\n' "$CONFIG_REF_RESOLVED" > "$CONFIG_REF_MARKER_FILE"
fi

# ── 1.2.1 部署脚本**自同步**（issue #8966）────────────────────────────────────
# 病根（**2026-11-21 生产实测**）：上面那段只同步 compose / nginx / tls-renew.sh，**不同步 deploy.sh 自己**
# ⇒ 盘上脚本一旦落后于 target ref 就**永远停在旧版**（没有任何东西会更新它）：旧版不读 `.env.site`、
# 不认识 `NEXT_PUBLIC_SITE_DOMAIN` ⇒ 它按**自己的旧逻辑**把 nginx 渲染回 canonical 原文（`migaozn.com`）
# 并少传一个 build-arg，全程**零报错**（日志只有一行「站点域名：migaozn.com」）⇒ 所有 `cytda.com`
# 请求落到 default server 被代理到 API ⇒ **全站 401**。
# 同源：`src/` 就是本次 target ref（`$CONFIG_REF_RESOLVED`）的仓库树 ⇒ 装上去的脚本与镜像 tag 同源。
# 幂等：内容相同 ⇒ 不覆盖、不备份、不产生任何新文件（连跑两次盘面逐字节一致）。
# ⚠️ 覆盖的是**正在运行的这个脚本文件** ⇒ 用「写临时文件 + `cat >` 原地覆盖」**保 inode**；
#    绝不用 `mv`（换 inode，某些挂载/执行场景会读到半截）。
# ⚠️ 覆盖完必须**当场停住**，不许接着往下跑：bash 是**按字节偏移**从同一个 fd 续读脚本的 ⇒
#    原地换掉内容后继续执行，读到的是**错位**的下一段（本机实测：覆盖后下一条命令变成
#    `p: command not found`）⇒ 那就是「半截执行」，比停在原地更坏。
#    ⇒ 覆盖后 `exit 1`，**不落任何派生配置**（nginx.conf 还没渲染、容器一个都没动）；
#      下一次（CI 的自动重试 / 人工复跑）执行的就是同源脚本，幂等、不再备份/覆盖。
#      CI 的 bootstrap 本来就先装同源脚本再执行（`swas-deploy-ci.sh`）⇒ 正常路径走不到这里。
# >>> deploy-selfsync
MIGAO_DEPLOY_SRC_FILE=${MIGAO_DEPLOY_SRC_FILE:-src/deploy/swas/deploy.sh}
MIGAO_DEPLOY_SELF=${MIGAO_DEPLOY_SELF:-./deploy.sh}
if [ ! -f "$MIGAO_DEPLOY_SRC_FILE" ]; then
  echo "  ⏭️ 跳过 deploy.sh 自同步：盘上没有 ${MIGAO_DEPLOY_SRC_FILE}（本次未取源码树 / 同 ref 复用配置）—— **部署不受影响**；盘上脚本保持现版本（issue #8966）"
elif [ ! -f "$MIGAO_DEPLOY_SELF" ]; then
  echo "  ⏭️ 跳过 deploy.sh 自同步：找不到盘上脚本 ${MIGAO_DEPLOY_SELF} —— **部署不受影响**（issue #8966）"
else
  _self_src_sha=$(sha256sum "$MIGAO_DEPLOY_SRC_FILE" 2>/dev/null | cut -d' ' -f1 || shasum -a 256 "$MIGAO_DEPLOY_SRC_FILE" | cut -d' ' -f1)
  _self_dst_sha=$(sha256sum "$MIGAO_DEPLOY_SELF" 2>/dev/null | cut -d' ' -f1 || shasum -a 256 "$MIGAO_DEPLOY_SELF" | cut -d' ' -f1)
  if [ -z "$_self_src_sha" ] || [ -z "$_self_dst_sha" ]; then
    # 两侧 sha 算不出来 ⇒ **不可判定**：不覆盖（否则每次都会「不同」⇒ 每次都备份 + 每次都 exit 1 的循环）
    echo "  ⏭️ 跳过 deploy.sh 自同步：算不出 sha256（src=${_self_src_sha:-?} / 盘上=${_self_dst_sha:-?}）—— **部署不受影响**（issue #8966）"
  elif [ "$_self_src_sha" = "$_self_dst_sha" ]; then
    echo "  ✅ deploy.sh 与 ref=${CONFIG_REF_RESOLVED} 同源（sha256=${_self_src_sha:0:8}）⇒ 不覆盖、不备份"
  else
    _self_bak="${MIGAO_DEPLOY_SELF}.bak-$(date +%Y%m%d-%H%M%S)"
    _self_tmp=$(mktemp "${TMPDIR:-/tmp}/migao-deploy-self.XXXXXX")
    cp -p "$MIGAO_DEPLOY_SELF" "$_self_bak"
    cat "$MIGAO_DEPLOY_SRC_FILE" > "$_self_tmp"
    # 🔴 原地覆盖（保 inode）：`cat >` 复用同一个文件；**不**用 `mv`（换 inode）
    cat "$_self_tmp" > "$MIGAO_DEPLOY_SELF"
    rm -f "$_self_tmp"
    chmod +x "$MIGAO_DEPLOY_SELF"
    echo "  🔄 deploy.sh 自同步（ref=${CONFIG_REF_RESOLVED}）：sha256 ${_self_dst_sha:0:8} → ${_self_src_sha:0:8}；旧版备份 $(basename "$_self_bak")"
    # 覆盖后**不许**在本进程里接着往下读（bash 按字节偏移续读同一个 fd ⇒ 会读到错位的下一段）。
    # 旧做法 = `exit 1` 让调用方「再跑一次」（issue #8966）；代价是**单次部署必然空跑一次**
    # —— 2026-11-22 实测：三次人工部署全部要靠「再跑一次」才生效，容易被误读成部署失败。
    # 新做法 = **exec 原地重入**：同一 PID 换成同源脚本从头执行，一次调用就完成部署；
    # 锁在重入时会重新 open fd 9（旧 fd 关闭即释放），不会自锁。
    # 防环：哨兵置位后再遇到「不同源」⇒ 说明源与盘上 sha 在自我漂移 ⇒ fail-closed 停住。
    if [ "${MIGAO_DEPLOY_SELF_REEXEC:-0}" = "1" ]; then
      echo "  ⛔ 自同步后**仍不同源**（src=${_self_src_sha:0:8} / 盘上=${_self_dst_sha:0:8}）⇒ 重入保护触发，停在这里："
      echo "     nginx.conf 未渲染、容器未动、回滚点未推进。处置：核对 ${MIGAO_DEPLOY_SRC_FILE} 是否在两次读取之间被改写。"
      exit 1
    fi
    export MIGAO_DEPLOY_SELF_REEXEC=1
    echo "  ↗️ 以同源脚本**原地重入**（exec，同一 PID）—— 单次调用即可完成本次部署，无需再跑一次"
    exec bash "$MIGAO_DEPLOY_SELF" "$@"
  fi
fi
# <<< deploy-selfsync

# ── 1.2.2 站点域名渲染（生产 cytda.com；缺省 migaozn.com ⇒ 与改前逐字相同）──────────────
# 输入永远是 `nginx.conf.canonical`（仓库原文），所以「域名变更」和「配置复用」都不会把
# 上一轮渲染过的产物再渲染一遍（那是幂等的，但更重要的是它不会让 A→B 改名悄悄失效）。
if [ ! -f ./nginx/nginx.conf.canonical ] && [ -f ./nginx/nginx.conf ]; then
  # 旧版本机器上只有渲染前落盘的 nginx.conf（第一版部署脚本没有 canonical 概念）。
  # 默认域名口径下它与仓库原文逐字相同 ⇒ 直接升格为 canonical，不重新下载整仓。
  cp -f ./nginx/nginx.conf ./nginx/nginx.conf.canonical
  echo "  ℹ️ 盘上没有 nginx.conf.canonical（旧版本升级）⇒ 以现有 nginx.conf 作为渲染输入"
fi
if [ ! -f ./nginx/nginx.conf.canonical ]; then
  echo "  ❌ 既没有 nginx.conf.canonical 也没有 nginx.conf —— 无法渲染站点域名 ⇒ **中止部署**"
  exit 1
fi
if [ "$MIGAO_PUBLIC_DOMAIN" = "migaozn.com" ]; then
  # 测试环境：纯拷贝，不跑 sed ⇒ 产物与改前逐字相同（含注释里的域名）
  cp -f ./nginx/nginx.conf.canonical ./nginx/nginx.conf
else
  # `migaozn.com` 在文件里只作为**域名**出现（`migao` / `migao-deploy` 等不含该串）⇒ 全局替换安全；
  # server_name / 注释 / 日志格式内的域名引用一次性对齐，避免出现「配置说 A、注释说 B」。
  sed "s/migaozn\.com/${MIGAO_PUBLIC_DOMAIN}/g" ./nginx/nginx.conf.canonical > ./nginx/nginx.conf.render.tmp
  mv -f ./nginx/nginx.conf.render.tmp ./nginx/nginx.conf
fi
_conf_sha=$(sha256sum ./nginx/nginx.conf 2>/dev/null | cut -d' ' -f1 || shasum -a 256 ./nginx/nginx.conf | cut -d' ' -f1)
echo "  站点域名：${MIGAO_PUBLIC_DOMAIN}（nginx.conf sha256=${_conf_sha:-unknown}）"
grep -E '^[[:space:]]*server_name[[:space:]]' ./nginx/nginx.conf | sed 's/^/    /' || true

# ── 1.2.3 渲染后 **fail-closed 断言**（issue #8966）──────────────────────────────
# 改前这里只打印一行「站点域名：…」就继续 ⇒ 那一行打的是**期望值**，与盘上配置的真实内容无关：
# 只要渲染输入或替换规则错了（旧脚本的「纯 cp canonical」分支正是），日志照样好看，而 nginx 里
# `server_name` 一个生产域名都没有 ⇒ 所有生产域请求落到 default server（实测形态 = 被代理到 API
# ⇒ **全站 401**）。⇒ 断言对象必须是**渲染产物本身**，不是变量、不是意图。
# 判据：`server_name` 里至少出现一处 `$MIGAO_PUBLIC_DOMAIN`（6 个面里任一命中即可；0 处 = 静默失效）。
# >>> nginx-domain-assert
_ngx_server_names=$(grep -E '^[[:space:]]*server_name[[:space:]]' ./nginx/nginx.conf || true)
if ! grep -qF "$MIGAO_PUBLIC_DOMAIN" <<<"$_ngx_server_names"; then
  echo "  ❌ nginx.conf 渲染后 \`server_name\` 里**没有**站点域名 ${MIGAO_PUBLIC_DOMAIN} ⇒ **中止部署**（issue #8966）"
  echo "     当前 server_name 清单（渲染产物 ./nginx/nginx.conf）："
  printf '%s\n' "${_ngx_server_names:-<空：一行 server_name 都没有>}" | sed 's/^/       /'
  echo "     后果：${MIGAO_PUBLIC_DOMAIN} 的请求会全部落到 default server（实测 = 被代理到 API ⇒ 全站 401）"
  echo "     排查：① 渲染输入 ./nginx/nginx.conf.canonical 是否来自 ref=${CONFIG_REF_RESOLVED}；"
  echo "           ② MIGAO_PUBLIC_DOMAIN 是否真读到了 .env.site（当前值=${MIGAO_PUBLIC_DOMAIN}）"
  exit 1
fi
echo "  ✅ nginx.conf 自证：server_name 含站点域名 ${MIGAO_PUBLIC_DOMAIN}"
# <<< nginx-domain-assert

# ── 1.3.1 微信「扫普通链接二维码打开小程序」校验文件落位（issue #8196）────────────
# 微信后台生成的是一个**根下随机的 `<一串字符>.txt`**（文件名/内容都由微信给，仓库不编、不改）。
# 它必须出现在 `https://app.migaozn.com/<名字>.txt` —— 也就是静态根的**根下**。
# 用户在微信后台下载后原样放进 `deploy/swas/wechat-verify/`（说明见该目录 README），本段负责落位。
# 🔴 **必须放在取配置之后、C′ 构建之前**：源码树 `src/` 只在第 1 段存在（构建成功后按磁盘策略删掉，
#    见 1.4 与 #5814）⇒ 放到 2.x 那一段时 `src/` 已不在，本段会永远「跳过」= 静默不落位。
#    配置**复用**（同 ref 重部署，盘上没有 `src/`）时本段照样跳过并出声：该 ref 的首次部署已经把
#    文件拷过去了（静态根跨部署保留）。
# 🔴 只**增/覆盖** `.txt`：静态根同时是 C 端 h5 的落地面（`index.html` / `js/` / `b/` / `w/` /
#    `terminal/` 都不归本段所有）⇒ 这里**不删**任何别的文件、也不做清理。
# 幂等：同一份输入连跑两次结果逐字节一致（判据 = tests/unit_ci_workflows/test_wechat_verify_route.py）。
# 任何跳过都**出声**且**不拖垮部署**（还没放文件是常态，不是故障）。
# >>> wechat-verify
MIGAO_VERIFY_STATIC_ROOT=${MIGAO_STATIC_ROOT:-/opt/migao-deploy/h5}
MIGAO_VERIFY_SRC_DIR=${MIGAO_WECHAT_VERIFY_DIR:-}
if [ -z "$MIGAO_VERIFY_SRC_DIR" ]; then
  # 默认取**本次解出来的源码树**（第 1 段的 `src/`）；从仓检出直接跑时退回 `deploy/…`。
  if [ -d src/deploy/swas/wechat-verify ]; then
    MIGAO_VERIFY_SRC_DIR=src/deploy/swas/wechat-verify
  else
    MIGAO_VERIFY_SRC_DIR=deploy/swas/wechat-verify
  fi
fi
MIGAO_VERIFY_COPIED=0
if [ ! -d "$MIGAO_VERIFY_SRC_DIR" ]; then
  echo "  ⏭️ 跳过微信校验文件：盘上没有 ${MIGAO_VERIFY_SRC_DIR}（本次未取源码树 / 同 ref 复用配置）—— **部署不受影响**"
elif [ ! -d "$MIGAO_VERIFY_STATIC_ROOT" ]; then
  echo "  ⏭️ 跳过微信校验文件：静态根 ${MIGAO_VERIFY_STATIC_ROOT} 不存在（h5 尚未落位）—— **部署不受影响**"
else
  for _migao_verify_file in "$MIGAO_VERIFY_SRC_DIR"/*.txt; do
    [ -e "$_migao_verify_file" ] || continue
    cp -f "$_migao_verify_file" "$MIGAO_VERIFY_STATIC_ROOT/$(basename "$_migao_verify_file")"
    MIGAO_VERIFY_COPIED=$((MIGAO_VERIFY_COPIED + 1))
    echo "  微信校验文件：$(basename "$_migao_verify_file") → ${MIGAO_VERIFY_STATIC_ROOT}/"
  done
  if [ "$MIGAO_VERIFY_COPIED" -eq 0 ]; then
    echo "  ℹ️ 微信校验文件：${MIGAO_VERIFY_SRC_DIR} 里还没有 *.txt（微信后台生成后原样放进来；**部署不受影响**）"
  fi
fi
# <<< wechat-verify

# ── 1.3c JWT classpath 公钥快照 + 持久缓存（issue #9051 / #9059）───────────────
# `src/` 是本次 ref 的仓库树，**1.4 构建成功后按磁盘策略删掉**（`rm -rf src`）⇒
# 需要它的地方必须在 1.4 之前把内容取走。而 2.5.9 的同源断言在 1.4 **之后**跑，且
# 「配置复用 / 回滚」档盘上根本没有 `src/` ⇒ 光有变量不够，还要在部署根落一份**持久缓存**
# （公钥不涉密、幂等覆盖），否则 `.env.admin-api` 的 `classpath:rsa/public.pem` 会恒被
# 判成 unjudgeable ⇒ 部署恒定中止（issue #9059 的实测形态）。
_MIGAO_CLASSPATH_PUBKEY_REL=${MIGAO_CLASSPATH_PUBKEY_REL:-rsa/public.pem}
_MIGAO_CLASSPATH_PUBKEY_CACHE=${MIGAO_CLASSPATH_PUBKEY_CACHE:-.migao-admin-api-classpath-public.pem}
if [ -f "src/backend/admin-api/src/main/resources/${_MIGAO_CLASSPATH_PUBKEY_REL}" ]; then
  cp -f "src/backend/admin-api/src/main/resources/${_MIGAO_CLASSPATH_PUBKEY_REL}" \
        "${_MIGAO_CLASSPATH_PUBKEY_CACHE}"
fi
_MIGAO_CLASSPATH_PUBKEY=""
if [ -f "${_MIGAO_CLASSPATH_PUBKEY_CACHE}" ]; then
  _MIGAO_CLASSPATH_PUBKEY=$(cat "${_MIGAO_CLASSPATH_PUBKEY_CACHE}")
fi

# ══════════════════════════════════════════════════════════════════════════════
# 1.4 C′ 服务器侧构建（issue #5814）—— **在本脚本已持有的 flock 之内**
#
# 为什么能在**这里**构建：上面第 1 段刚把 `src/` 整棵仓库树解出来（它本来只为取 4 个配置
# 文件而存在，取完就没用了）⇒ 构建上下文**零额外下载**。这也正是 C′ 成立的关键：
# 源码已经在服务器上，不需要任何新的下发通道（RunCommand 命令体实测上限仅 43.8–50.7KB，
# 装不下 gzip 后 2.5–2.8MB 的源码树 ⇒ 「一次 Base64 下发源码」不可实现，见 PR body 的阻塞登记）。
#
# 缓存（稳态秒级的**唯一**来源）：Docker 层缓存 + 下面 `docker builder prune` 的
# `until=168h` ⇒ 7 天内的 apt/pip 层保住 ⇒ 「只改源码」的部署是 **2s**（实测）。
# ⚠️ 不许无条件 `docker builder prune -af`：那会把稳态 2s 打回冷构建 29.7min。
#
# 退出码语义（与 PR #5816 同族，**有上界 + 会点名**）：
#   rc=124 ⇒ `timeout` 打死 ⇒ 显式打 `::error::` 点名「服务器侧构建超时」并带上界值；
#   其它非零 ⇒ 构建本身失败（看上方 docker 输出）。
# ══════════════════════════════════════════════════════════════════════════════
# ⚠️ `-z "$LOCAL_IMAGE_REF"`（issue #6551 ②）：非空 ⇒ 本腿**不构建**（本地已有该 tag 的镜像，
#    pull 段同样据此短路）⇒ 不占磁盘、不需要源码树。
if [ -n "$BUILD_SERVICE" ] && [ -z "$LOCAL_IMAGE_REF" ]; then
  echo "== 1.4 C′ 服务器侧构建（${_svc}，在 flock 之内；tag=${TAG}）=="
  _ctx=$(service_context_of "$BUILD_SERVICE")
  _df="$_ctx/Dockerfile"
  if [ -z "$_ctx" ] || [ ! -f "src/$_df" ]; then
    echo "❌ 源码包里找不到构建上下文/Dockerfile（src/${_df}）⇒ **中止**（tag=${TAG} 的源码树与该形态不同源）"
    exit 1
  fi
  # ── 本地镜像 ref 由 **compose 自己求值**得出（唯一真相源，不在本脚本里重抄一遍）──────
  # 硬编码 `${ACR_REGISTRY}/ai-customer-service/<svc>:${IMAGE_TAG}` 会在有人改 compose 时**静默漂移**
  # ⇒ 表现为「构建成功但 compose 找不到该镜像 ⇒ 去 ACR pull 一个从未推送的 tag」。
  # 这里读**已同步进来**的 ./docker-compose.yml（第 1 段刚从同源源码树 cp 过来）+ 与 compose
  # 相同的环境变量（IMAGE_TAG 由下方 export、ACR_REGISTRY 已在第 0 段 export）⇒ 逐字同源。
  export IMAGE_TAG="$TAG"
  _image_ref=$(local_image_ref_of "$_svc")
  if [ -z "$_image_ref" ]; then
    echo "❌ 取不到 compose 里 ${_svc} 的 \`image:\`（compose config 求值失败）⇒ **中止**（拒绝在 ref 不明时构建）"
    echo "   diagnostic: docker compose config --format json | python3 -c '…services[\"$_svc\"]…'"
    exit 1
  fi
  LOCAL_IMAGE_REF="$_image_ref"
  echo "  ✅ 本地镜像 ref（与 compose 同源自证，由 compose config 求值）：${LOCAL_IMAGE_REF}"
  # ── 磁盘前置检查（issue #5814 §四.4）────────────────────────────────────────
  # 实测：每次构建净增约 1 GB、构建缓存已 1.36 GB、服务器总盘 **40 GB**（不是 70）⇒ 余量是真约束。
  # 构建前先断言余量 ≥ 门槛（fail-closed：空间不够时**不动**正在跑的服务，直接中止）。
  _df_mb=$(disk_free_mb || true)
  _need_mb=${BUILD_MIN_FREE_MB:-4096}
  echo "  构建前磁盘可用：${_df_mb}MB（门槛 ${_need_mb}MB）"
  # ── issue #6508 ①：门槛判定**之前**先做一次「按水位的构建缓存回收」────────────────
  # 余量不足时，第一动作不再是「交给人工」（改前形态：真机上给的那条命令是空操作），
  # 而是**本脚本自己按水位清缓存、清到门槛以上为止**（幂等、带阈值、失败可见）。
  # ⚠️ 保留 `-lt` 之后的 fail-closed 中止**一字不改**（那是有效护栏，issue #6503 的实证）。
  _cache_mb=$(builder_cache_measure || true)
  if [ "${_df_mb:-0}" -lt "$_need_mb" ]; then
    RECOVERY_ANCHOR=1
    echo "  磁盘可用 ${_df_mb}MB < 门槛 ${_need_mb}MB ⇒ 先按水位回收构建缓存（issue #6508，不再只给人工出口）"
    builder_cache_recover "$_need_mb"
    _df_after_recover=$(disk_free_mb || true)
    _cache_after_recover=$(builder_cache_measure || true)
    echo "  缓存回收结果：${_df_mb}MB → ${_df_after_recover}MB（门槛 ${_need_mb}MB）；构建缓存：${_cache_mb:-?} → ${_cache_after_recover:-?}（清理档=${CACHE_RECOVER_DID}）"
    _df_mb=$_df_after_recover
  fi
  if [ "${_df_mb:-0}" -lt "$_need_mb" ]; then
    # 🔴 issue #6505：**机读标记**（部署日志里同族的那几个 `XXX=` 标记的写法）—— CI 收口据此判「**未开始部署**」
    #    （旧容器保持不动、环境未受影响），而不是把同一次闸门读成「两次独立失败 + 环境可能坏」。
    echo "ABORT_REASON=BUILD_MIN_FREE_MB"
    echo "  ❌ 磁盘可用 ${_df_mb}MB < 门槛 ${_need_mb}MB ⇒ **中止构建**（旧容器保持不动、环境未受影响）"
    echo "     回收出口（**人工**，本脚本不做无人值守删除 —— 铁律 10）："
    echo "       · 遗留旧源码克隆：/opt/migao（2026-08-13 残留，实测 2.2 GB）"
    # ⚠️ 本行**故意不逐字写出**「清掉所有未使用镜像」那条命令：它是被
    #    tests/unit_ci_workflows/test_swas_deploy_disk_retention.py 判红的形态
    #    （不带保留集 ⇒ 会连带删掉回滚点）⇒ 说明文字里写出字面量会被那条判据正确判红。
    echo "       · 清掉所有未使用镜像（prune 的 all 档，约 2.4 GB）—— ⚠️ 它**不带保留集**，会连带删掉回滚点；"
    echo "         只许在人工确认「当前在用 + .last-good-tag 都在保留范围」之后执行，见第 0 段保留策略"
    # 🔴 出口必须**真可行动**（issue #6508 的病根：改前逐字写死 `until=168h`，而真机上缓存条目
    #    全是 72h 内建的 ⇒ 那条命令匹配 0 条、`Total: 0B` —— 照着敲解决不了问题）。
    #    现取的候选窗口由**本次读数**给出；最紧档后面的 `--keep-storage 0` 是兜底（清空）。
    _sug_window=$(pick_cache_window "${_df_mb:-0}")
    echo "       · 构建缓存：docker builder prune --filter until=${_sug_window}h（按当前水位 ${_df_mb}MB 选的窗口；"
    echo "         仍不够 ⇒ 兜底 docker builder prune -af **只清构建缓存**，代价是下一次冷构建）"
    echo "       · 或扩容磁盘（用户 2026-09-30 已表态「有必要会扩容」）"
    exit 1
  fi
  # ── 构建参数 ───────────────────────────────────────────────────────────────
  _build_args=(--build-arg "APT_MIRROR=$APT_MIRROR")
  if [ -n "$PIP_INDEX_URL" ]; then _build_args+=(--build-arg "PIP_INDEX_URL=$PIP_INDEX_URL"); fi
  # 构建身份（issue #6951）：见上面 BUILD_SHA/BUILD_TAG/BUILT_AT 的说明。
  # ⚠️ 无条件传给**被构建的那个服务**：admin-api / ai-agent 的 Dockerfile 声明了这三个 ARG
  #    （ENV 进镜像 ⇒ `/api/version` 可读）；**没有声明它们的 Dockerfile（admin-web）会静默忽略**
  #    （docker 对未声明的 `--build-arg` 不报错）⇒ 三条腿共用本段是安全的。
  # ⚠️ `BUILD_TAG` 缺省回落成 `${TAG}`（= 镜像 tag，天然等于「这次部署的是哪个镜像」）。
  _build_args+=(--build-arg "MIGAO_BUILD_SHA=${BUILD_SHA:-}")
  _build_args+=(--build-arg "MIGAO_BUILD_TAG=${BUILD_TAG:-$TAG}")
  _build_args+=(--build-arg "MIGAO_BUILT_AT=${BUILT_AT:-}")
  # admin-web 的构建期环境变量：**构建已搬到服务器侧** ⇒ 覆盖口也从 CI 的 `--build-arg` 挪到这里。
  # 现取：默认值 = Dockerfile 的 ARG 缺省值 = 线上落位（与改前 CI 的 `secrets.X || <默认>` 的
  # **有效值**一致 —— 那几个 secret 从未在仓里登记过，Danger Scan 也不允许新增未登记的 secret 引用）。
  # 需要按环境覆盖时：在服务器上写 `/opt/migao-deploy/.env.build`（可选文件，缺省即不覆盖）。
  # ⚠️ 这是 C′ 带来的**配置面迁移**（CI secret → 服务器 env 文件），已在 PR body 的缺口节登记。
  if [ -f .env.build ]; then
    # shellcheck disable=SC1091
    set -a; . ./.env.build; set +a
    echo "  ℹ️  已加载 .env.build（构建期变量覆盖口）"
  fi
  if [ "$_svc" = "admin-web" ]; then
    # 默认值 = 站点域名派生（缺省 migaozn.com ⇒ 与改前逐字相同）；服务器侧 `.env.build` 优先级更高。
    _build_args+=(--build-arg "NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL:-https://api.${MIGAO_PUBLIC_DOMAIN}}")
    _build_args+=(--build-arg "NEXT_PUBLIC_AI_API_BASE_URL=${NEXT_PUBLIC_AI_API_BASE_URL:-https://ai-api.${MIGAO_PUBLIC_DOMAIN}}")
    _build_args+=(--build-arg "NEXT_PUBLIC_COOKIE_DOMAIN=${NEXT_PUBLIC_COOKIE_DOMAIN:-.${MIGAO_PUBLIC_DOMAIN}}")
    _build_args+=(--build-arg "NEXT_PUBLIC_BMINI_H5_URL=${NEXT_PUBLIC_BMINI_H5_URL:-https://app.${MIGAO_PUBLIC_DOMAIN}/b/}")
    # 站点域名（issue #8941）：商家登录 / canonical / sitemap / robots / proxy host 分流的唯一来源。
    # 与上面四条同源派生（缺省域名下 = `migaozn.com` ⇒ 测试环境产物与改前逐字相同）；
    # 服务器侧 `.env.build` 仍可显式覆盖。
    _build_args+=(--build-arg "NEXT_PUBLIC_SITE_DOMAIN=${NEXT_PUBLIC_SITE_DOMAIN:-${MIGAO_PUBLIC_DOMAIN}}")
  fi
  echo "  构建命令：timeout ${BUILD_TIMEOUT_SECS} docker build -f ${_df} -t ${LOCAL_IMAGE_REF} ${_build_args[*]} src/${_ctx}"
  if timeout "$BUILD_TIMEOUT_SECS" docker build -f "src/$_df" -t "$LOCAL_IMAGE_REF" "${_build_args[@]}" "src/$_ctx"; then
    echo "  ✅ 本地构建完成：${LOCAL_IMAGE_REF}"
  else
    _rc=$?
    if [ "$_rc" = "124" ]; then
      echo "::error::**服务器侧构建超时**（rc=124，超过上界 ${BUILD_TIMEOUT_SECS}s）—— 镜像 ${LOCAL_IMAGE_REF} 未产出；"
      echo "::error::冷构建实测 1782s（apt 1100s + pip 675s）⇒ 超上界说明缓存已失效或网络劣化；请人工确认后复跑。"
    else
      echo "::error::服务器侧构建失败（rc=${_rc}，上界 ${BUILD_TIMEOUT_SECS}s）—— 镜像 ${LOCAL_IMAGE_REF} 未产出。"
    fi
    exit "$_rc"
  fi
  # 本地构建的镜像**必须真的在本地**（fail-closed）：否则后续 compose 会去 ACR pull 一个不存在的 tag，
  # 表现成「部署成功但跑的是旧镜像」这类静默形态。
  if ! docker image inspect "$LOCAL_IMAGE_REF" >/dev/null 2>&1; then
    echo "❌ 构建报成功但 ${LOCAL_IMAGE_REF} **不在本地** ⇒ 中止（拒绝静默回落到 ACR）"
    exit 1
  fi
  # ── 产物域名**自证**（issue #8966）────────────────────────────────────────────
  # 病根：`docker build` 少一个 build-arg 时 Next **静默**把缺省域烤进产物（首页 / sitemap / robots
  # 全指向测试域），而构建、部署、健康检查**全绿** —— 只有用户被送去另一个站。
  # 口径：站点域名 != 测试域时，产物里的关键件**不得**含 `migaozn.com`。
  # ⚠️ 取不到那个文件 ⇒ **不可判定**（打印 SKIPPED），**不判绿也不判红**（不许拿「没读到」冒充「干净」）。
  # >>> image-domain-guard
  if [ "$_svc" = "admin-web" ] && [ "$MIGAO_PUBLIC_DOMAIN" != "migaozn.com" ]; then
    _guard_path=${MIGAO_DOMAIN_GUARD_FILE:-.next/server/app/sitemap.xml.body}
    _guard_dir=$(mktemp -d "${TMPDIR:-/tmp}/migao-domain-guard.XXXXXX" 2>/dev/null || true)
    _guard_cid=""
    _guard_got=0
    if [ -n "$_guard_dir" ] && _guard_cid=$(docker create "$LOCAL_IMAGE_REF" 2>/dev/null) && [ -n "$_guard_cid" ]; then
      if docker cp "${_guard_cid}:${_guard_path}" "${_guard_dir}/" >/dev/null 2>&1; then
        _guard_got=1
      fi
      docker rm -f "$_guard_cid" >/dev/null 2>&1 || true
    fi
    _guard_file="${_guard_dir}/${_guard_path##*/}"
    if [ "$_guard_got" = "1" ] && [ -f "$_guard_file" ]; then
      if grep -qF 'migaozn.com' "$_guard_file"; then
        echo "  ❌ 产物残留测试域 migaozn.com（站点域名=${MIGAO_PUBLIC_DOMAIN}，镜像=${LOCAL_IMAGE_REF}）⇒ **中止部署**（issue #8966）"
        echo "     命中行（前 3 条，${_guard_path}）："
        grep -nF 'migaozn.com' "$_guard_file" | head -3 | sed 's/^/       /' || true
        echo "     真因多半是 build-arg 没送到：核对 --build-arg NEXT_PUBLIC_SITE_DOMAIN=${MIGAO_PUBLIC_DOMAIN} 与 Dockerfile 的 ARG/ENV 透传"
        if [ -n "$_guard_dir" ]; then rm -rf "$_guard_dir"; fi
        exit 1
      fi
      echo "  ✅ 产物自证：${_guard_path} 不含测试域 migaozn.com（站点域名=${MIGAO_PUBLIC_DOMAIN}）"
    else
      echo "  ⏭️ SKIPPED（**不可判定**）：取不到镜像里的 ${_guard_path}（${LOCAL_IMAGE_REF}）—— 产物域名**未验证**，不判绿"
      echo "     判据要求（issue #8966）：站点域名=${MIGAO_PUBLIC_DOMAIN} 时产物不得含 migaozn.com ⇒ 本次无法验证"
    fi
    if [ -n "$_guard_dir" ]; then rm -rf "$_guard_dir"; fi
  fi
  # <<< image-domain-guard
  # ── 构建后回收（**只碰构建缓存**，铁律 10 口径：不删带 tag 的镜像、不碰保留集）──────
  # 缺口（issue #6508 ②）：Build Cache 此前**完全不在保留策略里**（只增不减，实测 12.44GB /
  # 184 条 / 100% RECLAIMABLE）⇒ 这里按**水位**回收（`builder_cache_recover`：清到门槛以上为止），
  # 并把**两个读数**（可用量 + 缓存占用）真的打进日志 —— 改前那一格逐字是 `构建缓存：?`。
  _cache_before_mb=$(builder_cache_measure || true)
  _used_before_mb=$(disk_used_mb || true)
  builder_cache_recover "$_need_mb"
  _df_after_mb=$(disk_free_mb || true)
  _cache_after_mb=$(builder_cache_measure || true)
  _used_after_mb=$(disk_used_mb || true)
  # ── 回收量的**口径**（issue #6512 ②）= **构建缓存占用差** ─────────────────────────
  # 改前用 Δ(整盘已用) 当回收量 ⇒ 把**构建自身写盘**混了进来：「prune 腾 2GB + 构建写 2GB」
  # 读数 = 0 ⇒ 假警（真机 run 37634071278：`已用 28042MB → 28042MB` ⇒ 报「回收量 0」而水位是健康的）。
  # 正确的量就在隔壁那行（`构建缓存：X → Y` 的差）；Δ已用只作**参照**打印，不是回收量。
  # 读数不可得（`?`）⇒ 显式说「无法判定」，**绝不**拿 0 冒充「没腾出空间」（失败可见）。
  _reclaim_known=0
  _reclaimed_mb=0
  if [ "${_cache_before_mb:-?}" != "?" ] && [ "${_cache_after_mb:-?}" != "?" ]; then
    _reclaimed_mb=$(( _cache_before_mb - _cache_after_mb ))
    _reclaim_known=1
  fi
  _reclaim_text="${_reclaimed_mb}MB"
  if [ "$_reclaim_known" = "0" ]; then _reclaim_text="无法判定（构建缓存读数不可得）"; fi
  echo "  构建后磁盘可用：${_df_after_mb}MB（构建前 ${_df_mb}MB）／构建缓存：${_cache_before_mb:-?} → ${_cache_after_mb:-?}（清理档=${CACHE_RECOVER_DID}）"
  echo "  缓存回收量：${_reclaim_text}（构建缓存 ${_cache_before_mb:-?}MB → ${_cache_after_mb:-?}MB；档位 ${CACHE_RECOVER_DID}/2）"
  echo "     · 参照：整盘已用 ${_used_before_mb:-?}MB → ${_used_after_mb:-?}MB（含构建自身写盘，**不是**回收量）"
  # ── 告警条件（issue #6512 ①）：只在**水位告急且出口没腾出空间**时才告警 ────────────────
  # 水位充裕（回收后可用量 ≥ 门槛）时，按水位选的窗口没匹配到可回收层 ⇒ 回收量 0 **是预期**
  # （真机：缓存层都是几十分钟内建的、而水位充裕时选 72h 档 ⇒ 匹配 0 条）⇒ 只打信息行。
  # 改前是**无条件**告警 ⇒ 每次健康部署一条黄标 = 告警疲劳（永久噪音让真失败与噪音同形）。
  if [ "$_reclaim_known" = "0" ]; then
    echo "  ⚠️ 构建缓存读数不可得 ⇒ 回收量无法判定（不冒充 0；可用量判定见下）"
  elif [ "${_reclaimed_mb:-0}" -le 0 ]; then
    if [ "${_df_after_mb:-0}" -ge "$_need_mb" ]; then
      echo "  ℹ️ 水位充裕（可用 ${_df_after_mb}MB ≥ 门槛 ${_need_mb}MB）⇒ 按 $(pick_cache_window "${_df_after_mb:-0}")h 档未匹配到可回收层，回收量 0 属预期（非异常）"
    else
      echo "  ::warning::缓存回收量为 0（构建缓存 ${_cache_before_mb:-?}MB → ${_cache_after_mb:-?}MB，清理档 ${CACHE_RECOVER_DID}/2）—— 水位告急（可用 ${_df_after_mb}MB < 门槛 ${_need_mb}MB）而出口没有真的腾出空间，需人工核对"
    fi
  fi
  if [ "${_df_after_mb:-0}" -lt "$_need_mb" ]; then
    echo "ABORT_REASON=BUILD_CACHE_RECLAIM_INSUFFICIENT"
    echo "  ::warning::构建后磁盘可用 ${_df_after_mb}MB 已低于门槛 ${_need_mb}MB ⇒ 本次部署继续，但下次构建会被前置检查拦住"
    # ⚠️ 同上前置检查里的理由：**不逐字写出**被 test_swas_deploy_disk_retention.py 判红的那条命令形态。
    echo "     处置：回收 /opt/migao（2.2GB）/ 清掉所有未使用镜像（prune 的 all 档，约 2.4GB，**须先确认保留集**）/ 扩容"
  fi
  # 构建完就把源码树删掉：它只被构建用了一次（配置已 cp 到 /opt/migao-deploy），
  # 留着会让每次部署净增约 84MB 的常驻占用（实测该目录此前**从不清理**）。
  # ⚠️ 只删本脚本自己解出来的 `src/` 与下载的 `src.tar.gz`（都在 /opt/migao-deploy 内），不碰别处。
  rm -rf src src.tar.gz
fi

# 1.5 AI 自动甄别配置自愈：admin-api 需调用 ai-agent 内部端点做入驻甄别，
# AI_AGENT_SERVICE_TOKEN 必须与 .env.ai-agent 的 SERVICE_TOKEN 一致，否则入驻全部
# fail-closed 驳回（系统繁忙）。旧服务器无该配置时自动补齐，避免静默降级。
if [ -f .env.admin-api ] && ! grep -q '^AI_AGENT_SERVICE_TOKEN=' .env.admin-api; then
  AI_TOKEN=$(grep '^SERVICE_TOKEN=' .env.ai-agent 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' || true)
  if [ -n "$AI_TOKEN" ]; then
    printf 'AI_AGENT_BASE_URL=http://ai-agent:8000\nAI_AGENT_SERVICE_TOKEN=%s\n' "$AI_TOKEN" >> .env.admin-api
    echo "  ✅ 自动补齐 admin-api 的 AI 甄别配置（AI_AGENT_SERVICE_TOKEN）"
  else
    echo "  ⚠️ .env.ai-agent 无 SERVICE_TOKEN，无法自动补齐 admin-api AI 甄别配置（入驻将 fail-closed）"
  fi
fi

# 1.6 SMS 万能码 fail-closed（决策 D2 修正 + 审计 07 P0-1 + audit-2026-09 P1）：
# sms.bypass-code 默认已改空（生产 fail-closed）。此前"自动补齐 123456"违反
# fail-closed 原则——生产首次部署若未显式配置即自动启用万能码登录（越权入口）。
# 现在改为：.env.admin-api 必须显式声明 SMS_BYPASS_CODE（可为空=禁用），缺失即中止。
if [ -f .env.admin-api ] && ! grep -q '^SMS_BYPASS_CODE=' .env.admin-api; then
  echo "  ❌ .env.admin-api 缺少显式 SMS_BYPASS_CODE 配置（fail-closed 强制）"
  echo "    · 测试环境（POC 万能码）：追加 SMS_BYPASS_CODE=123456 后重跑"
  echo "    · 生产环境：显式追加 SMS_BYPASS_CODE= 置空禁用万能码（技术债 Issue #2616 关闭前不允许缺省）"
  exit 1
fi
# 1.6b ai-agent 侧 SMS 万能码同规则（#518 回归）：order_create 工具的 bypass 校验
# 读的是 ai-agent 自身环境变量 SMS_BYPASS_CODE（app/tools/order_create.py），
# 缺失时 C 端下单的短信验证码必然校验失败。与 admin-api 同样强制显式声明。
if [ -f .env.ai-agent ] && ! grep -q '^SMS_BYPASS_CODE=' .env.ai-agent; then
  echo "  ❌ .env.ai-agent 缺少显式 SMS_BYPASS_CODE 配置（fail-closed 强制）"
  echo "    · 测试环境（POC 万能码）：追加 SMS_BYPASS_CODE=123456 后重跑"
  echo "    · 生产环境：显式追加 SMS_BYPASS_CODE= 置空禁用万能码（技术债 Issue #2616 关闭前不允许缺省）"
  exit 1
fi
# ══════════════════════════════════════════════════════════════════════════
# 1.6c JWT 文件式取值宿主路径预检（issue #8989 ④，fail-closed）
#
# 病（issue #8989 ③ 的破坏形态）：compose 把 ai-agent 的 `JWT_PUBLIC_KEY` 改成
# `file:/opt/migao-deploy/jwt/public.pem` 后，只有**重建 ai-agent** 时才真正读这个文件；
# 而 `app/config.py` 对 `file:` 是 fail-closed ⇒ 宿主文件缺失时 ai-agent **起不来** ⇒ AI 接口全挂。
# 旧断言此刻是 SKIPPED（它读的是**旧容器**）⇒ 拦不住。⇒ 在**任何 `docker compose up` 之前**
# 逐条校验宿主路径：存在 + 可读；任一不满足 ⇒ exit 1（旧容器保持不动）。
# 判据 = tests/unit_ci_workflows/test_swas_jwt_same_source.py 的注入式红证 b。
# ══════════════════════════════════════════════════════════════════════════
echo "== 1.6c JWT 文件式取值宿主路径预检（issue #8989 ④，fail-closed）=="

# 部署根：生产 = `/opt/migao-deploy`。抽成变量只为让测试能把同构目录指到临时目录
# （生产不设该变量 ⇒ 逐字一致、零行为变化）；`file:` 值里的绝对路径经它映射。
MIGAO_DEPLOY_ROOT=${MIGAO_DEPLOY_ROOT:-/opt/migao-deploy}

jwt_host_path() {
  case "$1" in
    /opt/migao-deploy/*) printf '%s' "${MIGAO_DEPLOY_ROOT}/${1#/opt/migao-deploy/}" ;;
    *) printf '%s' "$1" ;;
  esac
}

# stdin: `.env` 文本 → 每个 `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY` 的 `file:` 宿主路径（每行一条）
jwt_file_paths_of_env() {
  # ⚠️ 不用 BRE 的 `\|` 交替（BSD/macOS sed 不支持，会让本函数静默返回空 ⇒ 预检形同虚设）
  sed -n \
    -e 's/^[[:space:]]*export[[:space:]]*JWT_PRIVATE_KEY[[:space:]]*=[[:space:]]*//p' \
    -e 's/^[[:space:]]*export[[:space:]]*JWT_PUBLIC_KEY[[:space:]]*=[[:space:]]*//p' \
    -e 's/^[[:space:]]*JWT_PRIVATE_KEY[[:space:]]*=[[:space:]]*//p' \
    -e 's/^[[:space:]]*JWT_PUBLIC_KEY[[:space:]]*=[[:space:]]*//p' \
    | tr -d '\r' \
    | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//" \
    | sed -n 's/^file://p'
}

# compose 里直接写死的 `JWT_*: file:`（ai-agent 的公钥就是这条；compose 的 environment
# 优先级高于 env_file ⇒ 它才是下次重建真正生效的取值）
jwt_file_paths_of_compose() {
  sed -n \
    -e 's/^[[:space:]]*JWT_PRIVATE_KEY:[[:space:]]*file:\(.*\)$/\1/p' \
    -e 's/^[[:space:]]*JWT_PUBLIC_KEY:[[:space:]]*file:\(.*\)$/\1/p' \
    "$@" 2>/dev/null
}

# 取 `.env` 里某键的**最后一条**取值（同名以最后一次为准；去 CR / 成对引号）
jwt_env_value_of() {
  local env_file=$1 key=$2 val
  [ -f "${env_file}" ] || return 0
  val=$(sed -n -e "s/^[[:space:]]*export[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" \
    -e "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "${env_file}" | tr -d '\r' | tail -1)
  val=${val%\"}; val=${val#\"}
  val=${val%\'}; val=${val#\'}
  printf '%s' "${val}"
}

# `classpath:<rel>` ⇒ 该资源的**内容**（只解析 admin-api 的资源面）。取不到 ⇒ 非零（不可判定）。
# 解析源（按可信度）：① 本次部署树 `src/backend/admin-api/src/main/resources/<rel>`
#                     ② 仓检出形态 `backend/admin-api/src/main/resources/<rel>`（本地/判据用）
#                     ③ 1.3c 落盘的**持久缓存**（供「配置复用 / 回滚」档：那时盘上已没有 `src/`）
# 🔴 三条都取不到 ⇒ 调用方必须报 `unjudgeable`（**不得**判绿）：`classpath:` 解析不了不等于同源。
jwt_classpath_resource_of() {
  local rel=$1 root
  case "${rel}" in
    ""|*..*|/*) return 1 ;;
  esac
  for root in "src/backend/admin-api/src/main/resources" "backend/admin-api/src/main/resources"; do
    if [ -f "${root}/${rel}" ]; then cat "${root}/${rel}"; return 0; fi
  done
  if [ "${rel}" = "${_MIGAO_CLASSPATH_PUBKEY_REL:-rsa/public.pem}" ] \
     && [ -f "${_MIGAO_CLASSPATH_PUBKEY_CACHE:-.migao-admin-api-classpath-public.pem}" ]; then
    cat "${_MIGAO_CLASSPATH_PUBKEY_CACHE}"; return 0
  fi
  return 1
}

# stdin: `.env` 文本 → 只取 `JWT_PUBLIC_KEY` 的 `file:` 宿主路径（1.6d 物化只补公钥；私钥永不物化）
jwt_public_file_paths_of_env() {
  sed -n \
    -e 's/^[[:space:]]*export[[:space:]]*JWT_PUBLIC_KEY[[:space:]]*=[[:space:]]*//p' \
    -e 's/^[[:space:]]*JWT_PUBLIC_KEY[[:space:]]*=[[:space:]]*//p' \
    | tr -d '\r' \
    | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//" \
    | sed -n 's/^file://p'
}

# compose 里写死的**公钥** `file:`（ai-agent 的单一来源就是这条）
jwt_public_file_paths_of_compose() {
  sed -n -e 's/^[[:space:]]*JWT_PUBLIC_KEY:[[:space:]]*file:\(.*\)$/\1/p' "$@" 2>/dev/null
}

# ──────────────────────────────────────────────────────────────────────────────
# 1.6d JWT 宿主**公钥**补齐（issue #9051；判据 = 同文件 c 组）
#
# 病（2026-11-23 实测）：compose 把 ai-agent 的 `JWT_PUBLIC_KEY` 改成
# `file:/opt/migao-deploy/jwt/public.pem`（#8976 单一来源）之后，这条宿主路径**没有任何一步
# 负责创建**它 ⇒ 1.6c 的前置校验在测试环境宿主上**恒红**：
#     ❌ JWT 文件式取值指向的宿主路径**不存在**：/opt/migao-deploy/jwt/public.pem
# 自 1.6c 落地（2026-11-22T08:48Z）起，**每一次** push / dispatch 部署都在这里中止（两次尝试同一读数），
# 而 schedule 触发走的是 `skip=true`（**不做部署**）⇒ 那些 success **不是**「部署成功」。
#
# 修法 = **补齐**，不是放宽：缺失时从宿主**已有的权威源**把 public 半份物化到 compose 指的位置，
# 之后仍由 1.6c 逐条校验、2.5.9 两侧指纹同源断言兜底 ⇒ 判别力一分不降。来源优先级：
#   ① `.env.admin-api` 的**内联** `JWT_PUBLIC_KEY`（admin-api 真正在用的 public 半份）
#   ② `.env.ai-agent` 的内联 `JWT_PUBLIC_KEY`
#   ③ 部署树里 admin-api 的 classpath 公钥（`src/backend/admin-api/src/main/resources/rsa/public.pem`；
#      admin-api 未显式配置时的签发公钥来源）⇒ 同时把 `.env.admin-api` 钉成
#      `JWT_PUBLIC_KEY=file:<同一路径>`（否则 2.5.9 只能报 INCOMPLETE：一侧有值一侧「未配置」）
# 三条都取不到 ⇒ **什么都不写**，交回 1.6c 的 fail-closed（**真缺失仍然红**）。
# 私钥永不物化（它不是「配置」而是签发密钥：只能由人成对放入宿主）。
# ──────────────────────────────────────────────────────────────────────────────
echo "== 1.6d JWT 宿主公钥补齐（缺失 ⇒ 从宿主权威源物化；issue #9051）=="
_JWT_SELFHEAL_SEEN=" "
while IFS= read -r _jwt_pub_path; do
  _jwt_pub_path=${_jwt_pub_path%$'\r'}
  [ -n "${_jwt_pub_path}" ] || continue
  case "${_JWT_SELFHEAL_SEEN}" in *" ${_jwt_pub_path} "*) continue ;; esac
  _JWT_SELFHEAL_SEEN="${_JWT_SELFHEAL_SEEN}${_jwt_pub_path} "
  _jwt_pub_host=$(jwt_host_path "${_jwt_pub_path}")
  [ -e "${_jwt_pub_host}" ] && continue          # 已存在 ⇒ 不动（宿主权威源优先）
  _jwt_src=""
  _jwt_pem=""
  _jwt_pin_env=""
  for _jwt_env_file in .env.admin-api .env.ai-agent; do
    _jwt_pem=$(jwt_env_value_of "${_jwt_env_file}" JWT_PUBLIC_KEY)
    _jwt_pem=${_jwt_pem//\\n/$'\n'}
    case "${_jwt_pem}" in
      *"BEGIN PUBLIC KEY"*) _jwt_src="${_jwt_env_file} 的内联 JWT_PUBLIC_KEY"; break ;;
      *) _jwt_pem="" ;;
    esac
  done
  if [ -z "${_jwt_pem}" ] && [ -n "${_MIGAO_CLASSPATH_PUBKEY:-}" ]; then
    _jwt_pem=${_MIGAO_CLASSPATH_PUBKEY}
    _jwt_src="部署树 classpath 公钥（backend/admin-api/src/main/resources/rsa/public.pem）"
    _jwt_pin_env="1"
  fi
  if [ -z "${_jwt_pem}" ]; then
    echo "  ⚠️ 无法物化 ${_jwt_pub_path}：宿主权威源里**也没有**内联公钥 / 部署树公钥 ⇒ 交回 1.6c 判红"
    continue
  fi
  mkdir -p "$(dirname "${_jwt_pub_host}")"
  printf '%s\n' "${_jwt_pem}" > "${_jwt_pub_host}"
  chmod 0644 "${_jwt_pub_host}"     # 容器以非 root 读 :ro 卷 ⇒ 不能 0600
  echo "  🔧 JWT 公钥已物化：${_jwt_pub_path}（${#_jwt_pem} 字节）⇐ ${_jwt_src}"
  # 只有当 `.env.admin-api` **没有可用公钥**（行缺失或空值）时才钉：已有值属宿主权威源，不动它
  _jwt_cur_admin_pub=$(jwt_env_value_of .env.admin-api JWT_PUBLIC_KEY)
  if [ "${_jwt_pin_env:-}" = "1" ] && [ -f .env.admin-api ] && [ -z "${_jwt_cur_admin_pub}" ]; then
    printf 'JWT_PUBLIC_KEY=file:%s\n' "${_jwt_pub_path}" >> .env.admin-api
    echo "  🔧 .env.admin-api 已钉上 JWT_PUBLIC_KEY=file:${_jwt_pub_path}（两侧同源可判；2.5.9 会复核指纹）"
  fi
  echo "  JWT_FILE_SELFHEAL=created path=${_jwt_pub_path}"
done < <(
  for _jwt_env_file in .env.admin-api .env.ai-agent; do
    [ -f "${_jwt_env_file}" ] && jwt_public_file_paths_of_env < "${_jwt_env_file}"
  done
  jwt_public_file_paths_of_compose docker-compose.yml docker-compose.bluegreen.yml
)

_JWT_FILE_CHECK_FAILED=0
_JWT_FILE_PATHS_SEEN=" "
while IFS= read -r _jwt_path; do
  _jwt_path=${_jwt_path%$'\r'}
  [ -n "${_jwt_path}" ] || continue
  case "${_JWT_FILE_PATHS_SEEN}" in *" ${_jwt_path} "*) continue ;; esac
  _JWT_FILE_PATHS_SEEN="${_JWT_FILE_PATHS_SEEN}${_jwt_path} "
  _jwt_host_path=$(jwt_host_path "${_jwt_path}")
  if [ ! -e "${_jwt_host_path}" ]; then
    echo "  ❌ JWT 文件式取值指向的宿主路径**不存在**：${_jwt_path}"
    _JWT_FILE_CHECK_FAILED=1
  elif [ ! -r "${_jwt_host_path}" ]; then
    echo "  ❌ JWT 文件式取值指向的宿主路径**不可读**：${_jwt_path}（权限或挂载问题）"
    _JWT_FILE_CHECK_FAILED=1
  else
    echo "  ✅ JWT 文件式取值宿主路径可读：${_jwt_path}"
  fi
done < <(
  for _jwt_env_file in .env.admin-api .env.ai-agent; do
    [ -f "${_jwt_env_file}" ] && jwt_file_paths_of_env < "${_jwt_env_file}"
  done
  jwt_file_paths_of_compose docker-compose.yml docker-compose.bluegreen.yml
)
if [ "${_JWT_FILE_CHECK_FAILED}" -ne 0 ]; then
  echo "  ⇒ **中止部署**（fail-closed）：这些路径缺失时，重建对应容器会起不来（AI 接口全挂）。"
  echo "     处置：把该文件放回宿主（与签发密钥成对），或修正 .env.* 的 JWT_* 取值后重跑。"
  echo "     本次**未做任何 docker compose up**（旧容器保持不动）。"
  exit 1
fi
echo "  JWT_FILE_PATHS_CHECK=OK（${_JWT_FILE_PATHS_SEEN# }）"

# 1.7 模型名 canonical 自愈（#3483 / 官方命名）：DeepSeek 官方模型名为 deepseek-flash，
# 旧名 deepseek-v4-flash / deepseek-v4-flash-vision-exp 仅临时路由且随时下线——
# 部署时把服务器 .env.ai-agent 的旧名归一化，防旧值回滚（2026-09-14 云端修复实证）。
if [ -f .env.ai-agent ]; then
  if grep -qE '^PRIMARY_MODEL=deepseek-v4-flash' .env.ai-agent \
     || grep -qE '^VISION_MODEL=deepseek-v4-flash' .env.ai-agent; then
    sed -i 's/^PRIMARY_MODEL=deepseek-v4-flash.*/PRIMARY_MODEL=deepseek-flash/' .env.ai-agent
    sed -i 's/^VISION_MODEL=deepseek-v4-flash[-a-z]*.*/VISION_MODEL=deepseek-flash/' .env.ai-agent
    echo "  ✅ 模型名 canonical 化：PRIMARY_MODEL/VISION_MODEL → deepseek-flash"
  fi
fi

echo "== 1.9 磁盘水位预检（#2571 防护：部署前磁盘满会导致 pull/up 失败 + admin-api 503）=="
# 先登录 ACR（私有仓库）：深度清理后补回回滚点要用它 —— 缺凭据时 pull 必然失败（不许静默失去回滚点）。
registry_login
DISK_PCT=$(disk_pct)
if [ "${DISK_PCT:-0}" -gt 90 ]; then
  echo "  ⚠️ 磁盘水位 ${DISK_PCT}% > 90%，先深度清理再继续部署"
  # 🔴 issue #4808 ②：`docker system prune -af` **会删带 tag 的镜像**，包括 `.last-good-tag`
  #    指向的那一套 ⇒ 回滚点会在这一步**静默消失**。故：先记下回滚点，清理后**立刻复核并补回**。
  RB_BEFORE=$(rollback_tag)
  # ── 🔴 C′（issue #5814）：本形态下**镜像只在服务器本地构建、从不推 ACR** ⇒
  #    `docker system prune -af` 会删掉**带 tag** 的镜像（包括 `.last-good-tag` 指向的回滚点），
  #    而下面那段「从 ACR 补回」的**源已经不存在**（那个 tag 从未推送过）⇒
  #    在 C′ 下执行 `-af` 等于**自己删掉 #4767「失败即回滚」的目标，且无法补回**。
  #    ⇒ C′ 下**不走**这条深清路径，改由**既有保留策略**承担（`cleanup_project_images`：
  #      只删本项目命名空间前缀、保留「在用 + `.last-good-tag` + 最近 N 个」，且回滚点有**三道**
  #      独立防线）—— 「回滚点只许保留」在 C′ 下由保留策略保证。
  #    ⚠️ **保留可检出信号 / 自动复活**：本分支只决定「要不要执行 `-af`」，「补回」那段**逐字保留** ⇒
  #      将来若恢复推 ACR（`BUILD_SERVICE` 为空）时，深清 + 补回路径**自动复活**，行为与改前逐字相同。
  if [ -n "$BUILD_SERVICE" ]; then
    echo "  ⏭️  C′ 本地构建形态：**跳过 \`-af\` 深度清理**（镜像只在本地 ⇒ 删了就补不回来）"
    echo "      改由保留策略清理：在用 tag + 回滚点 + 最近 ${KEEP_RECENT_TAGS} 个，且**只删本项目前缀**"
    echo "      · C′ 下回滚点的**真实来源** = **本地镜像** + ${LAST_GOOD_FILE}（补回源 ACR 在 C′ 下不存在）"
    echo "      · 磁盘仍吃紧时的**人工**出口：回收 /opt/migao（2.2GB，2026-08-13 遗留旧源码克隆）/ 扩容"
  else
    docker system prune -af --volumes 2>/dev/null || docker system prune -af 2>/dev/null || true
  fi
  journalctl --vacuum-size=50M >/dev/null 2>&1 || true
  DISK_PCT2=$(disk_pct)
  echo "  清理后磁盘: ${DISK_PCT2}%（原 ${DISK_PCT}%）"
  if [ -n "$RB_BEFORE" ]; then
    if rollback_point_present "$RB_BEFORE"; then
      echo "  ✅ 回滚点 tag=${RB_BEFORE} 未被深度清理波及（仍可回滚）"
    else
      echo "  ⚠️ 深度清理把回滚点 tag=${RB_BEFORE} 删了 —— 正在从镜像仓库补回（不许静默失去回滚能力）"
      # ⚠️ **顺序铁律**：清理已经跑完 ⇒ 空间**已经释放** ⇒ **现在才**补回。
      # 若反过来（先补回再清理）会把 ≈3.14GB 叠在 >90% 的水位上，可能直接把磁盘顶过 95% 中止线。
      # 顺序在日志里**逐行可辨**：清理后水位 → 补回（附耗时空间）→ 补回后水位。
      RB_USED0=$(disk_used_mb)
      DISK_PCT_RB0=$(disk_pct)
      echo "  ℹ️ 补回顺序：深度清理**已完成**（当前 ${DISK_PCT_RB0}%）⇒ 现在才从 ACR 补回回滚点（3 个服务 ≈3.14GB）"
      PULLED=0
      for svc in admin-api ai-agent admin-web; do
        if IMAGE_TAG="$RB_BEFORE" timeout 180 docker compose pull "$svc" >/dev/null 2>&1; then
          PULLED=$((PULLED + 1))
        fi
      done
      RB_USED1=$(disk_used_mb)
      DISK_PCT_RB1=$(disk_pct)
      echo "  📦 补回回滚点占用空间：$((RB_USED1 - RB_USED0))MB（补回前 ${RB_USED0}MB → 补回后 ${RB_USED1}MB）"
      echo "  补回后磁盘水位：${DISK_PCT_RB1}%（补回前 ${DISK_PCT_RB0}%）"
      if [ "${DISK_PCT_RB1:-0}" -gt 95 ]; then
        # fail-closed：回滚点已补回（系统仍是「可回滚」的），但空间不足以继续 ⇒ 本次**不部署**。
        # 此时尚未拉取/替换任何容器 ⇒ 中止是干净的（旧容器照常服务）。
        echo "  ❌ 补回回滚点后磁盘 ${DISK_PCT_RB1}% > 95% —— 回滚点已补回，但空间已不足，中止部署"
        echo "   人工介入：ssh 服务器排查大文件（du -xhd1 / | sort -rh | head）或扩容"
        exit 1
      fi
      if [ "$PULLED" -eq 3 ] && rollback_point_present "$RB_BEFORE"; then
        echo "  ✅ 回滚点 tag=${RB_BEFORE} 已补回（#4767 的「失败即回滚」可用）"
      else
        echo "  ::warning::回滚点 tag=${RB_BEFORE} **补回失败**（成功 ${PULLED}/3 个服务）"
        echo "     ⇒ 本次部署若失败，#4767 的自动回滚**没有回滚点**，需人工介入（见 https://github.com/zhaokai-mgzn/migao/wiki/CI-CD）"
      fi
    fi
  fi
  if [ "${DISK_PCT2:-0}" -gt 95 ]; then
    echo "  ❌ 深度清理后磁盘仍 >95%（${DISK_PCT2}%），中止部署避免故障"
    echo "   人工介入：ssh 服务器排查大文件（du -xhd1 / | sort -rh | head）"
    exit 1
  fi
else
  echo "  磁盘水位 ${DISK_PCT}%（≤90%，OK）"
fi
# 磁盘水位可观测（issue #4808 ③）：**每次部署都报**，而不是只在 >90% 深度清理时说一句。
# ⚠️ 这里是**纯告警**：`::warning::` 只是 GitHub 注解文本，**绝不 `exit`** ⇒ 水位高会每次都喊，
#    但喊不等于失败（当前实测 86% ⇒ 每次部署都会 warn，这是**期望行为**，因为信号是真的）。
if [ "${DISK_PCT:-0}" -gt "$DISK_WARN_PCT" ]; then
  echo "  ::warning::磁盘水位 ${DISK_PCT}% > 告警阈值 ${DISK_WARN_PCT}%（清理后水位见 2.7 段）"
fi
report_rollback_point

# ══════════════════════════════════════════════════════════════════════════
# 2.05 「不许往回走」闸门（issue #4852）
#
# 事故（**生产 CI 实测**，非推断）：三条部署腿共用**同一把 server 侧 flock** ⇒ run 按**创建时刻**排队，
# 而 main 在排队期间前进 ⇒ **为旧 commit 创建的 run 会在更新的 run 成功之后才执行**；旧判据是
# 「该 TAG 的镜像在不在本地/ACR」⇒ 旧 tag 的镜像当时都在本地 ⇒ **服务被重建为旧 tag**，
# 而 run 结论 success、健康检查三个全 200、deploy.sh 自己的结论也是「✅ 部署成功」⇒ **三重绿、零告警**。
# 实测铁证：`35499382654`(56c8c5107,08:22 创建,~08:30 执行) → `35499604094`(ace521ff1,08:27 创建,
# ~08:38 执行) → `35499280090`(**7b03ed3d7**, **08:20 创建**, ~08:42 执行, 部署 `sha-7b03ed3`) ✗
# —— 它自己的日志里已经打出「回滚点 sha-ace521f」（= 它**知道**更新的部署刚刚成功），却仍然往回部署。
#
# 判据（**逐服务**）：target tag 是**该服务当前在跑 tag 的祖先** ⇒ 本服务**跳过** + `::warning::`（不静默）。
# 祖先关系 = **提交图**语义（等价于 `git merge-base --is-ancestor <target> <current>`），
# **不是**字符串比较、**也不是**时间戳（tag 是 `sha-<7>` ⇒ 字典序与提交序无关）。
# 实现走 GitHub compare API（**同一张提交图**）而不是本地 `git`：**实测**（2026-09-21）该服务器上
# `git clone --filter=tree:0 https://github.com/zhaokai-mgzn/migao` 连 `github.com:443` **超时**
# 32s（git 2.43.7 在，且同一次调用里 `git ls-remote` 成功 ⇒ 时通时不通），而 `api.github.com`
# 0.6s/HTTP 200 ⇒ 本地没有可用的历史、API 才是可靠判据（复核数据见 https://github.com/zhaokai-mgzn/migao/wiki/CI-CD）。
# ⚠️ 未认证 API 限 **60 次/小时/IP** ⇒ 一次部署内同「在跑 tag」**只查一次**（见下面的缓存）；
# 取不到判据（非 sha tag / 容器没起 / API 取不到 / 分叉）⇒ **fail-open + 告警**（不许静默放行）。
# 显式回滚（`gh workflow run deploy-*.yml -f image_tag=<tag>`，即 workflow 的 MODE=rollback）
# 经 `ALLOW_DOWNGRADE=1` 注入许可 ⇒ **仍能往回走**（#4767 的「失败即回滚」同样带这份许可）。
# ══════════════════════════════════════════════════════════════════════════
ALLOW_DOWNGRADE=${ALLOW_DOWNGRADE:-0}
# 判据源（**唯一一处**）：GitHub compare API。可被覆盖 ⇒ 守卫测试用桩打同一条码路。
DOWNGRADE_API=${DOWNGRADE_API:-https://api.github.com/repos/zhaokai-mgzn/migao/compare}

# `tag_to_sha()`（`sha-<hex>` → 提交 sha）已在**第 0 段**定义 —— 「配置与镜像同源」（#5083）
# 与这里的「提交序判据」（#4852）**共用同一份解析**，避免两处形态判断漂移。

# 该服务**当前在跑**的镜像 tag（容器没起 / docker 取不到 ⇒ 空串 = 判不了）
running_tag_of() {
  local svc=$1 cid img
  cid=$(docker compose ps -q "$svc" 2>/dev/null || true)
  # 取第一行：不用 `head`（pipefail 下 head 早退会让上游吃 SIGPIPE ⇒ 整条管道非零）
  cid=${cid%%$'\n'*}
  [ -n "$cid" ] || return 0
  img=$(docker inspect --format '{{.Config.Image}}' "$cid" 2>/dev/null || true)
  echo "${img##*:}"
  return 0
}

# 判据本体 = `git merge-base --is-ancestor <target> <current>`（**提交图**祖先关系）：
#   downgrade = target 是在跑的**祖先** ⇒ 本次部署会让该服务**往回走**（issue #4852 的事故形态）
#   forward   = 在跑的是 target 的祖先 ⇒ 正常前进（首次部署由 unknown 分支 fail-open 覆盖）
#   same      = 同一 commit（同 sha 重跑 / 重复部署）
#   unknown   = 判不了（非 sha tag / 取不到在跑 tag / API 取不到 / 分叉）⇒ **fail-open + 告警**
# ⚠️ API 的 `status` 是**相对于 `compare/<base>...<head>`** 的：这里 base=target、head=current，
#    故 `ahead`（current 在 target 之后）⇒ target 是祖先 ⇒ downgrade；`behind` ⇒ 前进。
ancestry_verdict() {
  local target=$1 current=$2 t c json status
  t=$(tag_to_sha "$target"); c=$(tag_to_sha "$current")
  [ -n "$t" ] && [ -n "$c" ] || { echo unknown; return 0; }
  [ "$t" != "$c" ] || { echo same; return 0; }
  json=$(curl -fsS -m 20 -H 'Accept: application/vnd.github+json' "$DOWNGRADE_API/$t...$c" 2>/dev/null || true)
  status=$(printf '%s' "$json" | python3 -c 'import sys, json
try:
    print(json.load(sys.stdin).get("status") or "")
except Exception:
    print("")' 2>/dev/null || true)
  case "$status" in
    ahead)     echo downgrade ;;
    behind)    echo forward ;;
    identical) echo same ;;
    *)         echo unknown ;;
  esac
  return 0
}

echo "== 2.05 「不许往回走」闸门（issue #4852）=="
if [ "$ALLOW_DOWNGRADE" = "1" ]; then
  echo "  ⚠️ ALLOW_DOWNGRADE=1 ⇒ **这是显式回滚**（人工指定 image_tag / #4767 的失败即回滚）：闸门放行，允许往回走"
fi
ALLOWED_SERVICES=""
SKIPPED_SERVICES=""
VERDICT_CACHE_CUR="__no_cache__"   # 一次部署内同「在跑 tag」只查一次 API（匿名 API 限 60 次/小时）
VERDICT_CACHE_VAL=""
for svc in admin-api ai-agent admin-web; do
  cur=$(running_tag_of "$svc")
  if [ "$cur" = "$VERDICT_CACHE_CUR" ]; then
    verdict=$VERDICT_CACHE_VAL
  else
    verdict=$(ancestry_verdict "$TAG" "$cur")
    # ⚠️ 缓存写在**父 shell**（不能用 `verdict=$(...)` 的返回再绕一层：命令替换是子 shell，缓存会丢）
    VERDICT_CACHE_CUR=$cur; VERDICT_CACHE_VAL=$verdict
  fi
  if [ "$ALLOW_DOWNGRADE" = "1" ]; then
    echo "  ↩ ${svc}：**显式回滚**放行（target=${TAG} / 在跑=${cur:-无} / 判据=${verdict}）"
  elif [ "$verdict" = "downgrade" ]; then
    echo "  ::warning::${svc} **跳过**：target=${TAG} 是**当前在跑 tag=${cur} 的祖先** ⇒ 本次部署会让它**往回走**（issue #4852）"
    echo "     ⇒ 不部署 ${svc}（线上保持 ${cur}）：更新的那次部署已生效；**故意回滚**请走 \`gh workflow run deploy-*.yml -f image_tag=${TAG}\`"
    SKIPPED_SERVICES="$SKIPPED_SERVICES $svc"
    continue
  elif [ "$verdict" = "unknown" ]; then
    echo "  ::warning::${svc} 判不出「target vs 在跑」的提交序（target=${TAG} / 在跑=${cur:-无}）⇒ **放行但告警**（fail-open，issue #4852）"
  fi
  ALLOWED_SERVICES="$ALLOWED_SERVICES $svc"
done
echo "  闸门结论：允许部署=[${ALLOWED_SERVICES# }] / 因「往回走」跳过=[${SKIPPED_SERVICES# }]"

echo "== 2. 拉取镜像（tag=${TAG}）=="
registry_login
export IMAGE_TAG="$TAG"
# 逐服务拉取：某个镜像尚未推送（首次接入）时跳过该服务，其余照常滚动更新
UP_SERVICES="nginx"
for svc in $ALLOWED_SERVICES; do
  # ── C′（issue #5814）：本次**本地构建过**的那个服务不 pull ──────────────────
  # 它刚在 1.4 段就地构建并打了**与 compose 逐字相同**的 ref ⇒ 本地已存在。
  # ⚠️ 这里**不能**改成「先 pull 再回落本地」：compose pull 会去 ACR 找这个 tag（本次从未推送）
  #    ⇒ 拉失败/拉超时白等 180s，且失败路径会打「可能尚未推送」这类误导性告警。
  #    正确形态 = **按已知事实短路**：本地就是权威来源，直接进更新集。
  if [ -n "$LOCAL_IMAGE_REF" ] && [ "$svc" = "$_svc" ]; then
    echo "  ⏭️  $svc 本次为 C′ 本地构建（${LOCAL_IMAGE_REF}）⇒ **跳过 ACR pull**（本地镜像即权威来源）"
    UP_SERVICES="$UP_SERVICES $svc"
    continue
  fi
  # ── C′ 模式：本腿**只负责自己那个服务** ──────────────────────────────────────
  # C′ 之后 CI **不再推 ACR** ⇒ 别的服务在本次 tag 下**必然不在 ACR** ⇒ 去 pull 只会白等
  # 180s 超时、再打一句"可能尚未推送"的误导告警（单次部署白等最多 2×180s）。
  # 它们的更新由**各自的腿**完成（三条腿同源于同一个 commit）⇒ 这里**显式跳过并说明理由**。
  if [ -n "$LOCAL_IMAGE_REF" ]; then
    echo "  ⏭️  $svc 不在本腿职责内（C′ 模式：本腿只构建/部署 ${_svc}）⇒ 跳过；它的更新由对应 deploy 腿完成"
    continue
  fi
  if timeout 180 docker compose pull "$svc" >/dev/null 2>&1; then
    UP_SERVICES="$UP_SERVICES $svc"
  else
    echo "  ⚠️ $svc 镜像拉取失败/超时（可能尚未推送 :${TAG}），跳过该服务"
  fi
done
# ── 2.1 「本次实际生效 tag」逐服务一行（issue #4852 ③）──────────────────────
# 事故里最误导的一句话就是 `✅ SWAS 部署成功（tag=sha-7b03ed3）` —— 它只说了**请求的** tag，
# 没说线上**实际**是哪个 commit。这里逐服务打机器可读行（CI 侧解析后落 `$GITHUB_STEP_SUMMARY`
# 与部署结论行）⇒ 「线上到底是哪个 commit」一眼可查，被闸门跳过的服务同样在列（生效 = 在跑的那个）。
# ⚠️ 格式是契约（CI 侧 `swas-deploy-ci.sh` 按它解析，守卫测试钉住）：`EFFECTIVE_TAG=<svc>:<tag>`
echo "== 2.1 本次实际生效 tag（逐服务）=="
for svc in admin-api ai-agent admin-web; do
  case " $UP_SERVICES " in
    *" $svc "*) eff=$TAG ;;
    *) eff=$(running_tag_of "$svc"); [ -n "$eff" ] || eff="unknown" ;;
  esac
  echo "  EFFECTIVE_TAG=${svc}:${eff}"
done
# 被闸门跳过的服务逐条给出**判据数据**（谁 vs 谁），便于事后对账：`DOWNGRADE_SKIPPED=<svc>:<target>:<running>`
for svc in $SKIPPED_SERVICES; do
  echo "  DOWNGRADE_SKIPPED=${svc}:${TAG}:$(running_tag_of "$svc")"
done
# ══════════════════════════════════════════════════════════════════════════
# 2.5 严格蓝绿（issue #4785）：**先起新的 → 健康检查通过 → 再切流量**
#
# 旧写法是 `docker compose up -d --no-deps $UP_SERVICES` —— 用的是 compose 的**替换**语义：
# **停旧 → 删旧 → 建新 → 起新**（不是滚动、更不是蓝绿）⇒ 新镜像起不来时**旧容器已经走了**
# —— 2026-09-21 事故（ca724257e）把 admin-api 打成 502、环境不可用直到手工回滚的那一步就是它。
#
# 现在：对每个待更新服务**先以 green 身份起同一镜像**（新容器名 + 第二端口，**旧容器完全不动**）
# → 用**与第 3 步完全同一份判据**做健康检查 → 通过才替换正式容器；不通过 ⇒ 删 green、exit 1，
# **旧容器一动不动**（失败窗口 = 0）。#4767 的「失败即回滚」（CI 侧）仍是**外层**兜底，本段是**内层**。
#
# 取舍（issue #4785 要求逐条说明）：**过去**刻意走第二端口而不碰 nginx upstream ——
# nginx.conf 的 `proxy_pass http://admin-api:8080` 走 compose DNS 名，改 nginx.conf 写坏 =
# **全站所有域名同时挂**（「部署脚本改坏 = 停掉所有人的部署」的形态）。
# 🔴 **M1-a（issue #9098）把成功路径的窗口也消掉了**：nginx.conf 现在是 **upstream 模型**
# （`migao_admin_api` / `migao_ai_agent` / `migao_admin_web`），发布期 `nginx_upstream_switch()`
# **只改成员行 + `nginx -t` + reload**，正式容器是在流量移走**之后**才重建的（下方 ④ 在 ②③ 之后）。
# 「写坏 = 全站挂」的四道锁：① 成员块有标记（只改那几行，其余一字不动）② 改完**先** `nginx -t`
# ③ `-t` 失败 ⇒ 当场把备份拷回、**不 reload**（入口一字未变）④ reload 失败 ⇒ 同样回退 + 重试一次。
# 失败路径（坏镜像）的窗口仍是 **0**（#4785 语义未变）；成功路径的窗口现在是 **0**
#（改动前是「替换 + 启动 + reload」的秒级～分钟级）。判据（会红）：见铁律 8 的固化声明；
# 承载体 = tests/unit_ci_workflows/test_zero_downtime_m1_cutover.py。
# ══════════════════════════════════════════════════════════════════════════

# green 的**第二端口**：与 deploy/swas/docker-compose.bluegreen.yml 的默认值必须一致
# （一致性由 tests/unit_ci_workflows/test_swas_deploy_blue_green.py 静态守卫钉住）
BG_ADMIN_API_PORT=${BG_ADMIN_API_PORT:-18080}
BG_AI_AGENT_PORT=${BG_AI_AGENT_PORT:-18000}
BG_ADMIN_WEB_PORT=${BG_ADMIN_WEB_PORT:-13001}
export BG_ADMIN_API_PORT BG_AI_AGENT_PORT BG_ADMIN_WEB_PORT
# 应急开关：蓝绿把部署门槛抬高了（green 要占一份内存/端口）⇒ 留一条**不改代码**的放行口
BG_OFF_FILE=${BG_OFF_FILE:-/opt/migao-deploy/.blue-green-off}
# green 与旧容器**并存**是蓝绿的前提 ⇒ 门槛 = 最重服务 mem_limit(1536m) + 512m 余量
BG_MEM_NEED_MB=${BG_MEM_NEED_MB:-2048}
BG_COMPOSE="docker compose -f docker-compose.yml -f docker-compose.bluegreen.yml"
BG_GREENS="admin-api-green ai-agent-green admin-web-green"
# 健康检查的重试预算（默认与改动前**逐字一致**：10 次 × 10s；守卫测试调小以免空耗）
HC_RETRIES=${HC_RETRIES:-10}
HC_INTERVAL_SECONDS=${HC_INTERVAL_SECONDS:-10}

bg_port() {
  case "$1" in
    admin-api) echo "$BG_ADMIN_API_PORT" ;;
    ai-agent)  echo "$BG_AI_AGENT_PORT" ;;
    admin-web) echo "$BG_ADMIN_WEB_PORT" ;;
    *)         echo "" ;;
  esac
}
svc_port() {
  case "$1" in
    admin-api) echo 8080 ;;
    ai-agent)  echo 8000 ;;
    admin-web) echo 3001 ;;
    *)         echo "" ;;
  esac
}
svc_health_path() {
  case "$1" in
    admin-api) echo /actuator/health ;;
    ai-agent)  echo /health ;;
    admin-web) echo / ;;
    *)         echo "" ;;
  esac
}
# ══════════════════════════════════════════════════════════════════════════
# M1-a nginx **upstream 摘挂**（issue #9098）—— 切换动作 = 只改 upstream 成员 + reload
#
# 这段存在的理由：下方 ⑤ 的「重建正式容器」（`up -d --no-deps <svc>`，compose 的**替换**语义：
# 停旧 → 删旧 → 建新 → 起新）只要发生在流量还指着旧容器的时候，中间就一定有一段
# 「没有进程在服务」的窗口（改动前实测 90s 的 502）。所以顺序改成：
#   ① green 起来且健康 → ② **只切 upstream**（green 主 + 正式容器 backup）+ `nginx -t` + reload
#   → ③ 入口 200 断言 → ④ drain（等旧 worker 把在途请求做完）→ ⑤ **现在才**重建正式容器
#   → ⑥ upstream 切回正式容器 → ⑦ 删 green。
# ⚠️ 稳态**只写现行实例一条成员**：nginx 解析配置时就会对 upstream 服务名做 DNS 解析，green 没在跑
#    时写它的名字 ⇒ `[emerg] host not found in upstream` ⇒ 全站起不来。green 成员只在发布期存在，
#    成功/失败都会恢复（`nginx_upstream_switch <svc> formal`）。
# ⚠️ 真机事实：nginx 跑在**容器**里（`migao-deploy-nginx-1`），宿主没有 nginx 二进制、没有
#    `/etc/nginx` ⇒ 一切测试/reload 都经 `docker compose exec -T nginx`。
# 判据（会红）：tests/unit_ci_workflows/test_zero_downtime_m1_cutover.py（含注入式红证：
#    把这里改回「重建 + reload」⇒ 判据红）。
# ══════════════════════════════════════════════════════════════════════════
NGINX_CONF_FILE=${NGINX_CONF_FILE:-./nginx/nginx.conf}
UPSTREAM_MEMBERS_BEGIN="# >>> migao-upstream-members"
UPSTREAM_MEMBERS_END="# <<< migao-upstream-members"
# drain 的上限：与 nginx.conf 的 `worker_shutdown_timeout 200s` 同值（= SSE 最长流 180s + 余量）
UPSTREAM_DRAIN_TIMEOUT=${UPSTREAM_DRAIN_TIMEOUT:-200}

upstream_name_of() {
  case "$1" in
    admin-api) echo migao_admin_api ;;
    ai-agent)  echo migao_ai_agent ;;
    admin-web) echo migao_admin_web ;;
    *)         echo "" ;;
  esac
}

# 成员行（**唯一一份口径**）：正式容器的稳态形态必须与 nginx.conf 里 checked-in 的那一行**逐字相同**
# （切回去要和原文逐字节一致 —— 否则每次发布都会在服务器上留下漂移）。
upstream_members_for() {
  local svc=$1 role=$2 port
  port=$(svc_port "$svc")
  case "$role" in
    green)
      # 发布期：green 主、正式容器 backup（主不可用时才回落 ⇒ 新镜像刚起就崩也不会打到用户）
      printf 'server %s-green:%s max_fails=2 fail_timeout=10s;\n' "$svc" "$port"
      printf 'server %s:%s backup;\n' "$svc" "$port" ;;
    formal)
      printf 'server %s:%s max_fails=2 fail_timeout=10s;\n' "$svc" "$port" ;;
    *) return 1 ;;
  esac
}

# >>> upstream-members-rewrite（判据会从本段抽出这段 python 单独跑：行为式证明「切换后两个后端」）
rewrite_upstream_members() {
  UPSTREAM_FILE="$1" UPSTREAM_TARGET="$2" UPSTREAM_MEMBERS="$3" \
  UPSTREAM_BEGIN="$UPSTREAM_MEMBERS_BEGIN" UPSTREAM_END="$UPSTREAM_MEMBERS_END" \
  python3 - <<'PY_UPSTREAM_MEMBERS'
import os
import sys
import tempfile

path = os.environ["UPSTREAM_FILE"]
target = os.environ["UPSTREAM_TARGET"]
members = [ln for ln in os.environ["UPSTREAM_MEMBERS"].splitlines() if ln.strip()]
begin = os.environ["UPSTREAM_BEGIN"].strip()
end = os.environ["UPSTREAM_END"].strip()
if not members:
    sys.exit("rewrite_upstream_members: 成员清单为空（不写出一个没有任何后端的 upstream）")
with open(path, encoding="utf-8") as fh:
    lines = fh.read().splitlines()
head = next((i for i, ln in enumerate(lines) if ln.strip() == f"upstream {target} {{"), None)
if head is None:
    sys.exit(f"rewrite_upstream_members: 找不到 `upstream {target} {{`")
tail = next((j for j in range(head + 1, len(lines)) if lines[j].strip() == "}"), None)
if tail is None:
    sys.exit(f"rewrite_upstream_members: `upstream {target}` 没有配对的 `}}`")
opens = [k for k in range(head + 1, tail) if lines[k].strip() == begin]
closes = [k for k in range(head + 1, tail) if lines[k].strip() == end]
if len(opens) != 1 or len(closes) != 1 or opens[0] > closes[0]:
    sys.exit(
        f"rewrite_upstream_members: `upstream {target}` 的成员标记不是恰好一对"
        f"（begin={len(opens)} end={len(closes)}）"
    )
new = lines[: opens[0] + 1] + ["    " + m for m in members] + lines[closes[0]:]
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".nginx.conf.")
with os.fdopen(fd, "w", encoding="utf-8") as fh:
    fh.write("\n".join(new) + "\n")
os.replace(tmp, path)
print(f"UPSTREAM_MEMBERS={target}:{len(members)}")
PY_UPSTREAM_MEMBERS
}
# <<< upstream-members-rewrite

# 只切 upstream：改成员 → `nginx -t` → reload。**不重建、不 restart 任何容器**（那就是窗口本身）。
# 失败一律回退到备份并返回非零 ⇒ 入口停在**改动之前**的形态。
# 返回码：0 = 已切换；1 = 失败（已回退）；3 = 入口不在运行（无从 reload ⇒ 调用方回落重建路径）
nginx_upstream_switch() {
  local svc=$1 role=$2 target members bak
  target=$(upstream_name_of "$svc")
  [ -n "$target" ] || { echo "     ❌ 未知服务 ${svc}：没有对应的 upstream 名"; return 1; }
  members=$(upstream_members_for "$svc" "$role") || { echo "     ❌ 未知角色 ${role}（只允许 green|formal）"; return 1; }
  if [ -z "$(docker compose ps -q nginx 2>/dev/null || true)" ]; then
    echo "     ⏭️  nginx 不在运行 ⇒ 无从「只切 upstream」"
    return 3
  fi
  bak="${NGINX_CONF_FILE}.bak-$(date +%Y%m%d-%H%M%S)"
  cp -f "$NGINX_CONF_FILE" "$bak" || { echo "     ❌ 备份 ${NGINX_CONF_FILE} 失败（不改入口）"; return 1; }
  if ! rewrite_upstream_members "$NGINX_CONF_FILE" "$target" "$members"; then
    cp -f "$bak" "$NGINX_CONF_FILE"
    echo "     ❌ 改写 upstream 成员失败 ⇒ 已恢复 ${bak}（入口未变）"
    return 1
  fi
  if ! docker compose exec -T nginx nginx -t; then
    cp -f "$bak" "$NGINX_CONF_FILE"
    echo "     ❌ nginx -t 不通过 ⇒ 已恢复 ${bak}、**未 reload**（入口一字未变）"
    return 1
  fi
  if ! docker compose exec -T nginx nginx -s reload; then
    cp -f "$bak" "$NGINX_CONF_FILE"
    echo "     ❌ reload 失败 ⇒ 已恢复 ${bak} 并重试一次 reload（旧 worker 仍在服务，不 restart）"
    docker compose exec -T nginx nginx -s reload || true
    return 1
  fi
  rm -f -- "$bak"
  echo "     ✅ upstream 已切换：${target} → $(printf '%s' "$members" | tr '\n' ' ')"
  return 0
}

# drain：等旧 nginx worker 把**在途请求**做完再重建正式容器（不是盲睡固定秒数）。
# 读数 = nginx 自己的 worker 标题：reload 后旧 worker 变成 `nginx: worker process is shutting down`
# （空闲连接它当场就关，只有**真在跑**的请求会留住它）⇒ 这个标题消失 = 在途请求收尾完毕。
# 读不到 worker 标题 ⇒ 明说「不可判定」，**不假装等过**；到上限只告警、不中止（nginx 会按
# worker_shutdown_timeout 强制收尾 —— 宁可慢，也不许把用户的长流砍了）。
upstream_drain_wait() {
  local svc=$1 limit=${UPSTREAM_DRAIN_TIMEOUT:-200} i ps_out
  echo "  ── ${svc} drain：等旧 nginx worker 收尾（上限 ${limit}s）"
  for i in $(seq 1 "$limit"); do
    if ! ps_out=$(docker compose exec -T nginx ps 2>/dev/null); then
      echo "     ⚠️ DRAIN=UNDECIDABLE（读不到 nginx worker 列表）⇒ 不做等待，也不假装等过"
      return 0
    fi
    if ! printf '%s' "$ps_out" | grep -q "worker process"; then
      echo "     ⚠️ DRAIN=UNDECIDABLE（\`ps\` 输出里没有 nginx worker 标题）⇒ 不做等待，也不假装等过"
      return 0
    fi
    if ! printf '%s' "$ps_out" | grep -q "worker process is shutting down"; then
      echo "     ✅ DRAIN=OK（旧 worker 已退出，在途请求已收尾；等待 ${i}s）"
      return 0
    fi
    sleep 1
  done
  echo "     ⚠️ DRAIN=TIMEOUT（${limit}s 内旧 worker 未全退，长流仍在跑）⇒ 交给 worker_shutdown_timeout 兜底"
  return 0
}

# 健康检查判据（**全脚本唯一一份**）：green 与正式容器共用同一函数 ⇒ 判据不可能漂移
# （推演项「两套判据 / 判据过严导致回滚抖动」正是靠这一点排除的）。
wait_healthy() {
  local port=$1 name=$2 path=$3 i code
  for i in $(seq 1 "$HC_RETRIES"); do
    code=$(curl -s -o /tmp/hc_$name.txt -w "%{http_code}" -m 10 "http://127.0.0.1:$port$path" || echo 000)
    if [ "$code" = "200" ] || [ "$code" = "301" ] || [ "$code" = "302" ]; then
      echo "  $name OK ($code)"; return 0
    fi
    echo "  $name -> $code (retry $i)"
    sleep "$HC_INTERVAL_SECONDS"
  done
  echo "  ❌ $name 健康检查未通过（重试 $HC_RETRIES 次仍未就绪）"
  return 1
}

# ── nginx 上游断言（issue #8976 ④；2026-11-21 生产实测全站 502 约 90s）──────────────
# 病：`docker compose up -d` 会**重建**容器（新 IP），而 nginx 在**启动 / reload 时**解析
#     `proxy_pass http://admin-api:8080` 这类 compose DNS 名并**缓存**该 IP ⇒ 重建后不 reload
#     ⇒ 请求继续打到**已经消失的**旧 IP ⇒ 502，直到下一次 reload（实测窗口 90s）。
# 判据（会红）：reload 之后**本机**上游必须回 200。**取不到读数是判红**（不是「没问题」）：
#     连不上 / 超时 / 非 200 / 取不到 => exit 1。
# ⚠️ 为什么探 https + `--resolve` 而不是字面的 `http://127.0.0.1/api/version`：
#     `deploy/swas/nginx.conf` 的 **:80 面是按设计 301 跳 https** 的
#     （`location / { return 301 https://$host$request_uri; }`）⇒ 按 :80 探**永远**不是 200，
#     那会变成一条恒红的空断言。`--resolve` 把 `api.<站点域>` 钉回 127.0.0.1:443
#     ⇒ 走的仍是 nginx **真实的** upstream 解析，且不出本机。
NGINX_PROBE_TRIES=${NGINX_PROBE_TRIES:-12}
NGINX_PROBE_INTERVAL=${NGINX_PROBE_INTERVAL:-2}
nginx_expect_upstream_ok() {
  local why=$1 code="" i api_host
  api_host="api.${MIGAO_PUBLIC_DOMAIN}"
  echo "  ── nginx 上游断言（${why}）"
  if [ -z "$(docker compose ps -q nginx 2>/dev/null || true)" ]; then
    # 首装 / 被清掉：先让入口存在（幂等）。否则探到的是「本机没有入口」，不是「上游没切换」。
    echo "     nginx 不在运行 ⇒ 先起它（幂等；否则本条断言证明不了 upstream 解析）"
    docker compose up -d --no-deps nginx
  fi
  # reload 优先（优雅：旧 worker 把在途请求做完再退），失败回落 restart（= 改动前行为）。
  if ! docker compose exec -T nginx nginx -s reload; then
    docker compose restart nginx
  fi
  for i in $(seq 1 "${NGINX_PROBE_TRIES}"); do
    code=$(curl -sk -o /dev/null -w "%{http_code}" -m 5 \
      --resolve "${api_host}:443:127.0.0.1" "https://${api_host}/api/version" 2>/dev/null) || code="000"
    if [ "${code}" = "200" ]; then
      echo "     ✅ 本机上游 200（https://${api_host}/api/version → nginx → admin-api）"
      echo "     NGINX_UPSTREAM=OK"
      return 0
    fi
    echo "     本机上游 -> ${code}（第 ${i}/${NGINX_PROBE_TRIES} 次）"
    sleep "${NGINX_PROBE_INTERVAL}"
  done
  echo "     NGINX_UPSTREAM=FAIL"
  echo "     ❌ nginx 上游未回 200（最后读数 ${code}）⇒ 入口仍指向重建前的旧上游 IP（站点正在 502）"
  echo "        排查：docker compose ps；docker compose exec -T nginx nginx -T | grep -n proxy_pass"
  echo "              docker compose logs --tail 50 nginx；curl -sk https://127.0.0.1/api/version -m 5"
  echo "        处置：docker compose restart nginx 后再跑一次本断言；上游自己起不来见各容器日志"
  exit 1
}

echo "== 2.5 严格蓝绿预验证（新容器先起 + 健康检查通过再切流量）=="
BG_VERIFIED=""
BG_SKIP=0
if [ -f "$BG_OFF_FILE" ]; then
  BG_SKIP=1
  echo "  ⏭️  存在 $BG_OFF_FILE ⇒ **跳过蓝绿预验证**（回到 #4767 的「失败即回滚」兜底路径）"
  echo "      ⚠️ 本次新镜像**未被预验证**：失败时靠 CI 侧回滚兜底（窗口 ≈2-4min）"
else
  echo "  green 第二端口：admin-api=$BG_ADMIN_API_PORT ai-agent=$BG_AI_AGENT_PORT admin-web=$BG_ADMIN_WEB_PORT"
  # 残留清理：上一轮被强杀/超时会留下 green 容器（占着容器名与第二端口）⇒ 先删，保证本次能起。
  # 并发安全：flock 覆盖**整个**脚本（含本段）⇒ 不会与另一个部署抢；本段无需另加锁。
  # shellcheck disable=SC2086
  $BG_COMPOSE rm -sf $BG_GREENS >/dev/null 2>&1 || true
  # 内存预检：green 与旧容器并存 ⇒ 必须容得下最重服务。不够 ⇒ **中止部署**（fail-closed：
  # 旧容器保持不动、环境不受影响）；应急放行 = touch $BG_OFF_FILE。
  MEM_AVAIL_MB=$(awk '/^MemAvailable:/{print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
  if [ "${MEM_AVAIL_MB:-0}" -lt "$BG_MEM_NEED_MB" ]; then
    echo "  ❌ 可用内存 ${MEM_AVAIL_MB}MB < 蓝绿所需 ${BG_MEM_NEED_MB}MB（green 必须与旧容器并存）"
    echo "     ⇒ 中止部署，**旧容器保持不动**、环境未受影响。应急放行：touch $BG_OFF_FILE"
    exit 1
  fi
  echo "  可用内存 ${MEM_AVAIL_MB}MB ≥ 门槛 ${BG_MEM_NEED_MB}MB（OK）"
fi

# ⚠️ 切换循环在 if/else **之外**：应急开关只跳过「green 预验证」，**不跳过更新本身**
#    （否则 `.blue-green-off` 会静默变成「本次不部署」—— 那是最恶劣的静默失效形态）。
for svc in $UP_SERVICES; do
  if [ "$svc" = "nginx" ]; then continue; fi
  GREEN="$svc-green"
  GPORT=$(bg_port "$svc")
  GPATH=$(svc_health_path "$svc")
  # 本次是否真的「切了 upstream」：0 = 是（重建后要切回正式容器）
  # 2 = 应急开关跳过；3 = 入口 nginx 不在运行；1 = 切换失败 ⇒ 三者都回落老路径（但 2/3 **不是失败**）
  SWITCH_RC=2

  # ── ① 蓝绿预验证：先起 green（新容器名 + 第二端口），**旧容器完全不动** ──
  if [ "$BG_SKIP" = "1" ]; then
    echo "  ── ${svc}：应急开关生效 ⇒ 跳过预验证，直接替换"
  else
    echo "  ── ${svc}：先起 ${GREEN}（新容器名 + 第二端口 ${GPORT}），**旧容器不动**"
    # shellcheck disable=SC2086
    if ! $BG_COMPOSE up -d --no-deps "$GREEN"; then
      echo "  ❌ $svc 的 green 容器起不来（第二端口/容器名冲突？）⇒ **旧容器保持不动**，环境未受影响"
      $BG_COMPOSE rm -sf "$GREEN" >/dev/null 2>&1 || true
      exit 1
    fi
    if ! wait_healthy "$GPORT" "$GREEN" "$GPATH"; then
      echo "  ❌ $svc 新镜像（tag=${TAG}）健康检查未通过 ⇒ **旧容器保持不动、流量未切**，环境未受影响"
      $BG_COMPOSE rm -sf "$GREEN" >/dev/null 2>&1 || true
      exit 1
    fi
    # 迁移失败闸门（issue #5792）：`MigrationRunner` 的语义是「单条失败只跳过这一条、继续跑后面的」，
    # 且**不参与健康判定** ⇒ 实测（2026-09-30）schema 与代码不一致却**部署三重全绿**，
    # 随后 Post-Deploy Smoke 在 85 秒后莫名 500（失败迁移把连接池里的连接留成 aborted 事务）。
    # ⇒ 在**切流量之前**就断言：只认 ERROR 形态的「❌ 迁移失败」；
    #   「已知存量非幂等」是 INFO 的「ℹ️ 迁移失败…」，**不算**（护栏②已按错因签名区分）。
    if $BG_COMPOSE logs --tail=800 "$GREEN" 2>&1 | grep -q "❌ 迁移失败"; then
      echo "  ❌ $svc 新镜像（tag=${TAG}）**迁移失败** ⇒ schema 可能与代码不一致，**不切流量**（旧容器保持服务、环境未受影响）："
      $BG_COMPOSE logs --tail=800 "$GREEN" 2>&1 | grep -aE "❌ 迁移失败|本次有 .* 条迁移失败" | tail -8
      $BG_COMPOSE rm -sf "$GREEN" >/dev/null 2>&1 || true
      exit 1
    fi
    echo "  ✅ $svc green 健康 ⇒ 新镜像已被证明能起，现在才替换正式容器"
  fi

  # ── ② M1-a：**只切 nginx upstream**（green 主 + 正式容器 backup）→ `nginx -t` → reload ──
  # 这一步是「零停机」的本体：流量移走**之后**（⑤）才重建正式容器。
  # 应急开关 / 入口不在运行 ⇒ 不切（`SWITCH_RC` 非 0）⇒ 境界明确地回落到老路径。
  if [ "$BG_SKIP" = "0" ]; then
    SWITCH_RC=0
    nginx_upstream_switch "$svc" green || SWITCH_RC=$?
  fi
  if [ "$SWITCH_RC" != "0" ]; then
    if [ "$SWITCH_RC" = "2" ]; then
      echo "  ── ${svc}：应急开关生效 ⇒ **不走 upstream 摘挂**（本次**不是零停机**；旧容器仍在服务）"
    elif [ "$SWITCH_RC" = "3" ]; then
      echo "  ⏭️  ${svc} 入口 nginx 未运行 ⇒ 本次退回「重建 + reload」老路径：**不是零停机**（旧容器仍在服务）"
    else
      echo "  ❌ ${svc} upstream 切换失败 ⇒ **不重建正式容器**（旧容器继续服务、入口保持切换前形态）"
      $BG_COMPOSE rm -sf "$GREEN" >/dev/null 2>&1 || true
      exit 1
    fi
  else
    # ── ③ 入口断言：nginx → green 这条路**真的通**（不是只看 reload 命令有没有报错）──
    nginx_expect_upstream_ok "${svc} 切到 green 后"
    # ── ④ drain：等旧 nginx worker 把在途请求做完（读的是 worker 状态，不是盲睡）──
    upstream_drain_wait "$svc"
    echo "  ✅ ${svc} 流量已切到 green 且旧 worker 已收尾（正式容器**尚未重建**）"
  fi

  # ── ⑤ 现在才重建正式容器（流量已不在它身上；M1-b 的优雅退出让它在途请求自然收尾）──
  docker compose up -d --no-deps "$svc"
  if ! wait_healthy "$(svc_port "$svc")" "$svc" "$GPATH"; then
    echo "  ❌ $svc 正式容器替换后健康检查未通过 ⇒ 中止"
    echo "     交给 CI 侧 #4767 的「失败即回滚」（回滚到 .last-good-tag）兜底"
    exit 1
  fi

  # 🔴 重建 = 换 IP ⇒ **必须**让 nginx 重新解析上游，并当场证明它回 200（issue #8976 ④）。
  # 这一步不能靠「2.6 稍后会 reload」：切换循环里每个服务之间可能隔几分钟健康检查，
  # 期间入口一直指着旧 IP ⇒ 生产实测就这样 502 了 90 秒。
  # （M1-a：正式容器此时在 upstream 里是 **backup** 成员，它的 IP 同样要重新解析。）
  nginx_expect_upstream_ok "${svc} 重建后"

  # ── ⑥ upstream 切回正式容器（green 退回 backup 后即可回收）──
  if [ "$SWITCH_RC" = "0" ]; then
    if ! nginx_upstream_switch "$svc" formal; then
      echo "  ❌ ${svc} upstream 切回正式容器失败 ⇒ **不删 green**（入口仍指向它，服务不中断）"
      echo "     恢复：docker exec migao-deploy-nginx-1 nginx -T | grep -n -A3 'upstream $(upstream_name_of "$svc")'"
      echo "           把成员块改回 \`server ${svc}:$(svc_port "$svc") max_fails=2 fail_timeout=10s;\`，然后："
      echo "           docker exec migao-deploy-nginx-1 nginx -t && docker exec migao-deploy-nginx-1 nginx -s reload"
      exit 1
    fi
    nginx_expect_upstream_ok "${svc} 切回正式容器后"
  fi

  # ── ⑦ 正式容器接棒 ⇒ 删掉 green 探针（不长期占内存/端口）──
  if [ "$BG_SKIP" = "0" ]; then
    $BG_COMPOSE rm -sf "$GREEN" >/dev/null 2>&1 || true
    BG_VERIFIED="$BG_VERIFIED $svc"
  fi
done
if [ "$BG_SKIP" = "1" ]; then
  echo "  ⏭️  蓝绿预验证已被应急开关跳过（本次**未验证**新镜像）"
else
  echo "  ✅ 蓝绿预验证结束：${BG_VERIFIED:-（无待更新服务）}"
fi

# ══════════════════════════════════════════════════════════════════════════
# 2.5.9 JWT 验签同源硬断言（issue #8976 ①；2026-11-21 生产 AI 接口**全 401**）
#
# 病：admin-api 用 `.env.admin-api` 的 `JWT_PRIVATE_KEY/JWT_PUBLIC_KEY`（`file:/opt/migao-deploy/jwt/*.pem`）
# 签发，ai-agent 用 compose 里**硬编码的 PEM** 验签 ⇒ 同一个 token 配了两把钥匙 ⇒
# `TOKEN_INVALID: Signature verification failed`，生产 AI 接口全 401。
# 这类不一致**永远不会自己好**（两侧都不报错、也没有任何读数为红）⇒ 只能拦在部署链上。
#
# 判据（四态，**`3` 不得当 `0` 读**；issue #8989 补齐第 ④ 态）：
#   ① 两侧指纹一致          => ✅ 打印两侧**来源 + 指纹**；
#   ② 两侧指纹不一致        => ❌ 打印两侧来源 + 指纹 + 排查口 => **exit 1**；
#   ③ 两侧都走 classpath 默认 => ⏭️ **SKIPPED**（**唯一**允许 SKIPPED 的形态），不判绿；
#   ④ 只有一侧可判 / 读到非公钥形态 => ❌ **INCOMPLETE** => **exit 1**（「读不到」不许当放过）。
# 🔴 读数源（issue #8989 ③）：只读**宿主权威源**（`.env.*` / compose 的 environment / `file:` 指向的
#    宿主文件），**不**读 `docker compose exec` —— 容器没被重建时读到的是旧容器，那正是 2026-11-21
#    那次部署「admin-api 不可判定、ai-agent 读到旧内联 PEM」的一半原因。
# 指纹口径 = sha256(PEM 公钥体) 前 16 位，与 scripts/align_agent_jwt_key.py **同一口径**
# （对拍判据 = tests/unit_ci_workflows/test_swas_jwt_same_source.py）。
# ══════════════════════════════════════════════════════════════════════════
echo "== 2.5.9 JWT 验签同源断言（admin-api 签发 ⇄ ai-agent 校验，issue #8976）=="

_sha256_hex() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | cut -d' ' -f1
  else
    shasum -a 256 | cut -d' ' -f1
  fi
}

# stdin: PEM 文本 → 公钥体指纹（sha256 前 16）。取不到 / 不是公钥 PEM ⇒ 非零退出（不可判定）。
# 🔴 issue #8989 ②：`.env.*` 里的 PEM 是**单行 + 字面 `\n`** 形态（awk 按行匹配永远取不到 body）。
# ⇒ 先把字面 `\n` 还原成真换行、去掉 `\r`，再走 awk；否则断言恒 SKIPPED（比不加断言更糟：
#   它给了「已守护」的错觉，而真实部署里这条断言**等于不存在**）。
jwt_pubkey_fingerprint() {
  local raw body
  raw=$(cat)
  raw=${raw//$'\r'/}
  raw=${raw//\\n/$'\n'}
  body=$(printf '%s\n' "${raw}" | awk '/-----BEGIN PUBLIC KEY-----/{f=1; next} /-----END PUBLIC KEY-----/{f=0} f' | tr -d ' \t\r\n')
  if [ -z "${body}" ]; then
    return 1
  fi
  printf '%s' "${body}" | _sha256_hex | cut -c1-16
}

# 取 compose `environment:` 里某服务**写死**的取值（优先级高于 env_file；ai-agent 的公钥走这条）
jwt_compose_value_of() {
  local compose_file=$1 svc=$2 key=$3 val
  [ -f "${compose_file}" ] || return 0
  val=$(awk -v svc="${svc}" -v key="${key}" '
    /^[[:space:]]*#/ { next }
    /^services:[[:space:]]*$/ { in_services=1; next }
    in_services && /^  [A-Za-z0-9_.-]+:[[:space:]]*$/ { cur=$1; sub(/:$/, "", cur); next }
    cur == svc && index($0, key ":") > 0 { sub(/^[[:space:]]*[^:]+:[[:space:]]*/, ""); print; exit }
  ' "${compose_file}")
  val=${val%\"}; val=${val#\"}
  printf '%s' "${val}"
}

# 值的**形态**描述（提取失败时写进输出 ⇒ 可归因，不再只有 `<不可判定>`；issue #8989 ②）
jwt_value_shape_of() {
  local raw=$1 bytes
  bytes=$(printf '%s' "${raw}" | wc -c | tr -d ' ')
  case "${raw}" in
    *"BEGIN PRIVATE KEY"*) printf '私钥 PEM（%s 字节，不能当公钥验签）' "${bytes}" ;;
    *"BEGIN PUBLIC KEY"*)
      if [ "${raw#*$'\n'}" != "${raw}" ]; then
        printf '公钥 PEM（%s 字节，含真换行）' "${bytes}"
      else
        printf '公钥 PEM（%s 字节，单行 + 字面 \\n 形态）' "${bytes}"
      fi
      ;;
    *) printf '非 PEM 文本（%s 字节，首 40 字：%s）' "${bytes}" "$(printf '%s' "${raw}" | cut -c1-40)" ;;
  esac
}

# 取某服务**下次重建会实际生效**的公钥：输出 "<指纹>|<状态>|<来源说明>"。
# 状态：`ok` = 已算出指纹；`absent` = 宿主未配置（走 classpath 默认）；`unjudgeable` = 有值但取不到指纹。
# 🔴 issue #8989 ③：只读**宿主权威源**（`.env.*` / compose 声明 / `file:` 指向的宿主文件）。
# 旧实现用 `docker compose exec` 读**运行中的容器** —— 容器没被重建时读到的是旧容器，
# 那正是 2026-11-21 那次部署「admin-api 不可判定、ai-agent 读到旧内联 PEM」的一半原因。
jwt_key_fingerprint_of() {
  local svc=$1 raw src path content fp
  case "${svc}" in
    admin-api)
      # env_file = .env.admin-api；compose 的 environment 里没有 JWT_* 覆盖。
      raw=$(jwt_env_value_of .env.admin-api JWT_PUBLIC_KEY)
      src=".env.admin-api 的 JWT_PUBLIC_KEY"
      ;;
    ai-agent)
      # compose 的 environment **优先于** env_file ⇒ 先读它；没有才回落 .env.ai-agent。
      raw=$(jwt_compose_value_of docker-compose.yml ai-agent JWT_PUBLIC_KEY)
      src="docker-compose.yml 的 ai-agent.environment.JWT_PUBLIC_KEY"
      if [ -z "${raw}" ]; then
        raw=$(jwt_env_value_of .env.ai-agent JWT_PUBLIC_KEY)
        src=".env.ai-agent 的 JWT_PUBLIC_KEY"
      fi
      ;;
    *)
      printf '|unjudgeable|未知服务 %s（断言只认 admin-api / ai-agent）' "${svc}"
      return 0
      ;;
  esac
  case "${raw}" in
    "")
      printf '|absent|%s（宿主未设置 ⇒ 下次重建走镜像 classpath 默认，宿主面无内容可判）' "${src}"
      ;;
    classpath:*)
      # issue #9059：`classpath:<rel>` 是 admin-api 的**默认取值形态**（`.env.admin-api` 里写的就是它）
      # ⇒ 必须能解析成**同一份**公钥再比指纹；解析不到仍判 `unjudgeable`（fail-closed，不许放行）。
      content=$(jwt_classpath_resource_of "${raw#classpath:}") || content=""
      if [ -z "${content}" ]; then
        printf '|unjudgeable|%s = %s（部署树 / 持久缓存里都解析不到该 classpath 资源 ⇒ 不可判定；取值形态已登记在 deploy/swas/jwt-value-forms.json）' "${src}" "${raw}"
        return 0
      fi
      fp=$(printf '%s' "${content}" | jwt_pubkey_fingerprint) || fp=""
      if [ -z "${fp}" ]; then
        printf '|unjudgeable|%s = %s（classpath 资源读到了但提取指纹失败：%s）' "${src}" "${raw}" "$(jwt_value_shape_of "${content}")"
      else
        printf '%s|ok|%s = %s（classpath 资源 backend/admin-api/src/main/resources/%s）' "${fp}" "${src}" "${raw}" "${raw#classpath:}"
      fi
      ;;
    file:*)
      path=$(jwt_host_path "${raw#file:}")
      content=$(cat "${path}" 2>/dev/null) || content=""
      if [ -z "${content}" ]; then
        printf '|unjudgeable|%s = %s（宿主读不到该文件）' "${src}" "${raw}"
        return 0
      fi
      fp=$(printf '%s' "${content}" | jwt_pubkey_fingerprint) || fp=""
      if [ -z "${fp}" ]; then
        printf '|unjudgeable|%s = %s（提取指纹失败：读到了 %s）' "${src}" "${raw}" "$(jwt_value_shape_of "${content}")"
      else
        printf '%s|ok|%s = %s（宿主文件）' "${fp}" "${src}" "${raw}"
      fi
      ;;
    *)
      fp=$(printf '%s' "${raw}" | jwt_pubkey_fingerprint) || fp=""
      if [ -z "${fp}" ]; then
        printf '|unjudgeable|%s（提取指纹失败：读到了 %s）' "${src}" "$(jwt_value_shape_of "${raw}")"
      else
        printf '%s|ok|%s（内联 PEM 内容）' "${fp}" "${src}"
      fi
      ;;
  esac
}

_JWT_API=$(jwt_key_fingerprint_of admin-api)
_JWT_AGENT=$(jwt_key_fingerprint_of ai-agent)
IFS='|' read -r _JWT_API_FP _JWT_API_STATE _JWT_API_SRC <<< "${_JWT_API}"
IFS='|' read -r _JWT_AGENT_FP _JWT_AGENT_STATE _JWT_AGENT_SRC <<< "${_JWT_AGENT}"
echo "  admin-api（签发）: 指纹=${_JWT_API_FP:-<不可判定>} 来源=${_JWT_API_SRC}"
echo "  ai-agent（验签）: 指纹=${_JWT_AGENT_FP:-<不可判定>} 来源=${_JWT_AGENT_SRC}"
if [ "${_JWT_API_STATE}" = "absent" ] && [ "${_JWT_AGENT_STATE}" = "absent" ]; then
  # 唯一允许 SKIPPED 的形态（issue #8989 验收口径）：两侧都走 classpath 默认，宿主面没有配置可判。
  echo "  JWT_KEY_SAME_SOURCE=SKIPPED"
  echo "  ⏭️  JWT 同源断言：**SKIPPED（两侧都走 classpath 默认，宿主面没有配置可判）** ⇒ **不判绿**"
  echo "     ::warning::JWT 同源断言 SKIPPED：admin-api=${_JWT_API_SRC} / ai-agent=${_JWT_AGENT_SRC}"
  echo "     让它可以判定：两侧都显式配「JWT_*」（生产 =「file:/opt/migao-deploy/jwt/…」，见"
  echo "     docs/deployment/production-deployment.md §5.5）后重跑本部署"
elif [ "${_JWT_API_STATE}" != "ok" ] || [ "${_JWT_AGENT_STATE}" != "ok" ]; then
  # 只有一侧可判 / 读到了非公钥形态 ⇒ **不是**「取不到就放过」：那是下一次全 401 的入口。
  echo "  JWT_KEY_SAME_SOURCE=INCOMPLETE"
  echo "  ❌ JWT 同源断言**无法完成**：admin-api=${_JWT_API_STATE}（${_JWT_API_SRC}）/ ai-agent=${_JWT_AGENT_STATE}（${_JWT_AGENT_SRC}）"
  echo "     口径：SKIPPED 只允许「两侧都走 classpath 默认」；一侧有值而另一侧读不到 = 配置不完整，**不得放行**。"
  echo "     排查（只读宿主权威源，不读运行中的容器）：grep '^JWT' /opt/migao-deploy/.env.admin-api /opt/migao-deploy/.env.ai-agent；grep JWT_PUBLIC_KEY docker-compose.yml"
  echo "     修好上面任一处后重跑本部署"
  exit 1
elif [ "${_JWT_API_FP}" != "${_JWT_AGENT_FP}" ]; then
  echo "  JWT_KEY_SAME_SOURCE=MISMATCH"
  echo "  ❌ JWT 验签**不同源**：admin-api=${_JWT_API_FP} / ai-agent=${_JWT_AGENT_FP}"
  echo "     后果：admin-api 签的 token ai-agent 一把都验不过 ⇒ AI 接口**全部 401**（TOKEN_INVALID）"
  echo "     口径：两侧必须读**同一份**公钥（ai-agent 的 JWT_PUBLIC_KEY=file:/opt/migao-deploy/jwt/public.pem，"
  echo "           与 admin-api 的 JWT_PRIVATE_KEY 成对）；见 docs/deployment/production-deployment.md §5.5"
  echo "     排查：grep '^JWT' /opt/migao-deploy/.env.admin-api /opt/migao-deploy/.env.ai-agent；grep JWT_PUBLIC_KEY docker-compose.yml"
  exit 1
else
  echo "  JWT_KEY_SAME_SOURCE=OK"
  echo "  ✅ JWT 验签同源（指纹 ${_JWT_API_FP}）—— admin-api 签发的 token ai-agent 能验"
fi

# ── 2.6 nginx（流量入口本身：独占 80/443、只有一个，不参与蓝绿）──────────────
docker compose up -d --no-deps nginx
# 上游容器重建后 IP 可能变化，nginx 启动时缓存旧上游 IP ⇒ 必须让它重新解析，否则 502。
# 用 **reload**（优雅：旧 worker 把在途请求做完再退）而不是 restart（硬重启 ⇒ 当场丢弃在途连接）；
# reload 不可用/失败 ⇒ 回落 restart（= 改动前的行为，不引入新的坏路径）。
docker compose exec -T nginx nginx -s reload || docker compose restart nginx
# 🔴 reload 只说明「命令发出去了」；入口是否真的指向**新**上游，只能靠探一次本机上游（issue #8976 ④）。
nginx_expect_upstream_ok "nginx 重建后"

# ── 2.6.1 TLS 证书自动续期（宿主 cron；issue #8201）──────────────────────────
# 幂等：/etc/cron.d/migao-tls-renew 内容未变则不重写（`--install-cron` 自己判）。
# 检测到**既有** crontab `certbot renew` 条目 ⇒ **不安装**（否则同一条续期一天跑两遍，
#   两把锁互不知情），改由 runbook 的一条人工命令切换（`--replace-legacy-cron`，先备份 crontab）。
# 任何跳过 / 失败都**不拖垮部署**（部署是主路径），但必须**出声** —— 不许静默。
if [ -f ./tls-renew.sh ]; then
  bash ./tls-renew.sh --install-cron || echo "  ⚠️ TLS 自动续期未安装（原因见上）—— **部署不受影响**；处置见 docs/deployment/tls-renewal.md"
else
  echo "  ⏭️ 跳过 TLS 自动续期安装：盘上没有 ./tls-renew.sh（本次未取源码树）—— **部署不受影响**"
fi


# ══════════════════════════════════════════════════════════════════════════
# 2.7 部署成功后：按**保留策略**清理（issue #4808 ①）——替换原来那句只清 dangling 的
#     `docker image prune -f`（它**不带 `-a`** ⇒ 带 tag 的 `sha-*` 旧镜像**永远不被清**
#     ⇒ 每次部署堆积 ≈3.14GB ⇒ 磁盘单调爬升 ⇒ 撞 95% 中止线）。
#
# 保留集 = 当前在用 tag + `.last-good-tag`（**回滚点，只许保留**）+ 最近 KEEP_RECENT_TAGS 个；
# 其余**只按本项目命名空间前缀**删 ⇒ 非本项目镜像（如 nginx:alpine）一律不碰。
# 回滚点有**三道**独立保护（不许静默丢）：① 它在保留集里；② `cleanup_project_images` 里的
# 逐镜像护栏（不看保留集）⇒ 保留集算错也删不掉它；③ 清理后**事后自检**，吃掉回滚点即告警。
# ══════════════════════════════════════════════════════════════════════════
echo "== 2.7 镜像保留策略清理（当前在用 + 回滚点 + 最近 ${KEEP_RECENT_TAGS} 个）=="
PREV_GOOD=$(rollback_tag)
KEEP_FILE=$(mktemp)
retained_tags "$TAG" "$PREV_GOOD" "$KEEP_RECENT_TAGS" > "$KEEP_FILE"
# 清理**前**的回滚点快照（要 3 个服务都在才算「清理前完整」）
RB_BEFORE_CLEAN=0
if [ -n "$PREV_GOOD" ] && [ "$(rollback_point_count "$PREV_GOOD")" -ge 3 ]; then RB_BEFORE_CLEAN=1; fi
cleanup_project_images "$TAG" "$PREV_GOOD" "$KEEP_FILE"
rm -f "$KEEP_FILE"
# 事后自检：清理前完整、清理后不完整 ⇒ 保留策略吃掉了回滚点（缺了这一步就是"静默失去回滚能力"）
if [ "$RB_BEFORE_CLEAN" = "1" ] && [ "$(rollback_point_count "$PREV_GOOD")" -lt 3 ]; then
  echo "  ::warning::保留策略清理后回滚点 tag=${PREV_GOOD} 不再完整（清理前是 3/3）⇒ 保留集计算有缺陷"
  echo "     人工核对：$LAST_GOOD_FILE 与 docker images 的 \`sha-*\` 命名"
fi
# 兜底：清掉真正的 dangling（无 tag）镜像 —— 保留策略不管这一类
docker image prune -f >/dev/null 2>&1 || echo "⚠️ docker image prune 失败（不影响本次部署）"

# 磁盘水位 + 回滚点**双可观测**（issue #4808 ③）：两个信号都在每次部署的日志里，
# 且都带 `::warning::` 形态 ⇒ 不再出现「只在 >90% 说一句」的静默窗口。
DISK_PCT_AFTER=$(disk_pct)
echo "  清理后磁盘水位：${DISK_PCT_AFTER}%（部署前 ${DISK_PCT}%）"
if [ "${DISK_PCT_AFTER:-0}" -gt "$DISK_WARN_PCT" ]; then
  echo "  ::warning::磁盘水位 ${DISK_PCT_AFTER}% > 告警阈值 ${DISK_WARN_PCT}%：保留策略已在跑，"
  echo "     若持续高于阈值 ⇒ 说明单次增长 > 保留策略的回收量，需扩容或调大清理力度（人工判断）"
fi
report_rollback_point

# ══════════════════════════════════════════════════════════════════════════
# 2.8 磁盘与**容器日志**水位读数（issue #8197 P1-02）—— **只读**，不删任何东西
#
# 病：四个服务的 json-file 日志原先**无上限**（compose 无 `logging:` 段）⇒ 单机磁盘单调爬升；
#     写满后四服务同时 502（`restart: unless-stopped` 救不了「写不进去」），而**没有任何读数**
#     会先变红 —— 「日志到底涨到多少了」改前只能靠人上机器 `du`。
# 修：compose 给每个服务 `max-size: 50m` / `max-file: 3`（见该文件的 `x-logging` 锚点）。
# 本段把**实测占用**打进每次部署的日志（与上面磁盘水位同一形态），并与**上界总和**对账：
#     越过上界 ⇒ 轮转没生效（`logging:` 被删 / docker 不认）⇒ 那是一次**具名**的告警，
#     而不是等磁盘满了才发现。
# 🔴 本段**只读**：不 prune、不 rm、不 truncate 日志文件（无人值守删除不安全 —— 铁律 10）。
# 判据 = tests/unit_ci_workflows/test_swas_container_runtime.py（含「本段不得出现删除动作」）
# ══════════════════════════════════════════════════════════════════════════
echo "== 2.8 磁盘 / 容器日志水位读数（只读；issue #8197 P1-02）=="
LOG_READING=$(container_log_footprint_mb || echo "0 0")
LOG_FOOTPRINT_MB=${LOG_READING%% *}
LOG_CONTAINER_COUNT=${LOG_READING##* }
LOG_CAP_PER_CONTAINER_MB=$(log_cap_per_container_mb)
LOG_CAP_TOTAL_MB=$((LOG_CAP_PER_CONTAINER_MB * LOG_CONTAINER_COUNT))
echo "MIGAO-DISK-WATERMARK root_pct=$(disk_pct) root_free_mb=$(disk_free_mb) container_logs_mb=${LOG_FOOTPRINT_MB} containers=${LOG_CONTAINER_COUNT} log_cap_per_container_mb=${LOG_CAP_PER_CONTAINER_MB} cap_total_mb=${LOG_CAP_TOTAL_MB}"
if [ "${LOG_CONTAINER_COUNT:-0}" -gt 0 ] && [ "${LOG_FOOTPRINT_MB:-0}" -gt "$LOG_CAP_TOTAL_MB" ]; then
  echo "  ::warning::容器 json-file 日志实测 ${LOG_FOOTPRINT_MB}MB > 上界总和 ${LOG_CAP_TOTAL_MB}MB"
  echo "     （= ${LOG_CAP_PER_CONTAINER_MB}MB × ${LOG_CONTAINER_COUNT} 个容器）⇒ **轮转没有生效**："
  echo "     核对 deploy/swas/docker-compose.yml 的 x-logging（max-size=${LOG_CAP_MB}m / max-file=${LOG_MAX_FILES}）"
  echo "     与 \`docker inspect <容器> --format '{{json .HostConfig.LogConfig}}'\`；日志无界增长会把磁盘写满 ⇒ 四服务 502。"
fi

echo "== 3. 健康检查（正式容器，最终判据；与蓝绿预验证**同一份**判据）=="
HC_FAILED=0
for spec in "8080 admin-api /actuator/health" "8000 ai-agent /health" "3001 admin-web /"; do
  # shellcheck disable=SC2086
  set -- $spec
  wait_healthy "$1" "$2" "$3" || HC_FAILED=1
done
if [ "$HC_FAILED" = "1" ]; then
  echo "❌ 健康检查失败，部署中止。排查：cd /opt/migao-deploy && docker compose logs <服务>"
  exit 1
fi

# ══════════════════════════════════════════════════════════════════════════════
# 3.5 `.env.ai-agent` 凭据探针（**只读**；issue #7718 的裁定 B，2026-11-02）
#
# 病（#7718 的实测链）：本脚本**从不写** `.env.ai-agent`（该文件人工维护）⇒ 2026-10-24 语音 /
# 生图切到 MaaS token-plan（#7661）后，服务器那份仍停在**旧百炼 key** ⇒ 线上 `401 InvalidApiKey`，
# 内核按 #7680 归入 `IMAGE_GEN_NO_KEY`，商家看到的是「商品图 AI 生成未配置完成」（同一把 key 也
# 让语音失效）—— 而部署链路**没有任何面**会报这件事，只能等人发现。
#
# 裁定（AI，2026-11-02）：**不**把 MaaS 密钥接进 CI secret（那会让「部署期」变成密钥的**唯一**
# 来源、扩大涉密面），只在部署链路加一条**只读探针**：缺 key ⇒ 打印**可行动告警**
# （缺哪一项 / 怎么补 / 影响是什么）。密钥的直接下发属**未采纳的 A 案**，重启条件见 issue #7718。
#
# 三条纪律（判据 = tests/unit_ci_workflows/test_ai_agent_key_probe.py）：
#   ① **绝不 `exit`**：缺 key 是**运维态**，不是构建失败。本仓 `exit 1` 的先例
#      （`.env.admin-api` 的 SMS_BYPASS_CODE）针对的是「缺了会让**部署产物本身**在错误语义下运行」
#      的显式开关；凭据缺失的形态是**可运行但降级** ⇒ 探针只告警，部署照旧走完。
#   ② **只读**：不改 `.env.ai-agent`、不重建容器（写它需要新的下发通道 —— 那正是裁定 A 排除的）。
#   ③ **绝不打印值**：只打印「已设置（长度 N）」/「未设置」；N 是长度读数，不是值
#      （判据 ③ 用假值注入断言「输出里绝不出现密钥值」）。
#
# 必需项（真名以 backend/ai-agent-service/app/config.py 为准；改名即判据红）：
#   · LLM_API_KEY       = PRIMARY_API_KEY 或 VISION_API_KEY（主推理 / 视觉；与该文件的 property 同口径）
#   · ASR_API_KEY       = 语音（**不回落** PRIMARY_API_KEY，见 #7661）
#   · IMAGE_GEN_API_KEY = 生图（未配时**复用 ASR_API_KEY**，见 app/images/generator.py 的取值行）
# >>> ai-agent-key-probe
MIGAO_AI_ENV_FILE=${MIGAO_AI_AGENT_ENV_FILE:-.env.ai-agent}
# `$1` = 键名 ⇒ stdout = 该键的**非空**值（return 0）；未设置 / 空值 ⇒ return 1、无输出。
# 同名多行取**最后一行**（compose `env_file` 的生效语义）；只去首尾空白与成对引号，不解释值。
_migao_ai_env_val() {
  _migao_ai_line=$(grep -E "^$1=" "$MIGAO_AI_ENV_FILE" 2>/dev/null | tail -1 || true)
  [ -n "$_migao_ai_line" ] || return 1
  _migao_ai_out=${_migao_ai_line#*=}
  _migao_ai_out=$(printf '%s' "$_migao_ai_out" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
  case "$_migao_ai_out" in
    \"*\") _migao_ai_out=${_migao_ai_out#\"}; _migao_ai_out=${_migao_ai_out%\"} ;;
    \'*\') _migao_ai_out=${_migao_ai_out#\'}; _migao_ai_out=${_migao_ai_out%\'} ;;
  esac
  [ -n "$_migao_ai_out" ] || return 1
  printf '%s' "$_migao_ai_out"
}
echo "== 3.5 .env.ai-agent 凭据探针（只读；issue #7718 裁定 B）=="
_migao_ai_missing=0
_migao_ai_status=""
if [ ! -f "$MIGAO_AI_ENV_FILE" ]; then
  echo "  ::warning::盘上没有 ${MIGAO_AI_ENV_FILE}（该文件人工维护，本脚本不创建）⇒ 下列凭据全部视为未设置"
fi
_migao_ai_llm=$(_migao_ai_env_val PRIMARY_API_KEY || true)
_migao_ai_vision=$(_migao_ai_env_val VISION_API_KEY || true)
_migao_ai_asr=$(_migao_ai_env_val ASR_API_KEY || true)
_migao_ai_image_own=$(_migao_ai_env_val IMAGE_GEN_API_KEY || true)
_migao_ai_llm=${_migao_ai_llm:-$_migao_ai_vision}
_migao_ai_image=${_migao_ai_image_own:-$_migao_ai_asr}
if [ -n "$_migao_ai_llm" ]; then
  echo "  ✅ LLM_API_KEY（PRIMARY_API_KEY / VISION_API_KEY）：已设置（长度 ${#_migao_ai_llm}，值不打印）"
  _migao_ai_status="${_migao_ai_status}LLM_API_KEY:set,"
else
  echo "  ::warning::.env.ai-agent 缺 **LLM_API_KEY**（PRIMARY_API_KEY / VISION_API_KEY 都未设置）"
  echo "     影响：主推理 + 视觉全部不可用（C 端米宝 / B 端黄金策 / 入驻 AI 甄别都会失败）"
  echo "     补法：在服务器 ${MIGAO_AI_ENV_FILE} 追加 PRIMARY_API_KEY=<DeepSeek key>（或 VISION_API_KEY=<同一把 key>）"
  _migao_ai_missing=$((_migao_ai_missing + 1))
  _migao_ai_status="${_migao_ai_status}LLM_API_KEY:missing,"
fi
if [ -n "$_migao_ai_asr" ]; then
  echo "  ✅ ASR_API_KEY：已设置（长度 ${#_migao_ai_asr}，值不打印）"
  _migao_ai_status="${_migao_ai_status}ASR_API_KEY:set,"
else
  echo "  ::warning::.env.ai-agent 缺 **ASR_API_KEY**"
  echo "     影响：语音识别 fail-closed（503「未配置」）—— 它**不回落** PRIMARY_API_KEY"
  echo "           （#7661：那是 DeepSeek 的 key，打到百炼只会 401）"
  echo "     补法：在服务器 ${MIGAO_AI_ENV_FILE} 追加 ASR_API_KEY=<MaaS token-plan key，形如 sk-sp-…>"
  _migao_ai_missing=$((_migao_ai_missing + 1))
  _migao_ai_status="${_migao_ai_status}ASR_API_KEY:missing,"
fi
if [ -n "$_migao_ai_image" ]; then
  if [ -n "$_migao_ai_image_own" ]; then
    echo "  ✅ IMAGE_GEN_API_KEY：已设置（长度 ${#_migao_ai_image_own}，值不打印）"
  else
    echo "  ✅ IMAGE_GEN_API_KEY：未单独设置，**复用 ASR_API_KEY**（长度 ${#_migao_ai_image}，值不打印）"
  fi
  _migao_ai_status="${_migao_ai_status}IMAGE_GEN_API_KEY:set,"
else
  echo "  ::warning::.env.ai-agent 缺 **IMAGE_GEN_API_KEY**（且 ASR_API_KEY 也为空 ⇒ 没有可复用的 MaaS key）"
  echo "     影响：建品页「AI 生成商品图」返回 IMAGE_GEN_NO_KEY ⇒ 商家看到「商品图 AI 生成未配置完成」"
  echo "           （#7680 的凭证失败语义 / #7718 的现场）"
  echo "     补法：在服务器 ${MIGAO_AI_ENV_FILE} 追加 IMAGE_GEN_API_KEY=<MaaS token-plan key>，或只补 ASR_API_KEY（生图会复用）"
  _migao_ai_missing=$((_migao_ai_missing + 1))
  _migao_ai_status="${_migao_ai_status}IMAGE_GEN_API_KEY:missing,"
fi
if [ "$_migao_ai_missing" -gt 0 ]; then
  echo "  📋 补齐动作（缺 key **不判失败**：本次部署已按流程走完，凭据缺失是运维态）"
  echo "     1) 在服务器改 ${MIGAO_AI_ENV_FILE}（本脚本**不写**它 —— 人工维护、不入库）"
  echo "     2) 改完必须 recreate（env_file 变更不重读），**并且**让 nginx 重新解析上游"
  echo "        （重建换 IP ⇒ 不 reload 就是全站 502，实测 90 秒；issue #8976）："
  echo "        docker compose -f docker-compose.yml -f docker-compose.bluegreen.yml up -d --no-deps --force-recreate ai-agent"
  echo "        docker compose exec -T nginx nginx -s reload || docker compose restart nginx"
  echo "        自证（站点域 = \${MIGAO_PUBLIC_DOMAIN}，本机探测，必须 200）："
  # ⚠️ `$` 必须**转义**（只打印给人抄）：本探针块会被判据**单独 source** 执行
  #    （tests/unit_ci_workflows/test_ai_agent_key_probe.py），那里没有 MIGAO_PUBLIC_DOMAIN
  #    ⇒ 真展开会 `set -u` 当场 unbound variable（实测 5 条判据红）。
  echo "        curl -sk -o /dev/null -w '%{http_code}\\n' --resolve \"api.\${MIGAO_PUBLIC_DOMAIN}:443:127.0.0.1\" \"https://api.\${MIGAO_PUBLIC_DOMAIN}/api/version\""
  echo "     3) 自证：容器内 ASR_API_KEY 指纹应为 sk-sp-…（MaaS）而不是 35 字节的旧百炼 key；curl -fsS http://127.0.0.1:8000/health"
  echo "     4) 密钥来源 / 轮换流程见 issue #7718（含 2026-10-25 的线上热修记录）"
fi
echo "  AI_AGENT_KEY_STATUS=${_migao_ai_status%,} MISSING=${_migao_ai_missing}（探针只读，不改部署结果）"
# <<< ai-agent-key-probe
# ── 迁移结果可观测（issue #4936 实测教训）────────────────────────────────────────
# `MigrationRunner` 的语义是「**单条失败只跳过这一条**、继续跑后面的」，且**不参与健康判定**
# ⇒ 整批迁移失败时**部署照样全绿**（实测 2026-09-20：V102~V106 在云测试环境静默未生效，
# 而蓝绿预验证、正式健康检查、Post-Deploy Smoke 全过 —— 只有读库/翻容器日志才能发现）。
# 这里把 admin-api 最近 200 行里的**迁移行**打进本次部署日志：它是「迁移到底跑没跑」的
# **唯一可见面**（本脚本 stdout 会回流到 CI 日志）。`grep` 无命中不算失败（可能未重启容器）。
echo "== 4. admin-api 迁移结果（MigrationRunner 事实 —— 静默迁移失败的唯一可见面）=="
docker compose logs --tail=1500 admin-api 2>&1 | grep -aE "MigrationRunner|迁移|PSQLException|Caused by|ERROR: " \
  || echo "  （最近 1500 行里没有迁移行：容器可能未重启，或日志已被轮转）"

# 迁移失败闸门兜底（issue #5792）：上面那段只是**打印事实**；这里把它变成**判红** ——
# 应急开关（`.blue-green-off`）跳过蓝绿时没有 green 可查，只能在此兜住。
# 只认 ERROR 形态的「❌ 迁移失败」（INFO 的「ℹ️ 迁移失败…」= 已知存量非幂等，不算）。
if docker compose logs --tail=1500 admin-api 2>&1 | grep -q "❌ 迁移失败"; then
  echo "  ❌ admin-api **迁移失败**（schema 可能与代码不一致）⇒ 本次部署判失败"
  echo "     恢复：见上文「恢复：IMAGE_TAG=…」；修好数据/迁移后重跑该 tag 的部署"
  exit 1
fi

echo "== deploy.sh 完成（耗时主要取决于镜像拉取） =="
