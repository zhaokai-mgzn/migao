#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# prod-release.sh — **生产发布唯一入口**，一条命令（在部署机上跑；GitHub 不参与）
#
# ## 为什么有这个脚本（2026-11-23 用户裁定逐字）
#
# > 「为什么部署生产环境还要依赖 github 的 ci？不可以直接走部署机吗？**生产环境需要和 github 的能力解耦**」
#
# 今天（2026-11-23）的现场就是答案：11:32–11:39 有一次**只更新 admin-api 的手工发布**
# （`admin-api=sha-26ff9f7` 起于 11-23 11:39，`admin-web=sha-caf01e4` 停在 11-21 22:52、
# `ai-agent=sha-0dced39` 停在 11-22 18:25）⇒ **三服务身份不自洽**，没有任何东西会报。
# 而 GitHub 那条腿先天拿不到现场：生产 **22 端口只对办公出口开放**，GitHub runner 不在那个出口；
# 部署机到生产 22 不通、**443 通**；凭证只在部署机 `~/.aliyun/config.json`（`prod` profile）。
#
# ⇒ 发布 = **部署机上的一次显式动作**，通道 = OpenAPI 云助手（`scripts/lib/prod-swas-run.sh`，唯一实现），
#   远端执行体 = **盘上既有的** `/opt/migao-deploy/deploy.sh`（本脚本**不重写**部署逻辑、**不重写**蓝绿）。
#
# ## 闸门（顺序即安全顺序；每道都会退非零并**具名**）
#
# | # | 闸门 | 判据 | 不满足 |
# |---|---|---|---|
# | ① | **机器闸门** | 本机身份 == `ssh -G <别名>` 解析出的 `HostName`（别名缺省 `migao-deploy`，**禁写死 IP**） | 退 1（具名 + 三个出口）· 读数不可得 ⇒ 退 3 |
# | ② | **发布线闸门** | 目标版本（缺省 `HEAD`，可 `--version <sha|tag>`）**必须是 `origin/release` 的祖先**；`release` 上有 `main` 没有的提交**允许**（记账），`main` 领先 `release` 的部分**报数**（本次不发） | 退 1（具名 + `git log release..target`）· 远端取不到 ⇒ 退 3 |
# | ③ | **默认安全（--apply 闸门）** | 不给 `--apply` = **dry-run**：只打印计划与线上身份，**一次 `run-command` 都不发**、不写任何东西 | — |
# | ④ | **真发** | `bash <远端 deploy.sh> <版本参数> <目标 sha>`；版本参数**先读 `--help` 判定**，读不到 ⇒ **退 3** 并打印 `--help` 原文片段（**不猜**） | 退 1（含远端输出尾段） |
# | ⑤ | **发后自检（同源）** | 三服务身份必须**同源同一 sha == 目标版本**：`docker ps` 的镜像 tag + 应用层 `curl`（`/api/version`、`/version.json`、`/version`） | 退 1，**点名**哪个服务、差多少 |
# | ⑥ | **台账** | 成功才追加一行 JSONL 到 `/opt/migao-deploy/release-ledger.jsonl`（**只追加**）；并打印可粘贴行 `PROD-RELEASE rc=…` | 追加失败 ⇒ 退 1（发布成功但台账缺行，那是缺口不许静默） |
#
# ## 无感发布：量出来，不猜（2026-11-23 用户裁定「未来做集群部署时如何不影响用户，让用户无感」）
#
# 盘上 `deploy.sh` 已是**严格蓝绿**（issue #4785：先起 green 到第二端口、用同一份健康判据、通过后才替换正式容器），
# 但切换 = **重建正式容器 + `nginx -s reload`**（它有意不走 upstream 切换）⇒ 切换窗口里**会有失败请求**。
# 本脚本**不动** `deploy.sh`（那是下一个包的事），只把「无感」**量出来**：
#
#   · `SWITCH-BLINDSPOT failures=<n> max_gap_ms=<ms>`：`--apply` 期间每 200ms 打一次
#     `https://api.<域>/api/version`，覆盖整个切换期（上限 `--probe-seconds`，默认 120）；
#     失败 > 0 ⇒ 打 `::warning::`（**不 fail**：改造 deploy.sh 不在本包范围），
#     `failures=0` 才算「这次切换对用户无感」；
#   · `SSE-PROBE breaks=<n>`：`MIGAO_PROD_SSE_PROBE_URL` 给了就单列计数
#     `/api/chat/*` 的流式连接（连上再被打断 = 1 次断流）；**没配置 ⇒ 打印 `SKIPPED` 并登记缺口**（不假装在探）；
#   · `DRAIN`：发布前读 `ai-agent` 容器里 `ss -tn state established '( sport = :8000 )'` 的活跃连接数，
#     `--apply` 时**等待 drain**（`--drain-seconds`，默认 10、上限 60）。
#
# ## 容量面**不做闸门**（2026-11-23 用户裁定「磁盘先不用管……可以依赖阿里云的能力」）
#
#   内存预检已在盘上 `deploy.sh`（green 与旧容器并存要 `mem_limit+512m`，不够它自己 fail-closed）——**复用它，不复制**；
#   资源面告警（磁盘 / 内存 / 连接数）未来走**阿里云云监控**，本脚本不自建阈值判据。
#
# ## 三态退出码
#
#   `0` 成功 / `1` 判红（闸门或自检不成立，具名）/ `2` 用法错误 / `3` **判不了**（CLI 缺、凭证缺、实例拿不到、
#   `deploy.sh --help` 读不到 ⇒ 不知道怎样把版本传进去）
#
# ## 用法
#
#   bash scripts/prod-release.sh                 # dry-run：打印计划 + 线上身份（**零写面**）
#   bash scripts/prod-release.sh --version <sha|tag>   # 发指定版本（仍是 dry-run，除非给 --apply）
#   bash scripts/prod-release.sh --apply         # 真发（之后自检 + 台账 + 记录行）
#   bash scripts/prod-release.sh --host-assert   # 只判「本机是不是部署机」（零副作用）
#   bash scripts/prod-release.sh --apply --drain-seconds 30 --probe-seconds 120
#
# ## 注入点（判据用；**读数**的口子，不是「跳过闸门」的开关）
#
#   MIGAO_PROD_SSH_ALIAS / MIGAO_PROD_SSH_CONFIG / MIGAO_PROD_HOST_ID     机器闸门
#   MIGAO_PROD_RELEASE_REF / MIGAO_PROD_MAIN_REF                         发布线 ref
#   MIGAO_PROD_ALIYUN_BIN / _PYTHON_BIN / _REGION / _BIZ_REGION / _INSTANCE_ID / _CRED_FILE   云助手通道
#   MIGAO_PROD_DEPLOY_SCRIPT / MIGAO_PROD_LEDGER                         远端盘上既有资产
#   MIGAO_PROD_BASE / MIGAO_PROD_CURL_BIN                                443 应用层读数（缺省域与 prod-smoke.sh 同口径）
#   MIGAO_PROD_SSE_PROBE_URL                                             流式断流探针端点（不给 ⇒ SKIPPED）
#   MIGAO_PROD_PROBE_INTERVAL_MS / MIGAO_PROD_DEPLOY_TIMEOUT             探针节奏 / 远端发布超时
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

