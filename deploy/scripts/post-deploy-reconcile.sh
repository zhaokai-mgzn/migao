#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# 部署后「线上一致性对账」—— **容器实际生效 tag / 静态副本** 是否等于 main 该有的那份
# （issue #4858；形态与既有对账 idiom 一致：每个判定一行依据 + 一行总结 + fail-open + `::warning::`）
#
# ── 本单要治的三种「线上与 main 不一致」形态（都有实测证据）──────────────────
#   ① 静默回退：为旧 commit 创建的 run 被 flock 排队到新 run 之后执行 ⇒ 服务被回退到旧 tag。
#      **#4854 的「不许往回走」闸门已拦住「发生」**，但**事后**仍无人核对线上到底是哪个 commit。
#   ② 静默跳过：某服务镜像拉取失败 ⇒ 远端 `⚠️ 跳过该服务`，而整次部署**仍报成功**
#      （实测 `sha-56c8c51` 那次跳过 ai-agent / admin-web —— 那次**合理**；但**若某模块改了、
#      镜像却没建**，跳过就是**静默不交付**）。**此前没有任何机制会发现**。
#   ③ 静态副本滞后：发布 workflow 按**路径过滤**触发 ⇒ 改动不在该路径里就不跑
#      （实测线上 `/w/src/app.mjs` 一度是旧副本，缺计件幂等修复）。**此前没有任何机制会发现**。
#
# ── 判定形态（**逐条打印依据**，不许"看起来对"）───────────────────────────────
#   容器侧（逐服务 3 条）：
#     `该有的 tag` = **该服务最近一次改动它代码路径的 main 提交**（真值源 = 各 `deploy-*.yml`
#     的 `on.push.paths`；有动态对齐守卫，见 tests/unit_ci_workflows/test_post_deploy_reconcile.py）。
#     ⚠️ **判据形态为什么是「提交图祖先关系」而不是「字符串相等」**（实测数据，非推断）：
#        部署 tag 是 `sha-${GITHUB_SHA::7}` = **main HEAD**（各 deploy workflow 的 `Resolve image tag`），
#        而「该有的」是**最后一个改该服务路径的提交** —— 两者在 HEAD 是 docs/ci 提交时**天然不等**。
#        本 PR 的真机只读读数：admin-api 在跑 `sha-122cbac`，而该服务最近一次改动
#        `backend/admin-api` 的 main 提交是 `f362d3f9c`（**不等**，但 `122cbac` 是它的后代 ⇒ 一致）。
#        ⇒ 按字符串相等判会把**常态**误报成不一致（判据失去判别力）。故：
#          · 相等 / 在跑的是「该有的」的**后代** ⇒ **一致**（线上已含该服务最近一次改动）
#          · 在跑的是「该有的」的**祖先** ⇒ **不一致**（线上缺该服务最近一次改动 —— 形态②的正身）
#          · 判不出（非 sha tag / 对象不可达 / compare 取不到）⇒ 走下面的**降级判据**
#    降级判据（issue #4858 原文：「该提交的镜像不存在时退化为『自上次成功部署以来该服务有无改动』」）：
#       a. `sha-<该有的>` 镜像存在（`docker manifest inspect`）⇒ 该 commit 已构建但线上没跑，
#          且提交序判不出 ⇒ **判不出** + `::warning::`（不猜方向）；
#       b. 镜像不存在 ⇒ 查「自该服务**上次成功部署**的 commit 起，其代码路径有无改动」：
#          有改动 ⇒ **不一致**（改了、镜像没建、线上没跑 = 形态②）；无改动 ⇒ **一致**（合理跳过）；
#          取不到基准 ⇒ **判不出** + `::warning::`。
#   静态侧（逐文件 1 条/文件）：
#     线上 `$BASE_URL/w/<rel>` 的 body 哈希 vs `origin/main:frontend/worker-h5/<rel>` 的哈希
#     （`git ls-tree -r origin/main -- frontend/worker-h5` 取清单，**排除 `tests/**`** —— 与发布
#     脚本 `deploy/swas/h5-publish-remote.sh` 的口径一致：`tests/**` 不发）。
#
# ── 可观测 / fail-open（issue #4858 要求 4）──────────────────────────────────
#   每个判定一行依据（读了什么 ⇒ 得出什么）+ 一行总结 `一致=N · 不一致=N · 判不出=N`；
#   **判不出必须 fail-open + `::warning::`**，**绝不许静默当作一致**（"没跑/判不出"必须长得像"判不出"）。
#   退出码：`0` = 无确认的不一致（含全部判不出 —— fail-open）；`1` = 有**确认的**不一致（真的少交付了）；
#           `2` = 对账腿自身无法运行（缺文件/无真值源）—— 与「判不出」区分开，**不许混为一谈**。
#
# ── 不削弱任何既有护栏（issue #4858 要求 5）─────────────────────────────────
#   本脚本**只读**：远端只跑 `deploy/swas/reconcile-read-remote.sh`（纯查询动词），
#   本地只做 git 读 / HTTP 读 / `docker manifest inspect`。**不 dispatch 任何部署**
#   （那是 `deploy-reconcile.yml` 的职责，其断路器与漂移判据一字未动）；
#   **不碰 `deploy/swas/deploy.sh`**（另一单 #4828 正在改它）⇒ 独立脚本 + 独立 workflow。
#
# 用法（CI / 本地同一条码路）：
#   bash deploy/scripts/post-deploy-reconcile.sh
# 沙箱/守卫测试用的**桩化**钩子（全部有默认值，线上不需要设）：
#   RECONCILE_REPO_DIR     真值源仓库（默认 = 本仓库根；守卫测试指向 fixture 仓库）
#   RECONCILE_REMOTE_CMD   用本地命令替代 SWAS 读取（**桩化、未真跑远端**）
#   RECONCILE_BASE_URL     线上基址（默认 https://app.migaozn.com）
#   RECONCILE_COMPARE_API  compare API 基址（默认 GitHub；可指向 file:// 桩）
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO_DIR=${RECONCILE_REPO_DIR:-$ROOT}
REMOTE_BODY=${RECONCILE_REMOTE_BODY:-$ROOT/deploy/swas/reconcile-read-remote.sh}
REMOTE_CMD=${RECONCILE_REMOTE_CMD:-}
BASE_URL=${RECONCILE_BASE_URL:-https://app.migaozn.com}
BASE_URL=${BASE_URL%/}
H5_SUBPATH=${RECONCILE_H5_SUBPATH:-w}
H5_SRC=${RECONCILE_H5_SRC:-frontend/worker-h5}
COMPARE_API=${RECONCILE_COMPARE_API:-https://api.github.com/repos/zhaokai-mgzn/migao/compare}
INSTANCE_ID=${SWAS_INSTANCE_ID:-b23c69e599524b1da719734f72e6a0e3}
REGION=${SWAS_REGION:-cn-hangzhou}
# 读取（发起云调用 + 轮询）的墙钟上界；CLI 单次调用另有上界（防 CLI 自己挂住 ⇒ 轮询永不返回）
READ_TIMEOUT_SECONDS=${RECONCILE_TIMEOUT_SECONDS:-300}
CLI_TIMEOUT_SECONDS=${RECONCILE_CLI_TIMEOUT_SECONDS:-60}
POLL_INTERVAL_SECONDS=${RECONCILE_POLL_INTERVAL_SECONDS:-10}
SUMMARY_FILE=${GITHUB_STEP_SUMMARY:-}

CONSISTENT=0; INCONSISTENT=0; UNKNOWN=0

say() {
  echo "$*"
  if [ -n "$SUMMARY_FILE" ]; then printf '%s\n' "$*" >> "$SUMMARY_FILE"; fi
  return 0
}
# 「判不出」的唯一出口：fail-open（不计不一致）**但一定出声** —— 不许静默当作一致
undecided() {
  UNKNOWN=$((UNKNOWN + 1))
  say "  · $1"
  echo "::warning::$1"
  return 0
}
consistent()   { CONSISTENT=$((CONSISTENT + 1));   say "  · $1"; return 0; }
inconsistent() {
  INCONSISTENT=$((INCONSISTENT + 1))
  say "  · $1"
  echo "::warning::$1"
  return 0
}

file_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}
# 从 stdin 取哈希（`git show origin/main:<path>` 的字节流 ⇒ 真值源永远是 **origin/main**，不是工作区）
stdin_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum | awk '{print $1}'; else shasum -a 256 | awk '{print $1}'; fi
}

