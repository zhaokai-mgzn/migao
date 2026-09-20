#!/bin/bash
# CI → SWAS 部署通道（被 deploy-admin-api / deploy-ai-agent-service / deploy-frontend 三个 workflow 调用）
# 用法: swas-deploy-ci.sh <INSTANCE_ID> <REGION> <ACCESS_KEY_ID> <ACCESS_KEY_SECRET> [ACR_USERNAME] [ACR_PASSWORD] [IMAGE_TAG]
#
# 2026-08-14 线上事故修复：
# - 下载加 --retry + gzip 校验（曾因瞬时下载损坏 tar exit 2）
# - 轮询窗口 90→180 次（60min）：服务器端 deploy.sh 带 flock 串行化，并发触发会排队
# - 轮询超时/CLI 异常均显式报错退出（此前超时静默 exit 0）
# - 传入 ACR 凭据时写服务器 .env.registry，deploy.sh 据此 docker login（快速部署拉镜像用）
#
# ══════════════════════════════════════════════════════════════════════════════
# 2026-09-21 部署链加固（issue #4767，云测试环境事故）—— 三件：
#
# ① **硬超时**：`DEPLOY_TIMEOUT_SECONDS`（默认 900s=15min）是**墙钟**上界，不是「180 次 × 20s」
#    这种**次数**上界；每次 aliyun CLI 调用另有 `with_deadline` 上界。事故形态 = CLI 调用自己挂住
#    ⇒ 轮询永不返回 ⇒ run 被永久钉在 `in_progress` ⇒ 占住 `deploy-*` 的 concurrency 组
#    ⇒ 后续 main 的部署**全被挡住**。超时即 `exit 1`（run 进终态 ⇒ 锁释放）。
#
# ② **远端输出可读**：SWAS 的 `InvocationResult.Output` 是 **base64** ⇒ 解码后打印，
#    并**完整落 `$GITHUB_STEP_SUMMARY`**（CI 日志会被截断 —— 实测只留前 1500 字节，summary 不受影响）；
#    非 base64 / 无 `Output` 字段 ⇒ 原样打印（**绝不吞信息**）。
#
# ③ **失败不留坏状态**：远端 deploy.sh 是「先 `up -d` 再健康检查」⇒ 新容器起不来时**旧容器已被替换**
#    （事故把 admin-api 打成 502 的机理）⇒ 失败**自动重试 1 次** → 仍失败则**回滚到上一个可用镜像**
#    （远端 deploy.sh 成功时记在 `/opt/migao-deploy/.last-good-tag`）→ 回滚也不行 ⇒ **`::error::` 显式告警**。
#
# 边界（照实登记，不写成恒真判据）：
#   · 「先起新容器 → 健康检查通过 → 再切流量」的**蓝绿**形态需要改 `deploy/swas/deploy.sh`（本单未授权），
#     本单实现的是 issue 明示可接受的替代式 —— **失败即回滚到上一个可用镜像**；
#   · **硬超时不做自动回滚**：远端 RunCommand 的 `--timeout 3600` ⇒ 超时那一刻远端**可能仍在跑**，
#     此刻回滚会与它抢 deploy.sh 的 flock（等待 600s 后才失败）⇒ 改为显式告警 + 恢复手册。
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

INSTANCE_ID=$1
REGION=$2
AK=$3
SK=$4
ACR_USERNAME=${5:-}
ACR_PASSWORD=${6:-}
IMAGE_TAG=${7:-latest}

# ── 硬超时参数（issue #4767 ①）────────────────────────────────────────────────
# DEPLOY_TIMEOUT_SECONDS：**一次「发起 SWAS 调用 + 轮询结果」的总墙钟上界**（不是次数上界）。
DEPLOY_TIMEOUT_SECONDS=${SWAS_DEPLOY_TIMEOUT_SECONDS:-900}
# CLI_TIMEOUT_SECONDS：**单次 aliyun CLI 调用**的上界（防 CLI 自己挂住 ⇒ 轮询永不返回）。
CLI_TIMEOUT_SECONDS=${SWAS_CLI_TIMEOUT_SECONDS:-60}
# POLL_INTERVAL_SECONDS：轮询间隔（线上 20s；守卫测试调小以免空耗）。
POLL_INTERVAL_SECONDS=${SWAS_POLL_INTERVAL_SECONDS:-20}
# RETRY_PAUSE_SECONDS：两次尝试之间的间隔（线上 10s；守卫测试调小以免空耗）。
RETRY_PAUSE_SECONDS=${SWAS_RETRY_PAUSE_SECONDS:-10}
DEADLINE=$(( $(date +%s) + DEPLOY_TIMEOUT_SECONDS ))

