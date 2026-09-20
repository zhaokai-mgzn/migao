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


# ══════════════════════════════════════════════════════════════════════════
# 2.5a 的状态变量（issue #4828）—— **必须在第 1 步覆盖配置文件之前读**。
#
# 运行中的 nginx 的上游色 == 「上一次成功 reload 时的配置文件内容」；而第 1 步**每次**都会把
# canonical（正式色）配置抄进 `$NGINX_CONF` ⇒ 那之后就再也看不出「上一轮把流量留在了 green」。
# ⇒ 残留切换快照只能在这里读（本单第一版把快照放在第 1 步之后 ⇒ 判据恒为「正式色」⇒ **死代码**）。
#
# 判据 = `$NGINX_CONF` **与它的上一版备份** `$NGINX_CONF_BAK` 里是否还有 `server <svc>-green:<端口>;`。
# 为什么要连备份一起看：②.5「写回正式色」是「先写文件、再 reload」，若在两者之间被强杀，
# **文件已是正式色而运行态仍指着 green**（green 容器还在，因为第 ③ 步没跑到）⇒ 只看文件会漏判，
# 漏判的后果 = 下一轮把唯一还在服务的 green 容器删掉 ⇒ **全站所有域名同时 502**。
# ⚠️ 备份会在每轮**干净收口**时被归一化成正式色（见 2.6 之后那段）⇒「备份里出现 green」专指「上一轮没走完」。
# ══════════════════════════════════════════════════════════════════════════
NGINX_CONF=${NGINX_CONF:-./nginx/nginx.conf}
NGINX_CONF_BAK=${NGINX_CONF_BAK:-$NGINX_CONF.last-good}
BG_PREV_GREEN=$(grep -hoE 'server[[:space:]]+[a-z0-9-]+-green:[0-9]+;' \
                  "$NGINX_CONF" "$NGINX_CONF_BAK" 2>/dev/null \
                | sed -E 's/^.*[[:space:]]+//; s/-green:.*$//' | sort -u | tr '\n' ' ' || true)

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

# `sha-<hex>` → 提交 sha；其它形态（latest / v1.2.3 / 空）⇒ 空串（= 没有提交序可判）
tag_to_sha() {
  local t=${1#sha-}
  case "$t" in
    *[!0-9a-f]*|"") echo ""; return 0 ;;
  esac
  if [ "${#t}" -ge 7 ]; then echo "$t"; else echo ""; fi
  return 0
}

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

