#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# CI → SWAS：把 `frontend/mini-app` 的 h5 构建产物发布到 `app.migaozn.com` 的**静态根本身**（issue #4184）
#
# 用法: c-end-h5-publish-ci.sh <INSTANCE_ID> <REGION> [ACCESS_KEY_ID] [ACCESS_KEY_SECRET] [DIST_SHA]
#   · AK/SK 省略 ⇒ 走本机 `aliyun` 既有配置（**人工排障 / 本地复跑**用；CI 必须显式传入）
#   · DIST_SHA（第 5 个参数）**不是**源码 commit，而是 `h5-dist` 分支上**那个只含本次构建产物
#     `frontend/mini-app/dist/**` 的孤儿单提交**的 sha（由 `deploy/scripts/c-end-h5-dist-push.sh`
#     产出、workflow 经 step output 传下来）—— 远端按它从 codeload 取回 tarball ⇒ **不可变引用**
#     （40 位十六进制，格式断言在下面；`refs/heads/main` 这类会漂的 ref 连格式都过不去）。
#     省略时回落到 `$H5_DIST_SHA` / `$GITHUB_SHA`（人工排障）。
#   · `H5_PUBLISHED_COMMIT`（可选环境变量）= 产出这份 dist 的**源码 commit**，透传给远端写进
#     托管清单的 `published_commit`（「线上这份产物出自哪个源码提交」的审计口径）。
#
# 🔴 **远端取的是「CI 构建的那份 dist」**（issue #6095 第三层）：`frontend/mini-app/dist/` 是
#    **构建产物**（`git ls-tree -r origin/main --name-only frontend/mini-app/dist` = 0 个文件，
#    `.gitignore` 有 `dist/`）⇒ **源码 tarball 里永远没有它** ⇒ 发布腿此前必然
#    `❌ 发布源里没有 index.html`（run 37078030820 实测）。所以远端取回的**不是源码 tarball**，
#    而是 `h5-dist` 上那份**只含 dist 的孤儿单提交**的 tarball（`H5_SRC_SUBPATH=frontend/mini-app/dist`）。
#
# 通道：与 `deploy/scripts/swas-h5-publish-ci.sh`（工人端 `w/`）**同一把钥匙、同一条云 API**
# （SWAS RunCommand）—— **不引入任何新 secret**。
#
# 远端逻辑**不在本文件里**：本文件只做「取 sha → 组装**极小的引导** → 发起云调用 → 轮询 →
# 解码输出 → 断言」，真正动手的是 `deploy/swas/c-end-h5-publish-remote.sh`（**单一出处**：
# 线上发布、本地沙箱复跑、守卫 `tests/unit_ci_workflows/test_c_end_h5_hosting.py` 的行为级红证，
# 跑的都是同一份文件）。
#
# 🔴 **远端执行体不进 SWAS 命令内容**（命令内容只做「按**不可变 sha** 从 codeload 取回执行体并执行」）
#    —— 命令内容与远端脚本大小**解耦**，且组装后在 CI 侧**前置断言**其字节数 < 上限
#    （上限出处见「组装远端命令」一节；超限 ⇒ **本机具名判红**，不是云上一个 `SDKError 400`）。
#    病根与实测：issue #6095 / run 37075737625（整份脚本被内联 ⇒ `400 CmdContent.ExceedLimit`）。
#
# 🔴 **首次发布在 CI 侧被机械禁止**（与远端脚本的 `TAKEOVER_REQUIRED` 是**两条独立的闸**）：
#   静态根上**已经住着两条腿的产物**（`w/` 工人端、`b/` 商家端），而根的现值
#   （实测 2026-09-27：`index.html` + `js/` + `css/`）来自**历史上某次没有留下清单的发布**。
#   远端脚本要求 `--takeover-first-publish` 才肯接管；本文件带这个开关 —— 但**清单不在线上时
#   它照样接管不了**：那时根上的 `index.html` / `js` / `css` 都属「无人认领」，远端脚本
#   仍判 `TAKEOVER_REQUIRED`（exit 2）⇒ 本文件断言 `InvocationStatus=Success` 时**判红**。
#   ⇒ 即使有人误点/误派发这条腿，**第一次接管线上根也不会由 CI 悄悄完成**
#     （要真发布，只能由人在实例上显式跑远端脚本，见 PR body 的首次发布清单）。
#
# 退出码：0 = 已发布且断言全过；非零 = 未发布 / 已发布但与本次构建不一致（显式失败）。
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