SELF_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "$SELF_DIR/.." && pwd)

# shellcheck source=lib/prod-swas-run.sh
. "$ROOT/scripts/lib/prod-swas-run.sh"

DEPLOY_ALIAS="${MIGAO_PROD_SSH_ALIAS:-migao-deploy}"
SSH_CONFIG_FILE="${MIGAO_PROD_SSH_CONFIG:-}"
HOST_ID_OVERRIDE="${MIGAO_PROD_HOST_ID:-}"
RELEASE_REF="${MIGAO_PROD_RELEASE_REF:-origin/release}"
MAIN_REF="${MIGAO_PROD_MAIN_REF:-origin/main}"
REMOTE_DEPLOY="${MIGAO_PROD_DEPLOY_SCRIPT:-/opt/migao-deploy/deploy.sh}"
REMOTE_LEDGER="${MIGAO_PROD_LEDGER:-/opt/migao-deploy/release-ledger.jsonl}"
BASE_DOMAIN="${MIGAO_PROD_BASE:-cytda.com}"
CURL_BIN="${MIGAO_PROD_CURL_BIN:-curl}"
SSE_PROBE_URL="${MIGAO_PROD_SSE_PROBE_URL:-}"
PROBE_INTERVAL_MS="${MIGAO_PROD_PROBE_INTERVAL_MS:-200}"
DEPLOY_TIMEOUT="${MIGAO_PROD_DEPLOY_TIMEOUT:-1800}"
HTTP_TIMEOUT="${MIGAO_PROD_HTTP_TIMEOUT:-15}"

APPLY=0
EXPLICIT_DRY=0
HOST_ASSERT_ONLY=0
VERSION_ARG=""
DRAIN_SECONDS=10
PROBE_SECONDS=120
TARGET_SHA=""
SHA7=""
RELEASE_SHA=""
MAIN_SHA=""
LEGACY_API=""
LEGACY_WEB=""
LEGACY_AI=""

usage() {
  cat <<'USAGE'
用法：bash scripts/prod-release.sh [--apply | --dry-run] [--version <sha|tag>] [--host-assert]

  缺省 = dry-run（打印计划 + 线上三服务身份；**零写面**，一次 run-command 都不发）
  --apply              真发（复用盘上 /opt/migao-deploy/deploy.sh + 发后同源自检 + 台账）
  --version <sha|tag>  目标版本（缺省 HEAD）；必须是 origin/release 的祖先
  --drain-seconds N    真发前等 ai-agent 活跃流排空（默认 10，上限 60）
  --probe-seconds N    切换盲区探针时长上限（默认 120）
  --host-assert        只判「本机是不是部署机」，零副作用

退出码：0 成功 / 1 判红（具名）/ 2 用法错误 / 3 判不了（CLI 缺、凭证缺、实例拿不到、deploy.sh --help 读不到）
USAGE
}

ok() { printf '✓ %s\n' "$*"; }
note() { printf '  · %s\n' "$*"; }
warn() { printf '::warning::%s\n' "$*" >&2; }
die_usage() { printf '用法错误：%s\n' "$*" >&2; usage >&2; exit 2; }
die_named() { printf '✗ %s\n' "$*" >&2; exit 1; }
die_undecidable() { printf '✗ 不可判定（3）：%s\n' "$*" >&2; exit 3; }

# ── 主机名归一 / 部署机身份（沿用 scripts/bmini-release.sh 的做法，**禁写死 IP**）────────
normalize_host() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -e 's/\.$//' -e 's/\.local$//'; }

