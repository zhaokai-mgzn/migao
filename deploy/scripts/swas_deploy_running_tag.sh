#!/usr/bin/env bash
# 「跳过部署」的运行面自证（issue #6294）—— **函数库**（无副作用：source 它不执行任何东西）。
#
# 消费点（唯一一处）：`deploy/scripts/swas-deploy-ci.sh` 顶部的 `--probe-running-tag` 分发
#   ⇒ 被三条部署腿的 `Assert running tag == target (skip 不得冒充已部署，issue #6294)` step 调用。
# ⚠️ 为什么是**库 + 分发**而不是自带 `$@` 解析的执行体：`source` 进来的脚本里 `$@` 仍是**主脚本**
#    的参数 ⇒ 在库里读 `$@` 会读到 `--probe-running-tag`（本包第一版就这么写错了，`pytest` 当场红）。
#    故库只定义**带显式参数**的函数，`$@` 只在主脚本的分发点解包一次。
#
# ## 病（现取读数，不是推断）
#
# `deploy-*.yml` 的 `Skip if already built (schedule reconcile)` 在 `schedule` / `workflow_dispatch`
# 触发时，只要「镜像已在 ACR」**或**「同 sha 的部署 run 结论 = success」就 `skip=true` + `exit 0`
# ⇒ `Deploy to SWAS` / `Assert server-side build` / `Post-Deploy Smoke Test` **整段 skipped**，
# 而 **run 结论 = success**（issue #6294 现场：`admin-web` 近 40 次 run 里的两条 `success`
# ——run `37156277078` / `37131394391`——都是这种形态）。对账侧（`deploy-reconcile.yml`）的断路器
# 把 `success` 放进**允许名单** ⇒ 判定「该 commit 已部署」⇒ 不再补部署 ⇒
# **环境停摆 40 小时而台账全绿**（SWAS 上在跑 `admin-web:sha-877ac15`，而 main HEAD 是 `9d82e2e60`）。
#
# ## 判据形态（issue #6294 判据 1 的「部署后**机械判据**：运行 tag == 目标 tag」）
#
# 走**与部署同一条** SWAS `RunCommand` 通道，**只读**地取回每个服务的在跑 tag
# （远端执行体 `deploy/swas/deploy.sh` 的 `--probe-running-tag` ⇒ 用**它自己的** `running_tag_of`
# 形态，不另立第二份取 tag 的实现），然后逐服务比较：
#
# | 情形 | 退出码 | 语义 |
# |---|---|---|
# | 在跑 tag == 目标 tag（全部服务） | **0** | `skip` 成立：该 commit **确实**在跑 ⇒ 放行（不报警） |
# | 在跑 tag != 目标 tag（任一服务） | **1** | **判红**（具名：服务 / 期望 tag / 实测 tag / 可复制命令） |
# | 探不到（云调用失败 / 输出无 `RUNNING_TAG=` / 未知服务键） | **3** | **fail-closed**（与 1 分开：三态三分） |
#
# ⚠️ **为什么判红而不是「顺手补一次部署」**：`skip` 的语义是「该 commit 已部署」，被打脸时必须**出声**。
#    自动重试同一个 tag 正是对账断路器（issue #4767 ③ / #5814 B）要防的 churn —— 那个决策归对账侧，
#    本库只负责把**事实**（运行面读数）变成**可归因的红**，具名给出出口。
#
# ⚠️ **本单不改远端磁盘**（issue #6294 边界）：探测是只读的，不 `docker build` / 不 `pull` / 不 `up`，
#    也不取远端 `flock`（它在 `deploy.sh` 里位于锁**之前** ⇒ 不会被在跑的部署挡住）。
#
# 用法（由 `swas-deploy-ci.sh` 的分发点调用，**不要**直接 `bash` 本文件）：
#   running_tag_probe_main <INSTANCE_ID> <REGION> <AK> <SK> <EXPECTED_TAG> <SERVICE_KEY> [<SERVICE_KEY>…]
#   例：running_tag_probe_main i-xxx cn-hangzhou "$AK" "$SK" sha-9d82e2e admin-web
#
# 判据 = tests/unit_ci_workflows/test_deploy_skip_is_not_success.py