# ══════════════════════════════════════════════════════════════════════════
# 2.5a nginx 上游切换（issue #4828）：把 #4785 如实登记的**成功路径残留窗口**打到 0
#
# 残留窗口的确切位置 = 下面循环的第 ② 步 `docker compose up -d --no-deps <svc>`：它走的是 compose 的
# **替换**语义（停旧 → 删旧 → 建新 → 起新），而 nginx 在**启动/reload 时**解析并缓存上游 IP
# （`proxy_pass http://admin-api:8080` 走 compose DNS 名）⇒ 从「旧容器已被删」到「正式容器健康 +
# nginx reload 完成」这段时间里，nginx 指向的是**已经没人监听的上游** ⇒ **502**。
# 真机实测这段 ≈ 容器重建 + JVM 启动（几十秒）；`wait_healthy` 跑在第 ② 步**之后** ⇒ 它只能**事后发现**，
# 覆盖不了这段（这正是 #4785 登记「与改动前同量级、未变差」的那一段）。
#
# 本段把每个服务的上游抽成 nginx.conf 里的一个 `upstream` 块（**每服务恰好一行 `server`**），
# 「切流量」= **就地改那一行**（正式色 ⇄ green 色），于是第 ② 步期间流量走在**已通过健康检查的 green** 上：
#   ①.5 green 健康（判据 = 第 3 步那份 `wait_healthy`）⇒ 改一行 → `nginx -t` → reload ⇒ 流量到 green；
#       ①.5 / ②.5 都只在 `BG_SWITCH_ON=1`（非应急开关 ∧ nginx 在跑）时执行 —— 其余情况一个字都不改配置。
#   ②   替换正式容器（这段空档没有任何请求打在正式容器上）；
#   ②.5 正式容器健康 ⇒ 改回正式色 → 校验 → reload ⇒ **才**在第 ③ 步删 green。
# ⇒ **成功路径窗口 = 0**（前提：本段真的执行了 —— 见 ⓖ）。失败路径的窗口在 #4785 已是 0，本段**不碰**它：
#    green 不健康 ⇒ 在第 ① 步就 `exit 1`，上游**一个字都没改**（下面 ①.5 在第 ① 步之后）。
#
# 🔴 写坏 nginx.conf = **全站所有域名同时挂**（#4785 当初不做这一步的理由）⇒ 逐条对消：
#   ⓐ 只改**一行**：判据 = 该服务的可切上游行必须**恰好 1 行**，改不动/改多处 ⇒ **不切**（fail-closed）；
#   ⓑ **先校验后落盘**：候选经 stdin 送进**正在运行的 nginx**，用 `nginx -t`（主配置 wrapper）解析候选
#      ⇒ 候选不过 ⇒ **联机文件一字未改**（真机实证：指向不存在的 green 会被 `host not found in upstream` 拦住）；
#   ⓒ 落盘用**原地改写**（`cat > 文件`，同 inode）—— `mv` / `sed -i` 会**换 inode** ⇒ 容器读到的还是旧文件
#      **且不报错**（docs/wiki/CI-CD.md 的 bind mount 小节已更正这条）；
#   ⓓ 落盘后**再** `nginx -t`（这次校验 nginx 真正会加载的那份文件）；reload 之前任何一步失败 ⇒ 就地写回
#      `nginx.conf.last-good` ⇒ 不 reload ⇒ 仍在跑的 worker 继续服务，部署中止；
#   ⓔ **可捕获的退出路径**：EXIT trap 若发现上游仍停在 green 色 ⇒ 写回正式色（正式容器不健康时
#      **保持指向 green** 并保留该 green 容器继续服务）⇒ 不把「当前激活色」留给下一轮。
#   ⓕ **不可捕获的退出路径**（SIGKILL / 强杀 ⇒ trap 根本不运行）：由**下一轮开头**的
#      「残留切换收敛」兜底 —— 判据是**第 1 步之前**读的快照（`$NGINX_CONF` ∪ `$NGINX_CONF_BAK`
#      里出现过的 `-green` 上游），因为第 1 步会把文件覆盖回正式色、事后无法再判。
#      收敛 fail-closed：正式容器健康 ⇒ 强制 reload 收回正式色（**不能**走 `bg_switch_upstream`
#      的「文件已等于目标 ⇒ 无需切换」短路 —— 那正是「不 reload、收不回来」的漏洞）；
#      不健康 ⇒ **本轮不碰任何容器**、中止（green 继续服务，站点不挂），放行口 = `touch $BG_OFF_FILE`。
#      ⚠️ 没有这一步，本段**自己**会引入一个比原窗口更糟的坏路径：nginx 还指着上一轮的 green 时，
#         `rm -sf $BG_GREENS` 会把**唯一在服务的后端**删掉 ⇒ 全站所有域名同时 502。
#   ⓖ **前提**：需要真有一个"在跑的 nginx"（判据 = 在该容器里跑 `nginx -t`）。首次部署时它尚未起、
#      且此刻也起不来（canonical 配置的上游容器还不存在 ⇒ `host not found in upstream`）⇒
#      跳过上游切换、走 #4785 原路径（nginx 由 2.6 起，那时正式容器已换好）。
# ══════════════════════════════════════════════════════════════════════════
# ⚠️ `NGINX_CONF` / `NGINX_CONF_BAK` 定义在脚本开头（**第 1 步之前** —— 残留切换快照必须先于
#    第 1 步的配置覆盖读取），两个变量跟着一起上移，保持**唯一一份**定义。
UPSTREAM_SERVICES="admin-api ai-agent admin-web"
BG_SWITCHED=""
# 上游目标容器名：正式色 = compose 服务名（与 docker-compose.yml 一致）；green 色 = `<服务>-green`
upstream_host() {
  case "$2" in
    green) echo "$1-green" ;;
    *)     echo "$1" ;;
  esac
}
# 候选配置（**只算不写**）：把该服务在 upstream 块里的那一行 `server <容器名>:<端口>;` 换成目标色
nginx_conf_candidate() {
  sed -E "s|^([[:space:]]*server[[:space:]]+)[^[:space:]]*:$(svc_port "$1");$|\1$(upstream_host "$1" "$2"):$(svc_port "$1");|" "$NGINX_CONF"
}
# **先校验后落盘**：候选片段走 stdin 进正在运行的 nginx（不落联机路径），用 nginx 真身解析候选。
# wrapper 只为给片段一个合法的 main 上下文（片段本身是 conf.d 片段，不能直接 `-c`）；
# 解析会**真的做 DNS 解析** ⇒ 目标容器不存在时这里就会失败（正是我们要拦的形态）。
nginx_conf_validate() {
  docker compose exec -T nginx sh -c '{ echo "events { worker_connections 64; }"; echo "http {"; cat; echo "}"; } > /tmp/migao-nginx-candidate.conf && nginx -t -c /tmp/migao-nginx-candidate.conf'
}
# **就地改写**（同 inode）：不许用 `mv` / `sed -i`（换 inode ⇒ 容器读旧文件且不报错）
nginx_conf_write_in_place() {
  cat > "$NGINX_CONF"
}
# 把**运行中的** nginx 重新加载到当前文件内容：**不比较、不短路**。
# 只用于「文件已是正式色、而运行态可能还指着 green」这种只有 reload 才能纠正的状态 ——
# 在那种状态下 `bg_switch_upstream` 会走「文件已等于目标 ⇒ 无需切换」的短路（**不 reload** ⇒ 收不回来）。
# 失败 ⇒ 保持现状（上一版配置仍在服务、旧 worker 继续跑），由调用方决定怎么处置。
bg_reload_nginx() {
  if ! docker compose exec -T nginx nginx -t >/dev/null 2>&1; then
    echo "  ❌ 联机配置未通过 nginx -t ⇒ 不 reload（上一版配置仍在服务，旧 worker 继续跑）"
    return 1
  fi
  if ! docker compose exec -T nginx nginx -s reload; then
    echo "  ❌ nginx reload 失败 ⇒ 保持现状（上一版配置仍在服务，旧 worker 继续跑）"
    return 1
  fi
  return 0
}
# 记账：仍停在 green 色的服务（EXIT trap 按它决定要不要写回）
bg_mark_switched() {
  local s out=""
  for s in $BG_SWITCHED; do [ "$s" = "$1" ] || out="$out $s"; done
  if [ "$2" = "green" ]; then out="$out $1"; fi
  BG_SWITCHED="$out"
}
# 把某服务的上游切到目标色：0 = 上游已停在目标色（联机文件 = 目标色、nginx 已 reload）
bg_switch_upstream() {
  local svc=$1 color=$2 host port cand n_src n_dst
  host=$(upstream_host "$svc" "$color")
  port=$(svc_port "$svc")
  if [ -z "$host" ] || [ -z "$port" ]; then
    echo "  ❌ 未知服务 ${svc}（拿不到上游名/端口）"; return 1
  fi
  cand=$(nginx_conf_candidate "$svc" "$color") || { echo "  ❌ ${svc}: 生成候选配置失败"; return 1; }
  # ⓐ 判据：该服务的可切上游行**恰好 1 行**，且候选把它改成了目标色
  n_src=$(grep -cE "^[[:space:]]*server[[:space:]]+[^[:space:]]*:${port};$" "$NGINX_CONF" || true)
  n_dst=$(printf '%s\n' "$cand" | grep -cE "^[[:space:]]*server[[:space:]]+${host}:${port};$" || true)
  if [ "$n_src" != "1" ] || [ "$n_dst" != "1" ]; then
    echo "  ❌ ${svc}: nginx.conf 里该服务的可切上游不是恰好 1 行（现状 ${n_src} / 目标 ${n_dst}）⇒ **不切**"
    return 1
  fi
  if [ "$cand" = "$(cat "$NGINX_CONF")" ]; then
    echo "  ℹ️  ${svc} 上游已在 ${host}:${port}（无需切换）"
    bg_mark_switched "$svc" "$color"
    return 0
  fi
  # ⓑ 先校验后落盘
  if ! printf '%s\n' "$cand" | nginx_conf_validate; then
    echo "  ❌ ${svc}: 候选配置未通过 nginx -t（**联机配置一字未改**）⇒ 不切上游"
    return 1
  fi
  cp "$NGINX_CONF" "$NGINX_CONF_BAK"
  printf '%s\n' "$cand" | nginx_conf_write_in_place
  # ⓓ 落盘后再校验一次（这次校验的是 nginx 真正会加载的那份文件）
  if ! docker compose exec -T nginx nginx -t; then
    echo "  ❌ ${svc}: 落盘后 nginx -t 未通过 ⇒ 就地写回上一版（未 reload ⇒ 旧 worker 继续服务）"
    cat "$NGINX_CONF_BAK" | nginx_conf_write_in_place
    return 1
  fi
  if ! docker compose exec -T nginx nginx -s reload; then
    echo "  ❌ ${svc}: nginx reload 失败 ⇒ 就地写回上一版（未生效 ⇒ 旧 worker 继续服务）"
    cat "$NGINX_CONF_BAK" | nginx_conf_write_in_place
    return 1
  fi
  echo "  ✅ ${svc} 上游已切到 ${host}:${port}（先校验后落盘 + nginx -t + 优雅 reload）"
  bg_mark_switched "$svc" "$color"
  return 0
}
# EXIT trap 用：**单次**探针（不重试）—— 收尾阶段不许再堵 100s（重试预算留给正式判据 wait_healthy）
bg_official_healthy_now() {
  ( HC_RETRIES=1 HC_INTERVAL_SECONDS=0 \
      wait_healthy "$(svc_port "$1")" "$1" "$(svc_health_path "$1")" ) >/dev/null 2>&1
}
bg_restore_upstreams_at_exit() {
  local svc
  for svc in $BG_SWITCHED; do
    [ -n "$svc" ] || continue
    if bg_official_healthy_now "$svc"; then
      bg_switch_upstream "$svc" official >/dev/null 2>&1 || true
    else
      echo "  ⚠️ ${svc} 正式容器此刻不健康 ⇒ **保持上游指向 green**（该 green 容器刻意不删，继续服务）"
      echo "     ⇒ 下一轮部署开头的「残留切换收敛」会先把它写回正式色（判据见脚本开头的 $NGINX_CONF_BAK 快照）"
    fi
  done
}
# ⚠️ EXIT trap 只有一个（后设覆盖先设）：把开头的「只解锁」升级为「先写回正式色 + 再解锁」。
#    开头那条 trap 仍是脚本前半段（本段之前）生效的那条，两条都保留。
trap 'bg_restore_upstreams_at_exit; flock -u 9' EXIT

