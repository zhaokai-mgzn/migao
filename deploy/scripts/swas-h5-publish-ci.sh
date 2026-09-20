#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# CI → SWAS：把 `frontend/worker-h5/` 发布到 `app.migaozn.com` 静态根下的 `w/`（issue #4837）
#
# 用法: swas-h5-publish-ci.sh <INSTANCE_ID> <REGION> [ACCESS_KEY_ID] [ACCESS_KEY_SECRET] [COMMIT_SHA]
#   · AK/SK 省略 ⇒ 走本机 `aliyun` 既有配置（**人工排障 / 本地复跑**用；CI 必须显式传入）
#   · COMMIT_SHA 省略 ⇒ 取 `$GITHUB_SHA`（远端按该 sha 从 codeload 取源码 —— **不可变引用**，
#     与「按 refs/heads/main 取」不同：后者在连续合并时会与 CI 命中的 commit 漂移）
#
# 通道：与 `deploy/scripts/swas-deploy-ci.sh` **同一把钥匙、同一条云 API**（SWAS RunCommand）——
# **不引入任何新 secret**（用既有 `ALIYUN_ACCESS_KEY_ID/SECRET`，实例/地域与 deploy workflow 同值）。
#
# 远端逻辑**不在本文件里**：本文件只做「取 sha → 发起云调用 → 轮询 → 解码输出 → 断言」，
# 真正动手的是 `deploy/swas/h5-publish-remote.sh`（同一份文件也被守卫测试在本地沙箱里跑）。
#
# 🔴 红线由远端脚本的 `assert_target_safe()` 强制执行（目标只能是 `<静态根>/w` 子树）；
#    本文件再加一层**验收断言**：
#      ① 远端报告 `TARGET` 必须等于期望值；
#      ② `PUBLISHED_INDEX_SHA256` 必须等于**本仓库** `frontend/worker-h5/index.html` 的哈希
#         （否则 = 发布的不是这次审过的内容 ⇒ fail-closed）；
#      ③ `PARENT_INDEX_BEFORE_SHA256 == PARENT_INDEX_AFTER_SHA256`
#         （静态根 —— 同时承载线上 C 端 H5 —— 未被触碰）。
#
# 退出码：0 = 已发布且三条断言全过；非零 = 未发布 / 已发布但与本次内容不一致（显式失败）。
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

[ $# -ge 2 ] || {
  echo "用法: swas-h5-publish-ci.sh <INSTANCE_ID> <REGION> [ACCESS_KEY_ID] [ACCESS_KEY_SECRET] [COMMIT_SHA]" >&2
  exit 2
}

INSTANCE_ID=$1
REGION=$2
AK=${3:-}
SK=${4:-}
SHA=${5:-${GITHUB_SHA:-}}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REMOTE_SCRIPT="$ROOT/deploy/swas/h5-publish-remote.sh"
LOCAL_INDEX="$ROOT/frontend/worker-h5/index.html"

# 超时参数（与 swas-deploy-ci.sh 同口径：**墙钟**上界，不是次数上界；CI 守卫测试调小以免空耗）
PUBLISH_TIMEOUT_SECONDS=${SWAS_H5_PUBLISH_TIMEOUT_SECONDS:-300}
CLI_TIMEOUT_SECONDS=${SWAS_CLI_TIMEOUT_SECONDS:-60}
POLL_INTERVAL_SECONDS=${SWAS_H5_POLL_INTERVAL_SECONDS:-10}
DEADLINE=$(( $(date +%s) + PUBLISH_TIMEOUT_SECONDS ))

SUMMARY_FILE=${GITHUB_STEP_SUMMARY:-}
say() {
  echo "$*"
  if [ -n "$SUMMARY_FILE" ]; then printf '%s\n' "$*" >> "$SUMMARY_FILE"; fi
  return 0
}

die() { echo "❌ $*" >&2; exit 1; }

file_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

# 受 deadline 约束的等待（绝不 sleep 超过剩余预算）
nap() {
  local want=$1 left
  left=$(( DEADLINE - $(date +%s) ))
  [ "$left" -lt "$want" ] && want=$left
  if [ "$want" -gt 0 ]; then sleep "$want"; fi
  return 0
}

# 带硬上界的子进程执行（防 CLI 自己挂住 ⇒ 轮询永不返回 ⇒ run 卡在 in_progress 占住并发组；
# 与 swas-deploy-ci.sh 的 with_deadline 同因、同法）
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