deploy_host_name() {
  command -v ssh >/dev/null 2>&1 || return 3
  local resolved
  if [ -n "$SSH_CONFIG_FILE" ]; then
    resolved=$(ssh -G -F "$SSH_CONFIG_FILE" "$DEPLOY_ALIAS" 2>/dev/null) || return 3
  else
    resolved=$(ssh -G "$DEPLOY_ALIAS" 2>/dev/null) || return 3
  fi
  printf '%s\n' "$resolved" | awk '$1 == "hostname" { print $2; exit }'
}

local_host_ids() {
  if [ -n "$HOST_ID_OVERRIDE" ]; then printf '%s\n' "$HOST_ID_OVERRIDE"; return 0; fi
  local ids="" name
  if command -v scutil >/dev/null 2>&1; then
    name=$(scutil --get LocalHostName 2>/dev/null) || name=""
    [ -n "$name" ] && ids="${ids}${name}
${name}.local
"
  fi
  name=$(hostname -s 2>/dev/null) || name=""
  [ -n "$name" ] && ids="${ids}${name}
"
  name=$(hostname 2>/dev/null) || name=""
  [ -n "$name" ] && ids="${ids}${name}
"
  [ -n "$ids" ] || return 3
  printf '%s' "$ids"
}

# ── ① 机器闸门 ────────────────────────────────────────────────────────────────
gate_machine() {
  echo "== ① 机器闸门（生产发布只在部署机执行）=="
  local target rc=0 ids rc_ids=0 id target_norm
  target=$(deploy_host_name) || rc=$?
  if [ "$rc" -ne 0 ] || [ -z "$target" ]; then
    die_undecidable "读不到 SSH 别名 '${DEPLOY_ALIAS}' 的 HostName（ssh -G 不可用 / 配置不可读）——
       出口：确认 ssh 可用、~/.ssh/config 里有 'Host ${DEPLOY_ALIAS}' 段（或用 MIGAO_PROD_SSH_CONFIG=<配置文件>），
       再跑 scripts/prod-release.sh --host-assert"
  fi
  ids=$(local_host_ids) || rc_ids=$?
  if [ "$rc_ids" -ne 0 ] || [ -z "$ids" ]; then
    die_undecidable "读不到本机身份（scutil LocalHostName / hostname 都失败）—— 判不了是不是部署机。
       出口：显式给读数 MIGAO_PROD_HOST_ID=\$(hostname -s) 后重跑 --host-assert"
  fi
  note "部署机（SSH 别名 ${DEPLOY_ALIAS} → HostName）= ${target}"
  note "本机身份 = $(printf '%s\n' "$ids" | paste -sd' /' -)"
  target_norm=$(normalize_host "$target")
  while IFS= read -r id; do
    [ -n "$id" ] || continue
    if [ "$(normalize_host "$id")" = "$target_norm" ]; then
      ok "本机就是部署机（${target}）"
      return 0
    fi
  done <<< "$ids"
  die_named "非部署机 ⇒ 拒绝发布（生产发布必须在部署机上：凭证在那台机器的 ~/.aliyun/config.json，不在别处）
   本机 = $(printf '%s\n' "$ids" | head -1)
   部署机（SSH 别名 '${DEPLOY_ALIAS}'）的 HostName = ${target}
   出口（三选一）：
     · **正确路径**：ssh ${DEPLOY_ALIAS} 之后在部署机上跑本脚本
     · 这台**就是**部署机（别名指错了）：把 ~/.ssh/config 的 'Host ${DEPLOY_ALIAS}' 段的 HostName 改成
       <本机 LocalHostName>.local，再跑 scripts/prod-release.sh --host-assert 复验
     · 只想看现场、不发布：scripts/prod-inspect.sh（只读盘点；GitHub 与它无关）"
}

# ── ② 发布线闸门 ──────────────────────────────────────────────────────────────
gate_version() {
  echo "== ② 发布线闸门（目标版本必须是 ${RELEASE_REF} 的祖先）=="
  git -C "$ROOT" fetch --quiet origin >/dev/null 2>&1 || die_undecidable "取不到 origin（网络 / 远端不可达）——
       发布线是否成立不可判定，不许当通过。出口：恢复对 origin 的访问后重跑"

  RELEASE_SHA=$(git -C "$ROOT" rev-parse --verify --quiet "$RELEASE_REF" 2>/dev/null) || RELEASE_SHA=""
  [ -n "$RELEASE_SHA" ] || die_named "拿不到 ${RELEASE_REF} ⇒ 发布线还不存在，这次不许发（否则「发什么」取决于工作区）
       出口：在部署机上跑 ./scripts/cut-release.sh（把 release 快进到 main，显式动作）后重跑"

  if [ -n "$VERSION_ARG" ]; then
    TARGET_SHA=$(git -C "$ROOT" rev-parse --verify --quiet "${VERSION_ARG}^{commit}" 2>/dev/null) || TARGET_SHA=""
    [ -n "$TARGET_SHA" ] || die_named "版本 '${VERSION_ARG}' 解析不了（不是本仓的 sha / tag）——
       出口：git rev-parse --verify '${VERSION_ARG}^{commit}' 自查，或直接给 7~40 位 sha"
  else
    TARGET_SHA=$(git -C "$ROOT" rev-parse --verify HEAD 2>/dev/null) || die_undecidable "拿不到本检出的 HEAD（不是 git 检出？）"
  fi
  SHA7=$(printf '%s' "$TARGET_SHA" | cut -c1-7)

  if ! git -C "$ROOT" merge-base --is-ancestor "$TARGET_SHA" "$RELEASE_SHA" 2>/dev/null; then
    die_named "目标版本不在发布线上：${SHA7} 不是 ${RELEASE_REF}（${RELEASE_SHA:0:7}）的祖先 —— 禁止发布不在发布线上的代码
       release..target 上有这些提交（先查它们从哪来）：
$(git -C "$ROOT" --no-pager log --oneline "${RELEASE_SHA}..${TARGET_SHA}" 2>/dev/null | head -10)"
  fi
  ok "目标版本 ${SHA7} 在发布线 ${RELEASE_REF}（${RELEASE_SHA:0:7}）上"

  MAIN_SHA=$(git -C "$ROOT" rev-parse --verify --quiet "$MAIN_REF" 2>/dev/null) || MAIN_SHA=""
  if [ -n "$MAIN_SHA" ]; then
    if ! git -C "$ROOT" merge-base --is-ancestor "$RELEASE_SHA" "$MAIN_SHA" 2>/dev/null; then
      note "${RELEASE_REF} 上有 ${MAIN_REF} 没有的提交（**允许**：发布线可独立前进，本次照发）：
$(git -C "$ROOT" --no-pager log --oneline "${MAIN_SHA}..${RELEASE_SHA}" 2>/dev/null | head -5 | sed 's/^/       /')"
    fi
    local ahead
    ahead=$(git -C "$ROOT" rev-list --count "${RELEASE_SHA}..${MAIN_SHA}" 2>/dev/null || echo "?")
    [ "$ahead" = "0" ] || note "${MAIN_REF} 比 ${RELEASE_REF} 多 ${ahead} 个提交（**本次不发它们**，要发先 cut-release.sh）"
  fi
  [ "$TARGET_SHA" = "$RELEASE_SHA" ] || note "目标版本 ${SHA7} ≠ 发布线 head（${RELEASE_SHA:0:7}，领先本次 ${SHA7} 若干）—— 发的是前者"
}