gitr() { git -C "$REPO_DIR" "$@" 2>/dev/null; }

# ── 真值源自检（**反空跑**）：拿不到 origin/main ⇒ 整条对账判不出，但必须出声 ──────
TRUTH_OK=1
if ! gitr rev-parse --verify --quiet origin/main >/dev/null; then
  TRUTH_OK=0
fi

say "# 部署后线上一致性对账（issue #4858）"
say ""
say "- 真值源：\`${REPO_DIR}\` 的 \`origin/main\`（可达=${TRUTH_OK}）"
say "- 线上基址：\`$BASE_URL/$H5_SUBPATH/\`（静态侧）· SWAS 实例 \`$INSTANCE_ID\`（${REGION}，容器侧）"
if [ -n "$REMOTE_CMD" ]; then
  say "- ⚠️ **桩化读取**：\`RECONCILE_REMOTE_CMD\` 已设置 ⇒ 容器侧读数来自本地桩命令，**未真跑远端**"
fi
say ""

# ══════════════════════════════════════════════════════════════════════════════
# 一、容器侧：从主机读**运行中容器的实际 image tag**（只读通道，复用既有 SWAS 只读通道）
# ══════════════════════════════════════════════════════════════════════════════
DEADLINE=0
remaining_seconds() { echo $(( DEADLINE - $(date +%s) )); }
nap() {
  local want=$1 left; left=$(remaining_seconds)
  [ "$left" -lt "$want" ] && want=$left
  if [ "$want" -gt 0 ]; then sleep "$want"; fi
  return 0
}
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
# aliyun CLI 新版 swas-open 要求 kebab-case，旧版用 CamelCase ⇒ 双兼容（同 swas-deploy-ci.sh）
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
  if printf '%s' "$out1" | grep -qE "not a valid api|unknown flag"; then
    out2=$(with_deadline "$CLI_TIMEOUT_SECONDS" aliyun swas-open "$c" "${camel_args[@]}") && { echo "$out2"; return 0; }
  fi
  printf '%s' "$out1" >&2
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