# aliyun CLI 新版 swas-open 要求 kebab-case，旧版用 CamelCase ⇒ 双兼容
run_cmd() {
  local k=$1 c=$2; shift 2
  local kebab_args=() camel_args=() arg
  for arg in "$@"; do
    case "$arg" in
      --instance-id)     kebab_args+=(--instance-id);     camel_args+=(--InstanceId) ;;
      --region-id)       kebab_args+=(--biz-region-id);   camel_args+=(--RegionId) ;;
      --name)            kebab_args+=(--name);            camel_args+=(--Name) ;;
      --type)            kebab_args+=(--type);            camel_args+=(--Type) ;;
      --timeout)         kebab_args+=(--timeout);         camel_args+=(--Timeout) ;;
      --command-content) kebab_args+=(--command-content); camel_args+=(--CommandContent) ;;
      --invoke-id)       kebab_args+=(--invoke-id);       camel_args+=(--InvokeId) ;;
      *)                 kebab_args+=("$arg");            camel_args+=("$arg") ;;
    esac
  done
  local out1 out2
  out1=$(with_deadline "$CLI_TIMEOUT_SECONDS" aliyun swas-open "$k" "${kebab_args[@]}") && { echo "$out1"; return 0; }
  if echo "$out1" | grep -qE "not a valid api|unknown flag"; then
    out2=$(with_deadline "$CLI_TIMEOUT_SECONDS" aliyun swas-open "$c" "${camel_args[@]}") && { echo "$out2"; return 0; }
  fi
  echo "$out1" >&2
  return 1
}

extract_status() {
  python3 -c "import sys,json;d=json.load(sys.stdin);v=d.get('InvocationResult') or d;print(v.get('InvocationStatus') or v.get('Status') or '')" 2>/dev/null || echo ""
}

# `InvocationResult.Output` 是 **base64**；解不开就原样打印（**绝不吞信息**）
extract_remote_log() {
  python3 - "$1" <<'PY'
import base64, binascii, json, sys
raw = sys.argv[1] if len(sys.argv) > 1 else ""
try:
    data = json.loads(raw)
except Exception:
    sys.stdout.write(raw); sys.exit(0)
v = data.get("InvocationResult") if isinstance(data, dict) else None
v = v if isinstance(v, dict) else (data if isinstance(data, dict) else {})
out = v.get("Output") if isinstance(v.get("Output"), str) else None
if out is None:
    sys.stdout.write(raw); sys.exit(0)
try:
    sys.stdout.write(base64.b64decode(out.strip(), validate=True).decode("utf-8", "replace"))
except (binascii.Error, ValueError):
    sys.stdout.write(out)
PY
}

# ── 前置校验（在**发起任何云调用之前**）─────────────────────────────────────
[ -f "$REMOTE_SCRIPT" ] || die "远端执行体缺失：$REMOTE_SCRIPT"
[ -f "$LOCAL_INDEX" ] || die "本仓库缺少 frontend/worker-h5/index.html（发布内容单一源）"
[ -n "$INSTANCE_ID" ] || die "缺少 SWAS 实例 ID"
[ -n "$REGION" ] || die "缺少地域"
[ -n "$SHA" ] || die "缺少 COMMIT_SHA（也没拿到 \${GITHUB_SHA}）"
case "$SHA" in
  *[!0-9a-fA-F]*) die "COMMIT_SHA 非法：'$SHA'（只接受十六进制；本脚本把它拼进远端命令，故先做字符集校验）" ;;
esac
[ "${#SHA}" -ge 7 ] || die "COMMIT_SHA 太短：'$SHA'"

# 静态根/子目录：字符集白名单（**注入防线**：这三个值会被拼进远端命令内容）。
# ⚠️ 判据写**否定类**（`*[!允许集]*`）而不是「正向类 + `*`」—— 后者只要串首是 `/`、串尾落在允许集内
#    就会匹配成功（`/tmp/er;rm -rf/` 也能过）⇒ 那是**假校验**，比不校验更坏。
STATIC_ROOT=${H5_STATIC_ROOT-/opt/migao-deploy/h5}
SUBDIR=${H5_SUBDIR-w}
case "$STATIC_ROOT" in
  /*) : ;;
  *) die "H5_STATIC_ROOT 必须是绝对路径：'$STATIC_ROOT'" ;;
esac
case "$STATIC_ROOT" in
  *[!A-Za-z0-9._/-]*) die "H5_STATIC_ROOT 含非法字符：'$STATIC_ROOT'" ;;
esac
case "$SUBDIR" in
  ""|*/*|*[!A-Za-z0-9._-]*) die "H5_SUBDIR 非法：'$SUBDIR'（单一组件，白名单 [A-Za-z0-9._-]）" ;;
esac
EXPECTED_TARGET="$STATIC_ROOT/$SUBDIR"
LOCAL_SHA="$(file_sha256 "$LOCAL_INDEX")"

say "# worker-h5 静态落位（issue #4837）"
say ""
say "- 目标：\`$EXPECTED_TARGET\`（静态根 = nginx 的 \`root\`，**同时承载 C 端 H5 ⇒ 只收敛 w/ 子树**）"
say "- 发布源：\`https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/$SHA\`（不可变 commit）"
say "- 本地 \`frontend/worker-h5/index.html\` 哈希：\`$LOCAL_SHA\`"

