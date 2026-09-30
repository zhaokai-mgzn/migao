#!/usr/bin/env bash
# =============================================================================
# machine-heavy-lock.sh —— **机器级**重活并发准入锁（issue #5814）
#
# ## 治的形态（2026-09-30 14:24 CST 现场，不是推断）
#
# 三份**同样的**全量 `tests/unit_ci_workflows` 套件并发跑在 8 核开发机上：
#   ① 自托管 runner 正在执行的 CI job（现已停用/卸载）② 本会话一个 subagent 的 `./verify-all.sh gate`
#   ③ 另一个会话 subagent 的 `./verify-all.sh gate`（`migao-wt/orders-new-batch5`）；
# 外加 6 个 `node (vitest)` **孤儿**（PPID=1）从 13:56 烧到 14:24（28 分钟纯浪费，父进程是被
# `cancelled` 的 CI job，worker 未被回收）；`load average` 一度 45.44，处置后 2.87。
# ⇒ 类级病 = **同一台机器上的重活没有并发准入**（3 份里 2 份是 agent 会话造成的，与 runner 无关）。
#
# ## 为什么锁文件必须是**机器级共享路径**
#
# 漏掉的正是**跨会话**那一路：锁若放在各自 worktree（`.sessions/<branch>.lock` 那种形态），
# 两个会话各持各的锁、各跑各的全量套件 ⇒ 「有锁」与「没锁」在机器上完全一样。
# 故默认锁文件在 `$HOME/.migao-heavy.lock`（**不在任何 worktree 内**，`dev-worktree.sh rm/prune`
# 的清理半径碰不到它）。
#
# ## 为什么 `acquire` 顺手回收「孤儿」是**安全**的（这条理由是本脚本的取舍依据）
#
# 判定面 = ① `PPID == 1`（父进程已不存在 ⇒ 它**不可能是任何人正在等的那个结果**：发起它的
# 进程/会话已经退出了）② 进程名命中测试运行器族（node / vitest / jest / playwright / pytest /
# python -m pytest）③ **命令行里至少有一个 token 落在已知工作根之下**（`_work` / `migao-wt` /
# 主工作区）—— 三条同时成立才杀。
# ⛔ **绝不按名字裸杀**：单靠 ①+② 会命中「用户自己开的 node 服务 / 别的仓库的测试」，
#    故 ③ 用**路径前缀**把射程收到最小（这就是「只杀 CI 工作区 / worktree 下的」的落码形态）。
# ⛔ 本脚本**不杀**自己的祖先进程链（`_ancestors_of_self`）——避免脚本把自己的父 shell 干掉。
#
# ## 值守面（铁律 10）
#
# **没有常驻告警**（不新增守护进程 / launchd agent，超出本包范围）。值守面 = ① `acquire` 的
# **拒绝行为**（拿不到锁就出声拒跑，不是静默跳过）② `status` 的值守读数。**拒绝本身就是机制**，
# 不是「提醒你记得去看」。
# 🔻 如实登记的缺口：本脚本**盖不到**「有人绕过入口直接 `pytest tests/unit_ci_workflows`」
#    （那一路没有锁）—— 承载体 = 研发模式纪律（`.agent-presets/migao`）＋ `verify-all.sh` 的
#    唯一入口，**不是**任何机械拦截。
#
# ## 用法
#
#   ./scripts/machine-heavy-lock.sh status            # 只读：锁持有者 / load / PPID=1 孤儿 / top CPU
#   ./scripts/machine-heavy-lock.sh acquire <名字>     # 拿锁（拿不到 ⇒ 非零退出 + 打印谁在跑 + kill 命令）
#   ./scripts/machine-heavy-lock.sh release           # 释放（只释放**自己**持有的那份）
#
# 调用方接线范式（`verify-all.sh` 的 `gate` 档就是这么做的）：
#
#   ./scripts/machine-heavy-lock.sh acquire "verify-all.sh gate" || exit $?
#   trap './scripts/machine-heavy-lock.sh release >/dev/null 2>&1 || true' EXIT
#
# 环境变量（判据用来把锁放到临时目录，**不改默认路径**）：
#   MIGAO_HEAVY_LOCK_FILE  锁文件路径（默认 `$HOME/.migao-heavy.lock`）
#   MIGAO_HEAVY_ROOTS      已知工作根（冒号分隔；默认见 `_default_roots`）
#
# 退出码：0 = 成功；1 = 锁被活的持有者占着（**拒绝**：这是准入判定，不是脚本错误）；
#         2 = 用法错误；3 = 无法判定（锁机制不可用/状态不一致 —— fail-closed，**不得当 0 读**）。
# =============================================================================
set -uo pipefail

