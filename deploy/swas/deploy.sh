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
  echo "== 检测到另一个部署正在进行，等待其完成 =="
  flock 9
fi
trap 'flock -u 9' EXIT

cd /opt/migao-deploy
TAG=${1:-latest}
REGISTRY=${ACR_REGISTRY:-crpi-qdcgkzwx9p9zckga.cn-hangzhou.personal.cr.aliyuncs.com}

echo "== 1. 同步 repo 内 canonical compose + nginx 配置 =="
curl -fsSL --retry 3 --retry-delay 5 -o src.tar.gz https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/refs/heads/main
rm -rf src && mkdir -p src && tar xzf src.tar.gz -C src --strip-components=1
mkdir -p nginx certbot-www
cp src/deploy/swas/docker-compose.yml ./docker-compose.yml
cp src/deploy/swas/nginx.conf ./nginx/nginx.conf

echo "== 2. 拉取镜像（tag=$TAG）=="
if [ -f .env.registry ]; then
  # shellcheck disable=SC1091
  . ./.env.registry
  if [ -n "${ACR_USERNAME:-}" ] && [ -n "${ACR_PASSWORD:-}" ]; then
    echo "$ACR_PASSWORD" | docker login "$REGISTRY" -u "$ACR_USERNAME" --password-stdin
  fi
fi
export IMAGE_TAG="$TAG"
docker compose pull
docker compose up -d

echo "== 3. 健康检查 =="
for spec in "8080 admin-api /actuator/health" "8000 ai-agent /health" "3001 admin-web /"; do
  # shellcheck disable=SC2086
  set -- $spec
  PORT=$1; NAME=$2; PATHV=$3
  for i in 1 2 3 4 5 6 7 8 9 10; do
    CODE=$(curl -s -o /tmp/hc_$NAME.txt -w "%{http_code}" -m 10 "http://127.0.0.1:$PORT$PATHV" || echo 000)
    if [ "$CODE" = "200" ] || [ "$CODE" = "301" ] || [ "$CODE" = "302" ]; then
      echo "  $NAME OK ($CODE)"; break
    fi
    echo "  $NAME -> $CODE (retry $i)"
    sleep 10
  done
done
echo "== deploy.sh 完成（耗时主要取决于镜像拉取） =="