# ── 443 应用层身份读数（dry-run 与自检共用；**不发 run-command**）──────────────────
svc_sha7() {
  local body
  body=$("$CURL_BIN" -s -m "$HTTP_TIMEOUT" "$1" 2>/dev/null) || { printf ''; return 0; }
  printf '%s' "$body" | "$PROD_PYTHON_BIN" -c '
import json, sys
raw = sys.stdin.read()
try:
    print((json.loads(raw).get("sha") or "")[:7])
except Exception:
    print("")'
}

read_identities() {
  LEGACY_API=$(svc_sha7 "https://api.${BASE_DOMAIN}/api/version")
  LEGACY_WEB=$(svc_sha7 "https://merchant.${BASE_DOMAIN}/version.json")
  LEGACY_AI=$(svc_sha7 "https://ai-api.${BASE_DOMAIN}/version")
  note "线上三服务身份（443 应用层读数；取不到就是「判不了」，不当通过）："
  note "  api = ${LEGACY_API:-判不了} · web = ${LEGACY_WEB:-判不了} · ai = ${LEGACY_AI:-判不了}"
}

ms_now() { "$PROD_PYTHON_BIN" -c 'import time; print(int(time.time() * 1000))'; }

# 切换盲区探针：每 200ms 一次 200 判定，日志 "ts OK|FAIL code"
probe_version_loop() {
  local log=$1 deadline=$2 stop=$3 now code
  : > "$log"
  while :; do
    [ -e "$stop" ] && break
    now=$(ms_now)
    [ "$now" -ge "$deadline" ] && break
    code=$("$CURL_BIN" -s -m 5 -o /dev/null -w '%{http_code}' "https://api.${BASE_DOMAIN}/api/version" 2>/dev/null)
    if [ "$code" = "200" ]; then printf '%s OK\n' "$now" >> "$log"; else printf '%s FAIL %s\n' "$now" "${code:-000}" >> "$log"; fi
    sleep 0.2
  done
}

# 流式探针：连上再被打断 = 断流（curl 18/52/56）；28 = 仍在流（正常）；0 = 服务端干净收尾
probe_sse_loop() {
  local log=$1 deadline=$2 stop=$3 now rc
  [ -n "$SSE_PROBE_URL" ] || return 0
  : > "$log"
  while :; do
    [ -e "$stop" ] && break
    now=$(ms_now)
    [ "$now" -ge "$deadline" ] && break
    "$CURL_BIN" -s -N -m 8 -o /dev/null "$SSE_PROBE_URL" >/dev/null 2>&1
    rc=$?
    printf '%s SSE %s\n' "$now" "$rc" >> "$log"
    sleep 0.2
  done
}

probe_stats() {
  "$PROD_PYTHON_BIN" -c '
import sys
rows = []
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    parts = line.split()
    if len(parts) < 2:
        continue
    try:
        ts = int(parts[0])
    except ValueError:
        continue
    rows.append((ts, parts[1]))
if not rows:
    print("failures=0 max_gap_ms=0 samples=0 window_ms=0")
    raise SystemExit
failures = sum(1 for _ts, kind in rows if kind == "FAIL")
ok_ts = [ts for ts, kind in rows if kind == "OK"]
gap = 0
if ok_ts:
    prev = rows[0][0]
    for ts, kind in rows:
        if kind == "OK":
            gap = max(gap, ts - prev)
            prev = ts
elif failures:
    gap = rows[-1][0] - rows[0][0]
window = rows[-1][0] - rows[0][0]
print("failures=%d max_gap_ms=%d samples=%d window_ms=%d" % (failures, gap, len(rows), window))
' "$1"
}

