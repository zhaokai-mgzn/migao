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

# 1.6 SMS 万能码 POC 自愈（决策 D2 + 审计 07 P0-1）：
# sms.bypass-code 默认已改空（生产 fail-closed）。POC 阶段保留万能码——
# 若 .env.admin-api 完全缺失 SMS_BYPASS_CODE 配置，自动补齐 123456 并醒目警告；
# 显式配置过（含置空禁用）则尊重现状，绝不覆盖。
if [ -f .env.admin-api ] && ! grep -q '^SMS_BYPASS_CODE=' .env.admin-api; then
  printf 'SMS_BYPASS_CODE=123456\n' >> .env.admin-api
  echo "  ⚠️【POC 模式】已自动启用 SMS 万能码 123456（决策 D2）。接入真实短信后须在 .env.admin-api 显式置空 SMS_BYPASS_CODE= 以禁用（技术债 Issue #2616）"
fi
# 1.6b ai-agent 侧 SMS 万能码自愈（#518 回归）：order_create 工具的 bypass 校验
# 读的是 ai-agent 自身环境变量 SMS_BYPASS_CODE（app/tools/order_create.py），
# 缺失时 C 端下单的短信验证码必然校验失败（用户收不到短信）。对齐 admin-api 自愈补齐。
if [ -f .env.ai-agent ] && ! grep -q '^SMS_BYPASS_CODE=' .env.ai-agent; then
  printf 'SMS_BYPASS_CODE=123456\n' >> .env.ai-agent
  echo "  ⚠️【POC 模式】已自动启用 ai-agent SMS 万能码 123456（决策 D2）。接入真实短信后须在 .env.ai-agent 显式置空 SMS_BYPASS_CODE= 以禁用（技术债 Issue #2616）"
fi

echo "== 2. 拉取镜像（tag=$TAG）=="
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
    echo "  ⚠️ $svc 镜像拉取失败/超时（可能尚未推送 :$TAG），跳过该服务"
  fi
done
# shellcheck disable=SC2086
docker compose up -d --no-deps $UP_SERVICES
# 容器重建后 IP 可能变化，nginx 启动时缓存旧上游 IP → reload/restart 否则 502
docker compose restart nginx

# 磁盘自愈：清理悬空/过期镜像（#2571 复现防护：旧镜像堆积曾导致磁盘 100% 部署失败）
# 只清 <none> 悬空镜像与未被容器引用的旧版本，运行中镜像不受影响
docker image prune -f || echo "⚠️ docker image prune 失败（不影响本次部署）"
# 额外水位告警：磁盘 >85% 时明确提示，便于及时介入
DISK_PCT=$(df / | awk 'NR==2 {gsub("%","",$5); print $5}')
if [ "${DISK_PCT:-0}" -gt 85 ]; then
  echo "⚠️ 磁盘水位 ${DISK_PCT}% > 85%，建议清理（docker image prune -a / 扩容）"
fi

echo "== 3. 健康检查 =="
HC_FAILED=0
for spec in "8080 admin-api /actuator/health" "8000 ai-agent /health" "3001 admin-web /"; do
  # shellcheck disable=SC2086
  set -- $spec
  PORT=$1; NAME=$2; PATHV=$3
  HC_OK=0
  for i in 1 2 3 4 5 6 7 8 9 10; do
    CODE=$(curl -s -o /tmp/hc_$NAME.txt -w "%{http_code}" -m 10 "http://127.0.0.1:$PORT$PATHV" || echo 000)
    if [ "$CODE" = "200" ] || [ "$CODE" = "301" ] || [ "$CODE" = "302" ]; then
      echo "  $NAME OK ($CODE)"; HC_OK=1; break
    fi
    echo "  $NAME -> $CODE (retry $i)"
    sleep 10
  done
  if [ "$HC_OK" != "1" ]; then
    echo "  ❌ $NAME 健康检查未通过（重试 10 次仍未就绪）"
    HC_FAILED=1
  fi
done
if [ "$HC_FAILED" = "1" ]; then
  echo "❌ 健康检查失败，部署中止。排查：cd /opt/migao-deploy && docker compose logs <服务>"
  exit 1
fi
echo "== deploy.sh 完成（耗时主要取决于镜像拉取） =="