REMOTE_LOG=""
REMOTE_RC=0
read_remote() {
  if [ -n "$REMOTE_CMD" ]; then
    # 桩化路径（守卫测试 / 本地沙箱）：**未真跑远端** —— 由调用方在报告里如实标注
    REMOTE_LOG=$(bash -c "$REMOTE_CMD" 2>&1) || REMOTE_RC=1
    return 0
  fi
  if [ ! -f "$REMOTE_BODY" ]; then
    REMOTE_RC=2; REMOTE_LOG="远端读取体缺失：$REMOTE_BODY"; return 0
  fi
  if ! command -v aliyun >/dev/null 2>&1; then
    REMOTE_RC=2; REMOTE_LOG="aliyun CLI 未安装（CI 侧应先安装，见 .github/workflows/post-deploy-reconcile.yml）"; return 0
  fi
  DEADLINE=$(( $(date +%s) + READ_TIMEOUT_SECONDS ))
  local content invoke invoke_id status res i=0
  content="$(cat "$REMOTE_BODY")"
  if ! invoke=$(run_cmd run-command RunCommand \
      --instance-id "$INSTANCE_ID" \
      --name migao-post-deploy-reconcile \
      --type RunShellScript \
      --timeout 300 \
      --region-id "$REGION" \
      --command-content "$content" 2>&1); then
    REMOTE_RC=2; REMOTE_LOG="RunCommand 调用失败：$invoke"; return 0
  fi
  invoke_id=$(printf '%s' "$invoke" | python3 -c "import sys,json;print(json.load(sys.stdin).get('InvokeId',''))" 2>/dev/null || echo "")
  if [ -z "$invoke_id" ]; then
    REMOTE_RC=2; REMOTE_LOG="未获得 InvokeId：$invoke"; return 0
  fi
  say "- 只读读取 InvokeId：\`$invoke_id\`（只读：远端只跑查询类命令）"
  while :; do
    i=$((i + 1))
    if [ "$(remaining_seconds)" -le 0 ]; then
      REMOTE_RC=2; REMOTE_LOG="只读读取硬超时（>${READ_TIMEOUT_SECONDS}s，已轮询 $i 次）"; return 0
    fi
    if res=$(run_cmd describe-invocation-result DescribeInvocationResult \
        --instance-id "$INSTANCE_ID" --invoke-id "$invoke_id" --region-id "$REGION" 2>&1); then
      status=$(extract_status <<<"$res")
      if [ "$status" = "Success" ] || [ "$status" = "Failed" ]; then
        REMOTE_LOG=$(extract_remote_log "$res")
        [ -n "$REMOTE_LOG" ] || REMOTE_LOG="$res"
        [ "$status" = "Success" ] || REMOTE_RC=2
        return 0
      fi
    fi
    nap "$POLL_INTERVAL_SECONDS"
  done
}

