#!/usr/bin/env bash
# acceptance/2026-10-04/env/swas-run.sh
# 通过 SWAS 云助手在测试实例上执行**一次**远端命令并回传 stdout（Output 为 base64，已解码）。
# 用途：issue #6294 的磁盘回收与重发布（用户 2026-10-04 明确授权「清盘后重跑部署」）。
# 纪律：铁律 10 —— 本脚本自身不做任何删除；删除动作由调用方显式给出，并逐条留读数。
# 用法: ./swas-run.sh '<remote shell command>' [timeout_secs]
set -euo pipefail
INSTANCE_ID=b23c69e599524b1da719734f72e6a0e3
REGION=cn-hangzhou
CMD=${1:?用法: ./swas-run.sh '<cmd>' [timeout]}
TIMEOUT=${2:-300}

INV=$(aliyun swas-open run-command \
  --instance-id "$INSTANCE_ID" --name migao-ops \
  --type RunShellScript --timeout "$TIMEOUT" \
  --biz-region-id "$REGION" --command-content "$CMD" 2>&1 || true)
IID=$(printf '%s' "$INV" | python3 -c 'import sys,json
try:
    print(json.load(sys.stdin).get("InvokeId",""))
except Exception:
    print("")' 2>/dev/null || true)
if [ -z "$IID" ]; then echo "FAILED RunCommand:"; printf '%s\n' "$INV" | head -c 1200; exit 3; fi
echo "invoke-id=$IID"

for _ in $(seq 1 80); do
  RES=$(aliyun swas-open describe-invocation-result \
    --instance-id "$INSTANCE_ID" --invoke-id "$IID" --biz-region-id "$REGION" 2>&1 || true)
  ST=$(printf '%s' "$RES" | python3 -c 'import sys,json
try:
    d=json.load(sys.stdin); r=d.get("InvocationResult") or d
    print(r.get("InvocationStatus") or r.get("Status") or "")
except Exception:
    print("")' 2>/dev/null || true)
  case "$ST" in
    Success|Failed|Timeout|PartialFailed)
      printf '%s' "$RES" | python3 -c 'import sys,json,base64
d=json.load(sys.stdin); r=d.get("InvocationResult") or {}
out=r.get("Output") or ""
try:
    out=base64.b64decode(out).decode("utf-8","replace")
except Exception:
    pass
print("[InvocationStatus] " + str(r.get("InvocationStatus") or "?"))
print(out if out.strip() else json.dumps(r, ensure_ascii=False, indent=1))'
      exit 0 ;;
    *) sleep 3 ;;
  esac
done
echo "轮询超时 invoke-id=$IID"; exit 4