# ── 组装远端命令 = 远端执行体 + 三个环境变量前缀（无参数拼接 ⇒ 无注入面）──────
COMMAND_CONTENT="export H5_PUBLISH_SHA=$SHA
export H5_STATIC_ROOT=$STATIC_ROOT
export H5_SUBDIR=$SUBDIR
$(cat "$REMOTE_SCRIPT")"

if [ -n "$AK" ] && [ -n "$SK" ]; then
  command -v aliyun >/dev/null 2>&1 || die "未安装 aliyun CLI（CI 侧应先安装，见 deploy-frontend.yml）"
  aliyun configure set --access-key-id "$AK" --access-key-secret "$SK" --region "$REGION" >/dev/null
else
  echo "ℹ️ 未传 AK/SK —— 使用本机 aliyun 既有配置（人工排障模式）"
fi

echo "== 触发 SWAS 云助手执行远端发布脚本 =="
INVOKE=$(run_cmd run-command RunCommand \
  --instance-id "$INSTANCE_ID" \
  --name migao-worker-h5-publish \
  --type RunShellScript \
  --timeout 600 \
  --region-id "$REGION" \
  --command-content "$COMMAND_CONTENT" 2>&1) || die "RunCommand 调用失败：$INVOKE"
INVOKE_ID=$(echo "$INVOKE" | python3 -c "import sys,json;print(json.load(sys.stdin).get('InvokeId',''))" 2>/dev/null || echo "")
[ -n "$INVOKE_ID" ] || die "未获得 InvokeId：$INVOKE"
echo "publish invokeId=$INVOKE_ID"

# ── 轮询（墙钟上界）─────────────────────────────────────────────────────────
REMOTE_LOG=""
STATUS=""
while :; do
  [ "$(( DEADLINE - $(date +%s) ))" -gt 0 ] || die "发布硬超时（>${PUBLISH_TIMEOUT_SECONDS}s）：远端状态未知"
  RES=$(run_cmd describe-invocation-result DescribeInvocationResult \
    --instance-id "$INSTANCE_ID" \
    --invoke-id "$INVOKE_ID" \
    --region-id "$REGION" 2>&1) || { nap "$POLL_INTERVAL_SECONDS"; continue; }
  STATUS=$(extract_status <<<"$RES")
  if [ "$STATUS" = "Success" ] || [ "$STATUS" = "Failed" ]; then
    REMOTE_LOG=$(extract_remote_log "$RES")
    [ -n "$REMOTE_LOG" ] || REMOTE_LOG="$RES"
    break
  fi
  echo "  publish status: ${STATUS:-?}（剩余 $(( DEADLINE - $(date +%s) ))s）"
  nap "$POLL_INTERVAL_SECONDS"
done

echo ""
echo "──────── 远端发布输出 ────────"
printf '%s\n' "$REMOTE_LOG"
echo "──────── 远端发布输出结束 ────────"
if [ -n "$SUMMARY_FILE" ]; then
  { echo ""; echo "### 远端发布输出"; echo '````'; printf '%s\n' "$REMOTE_LOG"; echo '````'; } >> "$SUMMARY_FILE"
fi

[ "$STATUS" = "Success" ] || die "远端发布失败（InvocationStatus=${STATUS}）—— 见上面的完整远端输出"

# ── 三条验收断言（fail-closed）────────────────────────────────────────────
grep -q "^TARGET=$EXPECTED_TARGET$" <<<"$REMOTE_LOG" \
  || die "远端 TARGET 不是期望值：期望 '$EXPECTED_TARGET'（输出里：$(grep -m1 '^TARGET=' <<<"$REMOTE_LOG" || echo '(缺 TARGET 行)')）"

REMOTE_INDEX_SHA=$(sed -n 's/^PUBLISHED_INDEX_SHA256=//p' <<<"$REMOTE_LOG" | head -1)
[ "$REMOTE_INDEX_SHA" = "$LOCAL_SHA" ] \
  || die "发布的 index.html 与本仓库内容不一致：远端 '$REMOTE_INDEX_SHA' ≠ 本地 '$LOCAL_SHA'"

PARENT_BEFORE=$(sed -n 's/^PARENT_INDEX_BEFORE_SHA256=//p' <<<"$REMOTE_LOG" | head -1)
PARENT_AFTER=$(sed -n 's/^PARENT_INDEX_AFTER_SHA256=//p' <<<"$REMOTE_LOG" | head -1)
[ -n "$PARENT_BEFORE" ] && [ "$PARENT_BEFORE" = "$PARENT_AFTER" ] \
  || die "静态根 index.html 被触碰（$PARENT_BEFORE → ${PARENT_AFTER}）—— 红线"

say ""
say "✅ 发布完成：\`$EXPECTED_TARGET/index.html\` 哈希 \`$REMOTE_INDEX_SHA\`（= 本仓库），静态根未触碰（\`$PARENT_AFTER\`）"