echo "== 2.5 严格蓝绿预验证（新容器先起 + 健康检查通过再切流量）=="
BG_VERIFIED=""
BG_SKIP=0
# 上游切换开关（#4828）：默认**关**；只有「非应急开关 ∧ nginx 在跑且联机配置可加载」才开。
# 关着 = **一个字都不改** nginx.conf（完全走 #4785 的原路径）—— 不做「半开半关」的中间态。
BG_SWITCH_ON=0
if [ -f "$BG_OFF_FILE" ]; then
  BG_SKIP=1
  echo "  ⏭️  存在 $BG_OFF_FILE ⇒ **跳过蓝绿预验证**（回到 #4767 的「失败即回滚」兜底路径）"
  echo "      ⚠️ 本次新镜像**未被预验证**：失败时靠 CI 侧回滚兜底（窗口 ≈2-4min）"
  echo "      ⚠️ 应急开关同时**关掉上游切换**（不切上游、不删 green）—— 与 #4785 的应急语义一致"
else
  echo "  green 第二端口：admin-api=$BG_ADMIN_API_PORT ai-agent=$BG_AI_AGENT_PORT admin-web=$BG_ADMIN_WEB_PORT"
  # ── ① 上游切换的**可行性**（#4828）：必须真有一个"在跑的 nginx"才动上游 ──
  # 判据 = 直接在 nginx 容器里 `nginx -t`：一次同时证明「nginx 在跑」+「联机配置能加载」。
  # 两条必需性（都是真实形态，不是假想）：
  #   · **首次部署**（新环境还没有任何容器）：nginx 尚未起，且**此刻也起不来** —— canonical 配置
  #     `proxy_pass http://migao_admin_api` 的上游容器都还不存在（`host not found in upstream`）；
  #     此刻也确实**没有流量**可切（nginx 没在服务任何人）。
  #   · nginx 未运行：站点本已不可用，「切流量」无从谈起。
  # ⇒ 任一情形都**跳过上游切换**（走 #4785 原路径，nginx 仍由 2.6 起）；绝不半开半关。
  BG_NGINX_UP=0
  if docker compose exec -T nginx nginx -t >/dev/null 2>&1; then BG_NGINX_UP=1; fi
  if [ "$BG_NGINX_UP" = "1" ]; then
    BG_SWITCH_ON=1
  else
    echo "  ⏭️  nginx 未在跑（首次部署 / nginx 不可用）⇒ **跳过上游切换**（配置一字未改）"
    echo "      此刻没有可切的流量；nginx 由 2.6 起（那时正式容器已换好）"
  fi
  # ── ② 残留切换收敛（#4828）：把**运行中的** nginx 从上一轮遗留的 green 上游收回正式色 ──
  # 为什么必须做：运行中的 nginx 若仍指着某个 `<svc>-green`，紧接着那句 `rm -sf $BG_GREENS` 就会把
  # **唯一还在服务的后端**删掉 ⇒ **全站所有域名同时 502**（比不做本单更糟）。
  # 判据 = `$BG_PREV_GREEN`（**第 1 步之前**读的快照：文件 ∪ 上一版备份里出现过的 `-green` 上游）。
  # 处置（fail-closed）：正式容器健康 ⇒ 强制 reload 收回正式色（用 `bg_reload_nginx`，**不能**走
  # `bg_switch_upstream` 的「文件已等于目标 ⇒ 无需切换」短路 —— 那正是「不 reload、收不回来」的漏洞）；
  # 正式容器不健康 ⇒ **本轮不碰任何容器**、中止（green 继续服务，站点不挂）。
  if [ "$BG_SWITCH_ON" = "1" ] && [ -n "${BG_PREV_GREEN// /}" ]; then
    echo "  ⚠️  上一轮把流量留在了 green 上：${BG_PREV_GREEN}（运行中的 nginx 仍可能指着它）"
    for svc in $BG_PREV_GREEN; do
      if ! bg_official_healthy_now "$svc"; then
        echo "  ❌ ${svc} 的正式容器此刻不健康 ⇒ **本轮不碰任何容器**（green 继续服务，避免全站 502）"
        echo "     处置：① 修好正式容器（docker compose up -d --no-deps ${svc}）后重跑；"
        echo "           ② 或应急放行：touch $BG_OFF_FILE 后重跑（应急开关不切上游、不删 green）"
        exit 1
      fi
    done
    if ! bg_reload_nginx; then
      echo "  ❌ 上游收不回正式色（reload 未生效）⇒ **本轮不碰任何容器**，人工介入"
      exit 1
    fi
    echo "  ✅ 上游已收回正式色（${BG_PREV_GREEN}）⇒ 现在删残留 green 才是安全的"
  fi
  # 残留清理：上一轮被强杀/超时会留下 green 容器（占着容器名与第二端口）⇒ 先删，保证本次能起。
  # 🔴 前提：**上面 ② 的收敛已经跑过**（运行中的 nginx 已收回正式色）⇒ 此刻删 green 不会删掉
  #     「唯一还在服务的后端」。收敛被跳过（nginx 未在跑）时也同样安全：那种状态没有在服务的 nginx。
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

  # ── ①.5 切流量到 green（#4828）：green **已通过健康检查** ⇒ 只改一行上游 + 校验 + reload ──
  #     这一步之后直到 ②.5，正式容器的替换**不会**造成任何 502（流量走在 green 上）。
  #     ⚠️ 条件用 `BG_SWITCH_ON`（= 非应急开关 ∧ nginx 在跑 ⇒ 蕴含 `BG_SKIP=0`）：应急开关下没有
  #        green 容器、nginx 未跑时切了也无意义 ⇒ 两种情况都必须**一个字都不改配置**。
  if [ "$BG_SWITCH_ON" = "1" ]; then
    if ! bg_switch_upstream "$svc" green; then
      echo "  ❌ ${svc} 上游切不到 green（候选校验/改写失败）⇒ **旧容器保持不动、流量未切**，部署中止"
      $BG_COMPOSE rm -sf "$GREEN" >/dev/null 2>&1 || true
      exit 1
    fi
  fi

  # ── ② 切换：替换正式容器（走过蓝绿 ⇒ 该镜像刚刚已被证明能起）──
  docker compose up -d --no-deps "$svc"
  if ! wait_healthy "$(svc_port "$svc")" "$svc" "$GPATH"; then
    echo "  ❌ $svc 正式容器替换后健康检查未通过 ⇒ 中止"
    echo "     交给 CI 侧 #4767 的「失败即回滚」（回滚到 .last-good-tag）兜底"
    echo "     上游交给 EXIT trap：正式容器不健康 ⇒ **保持指向 green**（该 green 不删，继续服务）"
    exit 1
  fi

  # ── ②.5 切回正式色（#4828）：正式容器**已健康** ⇒ reload 只把流量从 green 挪回正式容器（零 502）──
  #     ⚠️ 必须在第 ③ 步「删 green」**之前**：否则删掉的是唯一还在服务的后端。
  #     ⚠️ 与 ①.5 同条件（`BG_SWITCH_ON`）：不改配置 ⇒ 也就不会把上游留在 green 上。
  if [ "$BG_SWITCH_ON" = "1" ]; then
    if ! bg_switch_upstream "$svc" official; then
      echo "  ❌ ${svc} 上游切不回正式色 ⇒ **保留 green 继续服务**（不删它），部署中止，人工介入"
      exit 1
    fi
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

# 收口归一化（#4828）：本轮上游已全部回到正式色 ⇒ 把上一版备份也写成正式色。
# 目的 = 让「`$NGINX_CONF_BAK` 里出现 `-green`」**专指**「上一轮没走完」——下一轮开头的残留切换
# 快照正是读它。不归一化的话快照每轮都为真 ⇒ 收敛段每轮都跑，而它「正式容器不健康即中止」的
# fail-closed 分支会**误伤正常部署**（把不健康的非关键服务变成"部署被阻断"）。
# ⚠️ 只在本轮确实把上游收回正式色时才写（`BG_SWITCHED` 非空 = 还有服务停在 green ⇒ 不写）。
if [ "$BG_SWITCHED" = "" ] && [ -f "$NGINX_CONF" ]; then
  cp "$NGINX_CONF" "$NGINX_CONF_BAK" 2>/dev/null || true
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