running_tag_of() {  # $1 = compose 服务名 ⇒ 打印 tag（空串 = 读不到）
  printf '%s\n' "$REMOTE_LOG" | sed -n "s/^RUNNING_TAG=$1://p" | head -1 | tr -d '\r'
}
running_state_of() {
  printf '%s\n' "$REMOTE_LOG" | sed -n "s/^RUNNING_STATE=$1://p" | head -1 | tr -d '\r'
}

# ── 提交图祖先关系（**唯一判据源**）：本地 git 优先（CI 侧 fetch-depth: 0 有全历史、零限流），
#    对象不可达才退到 compare API（服务器侧同款判据；匿名 60 次/小时/IP ⇒ 只作兜底）─────────
ancestry_verdict() {  # $1 = 该有的(base) $2 = 在跑(head) ⇒ descendant|ancestor|identical|unknown
  local base=$1 head=$2
  [ -n "$base" ] && [ -n "$head" ] || { echo unknown; return 0; }
  [ "$base" != "$head" ] || { echo identical; return 0; }
  if gitr rev-parse --verify --quiet "${base}^{commit}" >/dev/null \
     && gitr rev-parse --verify --quiet "${head}^{commit}" >/dev/null; then
    if gitr merge-base --is-ancestor "$base" "$head"; then echo descendant; return 0; fi
    if gitr merge-base --is-ancestor "$head" "$base"; then echo ancestor; return 0; fi
    echo unknown; return 0
  fi
  local json status auth=()
  [ -n "${GH_TOKEN:-}" ] && auth=(-H "Authorization: Bearer ${GH_TOKEN}")
  json=$(curl -fsS -m 20 "${auth[@]}" -H 'Accept: application/vnd.github+json' "$COMPARE_API/$base...$head" 2>/dev/null || true)
  status=$(printf '%s' "$json" | python3 -c 'import sys, json
try:
    print(json.load(sys.stdin).get("status") or "")
except Exception:
    print("")' 2>/dev/null || true)
  case "$status" in
    ahead)     echo descendant ;;
    behind)    echo ancestor ;;
    identical) echo identical ;;
    *)         echo unknown ;;
  esac
  return 0
}

# 该服务**上次成功部署**的 commit（断路器同款取数；取不到 ⇒ 空串 = 判不出）
last_successful_deploy_sha() {  # $1 = deploy workflow
  local runs
  runs=$(gh run list --workflow "$1" --branch main --limit 30 --json headSha,conclusion 2>/dev/null || echo "[]")
  printf '%s' "$runs" | jq -r '[.[] | select(.conclusion == "success")][0].headSha // ""' 2>/dev/null || echo ""
}