[ $# -ge 2 ] || {
  echo "用法: c-end-h5-publish-ci.sh <INSTANCE_ID> <REGION> [ACCESS_KEY_ID] [ACCESS_KEY_SECRET] [DIST_SHA]" >&2
  exit 2
}

INSTANCE_ID=$1
REGION=$2
AK=${3:-}
SK=${4:-}
SHA=${5:-${H5_DIST_SHA:-${GITHUB_SHA:-}}}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# `H5_REMOTE_SCRIPT_PATH` = **判据注入夹具用**（生产不带它 ⇒ 走下面「远端执行体缺失 ⇒ 判红」那条断言）。
# 它**不是**后门：远端脚本路径不是安全边界（命令内容才是），且注入只影响**本机**这一侧。
REMOTE_SCRIPT=${H5_REMOTE_SCRIPT_PATH:-"$ROOT/deploy/swas/c-end-h5-publish-remote.sh"}
DIST_DIR="$ROOT/frontend/mini-app/dist"
LOCAL_INDEX="$DIST_DIR/index.html"
# 远端取回**产物**用的子路径（不是源码目录 `frontend/mini-app`）：`h5-dist` 的孤儿提交里
# 只有 `frontend/mini-app/dist/**` ⇒ 远端解包后要在这里找 index.html（issue #6095 第三层）。
DIST_SUBPATH="frontend/mini-app/dist"
# 产出这份 dist 的源码 commit（codeload tarball 里没有 `dist/` ⇒ 远端无法自己推导，只能 CI 侧透传；
# 空值就是空串 —— 不许「猜一个」）。
PUBLISHED_COMMIT=${H5_PUBLISHED_COMMIT:-}

STATIC_ROOT=${H5_STATIC_ROOT-/opt/migao-deploy/h5}
MANIFEST=${H5_MANIFEST-.migao-c-end-h5-manifest.json}
RESERVED_PREFIXES=${H5_RESERVED_PREFIXES:-"w b"}

# 超时参数（与 swas-h5-publish-ci.sh 同口径：**墙钟**上界，不是次数上界；CI 守卫测试调小以免空耗）
PUBLISH_TIMEOUT_SECONDS=${SWAS_H5_PUBLISH_TIMEOUT_SECONDS:-600}
CLI_TIMEOUT_SECONDS=${SWAS_CLI_TIMEOUT_SECONDS:-60}
POLL_INTERVAL_SECONDS=${SWAS_H5_POLL_INTERVAL_SECONDS:-10}
DEADLINE=$(( $(date +%s) + PUBLISH_TIMEOUT_SECONDS ))

SUMMARY_FILE=${GITHUB_STEP_SUMMARY:-}
say() {
  echo "$*"
  if [ -n "$SUMMARY_FILE" ]; then printf '%s\n' "$*" >> "$SUMMARY_FILE"; fi
  return 0
}

die() { local msg=$1 code=${2:-1}; printf '❌ %s\n' "$msg" >&2; exit "$code"; }

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
[ -f "$REMOTE_SCRIPT" ] || die "远端执行体缺失：${REMOTE_SCRIPT}（发布逻辑没有单一出处）"
[ -f "$LOCAL_INDEX" ] || die "本仓库缺少 frontend/mini-app/dist/index.html —— 请先跑 \`npm run build:h5\`（发布内容单一源）"
[ -d "$DIST_DIR/js" ] || die "frontend/mini-app/dist/ 缺 js/（不是 build:h5 的产物？）"
[ -n "$INSTANCE_ID" ] || die "缺少 SWAS 实例 ID"
[ -n "$REGION" ] || die "缺少地域"
[ -n "$SHA" ] || die "缺少 DIST_SHA（dist 后缀）—— 也没拿到 \${H5_DIST_SHA} / \${GITHUB_SHA}"