sse_stats() {
  "$PROD_PYTHON_BIN" -c '
import sys
breaks = samples = rejected = 0
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    parts = line.split()
    if len(parts) < 3:
        continue
    rc = parts[2]
    samples += 1
    if rc in ("0", "28"):
        continue
    if rc == "22":
        rejected += 1
        continue
    breaks += 1
print("breaks=%d samples=%d rejected=%d" % (breaks, samples, rejected))
' "$1"
}

# ── ④a drain：发布前读 ai-agent 活跃流，--apply 时等待排空 ──────────────────────
drain_before_deploy() {
  local out rc streams deadline
  echo "== ③ drain（发布前读 ai-agent 的活跃流；等排空再动容器）=="
  out=$(prod_swas_run "$(cat <<'REMOTE'
c=$(docker ps --format '{{.Names}}' | grep -Ei 'ai-agent' | head -1)
if [ -z "$c" ]; then echo 'STREAMS=unknown reason=no-ai-agent-container'; exit 0; fi
n=$(docker exec "$c" ss -tn state established '( sport = :8000 )' 2>/dev/null | tail -n +2 | wc -l | tr -d ' ')
echo "STREAMS=${n:-0} container=${c}"
REMOTE
)" 120 migao-prod-drain)
  rc=$?
  [ "$rc" -eq 3 ] && die_undecidable "读不到 ai-agent 活跃流（通道判不了）—— 真发需要这一条读数，不许猜"
  streams=$(printf '%s' "$out" | sed -n 's/^STREAMS=\([0-9]*\).*/\1/p' | head -1)
  note "drain 读数：$(printf '%s' "$out" | grep -m1 'STREAMS=' || echo 'STREAMS=unknown')"
  case "$streams" in
    ""|unknown) note "活跃流**判不了**（容器里没有 ss / 容器不在）⇒ 不等待，继续（这一格是缺口，见 docs）"; return 0 ;;
    0) ok "无活跃流，不必等待"; return 0 ;;
  esac
  deadline=$(( $(ms_now) + DRAIN_SECONDS * 1000 ))
  note "有 ${streams} 条活跃流 ⇒ 最多等 ${DRAIN_SECONDS}s 让它自然结束（不打断用户的对话）"
  while :; do
    [ "$(ms_now)" -ge "$deadline" ] && { warn "drain 超时（仍 >0 条活跃流）—— 继续发布；断流由 SSE-PROBE 计量"; return 0; }
    sleep 2
    out=$(prod_swas_run "$(cat <<'REMOTE'
c=$(docker ps --format '{{.Names}}' | grep -Ei 'ai-agent' | head -1)
n=$(docker exec "$c" ss -tn state established '( sport = :8000 )' 2>/dev/null | tail -n +2 | wc -l | tr -d ' ')
echo "STREAMS=${n:-unknown}"
REMOTE
)" 120 migao-prod-drain)
    [ $? -eq 3 ] && { warn "drain 复读判不了 ⇒ 不再等待"; return 0; }
    streams=$(printf '%s' "$out" | sed -n 's/^STREAMS=\([0-9]*\)/\1/p' | head -1)
    [ "$streams" = "0" ] && { ok "活跃流已排空"; return 0; }
  done
}

# ── ④b deploy.sh 的版本参数：先 --help，读不到 ⇒ 退 3（不猜） ──────────────────
detect_deploy_flag() {
  local out rc flag
  echo "== ④ 真发（复用盘上 ${REMOTE_DEPLOY}；版本参数先读 --help 判定）=="
  out=$(prod_swas_run "bash ${REMOTE_DEPLOY} --help 2>&1 | head -40" 120 migao-prod-help)
  rc=$?
  [ "$rc" -eq 3 ] && die_undecidable "读不到 ${REMOTE_DEPLOY} --help（通道判不了）"
  flag=$(printf '%s' "$out" | grep -oE -- '--(version|ref|sha|target|release|git-sha|runtime-sha)[a-z-]*' | head -1)
  if [ -z "$flag" ]; then
    # 兜底：**规范契约**是位置参数 `TAG=${1:-latest}`（`deploy/swas/deploy.sh` 的 `TAG=${1:-latest}` 契约）。
    # 盘上脚本若是旧版，`--help` 会被当成 **tag** ⇒ 退出非零、输出的是拒绝文本而不是帮助
    # （2026-11-24 11:16 真机实测：`追不到 tag=--help 指向的提交`）⇒ 此时**按契约判位置参数**，
    # 不再「不猜就停」：停在这里等于「发布永远发不出去」，而契约是脚本自己写着的。
    # 判据放在**本地仓库**里（`deploy/swas/deploy.sh` 就是会被自同步到主机的那一份）⇒ 不必再开一次远端调用。
    if grep -qF 'TAG=${1:-' "$SELF_DIR/../deploy/swas/deploy.sh" 2>/dev/null; then
      DEPLOY_FORM=positional
      ok "版本参数 = **位置参数**（盘上 ${REMOTE_DEPLOY} 是 \`TAG=\${1:-latest}\` 契约；--help 不可用 ⇒ 不猜 flag）"
    else
      die_undecidable "读不到 ${REMOTE_DEPLOY} 接受的**版本参数** ⇒ 不知道该怎样把目标版本传进去（**不猜**）
   --help 原文片段（前 20 行）：
$(printf '%s' "$out" | head -20 | sed 's/^/     /')"
    fi
  else
    ok "版本参数 = ${flag}"
    DEPLOY_FLAG="$flag"
  fi
}

