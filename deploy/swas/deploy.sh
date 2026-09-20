#!/bin/bash
# migao 快速部署脚本：SWAS 服务器拉取 CI 预构建镜像（不做源码构建）
#
# 流程：拉 repo 内 canonical compose/nginx → pull 镜像 → up -d → 健康检查
# 服务器每次部署从"源码构建 3 个服务（10-30min）"降为"拉镜像 + 滚动更新（<2min）"。
#
# 并发安全：flock 串行化（CI 可能并行触发）。
# 镜像 tag：${1:-latest}，CI 默认推 latest。
# 镜像仓库登录：若存在 .env.registry（ACR_USERNAME/ACR_PASSWORD）则登录；
#               ACR 仓库设为公开读时无需登录。
set -euo pipefail

LOCK=/tmp/migao-deploy.lock
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "== 检测到另一个部署正在进行，等待其完成（最多 10 分钟）=="
  if ! flock -w 600 9; then
    echo "❌ 等待部署锁超时（10 分钟）：可能有卡死的部署进程持有 $LOCK"
    echo "   排查：fuser -v $LOCK 找到占用 PID，确认后 kill；确认无进程后再删锁文件重试"
    exit 1
  fi
fi
trap 'flock -u 9' EXIT

cd /opt/migao-deploy
TAG=${1:-latest}
REGISTRY=${ACR_REGISTRY:-crpi-qdcgkzwx9p9zckga.cn-hangzhou.personal.cr.aliyuncs.com}

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


echo "== 1. 同步 repo 内 canonical compose + nginx 配置 =="
curl -fsSL --retry 3 --retry-delay 5 --connect-timeout 15 --max-time 120 -o src.tar.gz https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/refs/heads/main
rm -rf src && mkdir -p src && tar xzf src.tar.gz -C src --strip-components=1
mkdir -p nginx certbot-www
cp src/deploy/swas/docker-compose.yml ./docker-compose.yml
cp src/deploy/swas/nginx.conf ./nginx/nginx.conf
# 蓝绿 override（issue #4785）：**只新增** green 探针服务，不改既有服务定义
cp src/deploy/swas/docker-compose.bluegreen.yml ./docker-compose.bluegreen.yml

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
  docker system prune -af --volumes 2>/dev/null || docker system prune -af 2>/dev/null || true
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

echo "== 2. 拉取镜像（tag=${TAG}）=="
registry_login
export IMAGE_TAG="$TAG"
# 逐服务拉取：某个镜像尚未推送（首次接入）时跳过该服务，其余照常滚动更新
UP_SERVICES="nginx"
for svc in admin-api ai-agent admin-web; do
  if timeout 180 docker compose pull "$svc" >/dev/null 2>&1; then
    UP_SERVICES="$UP_SERVICES $svc"
  else
    echo "  ⚠️ $svc 镜像拉取失败/超时（可能尚未推送 :${TAG}），跳过该服务"
  fi
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
echo "== deploy.sh 完成（耗时主要取决于镜像拉取） =="
