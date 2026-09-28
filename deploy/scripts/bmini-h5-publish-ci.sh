#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# CI → SWAS：把 `frontend/bmini-app` 的 h5 构建产物发布到 `app.migaozn.com` 静态根下的 `b/`（issue #5668）
#
# 用法: bmini-h5-publish-ci.sh <INSTANCE_ID> <REGION> [ACCESS_KEY_ID] [ACCESS_KEY_SECRET] [IMAGE_TAG]
#   · AK/SK 省略 ⇒ 走本机 `aliyun` 既有配置（**人工排障 / 本地复跑**用；CI 必须显式传入）
#   · IMAGE_TAG 省略 ⇒ 拒绝（镜像 tag 必须由调用方显式给出：**不可变引用**，与"按 latest 取"不同——
#     后者会把「发布的是哪一次构建」变成不可判定，而本腿最值钱的判据正是产物身份）
#
# 通道：与 `deploy/scripts/swas-h5-publish-ci.sh`（工人端 `w/`）**同一把钥匙、同一条云 API**
# （SWAS RunCommand）—— **不引入任何新 secret**（用既有 `ALIYUN_ACCESS_KEY_ID/SECRET`）。
#
# 产物怎么上到实例：**ACR 传输镜像**（见 `deploy/bmini-h5/Dockerfile` 的理由）。
#   CI 侧只做「取 sha → 发起云调用 → 轮询 → 解码输出 → 断言」，真正动手的是
#   `deploy/swas/bmini-h5-publish-remote.sh`（同一份文件也被守卫测试在本地沙箱里跑）。
#
# 🔴 为什么**不**把工人端那条腿的脚本参数化：那条腿**线上在跑**，且它的形状（源码目录 = 产物、
#    零构建）与本腿（构建产物 + 镜像搬运 + 命名空间断言）不同。改共用一个脚本 = 让一条在跑的
#    线上腿承担本单的风险（#4837 之后才有的稳定落地面）。⇒ 本文件是**第二份实现**，但
#    ① 发布逻辑仍是**单一出处**（远端执行体只有一个：`deploy/swas/bmini-h5-publish-remote.sh`）；
#    ② 两份 CLI 包装的**安全口径**（墙钟硬超时 / CLI 单调用上界 / 目标与哈希三条断言 /
#       绝不 swallow 失败）由守卫测试 `tests/unit_ci_workflows/test_bmini_h5_hosting.py` 逐条钉住。
#
# 退出码：0 = 已发布且断言全过；非零 = 未发布 / 已发布但与本次构建不一致（显式失败）。
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

[ $# -ge 2 ] || {
  echo "用法: bmini-h5-publish-ci.sh <INSTANCE_ID> <REGION> [ACCESS_KEY_ID] [ACCESS_KEY_SECRET] [IMAGE_TAG]" >&2
  exit 2
}

INSTANCE_ID=$1
REGION=$2
AK=${3:-}
SK=${4:-}
IMAGE_TAG=${5:-}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REMOTE_SCRIPT="$ROOT/deploy/swas/bmini-h5-publish-remote.sh"
DIST_DIR="$ROOT/frontend/bmini-app/dist"
LOCAL_INDEX="$DIST_DIR/index.html"

# 与 deploy-frontend.yml 同值（同一个 ACR 仓库域；**不新增 secret**）
ACR_REGISTRY=${ACR_REGISTRY:-crpi-qdcgkzwx9p9zckga.cn-hangzhou.personal.cr.aliyuncs.com}
ACR_NAMESPACE=${ACR_NAMESPACE:-ai-customer-service}
IMAGE_NAME=${IMAGE_NAME:-bmini-h5}
STATIC_ROOT=${H5_STATIC_ROOT-/opt/migao-deploy/h5}
SUBDIR=${H5_SUBDIR-b}

# 超时参数（与 swas-h5-publish-ci.sh 同口径：**墙钟**上界，不是次数上界；CI 守卫测试调小以免空耗）
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

# 带硬上界的子进程执行（防 CLI 自己挂住 ⇒ 轮询永不返回 ⇒ run 卡在 in_progress 占住并发组）
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
[ -f "$LOCAL_INDEX" ] || die "本仓库缺少 frontend/bmini-app/dist/index.html —— 请先跑 \`npm run build:h5\`（发布内容单一源）"
[ -n "$INSTANCE_ID" ] || die "缺少 SWAS 实例 ID"
[ -n "$REGION" ] || die "缺少地域"
[ -n "$IMAGE_TAG" ] || die "缺少 IMAGE_TAG（镜像 tag 必须显式给出：本腿要断言「发布的就是这次构建」）"

# 字符集白名单（**注入防线**：这三个值会被拼进远端命令内容）。
# ⚠️ 判据写**否定类**（`*[!允许集]*`）而不是「正向类 + `*`」—— 后者只要串首是 `/`、串尾落在允许集内
#    就会匹配成功（`/tmp/er;rm -rf/` 也能过）⇒ 那是**假校验**，比不校验更坏。
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
case "$ACR_REGISTRY" in
  ""|*[!A-Za-z0-9._:/-]*) die "ACR_REGISTRY 非法：'$ACR_REGISTRY'" ;;
esac
case "$ACR_NAMESPACE" in
  ""|*[!A-Za-z0-9._/-]*) die "ACR_NAMESPACE 非法：'$ACR_NAMESPACE'" ;;
esac
case "$IMAGE_NAME" in
  ""|*[!A-Za-z0-9._-]*) die "IMAGE_NAME 非法：'$IMAGE_NAME'" ;;
esac
case "$IMAGE_TAG" in
  *[!A-Za-z0-9._-]*) die "IMAGE_TAG 非法：'$IMAGE_TAG'（只接受 [A-Za-z0-9._-]）" ;;