remaining_seconds() { echo $(( DEADLINE - $(date +%s) )); }

# 受 deadline 约束的等待：**绝不** sleep 超过剩余预算（否则超时判定会被 sleep 拖过界）
nap() {
  local want=$1 left
  left=$(remaining_seconds)
  [ "$left" -lt "$want" ] && want=$left
  if [ "$want" -gt 0 ]; then sleep "$want"; fi
  return 0
}

# ── job summary（issue #4767 ②）──────────────────────────────────────────────
# CI 日志会被截断（实测失败那次的 Output 只留了前 1500 字节）；summary 不受影响 ⇒ 远端输出**完整**落这里。
SUMMARY_FILE=${GITHUB_STEP_SUMMARY:-}
say() {
  echo "$*"
  if [ -n "$SUMMARY_FILE" ]; then printf '%s\n' "$*" >> "$SUMMARY_FILE"; fi
  return 0
}

echo "== 安装 Aliyun CLI =="
curl -fsSL --retry 3 --retry-delay 3 https://aliyuncli.alicdn.com/aliyun-cli-linux-latest-amd64.tgz -o /tmp/aliyun.tgz
file /tmp/aliyun.tgz | grep -q "gzip compressed data" || { echo "❌ 下载文件损坏或非 gzip 格式"; exit 2; }
tar xzf /tmp/aliyun.tgz -C /tmp
sudo mv /tmp/aliyun /usr/local/bin/
echo "✅ Aliyun CLI $(aliyun version 2>/dev/null || echo installed)"

aliyun configure set --access-key-id "$AK" --access-key-secret "$SK" --region "$REGION"
aliyun plugin install --names aliyun-cli-swas-open >/dev/null 2>&1 || true

# ── 带硬上界的子进程执行（issue #4767 ①）─────────────────────────────────────
# 不依赖 coreutils `timeout`（macOS 本地跑守卫测试走**同一条码路**，避免"测试测的是另一份实现"）。
# 到点先 TERM 再 KILL ⇒ 返回 143/137（**非零** ⇒ 调用方必须当失败处理）。
with_deadline() {
  local secs=$1; shift
  local out_file pid watchdog rc=0
  out_file=$(mktemp)
  "$@" >"$out_file" 2>&1 &
  pid=$!
  ( sleep "$secs"; kill -TERM "$pid" 2>/dev/null || true; sleep 2; kill -KILL "$pid" 2>/dev/null || true ) >/dev/null 2>&1 &
  watchdog=$!
  wait "$pid" || rc=$?
  kill "$watchdog" 2>/dev/null || true
  wait "$watchdog" 2>/dev/null || true
  cat "$out_file" || true
  rm -f "$out_file"
  return "$rc"
}

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
  # ⚠️ 每次 CLI 调用都过 `with_deadline`：CLI 自己挂住时也必须返回（否则轮询的上界形同虚设）
  out1=$(with_deadline "$CLI_TIMEOUT_SECONDS" aliyun swas-open "$k" "${kebab_args[@]}") && { echo "$out1"; return 0; }
  if echo "$out1" | grep -qE "not a valid api|unknown flag"; then
    out2=$(with_deadline "$CLI_TIMEOUT_SECONDS" aliyun swas-open "$c" "${camel_args[@]}") && { echo "$out2"; return 0; }
    out1="$out1
-- 回退 CamelCase 也失败 --
$out2"
  fi
  echo "$out1" >&2
  return 1
}

# ── 解析 SWAS 返回（issue #4767 ②）───────────────────────────────────────────
extract_status() {
  python3 -c "import sys,json;d=json.load(sys.stdin);v=d.get('InvocationResult') or d;print(v.get('InvocationStatus') or v.get('Status') or '')" 2>/dev/null || echo ""
}