postcheck_script() {
  cat <<'REMOTE'
d=$(sed -n 's/^MIGAO_PUBLIC_DOMAIN=//p' /opt/migao-deploy/.env.site 2>/dev/null | head -1)
echo '--- docker ---'
docker ps --format '{{.Names}}|{{.Image}}' | grep -Ei 'admin-api|admin-web|ai-agent'
echo '--- app-layer ---'
[ -n "$d" ] || exit 0
curl -sS -m 15 "https://api.${d}/api/version" 2>/dev/null; echo
curl -sS -m 15 "https://merchant.${d}/version.json" 2>/dev/null; echo
curl -sS -m 15 "https://ai-api.${d}/version" 2>/dev/null; echo
REMOTE
}

postcheck_parse() {
  "$PROD_PYTHON_BIN" -c '
import json, re, sys
target = sys.argv[1]
services = {"api": ("admin-api",), "web": ("admin-web",), "ai": ("ai-agent", "ai-agent-service")}
docker_sha, app_sha = {}, {}

def svc_for(name):
    for svc, keys in services.items():
        for key in keys:
            if key in name:
                return svc
    return None

for line in sys.stdin.read().splitlines():
    line = line.strip()
    if not line or line.startswith("---"):
        continue
    if "|" in line:
        name, image = line.split("|", 1)
        svc = svc_for(name)
        if not svc:
            continue
        tag = image.rsplit(":", 1)[-1]
        m = re.search(r"sha-([0-9a-fA-F]{5,40})", tag) or re.search(r"([0-9a-fA-F]{7,40})", tag)
        docker_sha[svc] = (m.group(1)[:7].lower() if m else "")
        continue
    try:
        data = json.loads(line)
    except Exception:
        continue
    name = str(data.get("app") or "")
    svc = svc_for(name)
    if svc and data.get("sha"):
        app_sha[svc] = str(data["sha"])[:7].lower()

for svc in ("api", "web", "ai"):
    print("IDENT %s %s %s" % (svc, docker_sha.get(svc) or "-", app_sha.get(svc) or "-"))
' "$1"
}

postcheck() {
  local out rc idents svc dsha asha dist mismatch="" missing=""
  echo "== ⑤ 发后自检（三服务必须同源同一 sha == ${SHA7}）=="
  out=$(prod_swas_run "$(postcheck_script)" 300 migao-prod-postcheck)
  rc=$?
  [ "$rc" -eq 3 ] && die_undecidable "发后自检读不到（通道判不了）—— 发布是否成功不可判定，不许当成功"
  idents=$(printf '%s' "$out" | postcheck_parse "$TARGET_SHA")
  while read -r tag svc dsha asha; do
    [ "$tag" = "IDENT" ] || continue
    [ "$dsha" = "$SHA7" ] && [ "$asha" = "$SHA7" ] && { ok "${svc} 同源 ${SHA7}（docker=${dsha} app=${asha}）"; continue; }
    if [ "$dsha" = "-" ] && [ "$asha" = "-" ]; then missing="${missing} ${svc}"; else
      dist=$(git -C "$ROOT" cat-file -e "${dsha:-$asha}" 2>/dev/null && git -C "$ROOT" rev-list --count "${dsha:-$asha}..${TARGET_SHA}" 2>/dev/null || echo "?")
      mismatch="${mismatch}
   ✗ ${svc}：docker=${dsha} app=${asha} ≠ 目标 ${SHA7}（差 ${dist} 个提交 / '?' = 该 sha 不在本仓历史）"
    fi
  done <<< "$idents"
  APP_API=$(printf '%s' "$idents" | awk '$1=="IDENT" && $2=="api" {print $4}')
  APP_WEB=$(printf '%s' "$idents" | awk '$1=="IDENT" && $2=="web" {print $4}')
  APP_AI=$(printf '%s' "$idents" | awk '$1=="IDENT" && $2=="ai" {print $4}')
  [ -n "$missing" ] && mismatch="${mismatch}
   ✗ 缺失（docker ps 里找不到）：${missing}"
  if [ -n "$mismatch" ]; then
    warn "三服务身份不同源 —— 这就是「发成半截」的形态（2026-11-23 11:32–11:39 的现场）"
    printf '%s\n' "$mismatch" >&2
    POSTCHECK_FAILED=1
  else
    ok "三服务同源同一 sha（${SHA7}）：admin-api / admin-web / ai-agent 全部一致"
    POSTCHECK_FAILED=0
  fi
}

record_row() {
  local rc=$1 api=$2 web=$3 ai=$4 at operator
  at=$(date -u +%FT%TZ)
  operator=$(git -C "$ROOT" config user.email 2>/dev/null || true)
  [ -n "$operator" ] || operator="unknown"
  printf 'PROD-RELEASE rc=%s version=%s api=%s web=%s ai=%s at=%s operator=%s\n' \
    "$rc" "$SHA7" "${api:-unknown}" "${web:-unknown}" "${ai:-unknown}" "$at" "$operator"
}