SELF="$0"
LOCK_FILE="${MIGAO_HEAVY_LOCK_FILE:-$HOME/.migao-heavy.lock}"
#: `acquire` 成功且**确实由本进程持有**时为 1（dispatch 据此决定 EXIT 时是否释放）。
LOCK_HELD=0
#: `acquire` 判定「拿不到锁」时为 1（dispatch 据此用退出码 1 退出 —— 与脚本错误 2/3 分开）。
LOCK_REFUSED=0

# ── 过程视图（**单一实现**：一条 `ps` 拿全量，供孤儿回收与 status 共用）────────────────
# 为什么是 `ps -o pid=,ppid=,command=`：`pid=`/`ppid=` 的数字**不带表头**、`command=` 是**完整
# 命令行**（进程名列 `comm` 在 macOS 上会被截断 / 变成 `(node)` 形态 ⇒ 不能用来判族）。
_process_table() {
  ps -A -o pid=,ppid=,command= 2>/dev/null || true
}

_pid_is_alive() {
  local pid="${1:-}"
  case "$pid" in
    ''|*[!0-9]*) return 1 ;;
  esac
  kill -0 "$pid" 2>/dev/null
}

# 进程名族：从命令行**任意** token 取 basename（`node` / `node (vitest)` / `/…/pytest` 全覆盖）。
_runner_of_command() {
  local tok base
  # shellcheck disable=SC2086  # 词分割是**有意**的：命令行要按空白切成 token
  for tok in $1; do
    base="${tok##*/}"
    case "$base" in
      node|nodejs|vitest|jest|playwright|pytest) printf '%s\n' "$base"; return 0 ;;
      python|python2|python3|python3.*|python3.1[0-9])
        case "$1" in *pytest*) printf '%s\n' 'pytest'; return 0 ;; esac ;;
    esac
  done
  return 1
}

_default_roots() {
  # ⚠️ 改动这里 = 改**射程**：`MIGAO_HEAVY_ROOTS` 覆盖时（判据用）只认覆盖值。
  # 观测到的两类载体：① 自托管 runner 的工作区 `$HOME/actions-runner/_work/<repo>/<repo>`
  # ② 主工作区与 `migao-wt/*`（worktree 就把它们都覆盖了）。`/tmp` 只在**测试**里被显式覆盖。
  printf '%s\n' "$HOME/actions-runner/_work" "$HOME/ai native"
}

