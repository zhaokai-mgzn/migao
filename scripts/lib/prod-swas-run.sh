# shellcheck shell=bash
# ══════════════════════════════════════════════════════════════════════════════
# prod-swas-run.sh — 生产实例**云助手通道**的唯一实现（被 source，不单独执行）
#
# ## 为什么有这个文件
#
# 2026-11-23 用户裁定逐字：「生产环境需要和 github 的能力解耦」。
# 解耦的钥匙不是「再建一条 CI 腿」，而是**部署机本地凭证** `~/.aliyun/config.json` 的 `prod` profile：
# 部署机 `migao-deploy` 到生产实例（SWAS 轻量 `c0080f77…` / `8.136.134.44` / `cn-hangzhou`）
# **22 端口不通**（只对办公出口开放）、**443 通** ⇒ 运维通道只能是 OpenAPI 的 `run-command`（云助手），
# 不是 ssh、更不是 GitHub runner。
#
# 本文件只做三件**与业务无关**的事，两个生产脚本（`prod-inspect.sh` / `prod-release.sh`）共用：
#   ① 解析工具（`aliyun` CLI / `python3`）——缺 ⇒ 调用方退 **3**（判不了，不当 0 读）；
#   ② 发 `swas-open run-command` → 轮询 `describe-invocation-result`；
#   ③ 把回读的 base64 `Output` 解成文本。
# **不做**任何业务判据（闸门 / 自检 / 台账都在调用方）——避免「同一件事两把尺子」。
#
# ## 三条踩过的坑（写死在这里，调用方不用再记）
#
#   1. `--command-content` 是**明文**。给它 base64（很多人的第一反应）会让云端把整串当成**一个超长文件名**
#      ⇒ 远端 `exit 127`（`command not found`），看起来像「命令没跑」；
#   2. 回读的 `Output` 是 **base64**，要解码；
#   3. 返回结构有**两种形态**：`{"InvocationResult": {...}}` 与
#      `{"InvocationResults": {"InvocationResult": [{...}]}}` —— 两种都要认（实测不同 API 版本/插件版本会给不同形态）。
#
# ## 注入点（判据用；沿用 `SERVED_VERSION_*` / `BMINI_GOLIVE_*` 先例）
#
#   MIGAO_PROD_ALIYUN_BIN     aliyun CLI 路径（默认先 PATH、再 `$HOME/bin/aliyun`）
#   MIGAO_PROD_PYTHON_BIN     python3 路径（默认 PATH 里的 `python3`）
#   MIGAO_PROD_REGION         OpenAPI region（默认 `cn-hangzhou`）
#   MIGAO_PROD_BIZ_REGION     `--biz-region-id`（默认同 region）
#   MIGAO_PROD_INSTANCE_ID    目标实例（默认 = 生产实例；该 id 在 `.github/workflows/terminal-publish.yml` 已是公开值）
#   MIGAO_PROD_CRED_FILE      凭证文件（默认 `$HOME/.aliyun/config.json`；**只在判「凭证在不在」时读，不解析、不打印**）
#   MIGAO_PROD_POLL_ATTEMPTS  describe 轮询次数上限（默认 40）
#   MIGAO_PROD_POLL_INTERVAL  轮询间隔秒（默认 2）
#   MIGAO_PROD_REMOTE_TIMEOUT `run-command` 远端超时秒（默认 120）
#
# ## 三态
#
#   `prod_swas_init` → 0 可用 / 3 判不了（CLI 或 python3 缺、凭证不在）
#   `prod_swas_run`  → **远端退出码**（0/1/…）；通道层判不了（发不出去 / 拿不到结果）⇒ **3**
# ══════════════════════════════════════════════════════════════════════════════