ledger_append() {
  local line rc
  line=$("$PROD_PYTHON_BIN" -c '
import json, sys
keys = sys.argv[1::2]
vals = sys.argv[2::2]
print(json.dumps(dict(zip(keys, vals)), ensure_ascii=False, sort_keys=True))' \
    version "$TARGET_SHA" api "${APP_API:-unknown}" web "${APP_WEB:-unknown}" ai "${APP_AI:-unknown}" \
    at "$(date -u +%FT%TZ)" operator "$(git -C "$ROOT" config user.email 2>/dev/null || echo unknown)" \
    rc 0 switch_failures "${BLIND_FAILURES:-unknown}" drain_seconds "$DRAIN_SECONDS")
  printf '%s\n' "$line" | grep -q "'" && { warn "台账行里出现了单引号，拒绝远端拼串（不猜）"; return 1; }
  prod_swas_run "printf '%s\n' '${line}' >> '${REMOTE_LEDGER}'" 60 migao-prod-ledger >/dev/null
  rc=$?
  [ "$rc" -eq 0 ] || { warn "台账追加失败（${REMOTE_LEDGER}，rc=${rc}）—— 记录行已打印，但台账缺这一行"; return 1; }
  ok "台账已追加（只追加）：${REMOTE_LEDGER}"
}

main() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --apply) APPLY=1 ;;
      --dry-run) EXPLICIT_DRY=1 ;;
      --version) shift; [ $# -gt 0 ] || die_usage "--version 需要一个值"; VERSION_ARG="$1" ;;
      --version=*) VERSION_ARG="${1#--version=}" ;;
      --drain-seconds) shift; [ $# -gt 0 ] || die_usage "--drain-seconds 需要一个值"; DRAIN_SECONDS="$1" ;;
      --probe-seconds) shift; [ $# -gt 0 ] || die_usage "--probe-seconds 需要一个值"; PROBE_SECONDS="$1" ;;
      --host-assert) HOST_ASSERT_ONLY=1 ;;
      -h|--help) usage; exit 0 ;;
      *) die_usage "未知参数 '$1'" ;;
    esac
    shift
  done
  [ "$APPLY" -eq 1 ] && [ "$EXPLICIT_DRY" -eq 1 ] && die_usage "--apply 与 --dry-run 不能同时给"
  case "$DRAIN_SECONDS" in *[!0-9]*) die_usage "--drain-seconds 必须是整数秒" ;; esac
  case "$PROBE_SECONDS" in *[!0-9]*) die_usage "--probe-seconds 必须是整数秒" ;; esac
  [ "$DRAIN_SECONDS" -le 60 ] || DRAIN_SECONDS=60
  [ "$PROBE_SECONDS" -gt 120 ] && PROBE_SECONDS=120

  prod_swas_init || exit 3
  gate_machine
  if [ "$HOST_ASSERT_ONLY" -eq 1 ]; then
    echo ""
    ok "--host-assert：零副作用（未读线上、未发任何 run-command）"
    exit 0
  fi
  echo ""
  gate_version
  echo ""
  read_identities

  if [ "$APPLY" -ne 1 ]; then
    echo ""
    echo "== 计划（dry-run；**未写任何东西**）=="
    note "目标版本 = ${SHA7}（完整 ${TARGET_SHA}）"
    note "发布线 = ${RELEASE_REF} @ ${RELEASE_SHA:0:7}"
    note "远端命令（--apply 时才执行）：bash ${REMOTE_DEPLOY} <版本参数> ${TARGET_SHA}"
    note "  版本参数在 --apply 时先由 'bash ${REMOTE_DEPLOY} --help' 判定；读不到 ⇒ 退 3（不猜）"
    note "切换盲区探针：dry-run 不启动（--apply 才量，上限 ${PROBE_SECONDS}s）"
    note "SSE 流式探针：${SSE_PROBE_URL:-未配置（MIGAO_PROD_SSE_PROBE_URL）⇒ --apply 时打印 SKIPPED}"
    note "台账：--apply 成功后追加一行到 ${REMOTE_LEDGER}（只追加）"
    echo ""
    echo "DRY-RUN=OK（零写面：本次没有发出任何 run-command）"
    exit 0
  fi

  POSTCHECK_FAILED=0
  BLIND_FAILURES=0
  local probe_tmp probe_log sse_log probe_stop deadline probe_pid sse_pid
  # 临时目录口径要**跨平台**：`mktemp -t <前缀>` 只有 BSD 认（GNU 要求模板里带 XXXXXX，实测算 CI Linux 上
  # 报 «mktemp: too few X's in template» ⇒ 真发路径直接退 3）。⇒ 一律用显式模板 + `mktemp -d`。
  probe_tmp="$(mktemp -d "${TMPDIR:-/tmp}/migao-prod-probe.XXXXXX")" \
    || die_undecidable "建不了探针临时目录（mktemp -d 失败）"
  probe_log="${probe_tmp}/probe.log"
  sse_log="${probe_tmp}/sse.log"
  probe_stop="${probe_tmp}/stop"   # 存在即停：发布一结束探针立刻收（不空跑满 120s）
  deadline=$(( $(ms_now) + PROBE_SECONDS * 1000 ))

  echo ""
  drain_before_deploy
  echo ""
  detect_deploy_flag

  # 探针与真发**并发**：先起探针（不带 set -e，任何情况都别挡住发布）
  probe_version_loop "$probe_log" "$deadline" "$probe_stop" &
  probe_pid=$!
  [ -n "$SSE_PROBE_URL" ] && { probe_sse_loop "$sse_log" "$deadline" "$probe_stop" & sse_pid=$!; } || sse_pid=""

  # ── 真发：**逐服务 C′ 构建**（issue #5814 之后 CI 不构建、不推 ACR）──
  # 病根（2026-11-24 07:23 真机实测）：不带 `BUILD_SERVICE` 时 deploy.sh 走「拉镜像」路径，
  #   ACR 里没有该 tag ⇒ 三个服务全部 `跳过该服务` ⇒ `EFFECTIVE_TAG` 全是旧值 ⇒ 健康检查查的是
  #   **旧容器** ⇒ `deploy.sh 完成` 且 rc=0 —— 一次**一个服务都没换**的「假绿」。
  #   （本次 = `PROD-RELEASE rc=1`，是被本脚本 ⑤ 的同源自检抓回来的，不是 deploy.sh 自己报的。）
  PROD_SERVICES=${PROD_SERVICES:-admin-api ai-agent admin-web}
  # 🔴 apt 源：宿主机在阿里云内网，用 `deb.debian.org` 实测 **>40 分钟没装完**（2026-11-24 11:37–12:38 两次被
  #    `timeout 2400 docker build` 杀掉 ⇒ ai-agent 发布失败两次）。deploy.sh 自己的注释就写了「服务器侧应传
  #    mirrors.aliyun.com」。换源后同一条构建 ~9 分钟完成（06:39→06:49 实测）。
  PROD_APT_MIRROR=${MIGAO_PROD_APT_MIRROR:-mirrors.aliyun.com}
  BUILT_AT_NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  deploy_rc=0
  deploy_out=""
  for svc in $PROD_SERVICES; do
    if [ "${DEPLOY_FORM:-flag}" = "positional" ]; then
      deploy_cmd="MIGAO_RELEASE_LINE=enforce APT_MIRROR=${PROD_APT_MIRROR} BUILD_SERVICE=${svc} BUILD_SHA=${TARGET_SHA} BUILT_AT=${BUILT_AT_NOW} bash ${REMOTE_DEPLOY} sha-$(printf '%s' "$TARGET_SHA" | cut -c1-7)"
    else
      deploy_cmd="bash ${REMOTE_DEPLOY} ${DEPLOY_FLAG} ${TARGET_SHA}"
    fi
    echo "  · [${svc}] 远端执行：${deploy_cmd}"
    out_one=$(prod_swas_run "$deploy_cmd" "$DEPLOY_TIMEOUT" "migao-prod-deploy-${svc}")
    rc_one=$?
    deploy_out="${deploy_out}${out_one}