# 命令行里是否有 token 落在已知工作根之下（**路径前缀**判定 —— 射程的机械边界）。
_command_in_roots() {
  local roots="${MIGAO_HEAVY_ROOTS:-$(_default_roots)}" cmd="$1" tok root
  # shellcheck disable=SC2086
  for tok in $cmd; do
    while IFS= read -r root; do
      [ -n "$root" ] || continue
      root="${root%/}"
      case "$tok" in "$root"/*) return 0 ;; esac
    done <<EOF
$roots
EOF
  done
  return 1
}

# 祖先链（含自身）：**绝不**拿它当回收目标。
_ancestors_of_self() {
  local pid="$$" table ppid
  table="$(_process_table)"
  printf '%s\n' "$pid"
  while :; do
    ppid="$(printf '%s\n' "$table" | awk -v p="$pid" '$1 == p { print $2; exit }')"
    [ -n "$ppid" ] || break
    case "$ppid" in 0|1) break ;; esac
    printf '%s\n' "$ppid"
    pid="$ppid"
  done
}

# 孤儿候选（PPID=1 + 命中测试运行器族 + 路径落在已知工作根下 + 不是自己的祖先）。
# ⚠️ 输出形态 = **TAB 分隔**：`pid<TAB>runner<TAB>command`。调用方**必须**用 `cut -f1/-f2/-f3` 取值，
#    **不要**用 `while read -r a b c` + `IFS=` 前缀 —— 那个写法在函数体内实测会把整行塞进第一个变量
#    （`kill -TERM "61298 node node -e setInterval…"` ⇒ 报「已退出或无权」，孤儿照旧活着；
#    根因 = 既有 IFS 咬掉前缀赋值）。本脚本初版就是这个缺陷，判据把它抓出来了。
_orphan_candidates() {
  local ancestors table pid ppid cmd runner
  ancestors="$(_ancestors_of_self)"
  table="$(_process_table)"
  printf '%s\n' "$table" | while read -r pid ppid cmd; do
    [ -n "${cmd:-}" ] || continue
    [ "${ppid:-}" = "1" ] || continue
    case "$pid" in ''|*[!0-9]*) continue ;; esac
    printf '%s\n' "$ancestors" | grep -qx -- "$pid" && continue
    runner="$(_runner_of_command "$cmd")" || continue
    _command_in_roots "$cmd" || continue
    printf '%s\t%s\t%s\n' "$pid" "$runner" "$cmd"
  done
}

# 执行回收：**打印杀了什么**（机械动作不靠人记得；回收到 0 个也要出声 = §23 G6）。
reap_orphans() {
  local rows pid runner cmd n=0
  rows="$(_orphan_candidates)"
  if [ -z "$rows" ]; then
    echo "  孤儿回收：无（判定 = PPID=1 ∧ 命中测试运行器族 ∧ 命令行落在已知工作根下）"
    return 0
  fi
  while IFS= read -r row; do
    [ -n "$row" ] || continue
    pid="$(printf '%s' "$row" | cut -f1)"
    runner="$(printf '%s' "$row" | cut -f2)"
    cmd="$(printf '%s' "$row" | cut -f3)"
    case "$pid" in ''|*[!0-9]*) echo "  ⚠️  候选行形态异常，跳过（fail-closed，不猜 pid）：$row"; continue ;; esac
    if kill -TERM "$pid" 2>/dev/null; then
      echo "  ♻️  回收孤儿：pid=${pid} 程序=${runner} 命令=${cmd:0:120}"
      n=$((n + 1))
    else
      echo "  ⚠️  回收孤儿失败（pid=${pid} 已退出或无权）：${cmd:0:120}"
    fi
  done <<EOF
$rows
EOF
  echo "  孤儿回收：共 $n 个（父进程已退出 ⇒ 不可能是任何人正在等的结果；射程 = 已知工作根前缀）"
  return 0
}

# ── 锁文件读写（**单一实现**）─────────────────────────────────────────────────
# 锁文件格式（4 行，`key=value`；判据现取这五项的**存在性**）：
#   name=…  pid=…  started_at=…（**epoch 秒**，唯一取值形态）  worktree=…  cwd=…
_lock_write() {
  local name="$1" pid="$2" cwd="$3" worktree="$4"
  {
    printf 'name=%s\n' "$name"
    printf 'pid=%s\n' "$pid"
    printf 'started_at=%s\n' "$(date +%s)"
    printf 'worktree=%s\n' "$worktree"
    printf 'cwd=%s\n' "$cwd"
  } > "$LOCK_FILE.tmp.$$" && mv -f "$LOCK_FILE.tmp.$$" "$LOCK_FILE"
}

_lock_field() {
  sed -n "s/^$2=//p" "$1" 2>/dev/null | head -n 1
}

# 人类可读的「已跑多久」：由 `started_at` 的 epoch 秒现算（不依赖锁文件里的可读串）。
_elapsed_of() {
  local started="$1"
  # started_at 里只放 epoch 秒（上面 _lock_write 的形态）；非纯数字（旧格式 / 手改）⇒ 「未知」，
  # 不猜 —— 「已跑多久」是给人看的读数，不该由它决定任何判定。
  case "$started" in ''|*[!0-9]*) printf '未知'; return 0 ;; esac
  local now; now="$(date +%s)"
  local d=$(( now - started ))
  [ "$d" -lt 0 ] && d=0
  printf '%dh%02dm%02ds' $(( d / 3600 )) $(( (d % 3600) / 60 )) $(( d % 60 ))
}

_load_avg() {
  uptime 2>/dev/null | sed -n 's/.*load average[s]*: *//p' || true
}