# `InvocationResult.Output` 是 **base64**。把 base64 当「日志」等于没有日志（事故里只能解出前 3 行）。
# 容错：非 base64 / 无 Output 字段 / JSON 解析失败 ⇒ **原样打印**，绝不吞信息。
# ⚠️ JSON 走 **argv**（`$1`）而不是 stdin：`python3 - <<'PY'` 的 heredoc **已经占了 stdin**，
#    再用 `sys.stdin.read()` 读到的是 EOF ⇒ 解码恒空（实测踩到，会让「输出可读」整条静默失效）。
extract_remote_log() {
  python3 - "$1" <<'PY'
import base64, binascii, json, sys

raw = sys.argv[1] if len(sys.argv) > 1 else ""


def find_output(obj):
    if not isinstance(obj, dict):
        return None
    v = obj.get("InvocationResult")
    v = v if isinstance(v, dict) else obj
    if isinstance(v.get("Output"), str):
        return v["Output"]
    for key in ("InvocationResults", "Results"):
        items = v.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("Output"), str):
                    return item["Output"]
    return None


try:
    data = json.loads(raw)
except Exception:
    sys.stdout.write(raw)
    sys.exit(0)

out = find_output(data)
if out is None:
    sys.stdout.write(raw)
    sys.exit(0)

try:
    sys.stdout.write(base64.b64decode(out.strip(), validate=True).decode("utf-8", "replace"))
except (binascii.Error, ValueError):
    sys.stdout.write(out)
PY
}

# 解码 + 取出回滚点（远端 deploy.sh 成功时记的 `.last-good-tag`，由 bootstrap 回显）
capture_remote_log() {
  local res=$1 prev
  REMOTE_LOG=$(extract_remote_log "$res" 2>/dev/null) || REMOTE_LOG=""
  if [ -z "$REMOTE_LOG" ]; then REMOTE_LOG="$res"; fi
  # ⚠️ 不接 `head -1`：pipefail 下 `head` 提前退出会让上游吃 SIGPIPE ⇒ 整条管道非零 ⇒ set -e 误杀
  prev=$(printf '%s\n' "$REMOTE_LOG" | sed -n 's/^PREV_GOOD_TAG=//p')
  PREV_GOOD_TAG=${prev%%$'\n'*}
  return 0
}

# **完整**打印远端输出（不截断）+ 落 job summary
emit_remote_log() {
  local title=$1
  echo ""
  echo "──────── $title ────────"
  printf '%s\n' "$REMOTE_LOG"
  echo "──────── $title 结束 ────────"
  if [ -n "$SUMMARY_FILE" ]; then
    {
      echo ""
      echo "### $title"
      echo '````'
      printf '%s\n' "$REMOTE_LOG"
      echo '````'
    } >> "$SUMMARY_FILE"
  fi
  return 0
}

# 恢复手册（issue #4767 验收判据：「恢复手册入库」+ 并发锁行为说明）
recovery_manual() {
  say ""
  say "**恢复手册**（并发锁行为：\`deploy-*\` 的 concurrency 组由 run 的**终态**释放 ——"
  say "run 卡在 \`in_progress\` 时会一直占着它，后续 main 的部署全被挡住）："
  say '1. `gh run list --workflow=deploy-admin-api.yml --limit 5` —— 找到卡住 / 失败的 run'
  say '2. `gh run cancel <run-id>` —— **清掉并发锁**（不需要等它自己结束）'
  say '3. `gh run rerun <run-id> --failed` —— 同 SHA 重跑，恢复推进'
  say '4. 环境已不可用时**手工回滚**：`gh workflow run deploy-admin-api.yml -f image_tag=<上一个可用 tag>`'
  say "   兜底：三个 deploy workflow 的部署 job 都带 \`timeout-minutes\` ⇒ 即使脚本被卡死，"
  say "   run 也会被 GitHub 终止（进终态）⇒ **锁一定会释放**。"
  return 0
}

echo "== 触发 SWAS 云助手执行 deploy.sh（拉源码 → flock → 构建 → 健康检查）=="
# 自愈式同步：每次先从 repo 拉取最新 deploy.sh 再执行（服务器不再维护手工副本）。
# 注意走 codeload.github.com（服务器可达）；raw.githubusercontent.com 在杭州机房超时（curl 56 errno 110）。
# 可选：写入 ACR 凭据到 .env.registry（deploy.sh 检测到即 docker login）。
REGISTRY_SETUP=""
if [ -n "$ACR_USERNAME" ] && [ -n "$ACR_PASSWORD" ]; then
  REGISTRY_SETUP="printf 'ACR_USERNAME=%s\nACR_PASSWORD=%s\n' \"$ACR_USERNAME\" \"$ACR_PASSWORD\" > /opt/migao-deploy/.env.registry && "