# 与 `deploy/swas/deploy.sh` 的 `service_name_of` **同口径**（未知键 ⇒ 拒绝猜，fail-closed）
running_tag_remote_service_of() {
  case "$1" in
    admin-api) echo "admin-api" ;;
    ai-agent)  echo "ai-agent" ;;
    admin-web) echo "admin-web" ;;
    *) echo "" ;;
  esac
}

# 「探不到」出口（退出码 **3**）：与「确认在跑的不是目标 tag」（退 1）是**两种东西**。
running_tag_fail_closed() {   # $1=理由（必须具名）
  echo "::error::跳过部署的运行面自证**无法判定**（探不到）：$1"
  echo "  · 语义：这是「**探不到**」，与「确认在跑的不是目标 tag」是两种东西（后者退 1）"
  echo "  · 出口：在 run 页面 Re-run，或复跑 \`gh workflow run <本腿>.yml --ref main\`"
  echo "  · 复算：\`deploy/scripts/swas-deploy-ci.sh --probe-running-tag ${INSTANCE_ID} ${REGION} <AK> <SK> ${EXPECTED_TAG:-<tag>} ${SERVICES:-<svc>}\`"
  exit 3
}

# 远端探测命令体（**只读**）：只 `docker compose ps` + `docker inspect` —— 不 build / 不 pull / 不 up
#（那会把「自证」变成一次静默部署）。由调用方用 `--probe-running-tag <svc…>` 交给远端执行体分发。
running_tag_remote_cmd() {   # $1=空格分隔的 compose 服务名
  printf '%s' "cd /opt/migao-deploy 2>/dev/null || true; for s in $1; do cid=\$(docker compose -f deploy/swas/docker-compose.yml ps -q \"\$s\" 2>/dev/null || true); cid=\${cid%%\$'\\n'*}; img=\"\"; if [ -n \"\$cid\" ]; then img=\$(docker inspect --format '{{.Config.Image}}' \"\$cid\" 2>/dev/null || true); fi; echo \"RUNNING_TAG=\${s}:\${img##*:}\"; done"
}

