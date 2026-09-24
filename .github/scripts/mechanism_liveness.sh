#!/usr/bin/env bash
# 存活读数发射器 —— issue #5326 判据 1 / 4 的**共享实现**（单一真值源；勿在 workflow 里另写一份）。
#
# ── 病根（本仓实测两例，各藏约 40 小时）──────────────────────────────────────
# 机制**停摆或瞎了**，但**没有任何读数会因此改变** ⇒ 只能靠人偶然发现：
#   · #5264：台账 `approve` 因分页缺陷**一次都没发出去**，而机制每次都"成功退出"并打印
#     **与事实相反**的 ✅ 读数；
#   · #5307：台账分支 required 测试恒红，**没有任何消费面**看得到。
# ⇒ 本发射器只解决一件事：**「我没做事」与「我没跑」必须长得不一样**。
#
# ── 读数语法（固定字段，`scripts/mechanism_liveness.py` 按同一语法解析）────────
#   ::notice::MECHANISM-LIVENESS mech=<id> run=<run_id> rc=<n> seen=<n|unknown> acted=<n|unknown> why=<单行文本>
#     · rc==0 ⇒ `::notice::`；rc!=0 ⇒ `::warning::`（**不许把失败报成 notice** —— #5264 的形态就是
#       "读数与事实相反"）。
#     · `run=` 是**归属绑定**：读数是**这一次 run** 的。看门人据此判「新鲜」，**不用挂钟时长**
#       （时长受 runner 负载污染，判据 4）。
#     · `seen` / `acted` 是**计数类**读数（本轮看了多少 / 改了多少）。取不到 ⇒ `unknown`
#       —— **不得编造**（§19.1）；取不到这件事本身在该机制的登记项里留痕（判据 5）。
#
# ── 两种用法 ────────────────────────────────────────────────────────────────
# ① 机制体（可选，**一行**，纯追加）：把本轮的计数交出来
#      source .github/scripts/mechanism_liveness.sh
#      mechanism_liveness_declare --seen 12 --acted 3 --why "补偿关闭 3 个 issue"
#    （不写也能跑：读数照出，`seen`/`acted` = `unknown`、`why` = `no-declaration` —— 即
#      「跑了但没说自己做了什么」，它与「**没跑**」（**没有这一行读数**）在形态上不同。）
# ② job 末尾**必加**的读数步（`if: always()`，见各 workflow）：
#      bash .github/scripts/mechanism_liveness.sh emit <id> --outcome "${OUTCOME}"
#
# ── 边界（照实登记）────────────────────────────────────────────────────────
#  · 本发射器只证明「**跑到读数点了、且 rc 是多少**」。它**不**验证机制本身的正确性
#    （#5264 里那句与事实相反的 ✅ 是机制**自己**打出来的）⇒ 机制的正确性仍归各自的判据。
#  · 注解会被 GitHub 限流（每 step 10 条 / 每 job 50 条）。读数步**单独一个 step** ⇒
#    本行必占该 step 的注解额度（见 `tests/unit_ci_workflows/test_mechanism_liveness.py`
#    的 `test_reading_step_is_its_own_step`）。
set -uo pipefail

MECHANISM_LIVENESS_MARKER="MECHANISM-LIVENESS"

# 处置文件：**跨 step 存活**（`$RUNNER_TEMP` 在同一个 job 内持久）。追加式 ⇒ 无读改写竞态，
# 读取端取**每个键的最后一次**声明。缺省落 `/tmp`（本机复跑用）。
mechanism_liveness_disposition_file() {
  printf '%s\n' "${MECHANISM_LIVENESS_DISPOSITION:-${RUNNER_TEMP:-/tmp}/mechanism-liveness.disposition}"
}

# 单行化 + 注解转义（GitHub annotation 用 `%25`/`%0A` 转义；裸换行会把 `::notice::` 截断）。
mechanism_liveness_sanitize() {
  printf '%s' "${1:-}" | tr -d '\r' | tr '\n' ' ' | sed 's/%/%25/g' | cut -c1-200
}

