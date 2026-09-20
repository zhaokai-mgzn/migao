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
DISK_PCT=$(df / | awk 'NR==2 {gsub("%","",$5); print $5}')
if [ "${DISK_PCT:-0}" -gt 90 ]; then
  echo "  ⚠️ 磁盘水位 ${DISK_PCT}% > 90%，先深度清理再继续部署"
  docker system prune -af --volumes 2>/dev/null || docker system prune -af 2>/dev/null || true
  journalctl --vacuum-size=50M >/dev/null 2>&1 || true
  DISK_PCT2=$(df / | awk 'NR==2 {gsub("%","",$5); print $5}')
  echo "  清理后磁盘: ${DISK_PCT2}%（原 ${DISK_PCT}%）"
  if [ "${DISK_PCT2:-0}" -gt 95 ]; then
    echo "  ❌ 深度清理后磁盘仍 >95%（${DISK_PCT2}%），中止部署避免故障"
    echo "   人工介入：ssh 服务器排查大文件（du -xhd1 / | sort -rh | head）"
    exit 1
  fi
else
  echo "  磁盘水位 ${DISK_PCT}%（≤90%，OK）"
fi

echo "== 2. 拉取镜像（tag=${TAG}）=="
if [ -f .env.registry ]; then
  # shellcheck disable=SC1091
  . ./.env.registry
  if [ -n "${ACR_USERNAME:-}" ] && [ -n "${ACR_PASSWORD:-}" ]; then
    echo "$ACR_PASSWORD" | docker login "$REGISTRY" -u "$ACR_USERNAME" --password-stdin
  fi
fi
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

# 磁盘自愈：清理悬空/过期镜像（#2571 复现防护：旧镜像堆积曾导致磁盘 100% 部署失败）
# 只清 <none> 悬空镜像与未被容器引用的旧版本，运行中镜像不受影响
docker image prune -f || echo "⚠️ docker image prune 失败（不影响本次部署）"
# 额外水位告警：磁盘 >85% 时明确提示，便于及时介入
DISK_PCT=$(df / | awk 'NR==2 {gsub("%","",$5); print $5}')
if [ "${DISK_PCT:-0}" -gt 85 ]; then
  echo "⚠️ 磁盘水位 ${DISK_PCT}% > 85%，建议清理（docker image prune -a / 扩容）"
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
echo "== deploy.sh 完成（耗时主要取决于镜像拉取） =="