# `InvocationResult.Output` 是 **base64**（容错：非 base64 / 无字段 ⇒ 原样打印，绝不吞信息）
running_tag_decode() {   # $1=SWAS 返回原文
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

# 唯一次安装：`aliyun` CLI（与 `swas-deploy-ci.sh` 的主流程同口径；探测与部署共用同一份）
running_tag_install_cli() {
  echo "== 安装 Aliyun CLI =="
  curl -fsSL --retry 3 --retry-delay 3 https://aliyuncli.alicdn.com/aliyun-cli-linux-latest-amd64.tgz -o /tmp/aliyun.tgz
  if ! file /tmp/aliyun.tgz | grep -q "gzip compressed data"; then
    echo "❌ 下载文件损坏或非 gzip 格式"; running_tag_fail_closed "aliyun CLI 下载损坏"
  fi
  tar xzf /tmp/aliyun.tgz -C /tmp
  sudo mv /tmp/aliyun /usr/local/bin/ 2>/dev/null || mv /tmp/aliyun /usr/local/bin/
  echo "✅ Aliyun CLI $(aliyun version 2>/dev/null || echo installed)"
}

# 主入口（**显式参数**：不读 `$@` ⇒ 可被 source）
running_tag_probe_main() {
  INSTANCE_ID=${1:-}
  REGION=${2:-}
  local AK=${3:-} SK=${4:-}
  EXPECTED_TAG=${5:-}
  shift 5 2>/dev/null || true
  SERVICES="$*"

  if [ -z "$INSTANCE_ID" ] || [ -z "$REGION" ] || [ -z "$AK" ] || [ -z "$SK" ] \
     || [ -z "$EXPECTED_TAG" ] || [ -z "$SERVICES" ]; then
    running_tag_fail_closed "参数不全（实例/地域/凭据/期望 tag/服务键 六件缺一不可）"
  fi

  # 逐服务「服务键 → compose 服务名」；未知键 ⇒ 拒绝发命令
  local _s _n REMOTE_SERVICES=""
  for _s in $SERVICES; do
    _n=$(running_tag_remote_service_of "$_s")
    if [ -z "$_n" ]; then
      running_tag_fail_closed "服务键 \`${_s}\` 不是已知服务（允许：admin-api / ai-agent / admin-web）"
    fi
    REMOTE_SERVICES="$REMOTE_SERVICES $_n"
  done
  REMOTE_SERVICES=${REMOTE_SERVICES# }

  REMOTE_PROBE=$(running_tag_remote_cmd "$REMOTE_SERVICES")

  # ── 命令内容字节前置断言（issue #6124 的类级契约；判据 = test_swas_command_content_limit.py）──
  # 本库也发 `RunCommand` ⇒ 同一道闸必须在这里也在场：超限只在**云上那一刻**冒
  # `SDKError 400 / CmdContent.ExceedLimit`（PR 里看不见）⇒ 必须本机判红。
  # 上限出处（**保守值**）：SWAS Open RunCommand 的 CommandContent 与自定义参数在 base64 编码后
  # 综合长度 ≤ 16 KB —— https://help.aliyun.com/zh/simple-application-server/developer-reference/api-swas-open-2020-06-01-runcommand
COMMAND_CONTENT_LIMIT_BYTES=${COMMAND_CONTENT_LIMIT_BYTES:-16384}
  local probe_bytes
  probe_bytes=$(printf '%s' "$REMOTE_PROBE" | wc -c | tr -d ' \n')
  echo "  上限出处：SWAS Open RunCommand base64 后 ≤ 16 KB —— https://help.aliyun.com/zh/simple-application-server/developer-reference/api-swas-open-2020-06-01-runcommand"
  echo "  本次探测命令内容 ${probe_bytes} 字节 / 上限 ${COMMAND_CONTENT_LIMIT_BYTES} 字节"
  if [ "$probe_bytes" -ge "$COMMAND_CONTENT_LIMIT_BYTES" ]; then
    echo "❌ SWAS 命令内容超限：探测命令 ${probe_bytes} 字节 / 上限 ${COMMAND_CONTENT_LIMIT_BYTES} 字节 —— 拒绝发起云调用（issue #6124）"
    running_tag_fail_closed "探测命令内容 ${probe_bytes} 字节 ≥ 上限 ${COMMAND_CONTENT_LIMIT_BYTES} 字节"
  fi

  echo "== 跳过部署的运行面自证（issue #6294）=="
  echo "  期望 tag：${EXPECTED_TAG} · 服务：${REMOTE_SERVICES}"

  running_tag_install_cli
  aliyun configure set --access-key-id "$AK" --access-key-secret "$SK" --region "$REGION"
  aliyun plugin install --names aliyun-cli-swas-open >/dev/null 2>&1 || true

  local INVOKE INVOKE_ID
  if ! INVOKE=$(running_tag_run_cmd); then
    printf '%s\n' "$INVOKE" | head -c 1500; echo
    running_tag_fail_closed "RunCommand 调用失败（上面是 CLI 原文）"
  fi
  INVOKE_ID=$(printf '%s' "$INVOKE" | python3 -c "import sys,json;print(json.load(sys.stdin).get('InvokeId',''))" 2>/dev/null || echo "")
  [ -n "$INVOKE_ID" ] || running_tag_fail_closed "RunCommand 未返回 InvokeId"
  echo "  探测 invokeId=${INVOKE_ID}"

  # 轮询结果（**有硬上界**；状态进终态即返回）
  local DEADLINE=$(( $(date +%s) + ${SWAS_PROBE_TIMEOUT_SECONDS:-180} ))
  local POLL=${SWAS_POLL_INTERVAL_SECONDS:-15}
  local STATUS="" RESULT=""
  while :; do
    if [ "$(date +%s)" -ge "$DEADLINE" ]; then
      running_tag_fail_closed "等待远端探测结果超过 ${SWAS_PROBE_TIMEOUT_SECONDS:-180}s"
    fi
    if ! RESULT=$(aliyun swas-open describe-invocation-result --instance-id "$INSTANCE_ID" \
                    --invoke-id "$INVOKE_ID" --biz-region-id "$REGION" 2>&1); then
      RESULT=$(aliyun swas-open DescribeInvocationResult --InstanceId "$INSTANCE_ID" \
                 --InvokeId "$INVOKE_ID" --RegionId "$REGION" 2>&1) || true
    fi
    STATUS=$(printf '%s' "$RESULT" | python3 -c "import sys,json
d=json.load(sys.stdin)
v=d.get('InvocationResult') or d
print(v.get('InvocationStatus') or v.get('Status') or '')" 2>/dev/null || echo "")
    [ -n "$STATUS" ] || STATUS="Failed"
    case "$STATUS" in
      Success | Failed) break ;;
    esac
    sleep "$POLL"
  done

  local REMOTE_LOG
  REMOTE_LOG=$(running_tag_decode "$RESULT")
  echo "──── 远端探测输出（status=${STATUS}）────────"
  printf '%s\n' "$REMOTE_LOG"
  echo "──────── 远端探测输出结束 ────────"

  [ "$STATUS" = "Success" ] || running_tag_fail_closed "远端探测命令执行失败（status=${STATUS}）"
  case "$REMOTE_LOG" in
    *"RUNNING_TAG="*) ;;
    *) running_tag_fail_closed "远端输出里没有 \`RUNNING_TAG=\` 读数（deploy.sh 版本可能不含探测模式）" ;;
  esac

  # ── 比较：**逐服务**具名判红 ──────────────────────────────────────────────
  local RC=0 got
  for _s in $REMOTE_SERVICES; do
    got=$(printf '%s\n' "$REMOTE_LOG" | sed -n "s/^RUNNING_TAG=${_s}://p" | head -n 1)
    if [ "$got" = "$EXPECTED_TAG" ]; then
      echo "✅ ${_s}：在跑 tag = ${got}（= 目标）⇒ 本轮的「跳过部署」成立"
      continue
    fi
    RC=1
    echo "::error::${_s} 的运行 tag ≠ 目标 tag ⇒ 本轮的「跳过部署」**不成立**（issue #6294：skip 不得冒充已部署）"
    echo "  · 服务：${_s} · 期望 tag：${EXPECTED_TAG} · 实测 tag：${got:-（空）容器没起 / 取不到镜像}"
    echo "  · 也就是说：该 commit 的部署 run 报 success、但环境**并没有在跑它** ⇒ 不要相信 run 结论"
    echo "  · 可复制复算命令："
    echo "      deploy/scripts/swas-deploy-ci.sh --probe-running-tag ${INSTANCE_ID} ${REGION} <AK> <SK> ${EXPECTED_TAG} ${_s}"
    echo "  · 出口：确认根因后复跑 \`gh workflow run <本腿>.yml --ref main\`（或在 run 页面 Re-run）；"
    echo "    若是磁盘 / 远端故障导致构建被闸门中止，先处理远端磁盘（issue #6294 的运维半边）"
  done

  if [ "$RC" -eq 0 ]; then
    echo "✅ 运行面自证通过：${REMOTE_SERVICES} 全部在跑 ${EXPECTED_TAG}"
  fi
  exit "$RC"
}

# `RunCommand`（新版 `--biz-region-id` / 旧版 `--RegionId` 双兼容，与 `swas-deploy-ci.sh` 同口径）
running_tag_run_cmd() {   # 用全局：INSTANCE_ID REGION REMOTE_PROBE
  local out1 out2
  out1=$(aliyun swas-open run-command --instance-id "$INSTANCE_ID" --name migao-ci-running-tag \
           --type RunShellScript --timeout 120 --biz-region-id "$REGION" \
           --command-content "$REMOTE_PROBE" 2>&1) && { echo "$out1"; return 0; }
  if printf '%s' "$out1" | grep -qE "not a valid api|unknown flag"; then
    out2=$(aliyun swas-open RunCommand --InstanceId "$INSTANCE_ID" --Name migao-ci-running-tag \
             --Type RunShellScript --Timeout 120 --RegionId "$REGION" \
             --CommandContent "$REMOTE_PROBE" 2>&1) && { echo "$out2"; return 0; }
  fi
  printf '%s\n' "$out1" >&2
  return 1
}