_top_cpu() {
  ps -A -o %cpu= -o pid= -o command= 2>/dev/null \
    | sort -k1,1 -nr 2>/dev/null | head -n "${1:-5}" || true
}

# 锁状态三态：`free` / `stale` / `held`。
_lock_state() {
  if [ ! -f "$LOCK_FILE" ]; then
    printf 'free\n'
    return 0
  fi
  local pid; pid="$(_lock_field "$LOCK_FILE" pid)"
  if _pid_is_alive "$pid"; then
    printf 'held\n'
  else
    printf 'stale\n'
  fi
}

# **拿不到锁**时的人类可读报文：谁在跑 + 可复制的一条 kill 命令（§23 G3 的可行动出口）。
_report_holder() {
  local name pid started worktree cwd
  name="$(_lock_field "$LOCK_FILE" name)"
  pid="$(_lock_field "$LOCK_FILE" pid)"
  started="$(_lock_field "$LOCK_FILE" started_at)"
  worktree="$(_lock_field "$LOCK_FILE" worktree)"
  cwd="$(_lock_field "$LOCK_FILE" cwd)"
  echo "⛔ 机器级重活锁被占用（${LOCK_FILE}）—— 本进程**拒绝启动**重活（不静默跳过，也不记成通过）"
  echo "   持有者 名字     : ${name:-未知}"
  echo "   持有者 PID      : ${pid:-未知}（活的）"
  echo "   持有者 已跑多久 : $(_elapsed_of "$started")（started_at=${started:-未知}）"
  echo "   持有者 worktree : ${worktree:-未知}"
  echo "   持有者 cwd      : ${cwd:-未知}"
  echo "   怎么办（二选一）："
  echo "     ① 等它跑完（重活串行是本锁的全部意义）：./scripts/machine-heavy-lock.sh status"
  echo "     ② 确认它确实卡死了再杀（**先看上面的 worktree/cwd 是不是你自己的会话**）："
  echo "        kill ${pid:-<pid>}"
}

# ── 子命令 ───────────────────────────────────────────────────────────────────
cmd_acquire() {
  local name="${1:-}"
  if [ -z "$name" ]; then
    echo "用法: $0 acquire <名字>（例：'verify-all.sh gate'）" >&2
    return 2
  fi
  # ── ① 先回收孤儿（机械动作：不靠人记得；**先于**拿锁，免得锁被孤儿拖着的负载误判）──
  reap_orphans

  # ── ② 准入判定 ────────────────────────────────────────────────────────────
  local state; state="$(_lock_state)"
  case "$state" in
    held)
      _report_holder
      LOCK_REFUSED=1
      return 1
      ;;
    free)
      echo "  ✅ 机器级重活锁空闲（${LOCK_FILE}）"
      ;;
    stale)
      local old_pid; old_pid="$(_lock_field "$LOCK_FILE" pid)"
      echo "  ♻️  回收**陈旧**锁：原持有者 pid=${old_pid:-未知} 已不存在（进程表里查不到）"
      rm -f "$LOCK_FILE"
      ;;
  esac

  # ── ③ 记录持有者（pid = 调用方的 shell：`$PPID`；cwd/worktree 现场取）────────
  # 取调用方 PID 而不是本子进程的 `$$`：本脚本由调用方以 `$(…)` / 独立进程方式唤起，
  # 记录 `$$` 会在脚本一退出就变成陈旧锁。`$PPID` = 真正在做重活的那个 shell。
  local holder_pid="${PPID:-$$}"
  local cwd worktree
  cwd="$(pwd)"
  worktree="$(git rev-parse --show-toplevel 2>/dev/null || printf '%s' "$cwd")"
  if ! _lock_write "$name" "$holder_pid" "$cwd" "$worktree"; then
    echo "❌ 无法写入锁文件 $LOCK_FILE —— 无法判定（fail-closed，不得当成功）" >&2
    return 3
  fi
  LOCK_HELD=1
  echo "  🔒 已获取机器级重活锁：name=$name pid=$holder_pid worktree=$worktree"
  echo "     释放：$SELF release（或调用方以 trap … EXIT 兜住异常退出）"
  return 0
}