# 该 commit 的镜像在 ACR 里存在吗（**只查**）。三态：
#   `yes` / `no` = 判据可用；`?` = **判不出**（docker 不在 / 未登录 / 查询被拒）——
#   ⚠️ 不许把「查不到」当「不存在」用（那会让降级判据把「镜像其实已建」读成「没建」）。
image_exists() {  # $1 = 完整镜像引用
  command -v docker >/dev/null 2>&1 || { echo "?"; return 0; }
  local err
  err=$(mktemp)
  if docker manifest inspect "$1" >/dev/null 2>"$err"; then rm -f "$err"; echo "yes"; return 0; fi
  if grep -qiE "unauthorized|denied|no basic auth|authentication required|forbidden" "$err"; then
    rm -f "$err"; echo "?"; return 0
  fi
  rm -f "$err"; echo "no"
}

# 单服务对账。$1=compose 服务名 $2=镜像 repo $3=deploy workflow $4=代码路径 $5=排除 pathspec（可空）
reconcile_service() {
  local svc=$1 repo=$2 wf=$3 svc_path=$4 excl=$5
  local running state expected7 image verdict pathspec=() drift p
  running=$(running_tag_of "$svc")
  state=$(running_state_of "$svc")
  pathspec=( "$svc_path" )
  if [ -n "$excl" ]; then pathspec+=( "$excl" ); fi
  expected7=$(gitr log -1 --format=%h origin/main -- "${pathspec[@]}" | tr -d '\r\n')
  image="${ACR_REGISTRY:-crpi-qdcgkzwx9p9zckga.cn-hangzhou.personal.cr.aliyuncs.com}/${ACR_NAMESPACE:-ai-customer-service}/${repo}:sha-${expected7}"

  if [ "$TRUTH_OK" != "1" ] || [ -z "$expected7" ]; then
    undecided "[容器/${svc}] 判不出：取不到 \`origin/main\` 上 \`${svc_path}\` 的最近一次改动提交（真值源不可达）"
    return 0
  fi
  if [ -z "$running" ]; then
    undecided "[容器/${svc}] 判不出：读不到运行中容器的 image tag（state=${state:-未读到}；容器未起/未跑 \`ps\`/读取通道失败）—— 线上在跑 ${svc_path} 的哪个 commit **未知**（不是「一致」）"
    return 0
  fi
  case "$running" in
    sha-*) : ;;
    *)
      undecided "[容器/${svc}] 判不出：在跑 tag \`$running\` 不是 \`sha-<7>\` 形态 ⇒ 没有提交序可判（该有的 = \`sha-${expected7}\`）"
      return 0 ;;
  esac
  running=${running#sha-}

  verdict=$(ancestry_verdict "$expected7" "$running")
  case "$verdict" in
    identical)
      consistent "[容器/${svc}] 一致：线上在跑 \`sha-${running}\` == 该服务最近一次改动 \`${svc_path}\` 的 main 提交 \`${expected7}\`（依据：\`git log -1 origin/main -- ${svc_path}\` + tag 相等）"
      return 0 ;;
    descendant)
      consistent "[容器/${svc}] 一致：线上在跑 \`sha-${running}\` 是该服务最近一次改动 \`${svc_path}\` 的提交 \`${expected7}\` 的**后代**（依据：提交图 \`merge-base --is-ancestor ${expected7} ${running}\` = 真；部署 tag 取 main HEAD，故与「最近一次改动」天然不等，相等不是判据）"
      return 0 ;;
    ancestor)
      inconsistent "[容器/${svc}] **不一致**：线上在跑 \`sha-${running}\` 是该服务最近一次改动 \`${svc_path}\` 的提交 \`${expected7}\` 的**祖先** ⇒ 线上**缺该服务最近一次改动**（依据：提交图 \`merge-base --is-ancestor ${running} ${expected7}\` = 真；形态②「静默跳过/静默不交付」的正身）"
      return 0 ;;
  esac

  # ── 降级判据（提交序判不出）：镜像在不在 + 自上次成功部署以来该服务有无改动 ──────
  local exists
  exists=$(image_exists "$image")
  if [ "$exists" = "yes" ]; then
    undecided "[容器/${svc}] 判不出：在跑 \`sha-${running}\` 与应有的 \`sha-${expected7}\` 的提交序判不出（本地无对象 / compare API 不可用），而该 commit 的镜像 \`${image}\` **已存在**（已构建但线上没跑）⇒ 不猜方向，fail-open"
    return 0
  fi
  p=$(last_successful_deploy_sha "$wf")
  if [ -z "$p" ]; then
    undecided "[容器/${svc}] 判不出：提交序判不出，且取不到 \`${wf}\` 的成功部署记录（降级判据无基准）⇒ fail-open"
    return 0
  fi
  drift=$(gitr log --oneline -1 "${p}..origin/main" -- "${pathspec[@]}" | tr -d '\r\n')
  if [ -n "$drift" ]; then
    inconsistent "[容器/${svc}] **不一致**：提交序判不出，但自上次成功部署 \`${p:0:7}\` 起 \`${svc_path}\` **有**代码改动（\`${drift%% *}\`），而该提交的镜像 \`${image}\` **不存在**（镜像存在性=${exists}）⇒ 改了、没建、线上没跑 = 静默不交付（形态②）"
  else
    consistent "[容器/${svc}] 一致（降级判据）：提交序判不出，但自上次成功部署 \`${p:0:7}\` 起 \`${svc_path}\` **无**代码改动，且该提交的镜像不存在（镜像存在性=${exists}）⇒ 合理的跳过（线上无需含该 commit 的构建产物）"
  fi
  return 0
}

