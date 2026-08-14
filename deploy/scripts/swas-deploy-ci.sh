#!/bin/bash
# CI → SWAS 部署通道（被 deploy-admin-api / deploy-ai-agent-service / deploy-frontend 三个 workflow 调用）
# 用法: swas-deploy-ci.sh <INSTANCE_ID> <REGION> <ACCESS_KEY_ID> <ACCESS_KEY_SECRET>
#
# 2026-08-14 线上事故修复：
# - 下载加 --retry + gzip 校验（曾因瞬时下载损坏 tar exit 2）
# - 轮询窗口 90→180 次（60min）：服务器端 deploy.sh 带 flock 串行化，并发触发会排队
# - 轮询超时/CLI 异常均显式报错退出（此前超时静默 exit 0）
set -euo pipefail

INSTANCE_ID=$1
REGION=$2
AK=$3
SK=$4

echo "== 安装 Aliyun CLI =="
curl -fsSL --retry 3 --retry-delay 3 https://aliyuncli.alicdn.com/aliyun-cli-linux-latest-amd64.tgz -o /tmp/aliyun.tgz
file /tmp/aliyun.tgz | grep -q "gzip compressed data" || { echo "❌ 下载文件损坏或非 gzip 格式"; exit 2; }
tar xzf /tmp/aliyun.tgz -C /tmp
sudo mv /tmp/aliyun /usr/local/bin/
echo "✅ Aliyun CLI $(aliyun version 2>/dev/null || echo installed)"

aliyun configure set --access-key-id "$AK" --access-key-secret "$SK" --region "$REGION"
aliyun plugin install --names aliyun-cli-swas-open >/dev/null 2>&1 || true

echo "== 触发 SWAS 云助手执行 deploy.sh（拉源码 → flock → 构建 → 健康检查）=="
# RunCommand 可能被阿里云 API 限流（并发触发时 Throttling → CLI exit 2），重试 3 次
INVOKE_ID=""
for attempt in 1 2 3; do
  INVOKE=$(aliyun swas-open RunCommand \
    --InstanceId "$INSTANCE_ID" \
    --Name migao-ci-deploy \
    --Type RunShellScript \
    --Timeout 3600 \
    --RegionId "$REGION" \
    --CommandContent "bash /opt/migao-deploy/deploy.sh" 2>&1) || {
      echo "  ⚠️ RunCommand 调用失败(第 $attempt 次):"; echo "$INVOKE" | head -c 800; echo;
      [ "$attempt" -lt 3 ] && { echo "  10s 后重试"; sleep 10; continue; }
      echo "❌ RunCommand 三次均失败"; exit 1; }
  INVOKE_ID=$(echo "$INVOKE" | python3 -c "import sys,json;print(json.load(sys.stdin).get('InvokeId',''))" 2>/dev/null || echo "")
  [ -n "$INVOKE_ID" ] && break
  echo "  ⚠️ 未获得 InvokeId(第 $attempt 次):"; echo "$INVOKE" | head -c 800; echo;
  [ "$attempt" -lt 3 ] && sleep 10
done
echo "deploy invokeId=$INVOKE_ID"
[ -n "$INVOKE_ID" ] || { echo "❌ 三次尝试均未获得 InvokeId"; exit 1; }

SUCCESS=0
for i in $(seq 1 180); do
  RES=$(aliyun swas-open DescribeInvocationResult \
    --InstanceId "$INSTANCE_ID" \
    --InvokeId "$INVOKE_ID" \
    --RegionId "$REGION" 2>&1) || {
      echo "  ⚠️ DescribeInvocationResult 异常(第 $i 次)，20s 后重试"; sleep 20; continue; }
  STATUS=$(echo "$RES" | python3 -c "import sys,json;d=json.load(sys.stdin);v=d.get('InvocationResult') or d;print(v.get('InvocationStatus') or v.get('Status') or '')" 2>/dev/null || echo "")
  echo "  deploy status: ${STATUS:-?} (poll $i)"
  if [ "$STATUS" = "Success" ]; then echo "✅ SWAS 部署成功"; SUCCESS=1; break; fi
  if [ "$STATUS" = "Failed" ]; then echo "❌ SWAS 部署失败:"; echo "$RES" | head -c 1500; exit 1; fi
  sleep 20
done
[ "$SUCCESS" = "1" ] || { echo "❌ 60min 轮询超时未等到 Success"; exit 1; }