cmd_release() {
  local state; state="$(_lock_state)"
  if [ "$state" = free ]; then
    echo "  ℹ️  无锁可释放（$LOCK_FILE 不存在）"
    return 0
  fi
  local pid; pid="$(_lock_field "$LOCK_FILE" pid)"
  if [ "$pid" != "${PPID:-}" ] && [ "$pid" != "${MIGAO_HEAVY_OWNER_PID:-}" ]; then
    echo "  ⚠️  锁由 pid=${pid} 持有，本进程（pid=${PPID:-?}）**不是**持有者 —— 不释放别人的锁"
    return 1
  fi
  rm -f "$LOCK_FILE"
  echo "  🔓 已释放机器级重活锁（pid=${pid}）"
  return 0
}

cmd_status() {
  echo "── 机器级重活锁 status（只读：不拿锁、不杀任何进程）──"
  echo "锁文件      : $LOCK_FILE"
  local state; state="$(_lock_state)"
  case "$state" in
    free)
      echo "当前持有者  : 无（锁文件不存在）"
      ;;
    stale)
      echo "当前持有者  : 【陈旧】pid=$(_lock_field "$LOCK_FILE" pid)已不存在 —— 下一次 acquire 会回收它"
      ;;
    held)
      local hname
      hname="$(_lock_field "$LOCK_FILE" name)"
      echo "当前持有者  : $hname"
      ;;
  esac
  if [ "$state" = held ]; then
    local pid started
    pid="$(_lock_field "$LOCK_FILE" pid)"
    started="$(_lock_field "$LOCK_FILE" started_at)"
    echo "  pid         : $pid"
    echo "  已跑多久    : $(_elapsed_of "$started")"
    echo "  worktree    : $(_lock_field "$LOCK_FILE" worktree)"
    echo "  cwd         : $(_lock_field "$LOCK_FILE" cwd)"
  fi
  echo "load average: $(_load_avg)"
  local rows; rows="$(_orphan_candidates)"
  if [ -z "$rows" ]; then
    echo "PPID=1 孤儿 : 0 个（判定 = 测试运行器族 ∧ 命令行落在已知工作根下）"
  else
    echo "PPID=1 孤儿 : 发现（**只报告，不动作** —— 回收动作只在 acquire 时做）"
    while IFS= read -r row; do
      [ -n "$row" ] || continue
      pid="$(printf '%s' "$row" | cut -f1)"
      runner="$(printf '%s' "$row" | cut -f2)"
      cmd="$(printf '%s' "$row" | cut -f3)"
      case "$pid" in ''|*[!0-9]*) continue ;; esac
      echo "   pid=${pid} 程序=${runner} 命令=${cmd:0:120}"
      echo "     可复制：kill ${pid}"
    done <<EOF
$rows
EOF
  fi
  echo "top CPU（前 5，%CPU + pid + 命令）:"
  _top_cpu 5 | sed 's/^/   /'
  return 0
}

# ── dispatch（is-callable 形态：`MIGAO_HEAVY_LIB=1` 时只装函数，供判据 source）──────
# 判据需要直接调 `_runner_of_command` / `_command_in_roots` 这类纯函数（零子进程、零时钟），
# 故留一个「只装不上膛」的开关；默认（不带该变量）行为一字不变。
if [ "${MIGAO_HEAVY_LIB:-}" = "1" ]; then
  return 0 2>/dev/null || true
else
  case "${1:-}" in
    acquire|release|status)
      sub="$1"; shift
      "cmd_${sub}" "$@"
      # ⚠️ **不在本进程退出时自动删锁**（`LOCK_HELD` 只作读数）：本脚本的 `$$` 与调用方的
      # `$PPID` 不是同一个进程，自动删会把「调用方还在跑」的活锁误删成空闲 ⇒ 准入当场失效。
      # 释放只有两条路：① 调用方显式 `release`（或 `trap … EXIT`）② 下一次 `acquire` 发现
      # 持有者 PID 已死（陈旧锁）时回收。调用方忘释放的最坏后果 = 一次「陈旧锁」，
      # 而**不是**「两把重活同时在跑」——失效方向选安全的那一边。
      exit "$?"
      ;;
    *)
      echo "用法: $0 {status|acquire <名字>|release}" >&2
      exit 2
      ;;
  esac
fi