fi
# ⚠️ 并发红线（issue #4625）：下面整段**不许出现任何跨 run 共享的固定路径**。
# 实测：`/tmp` 下那个固定源码目录被三个 workflow（admin-api / ai-agent / frontend）共用 ⇒ 同一次 push 的
# 并发 run 互相 `rm -rf`（run 35458389055 前端 `cp: cannot stat`；同刻 35458382449 服务端
# `rm: cannot remove ... Directory not empty`）⇒ 随机一端部署失败、线上前端落后一个版本。
# 注意：`deploy.sh` 内部的 flock **只覆盖 deploy.sh 自己**，覆盖不到 bootstrap 这一段 ——
# 「flock 会串行化」不能当作 bootstrap 可以共享路径的理由。
# 故 bootstrap 一律用 per-run 唯一路径（`mktemp -d`），装 deploy.sh 一律「先写临时名再 `mv -f`」（原子替换）。
# 转义纪律：本变量在 CI 侧求值 ⇒ **远端**求值的要写成 `\$(…)` / `\"\$SRC\"`；
# **本地**要展开的（`${REGISTRY_SETUP}` / `${IMAGE_TAG}`）保持原样。
#
# ③ 回滚点（issue #4767）：开头回显**上一个可用镜像 tag**（供失败时回滚），
#    deploy.sh **成功**（rc=0）后把本次 tag 写进 `.last-good-tag`。
#    无 marker（本改动上线后的首次部署）⇒ 退化为从**正在运行的容器镜像**取多数派 tag。
#    两处都在**同一次云调用**里完成 ⇒ 不额外增加 CLI 往返。
BOOTSTRAP="PREV=\$(cat /opt/migao-deploy/.last-good-tag 2>/dev/null || true); if [ -z \"\$PREV\" ] && command -v docker >/dev/null 2>&1; then PREV=\$(docker ps --format '{{.Image}}' 2>/dev/null | grep 'ai-customer-service/' | sed 's/.*://' | sort | uniq -c | sort -rn | head -1 | awk '{print \$2}'); fi; echo \"PREV_GOOD_TAG=\${PREV:-}\"; ${REGISTRY_SETUP}SRC=\$(mktemp -d) && TAR=\$(mktemp) && curl -fsSL --retry 3 https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/refs/heads/main -o \"\$TAR\" && tar xzf \"\$TAR\" -C \"\$SRC\" --strip-components=1 && mkdir -p /opt/migao-deploy && cp \"\$SRC\"/deploy/swas/deploy.sh /opt/migao-deploy/.deploy.sh.new && mv -f /opt/migao-deploy/.deploy.sh.new /opt/migao-deploy/deploy.sh && bash /opt/migao-deploy/deploy.sh ${IMAGE_TAG}; rc=\$?; if [ \$rc -eq 0 ]; then echo \"${IMAGE_TAG}\" > /opt/migao-deploy/.last-good-tag; fi; rm -rf \"\$SRC\" \"\$TAR\"; exit \$rc"