"
    if [ "$rc_one" -ne 0 ]; then deploy_rc=$rc_one; break; fi
  done
  : > "$probe_stop"     # 停探针（发布已结束，不需要再采样）
  wait "$probe_pid" 2>/dev/null
  [ -n "$sse_pid" ] && wait "$sse_pid" 2>/dev/null

  if [ "$deploy_rc" -eq 3 ]; then
    echo "SWITCH-BLINDSPOT $(probe_stats "$probe_log")" >&2
    die_undecidable "部署通道判不了（run-command / describe 失败）—— 生产是否在动**不可判定**，立刻用 scripts/prod-inspect.sh 复探"
  fi
  if [ "$deploy_rc" -ne 0 ]; then
    echo "SWITCH-BLINDSPOT $(probe_stats "$probe_log")" >&2
    printf '✗ 远端 deploy.sh 退出码 %s（发布未成功）—— 输出尾段：\n%s\n' "$deploy_rc" \
      "$(printf '%s' "$deploy_out" | tail -20 | sed 's/^/   /')" >&2
    record_row 1 "${LEGACY_API}" "${LEGACY_WEB}" "${LEGACY_AI}"
    exit 1
  fi

  # 盲区读数（先算，后面记录行/台账要用）
  blind=$(probe_stats "$probe_log")
  BLIND_FAILURES=$(printf '%s' "$blind" | sed -n 's/.*failures=\([0-9]*\).*/\1/p')
  echo ""
  echo "== ⑥ 切换盲区（无感发布的度量；改造 deploy.sh 不在本包范围）=="
  printf 'SWITCH-BLINDSPOT failures=%s max_gap_ms=%s\n' "$BLIND_FAILURES" \
    "$(printf '%s' "$blind" | sed -n 's/.*max_gap_ms=\([0-9]*\).*/\1/p')"
  printf 'SWITCH-BLINDSPOT window_ms=%s samples=%s\n' \
    "$(printf '%s' "$blind" | sed -n 's/.*window_ms=\([0-9]*\)$/\1/p')" \
    "$(printf '%s' "$blind" | sed -n 's/.*samples=\([0-9]*\).*/\1/p')"
  if [ "$BLIND_FAILURES" != "0" ]; then
    warn "切换窗口内有 ${BLIND_FAILURES} 次失败请求 / 最长连续失败 $(printf '%s' "$blind" | sed -n 's/.*max_gap_ms=\([0-9]*\).*/\1/p')ms ⇒ 这次切换**不是**对用户无感（单机蓝绿 ≠ 集群无感，见 docs）"
  else
    ok "切换窗口内 0 次失败请求 ⇒ 这次切换对用户无感"
  fi
  if [ -z "$SSE_PROBE_URL" ]; then
    echo "SSE-PROBE=SKIPPED reason=未配置端点（MIGAO_PROD_SSE_PROBE_URL）—— 这一格是缺口，不当通过"
  elif [ -s "$sse_log" ]; then
    printf 'SSE-PROBE %s\n' "$(sse_stats "$sse_log")"
  else
    echo "SSE-PROBE=SKIPPED reason=探针没跑起来（判不了，不当通过）"
  fi

  echo ""
  postcheck
  echo ""
  if [ "$POSTCHECK_FAILED" -ne 0 ]; then
    record_row 1 "${APP_API}" "${APP_WEB}" "${APP_AI}"
    exit 1
  fi
  ledger_append || { record_row 1 "${APP_API}" "${APP_WEB}" "${APP_AI}"; exit 1; }
  echo ""
  record_row 0 "${APP_API}" "${APP_WEB}" "${APP_AI}"
  exit 0
}

main "$@"