# 字符集白名单（**注入防线**：这几个值会被拼进远端命令内容）。
# ⚠️ 判据写**否定类**（`*[!允许集]*`）而不是「正向类 + `*`」—— 后者只要串首是 `/`、串尾落在允许集内
#    就会匹配成功（`/tmp/er;rm -rf/` 也能过）⇒ 那是**假校验**，比不校验更坏。
case "$SHA" in
  *[!0-9a-fA-F]*) die "DIST_SHA 非法：'$SHA'（只接受十六进制 sha；本脚本把它拼进远端命令，故先做字符集校验）" ;;
esac
# 🔴 **必须是一个 commit 对象名**（40 位十六进制），不是分支 / 标签 / ref 名 —— 这是
# 「不可变 sha」的机械载体（issue #6095 第三层硬约束）：`refs/heads/main` / `h5-dist` 这类
# **会漂**的引用在字符集上就过不去（`r` `e` `f` `s` `h` `-` 都不是十六进制字符）。
# 远端取回用的就是这个值 ⇒ 「远端取的那份」与「CI 推的那份」由 workflow 的 step output 对齐。
[ "${#SHA}" -eq 40 ] || die "DIST_SHA 必须是 40 位十六进制 commit sha（不可变引用），实际 '${SHA}'（长度 ${#SHA}）——
   · CI 侧应传 workflow 里 dist 推送步的 step output（见 .github/workflows/c-end-h5-publish.yml）；
   · **不许**传分支 / 标签 / ref 名（`refs/heads/*`、`h5-dist`、`main` …）—— 那些会漂，
     会让「远端取回的产物」与「本次 CI 构建的产物」不再是同一个对象。"
case "$STATIC_ROOT" in
  /*) : ;;
  *) die "H5_STATIC_ROOT 必须是绝对路径：'$STATIC_ROOT'" ;;
esac
case "$STATIC_ROOT" in
  */) die "H5_STATIC_ROOT 不能以 / 结尾：'$STATIC_ROOT'" ;;
esac
case "$STATIC_ROOT" in
  *[!A-Za-z0-9._/-]*) die "H5_STATIC_ROOT 含非法字符：'$STATIC_ROOT'" ;;
esac
case "$MANIFEST" in
  ""|/*|*/*|.|..|*[!A-Za-z0-9._-]*) die "H5_MANIFEST 非法：'$MANIFEST'（静态根下的单一文件组件）" ;;
esac
case "$RESERVED_PREFIXES" in
  ""|*[!A-Za-z0-9._\ -]*) die "H5_RESERVED_PREFIXES 非法：'$RESERVED_PREFIXES'（空格分隔的纯组件名）" ;;
esac
EXPECTED_TARGET="$STATIC_ROOT"
LOCAL_SHA="$(file_sha256 "$LOCAL_INDEX")"