PROD_REGION="${MIGAO_PROD_REGION:-cn-hangzhou}"
PROD_BIZ_REGION="${MIGAO_PROD_BIZ_REGION:-$PROD_REGION}"
PROD_INSTANCE_ID="${MIGAO_PROD_INSTANCE_ID:-c0080f77c8e24ad99f3eb3ebff753c18}"
PROD_CRED_FILE="${MIGAO_PROD_CRED_FILE:-$HOME/.aliyun/config.json}"
PROD_POLL_ATTEMPTS="${MIGAO_PROD_POLL_ATTEMPTS:-40}"
PROD_POLL_INTERVAL="${MIGAO_PROD_POLL_INTERVAL:-2}"
PROD_REMOTE_TIMEOUT="${MIGAO_PROD_REMOTE_TIMEOUT:-120}"

PROD_ALIYUN_BIN=""
PROD_PYTHON_BIN=""

# 通道层的「判不了」——统一文案，三态里的 `3` 不许当 `0` 读。
prod_undecidable() {
  printf '✗ 不可判定（3）：%s\n' "$*" >&2
  return 3
}

prod_swas_init() {
  local candidate
  if [ -n "${MIGAO_PROD_ALIYUN_BIN:-}" ]; then
    candidate="${MIGAO_PROD_ALIYUN_BIN}"
    [ -x "$candidate" ] || { prod_undecidable "MIGAO_PROD_ALIYUN_BIN=${candidate} 不可执行"; return 3; }
    PROD_ALIYUN_BIN="$candidate"
  else
    for candidate in "$(command -v aliyun 2>/dev/null || true)" "$HOME/bin/aliyun"; do
      [ -n "$candidate" ] && [ -x "$candidate" ] && { PROD_ALIYUN_BIN="$candidate"; break; }
    done
    [ -n "$PROD_ALIYUN_BIN" ] || {
      prod_undecidable "找不到 aliyun CLI（PATH 与 \$HOME/bin/aliyun 都没有）——
   部署机上它是 \`~/bin/aliyun\`（v3.5.4 arm64）+ 插件 \`aliyun-cli-swas-open\`。
   出口：装好后重跑，或显式给读数 MIGAO_PROD_ALIYUN_BIN=/abs/path/to/aliyun"
      return 3
    }
  fi

  if [ -n "${MIGAO_PROD_PYTHON_BIN:-}" ]; then
    PROD_PYTHON_BIN="${MIGAO_PROD_PYTHON_BIN}"
    [ -x "$PROD_PYTHON_BIN" ] || { prod_undecidable "MIGAO_PROD_PYTHON_BIN=${PROD_PYTHON_BIN} 不可执行"; return 3; }
  else
    PROD_PYTHON_BIN="$(command -v python3 2>/dev/null || true)"
    [ -n "$PROD_PYTHON_BIN" ] || {
      prod_undecidable "找不到 python3（本通道用它解析 OpenAPI 的 JSON 响应、解 base64）
   出口：装 python3，或显式给读数 MIGAO_PROD_PYTHON_BIN=/abs/path/to/python3"
      return 3
    }
  fi

  # 凭证**只判存在**，不解析、不打印、不入库（铁律：不得把任何口令写进仓库）。
  if [ ! -f "$PROD_CRED_FILE" ] && [ -z "${ALIBABA_CLOUD_ACCESS_KEY_ID:-}" ]; then
    prod_undecidable "没有凭证：既没有 ${PROD_CRED_FILE}，也没有 ALIBABA_CLOUD_ACCESS_KEY_ID ——
   本通道走部署机本地凭证（2026-11-23 用户裁定「生产环境和 github 解耦」的钥匙），
   不走 GitHub secret。出口：在部署机上 \`aliyun configure --profile prod\`（凭证只留在那台机器的 ~/.aliyun/config.json）"
    return 3
  fi
  return 0
}

# 从 `run-command` 的 JSON 里取 InvokeId（取不到 ⇒ 3）
prod_swas_invoke_id() {
  "$PROD_PYTHON_BIN" -c '
import json, sys
raw = sys.stdin.read()
try:
    data = json.loads(raw)
except Exception as exc:  # 非 JSON（CLI 打的是人读错误）⇒ 判不了
    sys.stderr.write("响应不是 JSON（%s）：%s\n" % (exc, raw[:400]))
    sys.exit(3)
invoke_id = data.get("InvokeId") or data.get("InvokeID") or ""
if not invoke_id:
    sys.stderr.write("响应里没有 InvokeId：%s\n" % raw[:400])
    sys.exit(3)
sys.stdout.write(invoke_id + "\n")
'
}

# 把 describe 的 JSON 压成 "状态<TAB>退出码<TAB>Output(base64)"
prod_swas_result() {
  "$PROD_PYTHON_BIN" -c '
import json, sys
raw = sys.stdin.read()
try:
    data = json.loads(raw)
except Exception as exc:
    sys.stderr.write("describe 响应不是 JSON（%s）：%s\n" % (exc, raw[:400]))
    sys.exit(3)
result = data.get("InvocationResult") or {}
if not result:
    # 形态二：InvocationResults.InvocationResult = {...} 或 [...]
    holder = data.get("InvocationResults") or {}
    items = holder.get("InvocationResult") or []
    if isinstance(items, dict):
        items = [items]
    result = items[0] if items else {}
status = result.get("InvokeStatus") or result.get("Status") or ""
exit_code = result.get("ExitCode")
exit_code = "" if exit_code is None else str(exit_code)
sys.stdout.write("%s\t%s\t%s\n" % (status, exit_code, result.get("Output") or ""))
'
}

# 远端执行一段**明文**脚本：stdout = 远端输出（已解 base64）；返回值 = 远端退出码，通道判不了 ⇒ 3
prod_swas_run() {
  local command_content="$1" timeout="${2:-$PROD_REMOTE_TIMEOUT}" name="${3:-migao-prod}"
  local out invoke_id attempt row status exit_code payload decoded

  out=$("$PROD_ALIYUN_BIN" swas-open run-command \
        --region "$PROD_REGION" --biz-region-id "$PROD_BIZ_REGION" \
        --instance-id "$PROD_INSTANCE_ID" --name "$name" --type RunShellScript \
        --command-content "$command_content" --timeout "$timeout" 2>&1)
  invoke_id=$(printf '%s' "$out" | prod_swas_invoke_id) || {
    prod_undecidable "run-command 没给出 InvokeId（通道没通：凭证 / region / 实例 / 插件）——
   原始响应（截断）：
$(printf '%s' "$out" | head -c 400)"
    return 3
  }

  attempt=0
  while :; do
    out=$("$PROD_ALIYUN_BIN" swas-open describe-invocation-result \
          --region "$PROD_REGION" --biz-region-id "$PROD_BIZ_REGION" \
          --instance-id "$PROD_INSTANCE_ID" --invoke-id "$invoke_id" 2>&1) || {
      prod_undecidable "describe-invocation-result 失败（invoke-id=${invoke_id}）：
$(printf '%s' "$out" | head -c 400)"
      return 3
    }
    row=$(printf '%s' "$out" | prod_swas_result) || return 3
    status=$(printf '%s' "$row" | cut -f1)
    exit_code=$(printf '%s' "$row" | cut -f2)
    payload=$(printf '%s' "$row" | cut -f3)
    case "$status" in
      Success|Failed|Stopped|Timeout|Cancelled) break ;;
    esac
    attempt=$((attempt + 1))
    if [ "$attempt" -ge "$PROD_POLL_ATTEMPTS" ]; then
      prod_undecidable "等不到执行结果（invoke-id=${invoke_id}，状态=${status:-未知}，轮询 ${PROD_POLL_ATTEMPTS} 次）——
   `3` 不当 `0` 读：远端可能仍在跑，重跑一次本命令看结果"
      return 3
    fi
    sleep "$PROD_POLL_INTERVAL"
  done

  decoded=$(printf '%s' "$payload" | "$PROD_PYTHON_BIN" -c '
import base64, sys
raw = sys.stdin.read().strip()
if not raw:
    sys.exit(0)
sys.stdout.write(base64.b64decode(raw).decode("utf-8", "replace"))
') || { prod_undecidable "回读的 Output 解不出 base64（invoke-id=${invoke_id}）"; return 3; }

  printf '%s' "$decoded"
  [ -n "$exit_code" ] || exit_code=0
  case "$status" in
    Success) return "$exit_code" ;;
    *) return "$exit_code" ;;
  esac
}
