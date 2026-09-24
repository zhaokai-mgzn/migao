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
#
# ── 2026-09-21 部署链加固之二（issue #4852，排队的旧 run 静默回退生产）──
# 闸门本体在远端 `deploy/swas/deploy.sh`（「target tag 是当前在跑 tag 的祖先 ⇒ 跳过该服务 + 告警」，
# 且必须**在 flock 之内**判 ⇒ 只能在远端判，否则有 TOCTOU 窗口）。本脚本负责**三件接线**：
#   ② **显式降级许可**：把 `ALLOW_DOWNGRADE`（0/1）注入远端 —— workflow 的 MODE=rollback
#      （`gh workflow run deploy-*.yml -f image_tag=<tag>`）给 1；#4767 的**自动回滚**那次尝试也给 1
#      （回滚本身就是往回走）。缺省 0 ⇒ 闸门生效。**只认 `1`**，其它值一律当 0（不许误开）。
#   ③ **部署结论行必须说「实际生效 tag」**：解析远端打的 `EFFECTIVE_TAG=<svc>:<tag>` /
#      `DOWNGRADE_SKIPPED=<svc>:<target>:<running>`，逐服务落 `$GITHUB_STEP_SUMMARY` +
#      拼进 `✅ SWAS 部署成功（…）` 那一行 —— 事故里那句 `✅ 部署成功（tag=sha-7b03ed3）`
#      只说了**请求的** tag，正是误导源。
#   ④ 远端 `::warning::` 行随远端输出一起 printf 到 stdout ⇒ GitHub 会把它渲染成注解（不静默）。
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

INSTANCE_ID=$1
REGION=$2
AK=$3
SK=$4
ACR_USERNAME=${5:-}
ACR_PASSWORD=${6:-}
IMAGE_TAG=${7:-latest}
# 显式降级许可（issue #4852 ②）：`gh workflow run deploy-*.yml -f image_tag=<tag>` 是**人工回滚接口**
# ⇒ workflow 在 MODE=rollback 时注入 `ALLOW_DOWNGRADE=1`（由本脚本转成远端环境变量）。
# **只认 `1`**：其它值（空 / 0 / 拼错）一律当 0 ⇒ 许可只能由显式路径给出，不会被环境意外打开。
ALLOW_DOWNGRADE=${ALLOW_DOWNGRADE:-0}
case "$ALLOW_DOWNGRADE" in
  1) ;;
  *) ALLOW_DOWNGRADE=0 ;;
esac

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
# 以及远端逐服务打的「实际生效 tag / 因往回走被跳过」（issue #4852 ③）。
capture_remote_log() {
  local res=$1 prev
  REMOTE_LOG=$(extract_remote_log "$res" 2>/dev/null) || REMOTE_LOG=""
  if [ -z "$REMOTE_LOG" ]; then REMOTE_LOG="$res"; fi
  # ⚠️ 不接 `head -1`：pipefail 下 `head` 提前退出会让上游吃 SIGPIPE ⇒ 整条管道非零 ⇒ set -e 误杀
  prev=$(printf '%s\n' "$REMOTE_LOG" | sed -n 's/^PREV_GOOD_TAG=//p')
  PREV_GOOD_TAG=${prev%%$'\n'*}
  # 逐服务「实际生效 tag」（`<svc>:<tag>`，三行）+ 被闸门跳过的服务（`<svc>:<target>:<running>`）
  EFFECTIVE_TAGS=$(printf '%s\n' "$REMOTE_LOG" | sed -n 's/^ *EFFECTIVE_TAG=//p')
  DOWNGRADE_SKIPS=$(printf '%s\n' "$REMOTE_LOG" | sed -n 's/^ *DOWNGRADE_SKIPPED=//p')
  return 0
}