say "## 一、容器侧（运行中容器的**实际** image tag vs 该有的 tag）"
say ""
read_remote
if [ -n "$REMOTE_CMD" ]; then
  say "> ⚠️ 本节读数来自 \`RECONCILE_REMOTE_CMD\` **桩命令**（**桩化、未真跑远端**）。"
  say ""
fi
if [ "$REMOTE_RC" -ne 0 ]; then
  undecided "[容器侧] 判不出：只读读取通道失败（rc=${REMOTE_RC}）⇒ 三个服务**全部**未知：${REMOTE_LOG}"
else
  # 逐服务（代码路径 = 各自 workflow 的 `on.push.paths` 真值源；有动态对齐守卫）
  reconcile_service admin-api admin-api deploy-admin-api.yml backend/admin-api ""
  reconcile_service ai-agent ai-agent-service deploy-ai-agent-service.yml backend/ai-agent-service ":(exclude)backend/ai-agent-service/tests"
  reconcile_service admin-web admin-web deploy-frontend.yml frontend/admin-web ""
fi
say ""

# ══════════════════════════════════════════════════════════════════════════════
# 二、静态侧：线上 `$BASE_URL/$H5_SUBPATH/` 的实际内容 vs `origin/main` 的 `frontend/worker-h5/**`
#     **逐文件哈希比对**（排除 `tests/**`，与发布脚本口径一致）
# ══════════════════════════════════════════════════════════════════════════════
say "## 二、静态侧（\`$BASE_URL/$H5_SUBPATH/\` vs \`origin/main:$H5_SRC/**\`，逐文件哈希）"
say ""

TMPDIR_RUN=$(mktemp -d)
trap 'rm -rf "$TMPDIR_RUN"' EXIT

if [ "$TRUTH_OK" != "1" ]; then
  undecided "[静态侧] 判不出：取不到 \`origin/main\`（真值源不可达）⇒ 无法给出该有的内容"