# ── 一次完整的「触发 + 轮询」（issue #4767 ①②③）────────────────────────────
# 结果写进全局：DEPLOY_RC（0=Success / 1=远端 Failed / 2=硬超时 / 3=云 API 调用失败）
#               REMOTE_LOG（**解码后**的远端输出）、PREV_GOOD_TAG（远端记录的上一个可用 tag）
# ⚠️ 本函数**恒返回 0**（结果只走 DEPLOY_RC）：`set -e` 下「函数返回非零」会当场终止脚本，
#    那样重试 / 回滚 / 告警全都被跳过（实测踩到，红证方向正好反过来）。
deploy_attempt() {
  local tag=$1
  DEPLOY_RC=3
  REMOTE_LOG=""
  PREV_GOOD_TAG=""
  # 每次尝试**各自**一个墙钟预算：一次尝试绝不无限轮询
  DEADLINE=$(( $(date +%s) + DEPLOY_TIMEOUT_SECONDS ))

  # ⚠️ BOOTSTRAP 里的 tag 是**CI 侧**展开的（`${IMAGE_TAG}`，见上面的转义纪律）⇒ 回滚要用**别的**
  #    tag 时必须按目标 tag 重写这一处。少写这一步的后果最恶劣：回滚会把**同一个坏镜像**再部署一次
  #    还报告"已回滚"（实测踩到）⇒ 替换没生效时**当场报错**，不许静默继续。
  local bootstrap=${BOOTSTRAP//"$IMAGE_TAG"/"$tag"}
  if [ "$tag" != "$IMAGE_TAG" ] && [ "$bootstrap" = "$BOOTSTRAP" ]; then
    echo "❌ 回滚 tag 替换未生效：BOOTSTRAP 里找不到当前 tag（$IMAGE_TAG）—— 拒绝用错 tag 部署"
    DEPLOY_RC=3
    return 0
  fi

  # RunCommand 可能被阿里云 API 限流（并发触发时 Throttling），重试 3 次
  local INVOKE="" INVOKE_ID="" attempt
  for attempt in 1 2 3; do
    if ! INVOKE=$(run_cmd run-command RunCommand \
        --instance-id "$INSTANCE_ID" \
        --name migao-ci-deploy \
        --type RunShellScript \
        --timeout 3600 \
        --region-id "$REGION" \
        --command-content "$bootstrap" 2>&1); then
      echo "  ⚠️ RunCommand 调用失败(第 $attempt 次):"; echo "$INVOKE" | head -c 1500; echo
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
      if [ "$attempt" -lt 3 ]; then echo "  10s 后重试"; nap "$RETRY_PAUSE_SECONDS"; continue; fi
      echo "❌ RunCommand 三次均失败"; DEPLOY_RC=3; return 0
    fi
    INVOKE_ID=$(echo "$INVOKE" | python3 -c "import sys,json;print(json.load(sys.stdin).get('InvokeId',''))" 2>/dev/null || echo "")
    if [ -n "$INVOKE_ID" ]; then break; fi
    echo "  ⚠️ 未获得 InvokeId(第 $attempt 次):"; echo "$INVOKE" | head -c 800; echo
    if [ "$attempt" -lt 3 ]; then nap "$RETRY_PAUSE_SECONDS"; fi
  done
  echo "deploy invokeId=$INVOKE_ID"
  if [ -z "$INVOKE_ID" ]; then echo "❌ 三次尝试均未获得 InvokeId"; DEPLOY_RC=3; return 0; fi

  echo "  （本次尝试的硬超时预算：${DEPLOY_TIMEOUT_SECONDS}s）"
  local i=0 status res
  while :; do
    i=$((i + 1))
    if [ "$(remaining_seconds)" -le 0 ]; then
      echo "❌ 硬超时：本次「发起 SWAS 调用 + 轮询结果」已超过 ${DEPLOY_TIMEOUT_SECONDS}s（已轮询 $i 次）"
      echo "   远端 RunCommand 的 timeout=3600s ⇒ 它**可能仍在跑**；此处**不做自动回滚**"
      echo "   （此刻回滚会与它抢 deploy.sh 的 flock —— 那把锁要等 600s 才会失败退出）。"
      DEPLOY_RC=2
      return 0
    fi
    if res=$(run_cmd describe-invocation-result DescribeInvocationResult \
        --instance-id "$INSTANCE_ID" \
        --invoke-id "$INVOKE_ID" \
        --region-id "$REGION" 2>&1); then
      :
    else
      echo "  ⚠️ DescribeInvocationResult 异常(第 $i 次)："; echo "$res" | head -c 600; echo
      if [ "$i" -eq 1 ]; then
        echo "  --- describe-invocation-result 用法（诊断） ---"
        aliyun help swas-open describe-invocation-result 2>&1 | head -20 || true
        echo "  ---------------------------------------------"
      fi
      nap "$POLL_INTERVAL_SECONDS"; continue
    fi
    status=$(extract_status <<<"$res")
    echo "  deploy status: ${status:-?} (poll $i, 剩余 $(remaining_seconds)s)"
    if [ "$status" = "Success" ]; then
      capture_remote_log "$res"
      DEPLOY_RC=0
      return 0
    fi
    if [ "$status" = "Failed" ]; then
      capture_remote_log "$res"
      DEPLOY_RC=1
      return 0
    fi
    nap "$POLL_INTERVAL_SECONDS"
  done
}

# ── 主流程 ──────────────────────────────────────────────────────────────────
say "# SWAS 部署（远端 deploy.sh）"
say ""
say "- 目标实例：\`$INSTANCE_ID\`（${REGION}）"
say "- 镜像 tag：\`$IMAGE_TAG\`"
say "- 硬超时预算：${DEPLOY_TIMEOUT_SECONDS}s / 次尝试（单次 CLI 调用 ${CLI_TIMEOUT_SECONDS}s）"

deploy_attempt "$IMAGE_TAG"
ATTEMPT_RC=$DEPLOY_RC
emit_remote_log "第 1 次部署（tag=${IMAGE_TAG}）远端输出"

if [ "$ATTEMPT_RC" -eq 0 ]; then
  say ""
  say "✅ SWAS 部署成功（tag=\`$IMAGE_TAG\`）"
  exit 0
fi

if [ "$ATTEMPT_RC" -eq 3 ]; then
  say ""
  say "::error::SWAS **云 API 调用**失败（RunCommand 三次均未成功）⇒ **远端从未执行**，环境未被改动。"
  say "多半是 RAM 权限 / API 限流 / 网络（上面有诊断输出）。"
  recovery_manual
  exit 1
fi

if [ "$ATTEMPT_RC" -eq 2 ]; then
  say ""
  say "::error::SWAS 部署**硬超时**（本次尝试 >${DEPLOY_TIMEOUT_SECONDS}s）：远端状态未知，**未自动回滚**。"
  recovery_manual
  exit 1
fi

# ── 远端明确失败 ⇒ **自动重试 1 次**（issue #4767 ③）────────────────────────
say ""
say "⚠️ 第 1 次部署失败（tag=\`$IMAGE_TAG\`）—— 10s 后**自动重试一次**"
echo "⚠️ 第 1 次部署失败，10s 后自动重试一次（同一 tag=${IMAGE_TAG}）"
nap "$RETRY_PAUSE_SECONDS"

deploy_attempt "$IMAGE_TAG"
ATTEMPT_RC=$DEPLOY_RC
emit_remote_log "第 2 次部署（自动重试，tag=${IMAGE_TAG}）远端输出"

if [ "$ATTEMPT_RC" -eq 0 ]; then
  say ""
  say "✅ SWAS 部署成功（第 2 次尝试，tag=\`$IMAGE_TAG\`）"
  exit 0
fi

# ── 重试仍失败 ⇒ **回滚到上一个可用镜像**（issue #4767 ③）──────────────────
if [ -z "$PREV_GOOD_TAG" ]; then
  say ""
  say "::error::部署失败（tag=\`$IMAGE_TAG\`，自动重试 1 次仍失败），且**没有可回滚的目标**："
  say "远端 \`/opt/migao-deploy/.last-good-tag\` 为空，且取不到正在运行的容器镜像 tag。"
  say "环境可能处于坏状态 ⇒ 请**立即人工介入**。"
  recovery_manual
  exit 1
fi

if [ "$PREV_GOOD_TAG" = "$IMAGE_TAG" ]; then
  say ""
  say "::error::部署失败（tag=\`$IMAGE_TAG\`，自动重试 1 次仍失败）；回滚点与本次 tag 相同（同 sha 重跑）⇒ 回滚无意义。"
  say "环境可能处于坏状态 ⇒ 请**立即人工介入**。"
  recovery_manual
  exit 1
fi

say ""
say "⚠️ 自动重试仍失败 ⇒ **回滚到上一个可用镜像 tag=\`$PREV_GOOD_TAG\`**"
echo "⚠️ 自动重试仍失败 ⇒ 回滚到上一个可用镜像 tag=$PREV_GOOD_TAG"
# ⚠️ 必须先存下来：`deploy_attempt` 会重置 `PREV_GOOD_TAG`（它承载的是**本次尝试**的远端回显）
#    ⇒ 回滚后直接用 `$PREV_GOOD_TAG` 会渲染成**空串**（实测踩到：告警里 tag=`` 等于没说）
ROLLBACK_TAG=$PREV_GOOD_TAG
nap "$RETRY_PAUSE_SECONDS"

deploy_attempt "$ROLLBACK_TAG"
ROLLBACK_RC=$DEPLOY_RC
emit_remote_log "回滚部署（tag=${ROLLBACK_TAG}）远端输出"

if [ "$ROLLBACK_RC" -eq 0 ]; then
  say ""
  say "::error::部署失败（tag=\`$IMAGE_TAG\`）—— **已自动回滚到上一个可用镜像 tag=\`$ROLLBACK_TAG\`**，环境已恢复服务。"
  say "根因在**新镜像**，不在环境：请看上面第 1/2 次部署的远端输出（已解码，含真正的报错）。"
  exit 1
fi

say ""
say "::error::部署失败（tag=\`$IMAGE_TAG\`），**且自动回滚（tag=\`$ROLLBACK_TAG\`）也失败**"
say "⇒ 环境可能处于坏状态，请**立即人工介入**。"
recovery_manual
exit 1