# 逐服务生效 tag → 一行（`admin-api=sha-x / ai-agent=sha-y / admin-web=sha-z`）；
# 远端没打标记（deploy.sh 版本早于 #4852）⇒ 空串（**不是**「已确认生效」）。
effective_tags_line() {
  printf '%s\n' "$EFFECTIVE_TAGS" \
    | awk -F: 'NF>=2 {printf "%s%s=%s", (n++ ? " / " : ""), $1, $2} END {if (n) print ""}'
}

# 拼进部署结论行：`；本次实际生效：`…``（取不到就**明写取不到**，不许沉默）
effective_suffix() {
  local line
  line=$(effective_tags_line)
  if [ -n "$line" ]; then
    echo "；本次实际生效：\`$line\`"
  else
    echo "；⚠️ 远端未给出「实际生效 tag 逐服务」（deploy.sh 版本早于 #4852 ⇒ 这不是「已确认」）"
  fi
}

# 「实际生效 tag 逐服务一行」+ 被跳过的服务（**落 job summary**，issue #4852 ③）
report_effective_tags() {
  local line skips
  line=$(effective_tags_line)
  if [ -z "$line" ]; then
    say "- ⚠️ 本次**无法**给出「实际生效 tag 逐服务」：远端输出里没有 \`EFFECTIVE_TAG=\` 标记"
    say "  （远端 deploy.sh 版本早于 #4852 ⇒ 这一项是「未知」，不是「已确认生效」）"
    return 0
  fi
  say "- 本次**实际生效** tag（逐服务）：\`$line\`"
  skips=$(printf '%s\n' "$DOWNGRADE_SKIPS" \
    | awk -F: 'NF>=3 {printf "%s%s（跳过：target=%s 是当前在跑 %s 的祖先）", (n++ ? "；" : ""), $1, $2, $3} END {if (n) print ""}')
  if [ -n "$skips" ]; then
    say "- ⚠️ 因「不许往回走」被跳过的服务（issue #4852）：$skips"
    say "  · 这是**期望行为**：更新的那次部署已生效，本次旧 run 不得把它回退"
    say "  · **故意**回滚请走显式接口：\`gh workflow run deploy-admin-api.yml -f image_tag=<tag>\`（该路径注入 ALLOW_DOWNGRADE=1）"
  fi
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
# 自愈式同步：每次先拉取**与本次镜像 tag 同源**的那份 deploy.sh 再执行（服务器不再维护手工副本）。
# ⚠️ **不是**「最新」（= main）—— 见下方 #5120 段：ref 由镜像 tag 推导，取不到即 fail-closed。
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
#
# ④ 降级许可（issue #4852 ②）：`ALLOW_DOWNGRADE=__ALLOW_DOWNGRADE__` 是**每次尝试各自渲染**的
#    占位符（`deploy_attempt` 替换；渲染后仍留占位符 ⇒ 当场报错，绝不静默当「无许可」）。
#    写成 `export …;` 前置（而不是 `${VAR}=… bash …` 前缀）⇒ 「cp → mv -f → bash deploy.sh」
#    的**原子安装形态**逐字不变（那是既有护栏，见 tests/unit_ci_workflows/test_swas_deploy_ci_bootstrap.py）。
BOOTSTRAP="export ALLOW_DOWNGRADE=__ALLOW_DOWNGRADE__; PREV=\$(cat /opt/migao-deploy/.last-good-tag 2>/dev/null || true); if [ -z \"\$PREV\" ] && command -v docker >/dev/null 2>&1; then PREV=\$(docker ps --format '{{.Image}}' 2>/dev/null | grep 'ai-customer-service/' | sed 's/.*://' | sort | uniq -c | sort -rn | head -1 | awk '{print \$2}'); fi; echo \"PREV_GOOD_TAG=\${PREV:-}\"; ${REGISTRY_SETUP}SRC=\$(mktemp -d) && TAR=\$(mktemp) && curl -fsSL --retry 3 https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/__BOOTSTRAP_REF__ -o \"\$TAR\" && tar xzf \"\$TAR\" -C \"\$SRC\" --strip-components=1 && mkdir -p /opt/migao-deploy && cp \"\$SRC\"/deploy/swas/deploy.sh /opt/migao-deploy/.deploy.sh.new && mv -f /opt/migao-deploy/.deploy.sh.new /opt/migao-deploy/deploy.sh && bash /opt/migao-deploy/deploy.sh ${IMAGE_TAG}; rc=\$?; if [ \$rc -eq 0 ]; then echo \"${IMAGE_TAG}\" > /opt/migao-deploy/.last-good-tag; fi; rm -rf \"\$SRC\" \"\$TAR\"; exit \$rc"

# ══════════════════════════════════════════════════════════════════════════
# ⑤ 部署脚本**自己**也必须与镜像 tag 同源（issue #5120）
#
# 病根（**#5083 修掉的那一层之上，又高了一层**）：`deploy.sh` **内部**的配置
# （compose / nginx）已按 tag 同源（`config_ref_for_tag` ⇒ `CONFIG_REF_RESOLVED`，
# 取不到即 fail-closed），但 **bootstrap 自己**此前仍无条件以 `refs/heads/main`
# 下载 **`deploy.sh` 本身** ⇒ 回滚到旧 tag 时是「**旧镜像 + 旧配置 + 新部署脚本**」，
# 与被 #5083 修掉的那层**同一形态**（未定义行为、且不报错）。
#
# 口径（与 `deploy/swas/deploy.sh` 的 `tag_to_sha` / `config_ref_for_tag` **逐字对齐**）：
#   `sha-<hex>`（纯 hex 且长度 ≥ 7）⇒ `<hex>`（不可变引用，与镜像**同一 commit**）
#   其它非空形态                     ⇒ `refs/tags/<tag>`（tag 不存在 ⇒ 404 ⇒ fail-closed）
#   空                               ⇒ 空串 ⇒ **调用方 fail-closed**
# ⇒ 本脚本里**不存在**「无条件取 main 的 deploy.sh」这条路径。
#
# ⚠️ **为什么不直接复用 `deploy.sh` 里那一份**（最少代码阶梯的"复用"档已评估）：
#   **鸡生蛋** —— 那两份函数所在的 `deploy.sh` **正是 bootstrap 要下载的东西**，
#   下载完成之前它不存在于服务器上，无从 source。故这里保留**第二份**实现，
#   并由守卫测试 tests/unit_ci_workflows/test_swas_bootstrap_same_source_guard.py
#   **逐字比对**两份口径（漂移即红）⇒「第二份」不可能静默走样。
# ══════════════════════════════════════════════════════════════════════════

# `sha-<hex>` → 提交 sha；其它形态（latest / v1.2.3 / 空）⇒ 空串（= 没有提交可锚）
bootstrap_tag_to_sha() {
  local t=${1#sha-}
  case "$t" in
    *[!0-9a-f]*|"") echo ""; return 0 ;;
  esac
  if [ "${#t}" -ge 7 ]; then echo "$t"; else echo ""; fi
  return 0
}

# 部署脚本的下载 ref：与镜像 tag **同源** ⇒ 任何分支都不可能返回 `refs/heads/main`
bootstrap_ref_for_tag() {
  local t=$1 s
  s=$(bootstrap_tag_to_sha "$t")
  if [ -n "$s" ]; then echo "$s"; return 0; fi
  if [ -n "$t" ]; then echo "refs/tags/$t"; fi
  return 0
}

# 渲染一次尝试的 bootstrap 的 **tag + ref** 部分（**唯一一处** ref 注入点）。
# 返回非零 = **取不到与 tag 同源的 ref** ⇒ 调用方必须 fail-closed（**绝不**静默回落 main）。
# ⚠️ 替换顺序**有意义**：先 tag 再 ref —— 反过来的话，`refs/tags/<tag>` 里的 tag 文本
#    会被随后的 tag 替换**二次改写**（如 IMAGE_TAG=`latest`、tag=`sha-abc1234`
#    ⇒ ref 被误改成 `refs/tags/sha-abc1234`）。
# ⚠️ **许可占位符 `__ALLOW_DOWNGRADE__` 有意不在这里渲染** —— 它由 `deploy_attempt` 就地渲染：
#    那一行是既有护栏（tests/unit_ci_workflows/test_swas_deploy_no_downgrade.py 逐字钉住它）。
render_bootstrap() {
  local tag=$1 ref out
  ref=$(bootstrap_ref_for_tag "$tag")
  [ -n "$ref" ] || return 1
  out=${BOOTSTRAP//"$IMAGE_TAG"/"$tag"}
  out=${out//__BOOTSTRAP_REF__/$ref}
  case "$out" in *__BOOTSTRAP_REF__*) return 1 ;; esac
  printf '%s' "$out"
  return 0
}

# ── 一次完整的「触发 + 轮询」（issue #4767 ①②③）────────────────────────────
# 结果写进全局：DEPLOY_RC（0=Success / 1=远端 Failed / 2=硬超时 / 3=云 API 调用失败）
#               REMOTE_LOG（**解码后**的远端输出）、PREV_GOOD_TAG（远端记录的上一个可用 tag）
# ⚠️ 本函数**恒返回 0**（结果只走 DEPLOY_RC）：`set -e` 下「函数返回非零」会当场终止脚本，
#    那样重试 / 回滚 / 告警全都被跳过（实测踩到，红证方向正好反过来）。
deploy_attempt() {
  local tag=$1 allow=${2:-0}
  DEPLOY_RC=3
  REMOTE_LOG=""
  PREV_GOOD_TAG=""
  EFFECTIVE_TAGS=""
  DOWNGRADE_SKIPS=""
  # 每次尝试**各自**一个墙钟预算：一次尝试绝不无限轮询
  DEADLINE=$(( $(date +%s) + DEPLOY_TIMEOUT_SECONDS ))

  # ⚠️ BOOTSTRAP 里的 tag 是**CI 侧**展开的（`${IMAGE_TAG}`，见上面的转义纪律）⇒ 回滚要用**别的**
  #    tag 时必须按目标 tag 重写这一处。少写这一步的后果最恶劣：回滚会把**同一个坏镜像**再部署一次
  #    还报告"已回滚"（实测踩到）⇒ 替换没生效时**当场报错**，不许静默继续。
  #    ⚠️ 判据里的基线要**先渲染掉降级许可占位符**（否则占位符一被替换，`!= $BOOTSTRAP` 恒成立 ⇒
  #    这条检查静默失效）。
  # ⚠️ ref（issue #5120）与 tag 一样**每次尝试各自渲染**：回滚用的 tag 与本次不同
  #    ⇒ 取到的 deploy.sh 也必须是对应**那个 tag** 的那一份。取不到 ⇒ **fail-closed**。
  local bootstrap baseline
  if ! bootstrap=$(render_bootstrap "$tag"); then
    echo "❌ 取不到与 tag 同源的 ref（tag=\`${tag:-<空>}\`）⇒ **拒绝回落到 main 的 deploy.sh**（issue #5120）"
    echo "   · 部署脚本必须与镜像**同一 commit**：否则回滚是「旧镜像 + 旧配置 + **新部署脚本**」（未定义行为、且不报错）"
    echo "   · 修法：tag 用 \`sha-<≥7位hex>\` 形态（CI 部署的正常形态），或一个**确实存在**的 tag 名"
    DEPLOY_RC=3
    return 0
  fi
  bootstrap=${bootstrap//__ALLOW_DOWNGRADE__/$allow}
  # 判据里的基线要**先渲染掉 ref + 降级许可占位符**（否则占位符一被替换，`!= $BOOTSTRAP` 恒成立
  # ⇒ 这条检查静默失效）。
  baseline=$(render_bootstrap "$IMAGE_TAG") || baseline=""
  baseline=${baseline//__ALLOW_DOWNGRADE__/$allow}
  if [ "$tag" != "$IMAGE_TAG" ] && [ "$bootstrap" = "$baseline" ]; then
    echo "❌ 回滚 tag 替换未生效：BOOTSTRAP 里找不到当前 tag（${IMAGE_TAG}）—— 拒绝用错 tag 部署"
    DEPLOY_RC=3
    return 0
  fi
  # 降级许可（issue #4852 ②）必须真的注进去：占位符还在 ⇒ 远端会拿到「许可状态未知」⇒ 拒绝部署
  case "$bootstrap" in
    *__ALLOW_DOWNGRADE__*)
      echo "❌ 降级许可注入未生效：BOOTSTRAP 里仍留 __ALLOW_DOWNGRADE__ 占位符 —— 拒绝在「许可状态未知」下部署"
      DEPLOY_RC=3
      return 0 ;;
  esac
  echo "  本次尝试：tag=${tag} / ALLOW_DOWNGRADE=${allow}"

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
say "- 显式降级许可（ALLOW_DOWNGRADE）：\`$ALLOW_DOWNGRADE\`（=1 ⇒ **这是显式回滚**，允许「往回走」）"
say "- 硬超时预算：${DEPLOY_TIMEOUT_SECONDS}s / 次尝试（单次 CLI 调用 ${CLI_TIMEOUT_SECONDS}s）"

deploy_attempt "$IMAGE_TAG" "$ALLOW_DOWNGRADE"
ATTEMPT_RC=$DEPLOY_RC
emit_remote_log "第 1 次部署（tag=${IMAGE_TAG}）远端输出"
report_effective_tags

if [ "$ATTEMPT_RC" -eq 0 ]; then
  say ""
  say "✅ SWAS 部署成功（tag=\`$IMAGE_TAG\`）$(effective_suffix)"
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

deploy_attempt "$IMAGE_TAG" "$ALLOW_DOWNGRADE"
ATTEMPT_RC=$DEPLOY_RC
emit_remote_log "第 2 次部署（自动重试，tag=${IMAGE_TAG}）远端输出"
report_effective_tags

if [ "$ATTEMPT_RC" -eq 0 ]; then
  say ""
  say "✅ SWAS 部署成功（第 2 次尝试，tag=\`$IMAGE_TAG\`）$(effective_suffix)"
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

# ⚠️ 回滚**本身就是往回走**（issue #4852 ②）⇒ 这一次尝试带**显式降级许可** `ALLOW_DOWNGRADE=1`，
#    否则新闸门会把 #4767 的「失败即回滚」也一起挡掉（= 削弱既有护栏）。
echo "⚠️ 回滚尝试：这是**显式回滚**（#4767 失败即回滚）⇒ ALLOW_DOWNGRADE=1，允许往回走"
deploy_attempt "$ROLLBACK_TAG" 1
ROLLBACK_RC=$DEPLOY_RC
emit_remote_log "回滚部署（tag=${ROLLBACK_TAG}）远端输出"
report_effective_tags

if [ "$ROLLBACK_RC" -eq 0 ]; then
  say ""
  say "::error::部署失败（tag=\`$IMAGE_TAG\`）—— **已自动回滚到上一个可用镜像 tag=\`$ROLLBACK_TAG\`**，环境已恢复服务。$(effective_suffix)"
  say "根因在**新镜像**，不在环境：请看上面第 1/2 次部署的远端输出（已解码，含真正的报错）。"
  exit 1
fi

say ""
say "::error::部署失败（tag=\`$IMAGE_TAG\`），**且自动回滚（tag=\`$ROLLBACK_TAG\`）也失败**"
say "⇒ 环境可能处于坏状态，请**立即人工介入**。"
recovery_manual
exit 1