else
  H5_FILES=$(gitr ls-tree -r --name-only origin/main -- "$H5_SRC" | grep -v '/tests/' || true)
  if [ -z "$H5_FILES" ]; then
    undecided "[静态侧] 判不出：\`origin/main\` 上 \`$H5_SRC\` 下**一个文件都没列出**（清单为空 ⇒ 反空跑，绝不当「一致」）"
  else
    for f in $H5_FILES; do
      rel=${f#"$H5_SRC"/}
      url="$BASE_URL/$H5_SUBPATH/$rel"
      out="$TMPDIR_RUN/$(printf '%s' "$rel" | tr '/' '_')"
      # ⚠️ 不用 `|| echo 000`：curl 失败时**仍会**把 `%{http_code}` 写成 `000` ⇒ 会拼成 `000000`。
      #    分开取 rc 与 code ⇒ 「连不上」与「404」可辨（前者是判不出，后者是不一致）。
      code=$(curl -sS -m 20 -H 'Cache-Control: no-cache' -o "$out" -w '%{http_code}' "$url" 2>/dev/null)
      curl_rc=$?
      want=$(gitr show "origin/main:$f" | stdin_sha256)
      if [ "$curl_rc" -ne 0 ] || [ "$code" = "000" ]; then
        # ⚠️ HTTP 000 = **连不上/超时**（curl 自己失败）⇒ 这是「判不出」，**不是**「确认不一致」：
        #    把读不到当成不一致会把「网络抖动」误报成「线上少交付」（判据失去判别力）。
        undecided "[静态/${rel}] 判不出：\`$url\` 取不到（curl rc=${curl_rc} / HTTP=${code} = 连接失败/超时）⇒ 线上这份到底在不在、对不对**未知**（不是「一致」）"
        continue
      fi
      if [ "$code" != "200" ] || [ ! -s "$out" ]; then
        inconsistent "[静态/${rel}] **不一致**：\`$url\` HTTP=${code}（期望 200 且有内容）⇒ 线上**没有**这份 \`origin/main:$f\`（形态③：发布腿按路径过滤没跑 / 落位失败）"
        continue
      fi
      got=$(file_sha256 "$out")
      if [ "$got" = "$want" ]; then
        consistent "[静态/${rel}] 一致：\`$url\` HTTP=200 · 线上哈希 \`$got\` == \`origin/main:$f\`"
      else
        inconsistent "[静态/${rel}] **不一致**：\`$url\` 线上哈希 \`$got\` ≠ \`origin/main:$f\` 的 \`$want\`（形态③：线上是**旧副本**）"
      fi
    done
  fi
fi
say ""
say "> 残留（如实登记）：线上 \`/$H5_SUBPATH/\` 里**多出来**的文件无法通过 HTTP 枚举 ⇒ 本对账只判「main 有的线上有没有、内容对不对」，"
say "> 不判「线上有没有多余文件」。"
say ""

# ══════════════════════════════════════════════════════════════════════════════
# 三、一行总结 + 退出码（**判不出必须 fail-open 但一定出声**）
# ══════════════════════════════════════════════════════════════════════════════
TOTAL=$((CONSISTENT + INCONSISTENT + UNKNOWN))
say "**结论**：一致=${CONSISTENT} · 不一致=${INCONSISTENT} · 判不出=${UNKNOWN}"
if [ "$TOTAL" -eq 0 ]; then
  # 反空跑：一个判定都没做出来 ⇒ 不许当「通过」
  echo "::warning::线上一致性对账**没有做出任何判定**（一致=0/不一致=0/判不出=0）—— 这不是「通过」，是「没跑」"
fi
if [ "$INCONSISTENT" -gt 0 ]; then
  echo "::error::线上一致性对账发现 ${INCONSISTENT} 项**确认的不一致**：线上与 main 该有的那份不符（真的少交付了）"
  exit 1
fi
if [ "$UNKNOWN" -gt 0 ]; then
  echo "::warning::线上一致性对账：${UNKNOWN} 项**判不出**（fail-open，不阻塞）—— 请人工确认；判不出 ≠ 一致"
fi
echo "::notice::线上一致性对账完成：一致=${CONSISTENT} · 不一致=0 · 判不出=${UNKNOWN}"
exit 0