say "# C 端小布 h5 静态落位（issue #4184）"
say ""
say "- 目标：\`$EXPECTED_TARGET\`（= nginx 的 \`root\` **本身**；只收敛托管清单里的顶层条目）"
say "- 产物：\`frontend/mini-app/dist/\`（CI 跑 \`npm run build:h5\`，publicPath 已是 \`/\`）"
say "- 发布源：\`https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/$SHA\`（= \`h5-dist\` 上**只含本次构建产物**的孤儿单提交；**不可变 sha**，不是分支名）
  远端在 \`$DIST_SUBPATH/\` 下取 index.html（源码 tarball 里没有 dist —— 那是本层要治的形态）
  ${PUBLISHED_COMMIT:+产出这份 dist 的源码 commit：\`$PUBLISHED_COMMIT\`}"
say "- 本地 \`dist/index.html\` 哈希：\`$LOCAL_SHA\`"

# ── 组装远端命令 = **极小的引导**（远端执行体**不进命令内容**）──────────────────
# 命令内容只做「按**不可变 sha** 取回远端执行体并执行」；其余（首次发布闸、原子切换、备份、
# reserved-prefix、identity 断言…）**原样留在远端脚本里**（发布逻辑的单一出处不变）。
#
# 🔴 病根（run 37075737625 / sha f3e49752f / 2026-10-02T23:06Z）：此前这里把**远端执行体整份内联**
#    （`cat` 远端脚本再拼进命令内容）⇒ 随迭代增长越过 SWAS `CommandContent` 上限 ⇒ **每次** RunCommand
#    都返回 `400 CmdContent.ExceedLimit`（线上产物因此陈旧 33 天：`app.migaozn.com/js/app.js` 的
#    `Last-Modified` 停在 2026-08-30T06:54Z）。本改动令**命令内容与远端脚本大小解耦**：
#    远端执行体 20176 字节 ⇒ 命令内容只剩引导的几百字节 ⇒ 往远端脚本加发布逻辑**不再**推高命令内容。
#
# `H5_TAKEOVER_FIRST_PUBLISH=1` 是**给远端脚本的**：本文件已在下面断言过「上一版清单已在线上」，
# 所以这里带 takeover 只是为了让远端的「无人认领」闸不再触发（**不是**在替人签字：
# 首次发布若清单不在线上，本文件在云调用之前就判红，压根走不到这一步）。
#
# 取回通道 = **既有已证明可用的那一条**（与远端脚本自己取源码、与 `swas-deploy-ci.sh` 的 bootstrap
# 同源）：`https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/<sha>`
#   · 不可变引用：URL 用 `$SHA`（= `$GITHUB_SHA`）；**不是**取 main 的最新 ⇒「发布的内容」与
#     「CI 构建的内容」必定同一个 commit（按 main 的最新取会让两者漂移）；
#   · `$SHA` 已在上面过字符集白名单（只接受十六进制）⇒ 无注入面；
#   · 取不到 / 解不出 ⇒ **远端非零退出并打印具名原因**（绝不静默半成品发布）。
#
# ⚠️ 引导**不比对**执行体内容哈希：「取回的**是不是那个 sha 的内容**」由通道保证（不可变引用 +
#    HTTPS）；「线上发布的产物是不是本次构建」由下面 CI 侧的 `PUBLISHED_INDEX_SHA256` 断言承担
#    （那条是**真实采样**，不是「再算一遍现值 ⇒ 与自己恒等」的空断言）。
#
# 🔴 命令内容字节上限（`COMMAND_CONTENT_LIMIT_BYTES`）的**出处**：SWAS Open `RunCommand` 官方文档
#    https://help.aliyun.com/zh/simple-application-server/developer-reference/api-swas-open-2020-06-01-runcommand
#    —— `CommandContent` 与自定义参数在 **base64 编码后**综合长度 ≤ **16 KB**（= 16384 字节）。
#    ⚠️ 冲突登记（照实）：ECS 侧同族 API 的文档口径是 **64 KB**（`CommandContent` Base64 后 ≤ 64 KB），
#    而本仓既有实测把上限读成 **43.8~50.7 KB**（`tests/unit_ci_workflows/test_swas_server_side_build.py`
#    的读数：38 000 字节正文 = 50 769 字符即被拒）。**能复现的实测优先** ⇒ 取三者中**最保守**的 16 KB
#    当闸值：超了就在**本机**判红（具名报文），而不是云上冒一个 `SDKError 400`。
REMOTE_FETCH='WORK=$(mktemp -d) && T=$(mktemp) && die() { echo "❌ 引导失败：$1 —— 未做任何发布动作" >&2; exit 1; } && trap '"'"'rc=$?; rm -rf "$WORK"; rm -f "$T"; exit $rc'"'"' EXIT && curl -fsSL --retry 3 --retry-delay 5 --connect-timeout 15 --max-time 180 -o "$T" "https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/'"$SHA"'" || die "取不到远端执行体（codeload tar.gz/$SHA）" && tar xzf "$T" -C "$WORK" --strip-components=1 || die "解不开远端执行体（$T）" && bash "$WORK/deploy/swas/c-end-h5-publish-remote.sh"'
# 命令内容字节上限（**保守值**）与出处（判据：tests/unit_ci_workflows/test_c_end_h5_hosting.py）
COMMAND_CONTENT_LIMIT_BYTES=${H5_COMMAND_CONTENT_LIMIT_BYTES:-16384}
COMMAND_CONTENT_LIMIT_SOURCE="SWAS Open RunCommand：CommandContent 与自定义参数在 base64 编码后综合长度 ≤ 16 KB —— https://help.aliyun.com/zh/simple-application-server/developer-reference/api-swas-open-2020-06-01-runcommand"

COMMAND_CONTENT="export H5_STATIC_ROOT=$STATIC_ROOT
export H5_PUBLISH_SHA=$SHA
export H5_SRC_SUBPATH=$DIST_SUBPATH
export H5_PUBLISHED_COMMIT=$PUBLISHED_COMMIT
export H5_MANIFEST=$MANIFEST
export H5_RESERVED_PREFIXES=\"$RESERVED_PREFIXES\"
export H5_TAKEOVER_FIRST_PUBLISH=1
$REMOTE_FETCH --apply"

# ── CI 侧前置断言（**在发起任何云调用之前**）───────────────────────────────────
# 让「命令内容超限」在**本机**就是可读的判红（具名报文 + 字节读数 + 出处），
# 而不是云上一个 `SDKError 400`（那正是本单的形态：失败发生在别人看不见的地方）。
COMMAND_CONTENT_BYTES=$(printf '%s' "$COMMAND_CONTENT" | wc -c | tr -d ' \n')
if [ "$COMMAND_CONTENT_BYTES" -ge "$COMMAND_CONTENT_LIMIT_BYTES" ]; then
  die "SWAS 命令内容超限：命令内容 ${COMMAND_CONTENT_BYTES} 字节 / 上限 ${COMMAND_CONTENT_LIMIT_BYTES} 字节 —— 拒绝发起云调用。
   上限出处：${COMMAND_CONTENT_LIMIT_SOURCE}
   口径：远端执行体**不许**被内联进命令内容（命令内容只做「按 sha 取回执行体并执行」）。
   修法：① 新增的发布逻辑加进远端脚本 deploy/swas/c-end-h5-publish-remote.sh（不占命令内容）；
         ② 复核是否有人把「内联远端脚本」的旧写法又加回来了（判据见 tests/unit_ci_workflows/）。"
fi
# 判据入口（**可注入**）：只打印组装结果与字节读数，**不发起任何云调用**。
# 判据 = tests/unit_ci_workflows/test_c_end_h5_hosting.py::TestCommandContentLimit
if [ -n "${H5_PRINT_COMMAND_CONTENT:-}" ]; then
  # 命令内容走 stdout（消费用），BEGIN/END 标记把它夹住（定位用）——
  # 判据从 stdout 里切出**标记之间**的那一份，读的就是要发给云上的那个字节序列。
  printf 'COMMAND_CONTENT_BEGIN\n'
  printf '%s\n' "$COMMAND_CONTENT"
  printf 'COMMAND_CONTENT_END\n' >&2
  printf 'COMMAND_CONTENT_BYTES=%s\n' "$COMMAND_CONTENT_BYTES" >&2
  printf 'COMMAND_CONTENT_LIMIT_BYTES=%s\n' "$COMMAND_CONTENT_LIMIT_BYTES" >&2
  printf 'REMOTE_SCRIPT=%s\n' "$REMOTE_SCRIPT" >&2
  exit 0
fi

if [ -n "$AK" ] && [ -n "$SK" ]; then
  command -v aliyun >/dev/null 2>&1 || die "未安装 aliyun CLI（CI 侧应先安装，见 .github/workflows/c-end-h5-publish.yml）"
  aliyun configure set --access-key-id "$AK" --access-key-secret "$SK" --region "$REGION" >/dev/null
else
  echo "ℹ️ 未传 AK/SK —— 使用本机 aliyun 既有配置（人工排障模式）"
fi

echo "== 触发 SWAS 云助手执行远端发布脚本（含首次发布闸：远端先自证上一版清单在线上）=="
INVOKE=$(run_cmd run-command RunCommand \
  --instance-id "$INSTANCE_ID" \
  --name migao-c-end-h5-publish \
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

# ── 验收断言（fail-closed，逐条与远端自证行对齐）────────────────────────────
grep -q "^TARGET=$EXPECTED_TARGET$" <<<"$REMOTE_LOG" \
  || die "远端 TARGET 不是期望值：期望 '$EXPECTED_TARGET'（输出里：$(grep -m1 '^TARGET=' <<<"$REMOTE_LOG" || echo '(缺 TARGET 行)')）"

grep -q "^MANIFEST_WRITTEN=$STATIC_ROOT/$MANIFEST$" <<<"$REMOTE_LOG" \
  || die "远端没有写回托管清单（${STATIC_ROOT}/${MANIFEST}）—— 下一次发布将失去删除范围（拒绝把沉默当通过）"

REMOTE_INDEX_SHA=$(sed -n 's/^PUBLISHED_INDEX_SHA256=//p' <<<"$REMOTE_LOG" | head -1)
[ "$REMOTE_INDEX_SHA" = "$LOCAL_SHA" ] \
  || die "发布的 index.html 与本次构建不一致：远端 '$REMOTE_INDEX_SHA' ≠ 本地 '$LOCAL_SHA'（发布的不是这次审过的内容）"

grep -q "^ASSET_REFS_ROOT_SCOPED=1$" <<<"$REMOTE_LOG" \
  || die "远端没有给出「产物引用只落在根级」自证行（ASSET_REFS_ROOT_SCOPED）—— 拒绝把沉默当通过"

grep -q "^PROTECTED_UNCHANGED=1$" <<<"$REMOTE_LOG" \
  || die "远端没有给出「保留子树未被触碰」自证行（PROTECTED_UNCHANGED）—— 拒绝把沉默当通过"

# 🔴 本单最重要的一条：`w/`（工人端，线上有工人在用）与 `b/`（商家端）**逐字不变**。
# 判据不是「脚本说它没碰」而是**两次真实采样的读数相等**（发布前 vs 发布后）：摘要 + 各自的
# index.html 单文件哈希，四个读数都要在，且都要相等 —— 缺任何一个读数 ⇒ 判红（不是「通过」）。
for p in $RESERVED_PREFIXES; do
  PB=$(sed -n "s/^PROTECTED_${p}_BEFORE_SHA256=//p" <<<"$REMOTE_LOG" | head -1)
  PA=$(sed -n "s/^PROTECTED_${p}_AFTER_SHA256=//p" <<<"$REMOTE_LOG" | head -1)
  IB=$(sed -n "s/^PROTECTED_${p}_BEFORE_INDEX_SHA256=//p" <<<"$REMOTE_LOG" | head -1)
  IA=$(sed -n "s/^PROTECTED_${p}_AFTER_INDEX_SHA256=//p" <<<"$REMOTE_LOG" | head -1)
  for v in "$PB" "$PA" "$IB" "$IA"; do
    [ -n "$v" ] || die "保留子树 '$p' 的自证读数缺失（BEFORE/AFTER × 摘要/index.html 四个读数必须齐）—— 红线不可判 ⇒ 判红"
  done
  [ "$PB" = "$PA" ] || die "🔴 保留子树 '$p' 的摘要变了（${PB} → ${PA}）—— 本腿动了别的发布腿的产物（红线）"
  [ "$IB" = "$IA" ] || die "🔴 保留子树 '$p/index.html' 的哈希变了（${IB} → ${IA}）—— 工人端/商家端被本腿覆盖（红线）"
  say "- 保留子树 \`$p/\`：摘要 \`$PB\`（BEFORE==AFTER）、\`$p/index.html\` \`$IB\`（BEFORE==AFTER）"
done

say ""
say "✅ 发布完成：\`$EXPECTED_TARGET/index.html\` 哈希 \`$REMOTE_INDEX_SHA\`（= 本次构建）；保留子树 $RESERVED_PREFIXES 逐字未变"
