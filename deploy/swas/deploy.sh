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
    echo "   内核都会关闭 fd 并释放锁（见 docs/wiki/CI-CD.md 的「远端 flock 与超时强杀的关系」）。"
    echo "   ⇒ 处置：**不要**手工清 $LOCK 后重试（它不会被遗留 ⇒ 清了也不会变快），也**不要** kill 占用者"
    echo "     （它多半正在**正常**部署，kill 只会留下半截环境）。等它跑完，下次部署会正常拿到锁。"
    echo "   次要核对（只想知道占用者是谁时）：fuser -v $LOCK"
    exit 1
  fi
fi
trap 'flock -u 9' EXIT

cd /opt/migao-deploy
TAG=${1:-latest}
REGISTRY=${ACR_REGISTRY:-crpi-qdcgkzwx9p9zckga.cn-hangzhou.personal.cr.aliyuncs.com}

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

# ACR 登录（**唯一一份**）：1.9 的「回滚点补回」与第 2 步的常规拉取共用 ⇒ 判据/凭据读取不会漂移。
# ACR 是私有仓库（docs/wiki/CI-CD.md：服务器需凭据拉私有镜像）⇒ 补回前必须先登录，否则必然失败。
# ⚠️ 本函数**在 C′ 本地构建时也照常登录**：虽然本次镜像本地构建、不推 ACR，但 1.9 的
#    「深度清理后从 ACR 补回回滚点」仍需凭据（回滚点是**上一次**推上去的 tag）⇒ 不能因为
#    本次走本地构建就跳过登录（那会把「失败即回滚」的能力悄悄砍掉）。
registry_login() {
  if [ -f .env.registry ]; then
    # shellcheck disable=SC1091
    . ./.env.registry
    if [ -n "${ACR_USERNAME:-}" ] && [ -n "${ACR_PASSWORD:-}" ]; then
      echo "$ACR_PASSWORD" | docker login "$REGISTRY" -u "$ACR_USERNAME" --password-stdin >/dev/null 2>&1 || true
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


CONFIG_REF_RESOLVED=$(config_ref_for_tag "$TAG")
if [ -z "$CONFIG_REF_RESOLVED" ]; then
  echo "❌ 无法把镜像 tag 追溯到具体 commit（tag=${TAG}）⇒ **拒绝用 main 的配置**（issue #5083）"
  echo "   配置（compose/nginx）必须与镜像**同一 commit**：否则回滚时是「旧镜像 + 新配置」（未定义行为、且不报错）"
  echo "   修法：改用 \`sha-<7位hex>\` 形态的 tag（= CI 部署的正常形态）"
  exit 1
fi
echo "== 1. 同步 repo 内 canonical compose + nginx 配置（ref=${CONFIG_REF_RESOLVED}，与镜像 tag=${TAG} 同源）=="
# ⚠️ 这一段是「配置与镜像同源」的**唯一**落点（issue #5083）：URL 的 ref 来自 `$CONFIG_REF_RESOLVED`，
#    它由 `config_ref_for_tag "$TAG"` 推导 ⇒ 脚本里**不存在**「无条件取 main 配置」的路径。
if ! curl -fsSL --retry 3 --retry-delay 5 --connect-timeout 15 --max-time 120 -o src.tar.gz "$CONFIG_TARBALL_BASE/$CONFIG_REF_RESOLVED"; then
  echo "  ❌ 取不到 tag=${TAG} 对应的配置（ref=${CONFIG_REF_RESOLVED}）⇒ **中止部署**（绝不回落到 main 的配置）"
  echo "     · 若 tag 是 latest 这类**移动 tag**（追不到具体 commit）⇒ 改用 sha-<7位hex> 形态的 tag"
  echo "     · 否则核对：该 commit/tag 在 zhaokai-mgzn/migao 上存在且可达"
  exit 1
fi
rm -rf src && mkdir -p src && tar xzf src.tar.gz -C src --strip-components=1
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
cp src/deploy/swas/nginx.conf ./nginx/nginx.conf
# 蓝绿 override（issue #4785）：**只新增** green 探针服务，不改既有服务定义
cp src/deploy/swas/docker-compose.bluegreen.yml ./docker-compose.bluegreen.yml

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
if [ -n "$BUILD_SERVICE" ]; then
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
  # ⚠️ `|| true`：本脚本是 `set -euo pipefail` ⇒ 命令替换里任一环失败会**当场静默退出**
  #    （连下面那句 ❌ 都打不出来）⇒ 显式吞掉非零，交由紧随其后的 `-z` 判定给出可行动报错。
  _image_ref=$(docker compose config --format json 2>/dev/null \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["services"][sys.argv[1]].get("image",""))' "$_svc" 2>/dev/null || true)
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
  _df_mb=$(df -Pk / | awk 'NR==2 {print int($4/1024)}' || true)
  _need_mb=${BUILD_MIN_FREE_MB:-4096}
  echo "  构建前磁盘可用：${_df_mb}MB（门槛 ${_need_mb}MB）"
  if [ "${_df_mb:-0}" -lt "$_need_mb" ]; then
    echo "  ❌ 磁盘可用 ${_df_mb}MB < 门槛 ${_need_mb}MB ⇒ **中止构建**（旧容器保持不动、环境未受影响）"
    echo "     回收出口（**人工**，本脚本不做无人值守删除 —— 铁律 10）："
    echo "       · 遗留旧源码克隆：/opt/migao（2026-08-13 残留，实测 2.2 GB）"
    # ⚠️ 本行**故意不逐字写出**「清掉所有未使用镜像」那条命令：它是被
    #    tests/unit_ci_workflows/test_swas_deploy_disk_retention.py 判红的形态
    #    （不带保留集 ⇒ 会连带删掉回滚点）⇒ 说明文字里写出字面量会被那条判据正确判红。
    echo "       · 清掉所有未使用镜像（prune 的 all 档，约 2.4 GB）—— ⚠️ 它**不带保留集**，会连带删掉回滚点；"
    echo "         只许在人工确认「当前在用 + .last-good-tag 都在保留范围」之后执行，见第 0 段保留策略"
    echo "       · 构建缓存：docker builder prune --filter until=168h（**保留 7 天内**，别用 -af）"
    echo "       · 或扩容磁盘（用户 2026-09-30 已表态「有必要会扩容」）"
    exit 1
  fi
  # ── 构建参数 ───────────────────────────────────────────────────────────────
  _build_args=(--build-arg "APT_MIRROR=$APT_MIRROR")
  if [ -n "$PIP_INDEX_URL" ]; then _build_args+=(--build-arg "PIP_INDEX_URL=$PIP_INDEX_URL"); fi
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
    _build_args+=(--build-arg "NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL:-https://api.migaozn.com}")
    _build_args+=(--build-arg "NEXT_PUBLIC_AI_API_BASE_URL=${NEXT_PUBLIC_AI_API_BASE_URL:-https://ai-api.migaozn.com}")
    _build_args+=(--build-arg "NEXT_PUBLIC_COOKIE_DOMAIN=${NEXT_PUBLIC_COOKIE_DOMAIN:-.migaozn.com}")
    _build_args+=(--build-arg "NEXT_PUBLIC_BMINI_H5_URL=${NEXT_PUBLIC_BMINI_H5_URL:-https://app.migaozn.com/b/}")
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
  # ── 构建后回收（**非破坏性**，铁律 10 口径：只清构建缓存，不删带 tag 的镜像）──────
  # `until=168h` = 只清 7 天前的缓存 ⇒ 保住稳态秒级所需的热层；`-a` 一律不用。
  docker builder prune -f --filter until=168h >/dev/null 2>&1 \
    || echo "  ⚠️ docker builder prune 失败（不影响本次部署；缓存偏多时人工清理）"
  _df_after_mb=$(df -Pk / | awk 'NR==2 {print int($4/1024)}' || true)
  _cache_mb=$(docker system df --format '{{.Type}} {{.Size}}' 2>/dev/null | awk '$1=="Build Cache"{print $2}' || true)
  echo "  构建后磁盘可用：${_df_after_mb}MB（构建前 ${_df_mb}MB）／构建缓存：${_cache_mb:-?}"
  if [ "${_df_after_mb:-0}" -lt "$_need_mb" ]; then
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
        echo "     ⇒ 本次部署若失败，#4767 的自动回滚**没有回滚点**，需人工介入（见 docs/wiki/CI-CD.md）"
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
# 0.6s/HTTP 200 ⇒ 本地没有可用的历史、API 才是可靠判据（复核数据见 docs/wiki/CI-CD.md）。
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
# 取舍（issue #4785 要求逐条说明）：走**第二端口**而不是 **nginx upstream 切换** ——
# nginx.conf 里 `proxy_pass http://admin-api:8080` 走 compose DNS 名，nginx 在**启动/reload 时**
# 解析并缓存上游 IP；改 nginx.conf 写坏 = **全站所有域名同时挂**（正是「部署脚本改坏 = 停掉
# 所有人的部署」的形态）⇒ 本单不碰它。代价（如实登记）：**成功路径**仍有「替换正式容器 +
# 启动 + reload」的秒级窗口 —— 与改动前**同量级、未变差**，且此刻镜像已被证明能起；
# **失败路径**（坏镜像）的窗口已被打到 **0**。
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

  # ── ② 切换：替换正式容器（走过蓝绿 ⇒ 该镜像刚刚已被证明能起）──
  docker compose up -d --no-deps "$svc"
  if ! wait_healthy "$(svc_port "$svc")" "$svc" "$GPATH"; then
    echo "  ❌ $svc 正式容器替换后健康检查未通过 ⇒ 中止"
    echo "     交给 CI 侧 #4767 的「失败即回滚」（回滚到 .last-good-tag）兜底"
    exit 1
  fi

  # ── ③ 正式容器接棒 ⇒ 删掉 green 探针（不长期占内存/端口）──
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

# ── 2.6 nginx（流量入口本身：独占 80/443、只有一个，不参与蓝绿）──────────────
docker compose up -d --no-deps nginx
# 上游容器重建后 IP 可能变化，nginx 启动时缓存旧上游 IP ⇒ 必须让它重新解析，否则 502。
# 用 **reload**（优雅：旧 worker 把在途请求做完再退）而不是 restart（硬重启 ⇒ 当场丢弃在途连接）；
# reload 不可用/失败 ⇒ 回落 restart（= 改动前的行为，不引入新的坏路径）。
docker compose exec -T nginx nginx -s reload || docker compose restart nginx

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
