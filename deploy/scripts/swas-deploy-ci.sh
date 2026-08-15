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

# aliyun CLI 新版 swas-open 要求 kebab-case（run-command --instance-id），旧版用 CamelCase
# （RunCommand --InstanceId）。latest tarball 是移动目标（2026-08-14 晚起逐步收紧命名），双兼容：
# 先试 kebab action+flags；遇 "not a valid api"/"unknown flag" 回退 Camel action+flags。
run_cmd() {
  local k=$1 c=$2; shift 2
  local kebab_args=() camel_args=() arg
  for arg in "$@"; do
    case "$arg" in
      --instance-id)      kebab_args+=(--instance-id);      camel_args+=(--InstanceId) ;;
      # 新版 CLI 的 region 参数名为 --biz-region-id（旧版 --RegionId）
      --region-id)        kebab_args+=(--biz-region-id);    camel_args+=(--RegionId) ;;
      --name)             kebab_args+=(--name);             camel_args+=(--Name) ;;
      --type)             kebab_args+=(--type);             camel_args+=(--Type) ;;
      --timeout)          kebab_args+=(--timeout);          camel_args+=(--Timeout) ;;
      --command-content)  kebab_args+=(--command-content);  camel_args+=(--CommandContent) ;;
      --invoke-id)        kebab_args+=(--invoke-id);        camel_args+=(--InvokeId) ;;
      *)                 kebab_args+=("$arg");             camel_args+=("$arg") ;;
    esac
  done
  local out1 out2
  out1=$(aliyun swas-open "$k" "${kebab_args[@]}" 2>&1) && { echo "$out1"; return 0; }
  if echo "$out1" | grep -qE "not a valid api|unknown flag"; then
    out2=$(aliyun swas-open "$c" "${camel_args[@]}" 2>&1) && { echo "$out2"; return 0; }
    out1="$out1
-- 回退 CamelCase 也失败 --
$out2"
  fi
  echo "$out1" >&2
  return 1
}

echo "== 触发 SWAS 云助手执行 deploy.sh（拉源码 → flock → 构建 → 健康检查）=="
# 自愈式同步：每次先从 repo 拉取最新 deploy.sh 再执行（服务器不再维护手工副本）
BOOTSTRAP='curl -fsSL --retry 3 https://raw.githubusercontent.com/zhaokai-mgzn/migao/main/deploy/swas/deploy.sh -o /opt/migao-deploy/deploy.sh && bash /opt/migao-deploy/deploy.sh'
# RunCommand 可能被阿里云 API 限流（并发触发时 Throttling），重试 3 次
INVOKE_ID=""
for attempt in 1 2 3; do
  if ! INVOKE=$(run_cmd run-command RunCommand \
      --instance-id "$INSTANCE_ID" \
      --name migao-ci-deploy \
      --type RunShellScript \
      --timeout 3600 \
      --region-id "$REGION" \
      --command-content "$BOOTSTRAP" 2>&1); then
    echo "  ⚠️ RunCommand 调用失败(第 $attempt 次):"; echo "$INVOKE" | head -c 1500; echo;
    if echo "$INVOKE" | grep -q "NoPermission\|not authorized\|StatusCode: 403"; then
      echo "  ─────────────────────────────────────────────────────"
      echo "  🔑 RAM 权限缺失：CI 使用的 AccessKey 子账号没有 swas-open:RunCommand 权限。"
      echo "  请在阿里云 RAM 控制台为该子账号授权：AliyunSWASOpenFullAccess"
      echo "  （或自定义策略 Action=swas-open:RunCommand, swas-open:DescribeInvocationResult,"
      echo "    Resource=实例 b23c69e599524b1da719734f72e6a0e3）。授权后重跑本工作流即可。"
      echo "  ─────────────────────────────────────────────────────"
    fi
    if [ "$attempt" -eq 1 ] && ! echo "$INVOKE" | grep -q "NoPermission\|not authorized"; then
      echo "  --- run-command 用法（诊断） ---"
      aliyun help swas-open run-command 2>&1 | head -40 || true
      echo "  --------------------------------"
    fi
    [ "$attempt" -lt 3 ] && { echo "  10s 后重试"; sleep 10; continue; }
    echo "❌ RunCommand 三次均失败"; exit 1; fi
  INVOKE_ID=$(echo "$INVOKE" | python3 -c "import sys,json;print(json.load(sys.stdin).get('InvokeId',''))" 2>/dev/null || echo "")
  [ -n "$INVOKE_ID" ] && break
  echo "  ⚠️ 未获得 InvokeId(第 $attempt 次):"; echo "$INVOKE" | head -c 800; echo;
  [ "$attempt" -lt 3 ] && sleep 10
done
echo "deploy invokeId=$INVOKE_ID"
[ -n "$INVOKE_ID" ] || { echo "❌ 三次尝试均未获得 InvokeId"; exit 1; }

SUCCESS=0
for i in $(seq 1 180); do
  RES=$(run_cmd describe-invocation-result DescribeInvocationResult \
    --instance-id "$INSTANCE_ID" \
    --invoke-id "$INVOKE_ID" \
    --region-id "$REGION" 2>&1) || {
      echo "  ⚠️ DescribeInvocationResult 异常(第 $i 次)："; echo "$RES" | head -c 600; echo;
      if [ "$i" -eq 1 ]; then
        echo "  --- describe-invocation-result 用法（诊断） ---"
        aliyun help swas-open describe-invocation-result 2>&1 | head -20 || true
        echo "  ---------------------------------------------"
      fi
      sleep 20; continue; }
  STATUS=$(echo "$RES" | python3 -c "import sys,json;d=json.load(sys.stdin);v=d.get('InvocationResult') or d;print(v.get('InvocationStatus') or v.get('Status') or '')" 2>/dev/null || echo "")
  echo "  deploy status: ${STATUS:-?} (poll $i)"
  if [ "$STATUS" = "Success" ]; then echo "✅ SWAS 部署成功"; SUCCESS=1; break; fi
  if [ "$STATUS" = "Failed" ]; then echo "❌ SWAS 部署失败:"; echo "$RES" | head -c 1500; exit 1; fi
  sleep 20
done
[ "$SUCCESS" = "1" ] || { echo "❌ 60min 轮询超时未等到 Success"; exit 1; }