esac

EXPECTED_TARGET="$STATIC_ROOT/$SUBDIR"
IMAGE="$ACR_REGISTRY/$ACR_NAMESPACE/$IMAGE_NAME:$IMAGE_TAG"
LOCAL_SHA="$(file_sha256 "$LOCAL_INDEX")"

# 本地侧先把**命名空间断言**跑一遍（与远端同口径）：构建时漏传 TARO_APP_H5_PUBLIC_PATH ⇒
# 这里就红，**在发起任何云调用之前**，不必等远端拒绝。
python3 - "$LOCAL_INDEX" "$SUBDIR" <<'PY' || exit 1
import re, sys
from pathlib import Path
index, subdir = Path(sys.argv[1]), sys.argv[2]
html = index.read_text(encoding="utf-8", errors="replace")
refs = re.findall(r'(?:src|href)="([^"]*)"', html)
if not refs:
    sys.exit("❌ dist/index.html 里没有任何 src/href —— 产物不完整")
bad = [r for r in refs if not (r.startswith(f"/{subdir}/") or "://" in r or r.startswith("//") or r.startswith("data:"))]
if bad:
    sys.exit("❌ dist/index.html 引用了 /%s/ 之外的资源：%s —— 构建时须传 TARO_APP_H5_PUBLIC_PATH=/%s/（否则会与同静态根下的 C 端共用路径）" % (subdir, " ".join(bad), subdir))
missing = [r for r in refs if r.startswith(f"/{subdir}/") and not (index.parent / r[len(subdir) + 2:]).is_file()]
if missing:
    sys.exit("❌ dist/ 里缺少 index.html 引用的文件：%s" % " ".join(missing))
print("✅ 本地产物命名空间与完整性断言通过（%d 个引用全部落在 /%s/ 内且都存在）" % (len(refs), subdir))
PY

say "# B 端 h5（bmini）静态落位（issue #5668）"
say ""
say "- 目标：\`$EXPECTED_TARGET\`（静态根 = nginx 的 \`root\`，**同时承载 C 端小布 ⇒ 只收敛 $SUBDIR/ 子树**）"
say "- 产物：\`frontend/bmini-app/dist/\`（CI 按 \`TARO_APP_H5_PUBLIC_PATH=/$SUBDIR/\` 构建）"
say "- 传输：ACR 镜像 \`$IMAGE\`（实例 \`docker cp\` 取出 /dist ⇒ 线上字节 == CI 构建字节）"
say "- 本地 \`dist/index.html\` 哈希：\`$LOCAL_SHA\`"

# ── 组装远端命令 = 远端执行体 + 三个环境变量前缀（无参数拼接 ⇒ 无注入面）──────
COMMAND_CONTENT="export H5_STATIC_ROOT=$STATIC_ROOT
export H5_SUBDIR=$SUBDIR
export H5_PUBLISH_IMAGE=$IMAGE
$(cat "$REMOTE_SCRIPT")"

if [ -n "$AK" ] && [ -n "$SK" ]; then
  command -v aliyun >/dev/null 2>&1 || die "未安装 aliyun CLI（CI 侧应先安装，见 .github/workflows/bmini-h5-publish.yml）"
  aliyun configure set --access-key-id "$AK" --access-key-secret "$SK" --region "$REGION" >/dev/null
else
  echo "ℹ️ 未传 AK/SK —— 使用本机 aliyun 既有配置（人工排障模式）"
fi

echo "== 触发 SWAS 云助手执行远端发布脚本 =="
INVOKE=$(run_cmd run-command RunCommand \
  --instance-id "$INSTANCE_ID" \
  --name migao-bmini-h5-publish \
  --type RunShellScript \
  --timeout 900 \
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

# ── 四条验收断言（fail-closed）────────────────────────────────────────────
grep -q "^TARGET=$EXPECTED_TARGET$" <<<"$REMOTE_LOG" \
  || die "远端 TARGET 不是期望值：期望 '$EXPECTED_TARGET'（输出里：$(grep -m1 '^TARGET=' <<<"$REMOTE_LOG" || echo '(缺 TARGET 行)')）"

REMOTE_INDEX_SHA=$(sed -n 's/^PUBLISHED_INDEX_SHA256=//p' <<<"$REMOTE_LOG" | head -1)
[ "$REMOTE_INDEX_SHA" = "$LOCAL_SHA" ] \
  || die "发布的 index.html 与本次构建不一致：远端 '$REMOTE_INDEX_SHA' ≠ 本地 '$LOCAL_SHA'"

PARENT_BEFORE=$(sed -n 's/^PARENT_INDEX_BEFORE_SHA256=//p' <<<"$REMOTE_LOG" | head -1)
PARENT_AFTER=$(sed -n 's/^PARENT_INDEX_AFTER_SHA256=//p' <<<"$REMOTE_LOG" | head -1)
[ -n "$PARENT_BEFORE" ] && [ "$PARENT_BEFORE" = "$PARENT_AFTER" ] \
  || die "静态根 index.html 被触碰（$PARENT_BEFORE → ${PARENT_AFTER}）—— 红线"

grep -q "^ASSET_REFS_SCOPED=1$" <<<"$REMOTE_LOG" && grep -q "^ASSETS_PRESENT=1$" <<<"$REMOTE_LOG" \
  || die "远端没有给出「资源命名空间 / 完整性」自证行（ASSET_REFS_SCOPED / ASSETS_PRESENT）—— 拒绝把沉默当通过"

say ""
say "✅ 发布完成：\`$EXPECTED_TARGET/index.html\` 哈希 \`$REMOTE_INDEX_SHA\`（= 本次构建），静态根未触碰（\`$PARENT_AFTER\`）"