# 机制体调用它交出本轮读数（可多次调用，后写的键覆盖先写的）。
mechanism_liveness_declare() {
  local seen="" acted="" why="" f
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --seen)  seen="${2:-}";  shift 2 ;;
      --acted) acted="${2:-}"; shift 2 ;;
      --why)   why="${2:-}";   shift 2 ;;
      *) shift ;;
    esac
  done
  f="$(mechanism_liveness_disposition_file)"
  { [ -n "$seen" ]  && printf 'seen=%s\n'  "$(mechanism_liveness_sanitize "$seen")"
    [ -n "$acted" ] && printf 'acted=%s\n' "$(mechanism_liveness_sanitize "$acted")"
    [ -n "$why" ]   && printf 'why=%s\n'   "$(mechanism_liveness_sanitize "$why")"
  } >> "$f" 2>/dev/null || true
}

mechanism_liveness_disposition_get() {
  local key="$1" f
  f="$(mechanism_liveness_disposition_file)"
  [ -f "$f" ] || return 0
  grep -E "^${key}=" "$f" 2>/dev/null | tail -1 | cut -d= -f2- || true
}

# `--outcome success|failure|cancelled` ⇒ rc（显式 `--rc` 优先）。
mechanism_liveness_rc_of_outcome() {
  case "${1:-}" in
    success)   printf '0' ;;
    failure)   printf '1' ;;
    cancelled) printf '130' ;;
    *)         printf '?' ;;
  esac
}

# 发射**恰好一行**读数。返回值 = 机制本身的 rc（发射行为**绝不**改变机制结论）。
mechanism_liveness_emit() {
  local id="${1:-unknown}"; shift || true
  local rc="" outcome="" seen="" acted="" why="" level line
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --rc)      rc="${2:-}";      shift 2 ;;
      --outcome) outcome="${2:-}"; shift 2 ;;
      --seen)    seen="${2:-}";    shift 2 ;;
      --acted)   acted="${2:-}";   shift 2 ;;
      --why)     why="${2:-}";     shift 2 ;;
      *) shift ;;
    esac
  done
  [ -n "$rc" ] || rc="$(mechanism_liveness_rc_of_outcome "$outcome")"
  [ -n "$seen" ]  || seen="$(mechanism_liveness_disposition_get seen)"
  [ -n "$acted" ] || acted="$(mechanism_liveness_disposition_get acted)"
  [ -n "$why" ]   || why="$(mechanism_liveness_disposition_get why)"
  if [ -z "$seen" ] && [ -z "$acted" ]; then why="${why:-no-declaration}"; fi
  seen="${seen:-unknown}"; acted="${acted:-unknown}"

  if [ "$rc" = "0" ]; then level="notice"; else level="warning"; fi
  line="::${level}::${MECHANISM_LIVENESS_MARKER} mech=${id} run=${GITHUB_RUN_ID:-local} rc=${rc} seen=${seen} acted=${acted} why=$(mechanism_liveness_sanitize "${why:-（未声明原因）}")"
  printf '%s\n' "$line"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    printf '%s\n' "$line" >> "$GITHUB_STEP_SUMMARY" 2>/dev/null || true
  fi
  return 0
}

# ── CLI（`bash mechanism_liveness.sh <子命令> …`）────────────────────────────
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  case "${1:-}" in
    emit)    shift; mechanism_liveness_emit "$@"; exit 0 ;;
    declare) shift; mechanism_liveness_declare "$@"; exit 0 ;;
    *) echo "用法: mechanism_liveness.sh {emit <id> [--rc N|--outcome S] [--seen N] [--acted N] [--why T] | declare [--seen N] [--acted N] [--why T]}" >&2; exit 2 ;;
  esac
fi