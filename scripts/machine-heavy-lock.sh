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
# 🔻 缺口①已收口（2026-10-02，issue #6019）：**直连整目录也拿锁** —— 由 `tests/unit_ci_workflows/conftest.py`
#    的套件自带准入承担（`pytest_collection` 里 acquire / `pytest_sessionfinish` 里 release），
#    判据 = `test_suite_self_lock.py`。⇒ 本脚本的射程现在是**直连与入口两条路**。
# 🔻 缺口②（**仍然是缺口**，照实登记）：本脚本盖不到「**入口打不开**」这一类 —— 即「在**不该**跑
#    全量的工作区里跑」（子包 worktree）。那一路由 `verify-all.sh` 的**角色守卫**承担
#    （2026-10-03，issue #6084；判据 `test_package_heavy_entry_ban.py`），**不是**本脚本。
#    承载体也不再是「研发模式纪律」：🔴 S4 / issue #6020 起研发模式住在**预设仓**
#    `zhaokai-mgzn/migao-agent-presets`，业务仓已无 `.agent-presets/**`。
#
# ## 用法
#
#   ./scripts/machine-heavy-lock.sh status            # 只读：锁持有者 / load / PPID=1 孤儿 / top CPU
#   ./scripts/machine-heavy-lock.sh acquire <名字>              # 拿锁（拿不到 ⇒ **立即**非零退出 + 打印谁在跑 + kill 命令）
#   ./scripts/machine-heavy-lock.sh acquire <名字> --wait <秒>   # 拿锁（拿不到 ⇒ 内部轮询至多 <秒>；超时仍非零退出 + 具名）
#   ./scripts/machine-heavy-lock.sh release                    # 释放（只释放**自己**持有的那份）
#   ./scripts/machine-heavy-lock.sh stats [--since <窗口>] [--json]  # 只读：准入/溢出**台账**读数（离线；issue #6091）
#
# ## 拿不到锁时怎么办（**重试约定**，2026-10-01 补，issue #5863）
#
# `acquire` 的**默认语义是立即拒绝**（`held` ⇒ `return 1`），它**不排队**。于是「谁重试得勤谁拿到」——
# 实测（2026-10-01 11:04~11:38 +08）：一个以 **30s 固定间隔**重试的客户端探测 **56 次 / 约 34 分钟，一次未中**；
# 同期锁被 3 个持有者轮转（pid 48499 / 29770 / 75210），60s 采样显示**释放瞬间总被当场接走**。
# ⇒ 两条**等价**的合规做法（选一条，别自己发明第三套）：
#   ① **`--wait <秒>`**（推荐）：由本脚本内部轮询，间隔 **2~5 秒随机抖动**，客户端只调用一次；
#   ② 客户端自己循环 ⇒ 间隔**必须短且带抖动**（`sleep $((2 + RANDOM % 4))`）；
#      ⛔ **不要**用固定长间隔 —— 在多客户端竞争下那是**系统性饿死**（见上实测）。
#
# 调用方接线范式（`verify-all.sh` 的 `gate` 档就是这么做的）：
#
#   ./scripts/machine-heavy-lock.sh acquire "verify-all.sh gate" || exit $?
#   trap './scripts/machine-heavy-lock.sh release >/dev/null 2>&1 || true' EXIT
#
# 环境变量（判据用来把锁放到临时目录，**不改默认路径**）：
#   MIGAO_HEAVY_LOCK_FILE  锁文件路径（默认 `$HOME/.migao-heavy.lock`）
#   MIGAO_HEAVY_ROOTS      已知工作根（冒号分隔；默认见 `_default_roots`）
#   MIGAO_HEAVY_OWNER_PID  `release` 的显式持有者逃生口（默认比对 `$PPID` —— 也就是 `acquire` 时记下的那个）
#   MIGAO_HEAVY_LEDGER     准入/溢出台账路径（默认 `$HOME/.migao-heavy-lock-ledger.jsonl`）
#
# 退出码：0 = 成功；1 = 锁被活的持有者占着（**拒绝**：这是准入判定，不是脚本错误）；
#         2 = 用法错误；3 = 无法判定（锁机制不可用/状态不一致 —— fail-closed，**不得当 0 读**）。
#
# =============================================================================
# 准入/溢出**台账**（measurement only，issue #6091；蓝图 P2 的「测量那一半」）
#
# ## 治什么
#
# 蓝图 `docs/wiki/Dev-Mode-Balance.md` §4 行 4/5 + §10 的 P2 行：**分档准入**与
# **「准入被拒 ⇒ 改走 CI」计数**都还是 ⏳。而在分档准入落地之前，本机是「并发 = 1 的重活单槽」——
# 重活要么拿到锁、要么**安静排队**（实测有排队 45 分钟的先例），**没有任何台账**回答
# 「到底溢出多少次、每次都等多久、是谁在抢」。没有这份读数，分档容量与批次粒度都只能凭感觉。
# ⇒ 本块把**事实**记下来，并把「槽满」变成**出声**。**它不改任何准入判定**（见下「旁路」）。
#
# ## 五类 kind（判据逐条钉住；语义表也在 `docs/wiki/Development.md`）
#
#   acquired_nowait       立即拿到（本次调用**一次都没等**）⇒ wait_seconds == 0
#   acquired_after_wait   **排队等待后**拿到（`--wait` 真排上过队）⇒ wait_seconds > 0
#   refused_busy          **溢出 / 准入被拒**：默认语义下第一次尝试就被活的持有者挡回
#   acquire_timeout       溢出（等待档）：`--wait <n>` 等满上限仍被挡回（真溢出且**白等**了墙钟）
#   stale_reaped          陈旧锁回收（持有者 PID 已死 —— 它是准入判定的一部分，值得留读数）
#   released              释放（记持有者，供「持有者 / 抢占者」读数）
#   unknown               形态不认识的行（旧格式 / 判据手写的 fixture）—— 读出口径**不猜**
#
# ## 覆盖边界（**有意**不做，照实登记 §19.1）
#
# - ⛔ **不做分档准入**（heavy/service/jvm/tooling/ops）：那是蓝图 P2 的**另一半** ——
#   本块只提供「该不该做、能做到几路」所需的**现取读数**；本块**不改**任何容量/并发决策。
# - ⛔ **不做轮转 / 上限**：台账只追加、会无限增长（本机口径，约 200 字节/条；读出口径按 kind
#   过滤，故暂不需要 cap）。**这是登记在案的未固化项**，不是「已经处理好了」。
# - ⛔ **不是多机台账**：路径与语义都是**本机单槽**口径（多机各记各的，不聚合）。
# - ⛔ **不是值守面**：本块只记读数；「拿不到锁怎么办」的出口在拒绝报文里（人不看台账也读得到）。
#
# ## 旁路（铁律：**绝不动锁语义**）—— 三条硬约束，都有判据
#
# ① **写台账时绝不持锁**：全部写点在 `_acquire_once` **之外**（判定已定、锁要么还没写、
#    要么已经删掉）⇒ 没有「持锁期间做 IO」这一步，也就没有 #6076 同族的递归/死锁风险；
# ② **写失败只 warning**：`|| true` + `_ledger_warn`，**不**参与任何 `if` / `return` 判定；
# ③ **零额外子进程**：一次 `printf >>`（O_APPEND，短行 < `PIPE_BUF` ⇒ 并发追加原子），
#    不 fork `python3` —— 本脚本在**拒绝路径**上跑，那里最不该变慢（同 `_process_table` 的注）。
#
# ## 批次事件可识别（「批次粒度」重启条件 = 批次记录 ≥5 次）
#
# `scripts/batch-gate.sh` 发起的那一次全量**不改 batch-gate 一行**即可被数出来：它跑的 worktree 里
# 有批次标记 `migao-package-heavy-entry-allow`（#6084 留的，位置由 `git rev-parse --git-path` 现取）
# ⇒ 本脚本按 `surface=batch-integration` 记，`stats` 单独报 `batch_integration=`。
# 判据 = `tests/unit_ci_workflows/test_machine_heavy_lock_ledger.py` 的 `TestBatchSurface`。
# =============================================================================
set -uo pipefail

SELF="$0"
LOCK_FILE="${MIGAO_HEAVY_LOCK_FILE:-$HOME/.migao-heavy.lock}"
LEDGER="${MIGAO_HEAVY_LEDGER:-$HOME/.migao-heavy-lock-ledger.jsonl}"
#: 台账首行（schema 头）。与 `scripts/package-heavy-entry-ledger.sh` 同口径：读出口径按 `_kind` 认对象。
LEDGER_KIND="migao.heavy-lock-ledger"
#: `batch-gate.sh` 的批次标记名（**与 `verify-all.sh` 的角色判定共用同一个约定**；名字变了两边一起变
#: —— 本脚本**只读**）。见 #6084。
BATCH_MARKER_NAME="migao-package-heavy-entry-allow"

# ── 过程视图（**单一实现**：一条 `ps` 拿全量，供孤儿回收与 status 共用）────────────────
# 为什么是 `ps -o pid=,ppid=,command=`：`pid=`/`ppid=` 的数字**不带表头**、`command=` 是**完整
# 命令行**（进程名列 `comm` 在 macOS 上会被截断 / 变成 `(node)` 形态 ⇒ 不能用来判族）。
_process_table() {
  # ⚠️ **`-ww` 不能省**（CI 实测，2026-09-30；本脚本首轮 CI 红的就是它）：procps 的 `ps` 在
  #    **输出不是终端**时按 **80 列**截断命令行（macOS 的 ps 不截断 ⇒ 本地绿 / CI 红）—— 落在 80 列
  #    之后的工作根 token 被切断 ⇒ 族判定看不见 `vitest` / `node` / `pytest` ⇒ **孤儿回收静默失效**
  #    且**不会报错**（实测报文：「孤儿回收：无」，而那个进程的 PPID 确实是 1）。
  #    `-ww` = 不限宽（macOS 的 BSD ps 与 Linux 的 procps 都支持）。
  ps -A -ww -o pid=,ppid=,command= 2>/dev/null || true
}

_pid_is_alive() {
  local pid="${1:-}"
  case "$pid" in
    ''|*[!0-9]*) return 1 ;;
  esac
  kill -0 "$pid" 2>/dev/null
}

# 进程名族：从命令行**任意** token 取 basename（`node` / `node (vitest)` / `/…/pytest` 全覆盖）。
# ⚠️ 命中时**设全局 `RUNNER_NAME` 并返回 0**（不往 stdout 打）：本函数在**逐进程**循环里被调用，
#    命令替换会给每个候选额外 fork 一个子 shell —— 实测（2026-09-30，机器上孤儿多时）这一处
#    连同下面的逐候选 `grep` 能把 `acquire` 拖到 **3.5 秒**，把判据的轮询窗口吃满 ⇒ 假红。
_runner_of_command() {
  local tok base
  RUNNER_NAME=""
  # shellcheck disable=SC2086  # 词分割是**有意**的：命令行要按空白切成 token
  for tok in $1; do
    base="${tok##*/}"
    case "$base" in
      node|nodejs|vitest|jest|playwright|pytest) RUNNER_NAME="$base"; return 0 ;;
      python|python2|python3|python3.*|python3.1[0-9])
        case "$1" in *pytest*) RUNNER_NAME="pytest"; return 0 ;; esac ;;
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
  local ancestors table pid ppid cmd
  # 祖先链收成**一行**（前后各留一个空格）⇒ 逐候选用 `case` 比，不再每个候选起一个 `grep` 子进程。
  ancestors=" $(_ancestors_of_self | tr '\n' ' ') "
  table="$(_process_table)"
  printf '%s\n' "$table" | while read -r pid ppid cmd; do
    [ -n "${cmd:-}" ] || continue
    [ "${ppid:-}" = "1" ] || continue
    case "$pid" in ''|*[!0-9]*) continue ;; esac
    case "$ancestors" in *" $pid "*) continue ;; esac
    _runner_of_command "$cmd" || continue
    _command_in_roots "$cmd" || continue
    printf '%s\t%s\t%s\n' "$pid" "$RUNNER_NAME" "$cmd"
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

# ── 台账（准入/溢出测量；**旁路**，绝不参与判定）────────────────────────────────
# ⚠️ JSON 转义**手写**（同 `package-heavy-entry-ledger.sh` 的口径）：只有 `\` 与 `"` 两种在
#    路径 / 名字里可能出现，而**不引 python3** 是硬要求 —— 本函数在**拒绝路径**上跑，那里多 fork
#    一个解释器就是可感知变慢（也避免「记账失败」与「判定」耦合）。
# ⚠️ **顺序**：`tr` 先把控制字符（换行 / 回车 / TAB）压成空格 —— **必须在** `sed` 之前：
#    `sed 's/\\/\\\\/g'` 产生的反斜杠若被 `tr '\\' …` 再处理一次就变成双重转义（坏 JSON）。
#    `\r` **必须**处理：它会让 `awk` 把 JSON 行切错（行尾多出控制字符 ⇒ 读出口径误判损坏）。
#: ⚠️ **常见情形零 fork**：本机路径 / 名字里几乎不会出现 `\` `"` 控制字符 ⇒ 先用一行 `case`
#:    短路（bash 内建）—— 每次调用省下 `tr` + `sed` 两个子进程（本包实测，逐值调用 4~6 次/条）。
#:    真出现要转义的字符时才走子进程那条路（正确性不变）。
_simple_json_value() {
  case "$1" in
    *\\*|*\"*|*$'\n'*|*$'\r'*|*$'\t'*) return 1 ;;
    *) return 0 ;;
  esac
}

_ledger_escape() {
  _simple_json_value "$1" && { printf '%s' "$1"; return 0; }
  printf '%s' "$1" | tr '\n\r\t' '   ' | sed 's/\\/\\\\/g; s/"/\\"/g'
}

_ledger_warn() {
  # 🔴 **出声不改判定**：GitHub Actions 认 `::warning::`，终端也读得懂 ⇒ 一处写、两处可见。
  echo "::warning::机器级重活锁**台账**写不进去（${LEDGER}）：$* —— 准入判定与退出码**一字不变**" >&2
}

#: append 严格**在判定之后**调用（锁要么还没写、要么已删）⇒ 不存在「持锁期间做 IO」。
# ⚠️ **参数个数 = printf 的 %s 个数（11 个），一个都不许多**：多一个 ⇒ `printf` 会**重启格式串**，
#    于是每条记录后面**多出一行残缺 JSON**（实测踩过；读出口径会把它记成 `malformed`）——
#    这不是"多余参数被忽略"，而是一个**沉默的坏行发射器**。改格式串时必须同步改这一行。
_ledger_append() {
  local kind="$1" req="$2" wait_s="$3" ck="$4" cp="$5" opid="${6:-}"
  _ledger_git_probe
  local dir; dir="$(dirname "$LEDGER")"
  if [ ! -d "$dir" ]; then
    # 只试一次建目录；失败也不拦（真正的判定在下面的 `||`）。
    mkdir -p "$dir" 2>/dev/null || true
    [ -d "$dir" ] || { _ledger_warn "台账目录不存在且建不出来：${dir}"; return 0; }
  fi
  if [ ! -s "$LEDGER" ]; then
    printf '{"_kind":"%s","_what":"机器级重活锁的准入/溢出**只追加**台账（issue #6091）：每次 acquire 尝试的结局与每次 release 各记一条。","_judged_by":"tests/unit_ci_workflows/test_machine_heavy_lock_ledger.py","_count":"./scripts/machine-heavy-lock.sh stats","_kinds":"acquired_nowait|acquired_after_wait|refused_busy|acquire_timeout|stale_reaped|released"}\n' \
      "$LEDGER_KIND" >> "$LEDGER" 2>/dev/null \
      || { _ledger_warn "台账首行追加失败（目录可写？磁盘满？）"; return 0; }
  fi
  local ts wt br
  ts="$(_ledger_now)"
  # 三个读数**一次 probe** 拿全（见 `_ledger_git_probe` 的注）；`IFS=tab` ⇒ 一行拆三个。
  IFS=$'\t' read -r wt br _ <<EOF2
$(_ledger_git_values)
EOF2
  printf '{"ts":"%s","kind":"%s","req":"%s","wait_seconds":%s,"worktree":"%s","branch":"%s","surface":"%s","holder":"%s","holder_pid":"%s","owner_pid":"%s"}\n' \
    "$ts" "$kind" "$(_ledger_escape "$req")" "${wait_s:-0}" "$(_ledger_escape "$wt")" \
    "$(_ledger_escape "$br")" "$(_ledger_surface)" "$(_ledger_escape "$ck")" \
    "$(_ledger_escape "$cp")" "$(_ledger_escape "$opid")" \
    >> "$LEDGER" 2>/dev/null \
    || { _ledger_warn "追加失败（kind=${kind} req=${req}）"; return 0; }
  return 0
}

#: 带**时区**的时间戳（本机 Asia/Shanghai）。`date +%z` 在 BSD 与 GNU 上都会给出 `+0800` 形态。
_ledger_now() {
  printf '%s%s' "$(date '+%Y-%m-%dT%H:%M:%S')" "$(date '+%z')"
}

#: 一次 `git rev-parse` 同时取三个读数（批次标记路径 / 工作树 / 分支）。
#: ⚠️ **为什么必须合成一次**（本包实测）：分开调三次 = 每个记账点多 ~126ms（60 组 acquire+release 的
#: 均值 197ms → 323ms）；合成一次后回到基线量级。记账不许让准入路径可感知变慢（铁律）。
#: ⚠️ **顺序不能换**（实测，git 2.54）：`--abbrev-ref HEAD` 在**还没有提交**的仓里会 `fatal: ambiguous
#: argument 'HEAD'` **并从那里截断 argv** ⇒ 排在前面的 `--git-path` 会被静默吞掉、批次面判成 `single`。
#: `--git-path` 永远成功 ⇒ 放**最前**，后面被截断也不影响它。
#: ⚠️ 成败都写进**全局** `_LEDGER_GIT`（挂在 `$$` 上的 append 会静默丢值）。
_LEDGER_GIT=""
_ledger_git_probe() {
  _LEDGER_GIT="$(git rev-parse --git-path "$BATCH_MARKER_NAME" --show-toplevel --abbrev-ref HEAD 2>/dev/null)"
  return 0
}

#: 从全局读数里拆出 (worktree, branch, marker) —— 三行，**全程零 fork**（不用 `cut`/`sed`）。
_ledger_git_values() {
  local nl=$'\n' raw="$_LEDGER_GIT"
  local wt br marker rest
  marker="${raw%%"$nl"*}"
  if [ "$raw" != "$marker" ]; then
    rest="${raw#*"$nl"}"; wt="${rest%%"$nl"*}"
    if [ "$rest" = "$wt" ]; then br=""; else br="${rest#*"$nl"}"; fi
  else
    wt=""; br=""; marker=""
  fi
  # ⚠️ tab 分隔（不是换行）：整份读数**永远在一行** ⇒ 调用方一句 `read` 就能拆开
  #    （换行分隔时 `read` 只吃第一行、其余**整段塞进第二个变量** —— 实测踩过）。
  printf '%s\t%s\t%s\n' "${wt:-$(pwd)}" "${br:-?}" "$marker"
}

#: 批次面判定（只读；见文件头「批次事件可识别」）。⚠️ `git rev-parse --git-path` 取的是
#: **管理目录**（`.git/worktrees/<name>/…`）⇒ **不在工作树里**，所以它不会进 `git status`。
_ledger_surface() {
  # ⚠️ 只从**已取好的**全局读数里拆（`_ledger_append` 入口已经 probe 过）⇒ 零额外 git 调用。
  local parts marker
  parts="$(_ledger_git_values)"
  # ⚠️ 只取**第 3 段**（marker）：`read` 一句就够（tab 分隔 ⇒ 一行）
  local IFS=$'\t'
  # shellcheck disable=SC2034  # wt/br 只为把位置占住，这里不用
  read -r _wt _br marker <<EOF2
$parts
EOF2
  if [ -n "$marker" ] && [ -f "$marker" ]; then printf 'batch-integration'; else printf 'single'; fi
}

#: 记 **acquire 的一次调用**（调用点只在 `cmd_acquire`，**不在** `_acquire_once` 里 —— 见文件头旁路①）。
_ledger_record_acquire() {
  local kind="$1" req="$2" waited="$3"
  local hname hpid
  hname="$(_lock_field "$LOCK_FILE" name)"
  hpid="$(_lock_field "$LOCK_FILE" pid)"
  _ledger_append "$kind" "$req" "$waited" "$hname" "$hpid" ""
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
  ps -A -ww -o %cpu= -o pid= -o command= 2>/dev/null \
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
  # 三条**可行动**出口（蓝图 §4 行 5「槽满 ⇒ 出声 + 溢出 CI + 留痕」；issue #6091）：
  # ① 等（串行是锁的意义）② **改走 CI**（不再抢本机单槽）③ 先杀（仅在确认卡死时）。
  echo "   怎么办（三选一）："
  echo "     ① 等它跑完（重活串行是本锁的全部意义）：./scripts/machine-heavy-lock.sh status"
  echo "     ② **改走 CI（推荐）**：把分支推上去即可 —— GitHub 上每个 PR 并行跑同一套 required 检查，"
  echo "        它是**权威**，且不占本机这颗单槽；本地这一趟**没跑**就必须在 PR body 写清楚："
  echo "        「本机未跑（机器级重活锁被 ${name:-别人} 占着）+ 理由 + CI 覆盖清单」。"
  echo "     ③ 确认它确实卡死了再杀（**先看上面的 worktree/cwd 是不是你自己的会话**）："
  echo "        kill ${pid:-<pid>}"
  echo "   溢出读数：./scripts/machine-heavy-lock.sh stats   # 这份台账回答「被拒了多少次 / 每次都等多久」"
}

# ── 子命令 ───────────────────────────────────────────────────────────────────
#: `--wait` 的轮询间隔区间（秒）。**抖动是有意的**：多个等待者若同刻醒来会互相踩（惊群），
#: 而固定间隔已被实测证明会让慢的一方饿死（见文件头「重试约定」）。
WAIT_MIN_SECONDS=2
WAIT_MAX_SECONDS=5

_wait_backoff_seconds() {
  # 纯函数（判据直调）：返回本次重试前应睡的秒数，落在 [WAIT_MIN_SECONDS, WAIT_MAX_SECONDS]。
  echo $(( WAIT_MIN_SECONDS + RANDOM % (WAIT_MAX_SECONDS - WAIT_MIN_SECONDS + 1) ))
}

_acquire_once() {
  # 单次准入尝试。0 = 拿到；1 = 被**活的**持有者占着（可等）；3 = 无法判定（**不可等**，fail-closed）。
  # ⚠️ `reap_orphans` 只在**第一次**尝试时跑（它最坏要 3.5 秒，见 `_process_table` 的注）：轮询里
  #    每次都跑会把 2~5s 的间隔撑成 5.5~8.5s，且对「锁是否空出来」没有任何帮助。
  local name="$1" do_reap="${2:-1}"
  [ "${do_reap}" = "1" ] && reap_orphans

  local state; state="$(_lock_state)"
  case "$state" in
    held)
      _report_holder
      return 1
      ;;
    free)
      echo "  ✅ 机器级重活锁空闲（${LOCK_FILE}）"
      ;;
    stale)
      local old_pid old_name; old_pid="$(_lock_field "$LOCK_FILE" pid)"; old_name="$(_lock_field "$LOCK_FILE" name)"
      echo "  ♻️  回收**陈旧**锁：原持有者 pid=${old_pid:-未知} 已不存在（进程表里查不到）"
      # 台账：回收**先记**（`rm` 之后锁文件就没了 ⇒ 记不到是谁的陈旧锁了）。此刻锁尚未被本进程持有
      # （`rm` 立刻跟在后面）⇒ 满足旁路①「写台账时绝不持锁」。
      _ledger_append "stale_reaped" "$name" 0 "$old_name" "$old_pid" ""
      rm -f "$LOCK_FILE"
      ;;
    *)
      echo "❌ 锁状态不可判定（state=${state}）—— fail-closed，不得当成功" >&2
      return 3
      ;;
  esac

  # 记录持有者（pid = 调用方的 shell：`$PPID`；cwd/worktree 现场取）
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
  echo "  🔒 已获取机器级重活锁：name=$name pid=$holder_pid worktree=$worktree"
  echo "     释放：$SELF release（或调用方以 trap … EXIT 兜住异常退出）"
  return 0
}

cmd_acquire() {
  local name="${1:-}"; [ $# -gt 0 ] && shift
  local wait_seconds=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --wait)
        if [ $# -lt 2 ]; then
          echo "用法: $0 acquire <名字> [--wait <秒>]（--wait 缺参数）" >&2; return 2
        fi
        case "$2" in
          ''|*[!0-9]*) echo "用法: $0 acquire <名字> [--wait <秒>]（--wait 要非负整数秒，现值：$2）" >&2; return 2 ;;
        esac
        wait_seconds="$2"; shift 2 ;;
      *)
        echo "用法: $0 acquire <名字> [--wait <秒>]（未知参数：$1）" >&2; return 2 ;;
    esac
  done
  if [ -z "$name" ]; then
    echo "用法: $0 acquire <名字> [--wait <秒>]（例：'verify-all.sh gate'）" >&2
    return 2
  fi

  # 默认（wait_seconds=0）**与既有语义逐字等价**：一次尝试，拿不到就立即非零退出。
  local deadline=$(( $(date +%s) + wait_seconds ))
  local waited=0 first=1 rc=0
  # 台账的三个终局量：`refused=1`（被**活的**持有者挡回）/ `timed_out=1`（等满上限）。
  # ⚠️ 记在**循环内**、每个终局只置一次；`unknown_request` 只在「第一次尝试就不可判定」时置
  #    （它没有 kind 语义 ⇒ **不**记账 —— 记一条 `unknown` 只会把 `stats` 的 kind 计数搅浑）。
  local refused=0 timed_out=0 unknown_request=0
  while :; do
    rc=0; _acquire_once "$name" "$first" || rc=$?
    first=0
    [ "${rc}" -eq 0 ] && break
    # 只有「被活的持有者占着」才值得等；**无法判定（3）立即失败** —— 不拿等待掩盖它。
    if [ "${rc}" -eq 3 ]; then
      [ "${waited}" -eq 0 ] && unknown_request=1
      break
    fi
    refused=1
    [ "${wait_seconds}" -gt 0 ] || break
    local now; now="$(date +%s)"
    if [ "${now}" -ge "${deadline}" ]; then
      echo "⏱️  等待已到上限（--wait ${wait_seconds}s）仍未拿到锁 —— **本次没有跑**任何重活（这不是「通过」）"
      _report_holder
      timed_out=1
      break
    fi
    local nap remain; nap="$(_wait_backoff_seconds)"; remain=$(( deadline - now ))
    [ "${nap}" -le "${remain}" ] || nap="${remain}"
    waited=$(( waited + nap ))
    echo "⏳ 锁被占，${nap}s 后重试（已等 ${waited}s / 上限 ${wait_seconds}s）"
    sleep "${nap}"
  done

  # ── 台账（**旁路**：判定已定、锁要么还没写、要么已经删）──────────────────────────
  if [ "${rc}" -eq 0 ]; then
    if [ "${waited}" -gt 0 ]; then
      _ledger_record_acquire "acquired_after_wait" "$name" "$waited"
      echo "  ⏳ 本次为**排队等待**后取得：累计等待 ${waited}s（上限 ${wait_seconds}s）"
    else
      _ledger_record_acquire "acquired_nowait" "$name" 0
    fi
    return 0
  fi
  if [ "${unknown_request}" -eq 1 ]; then
    return "${rc}"
  fi
  if [ "${timed_out}" -eq 1 ]; then
    _ledger_record_acquire "acquire_timeout" "$name" "$waited"
  else
    _ledger_record_acquire "refused_busy" "$name" 0
  fi
  return "${rc}"
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
  local hname; hname="$(_lock_field "$LOCK_FILE" name)"
  rm -f "$LOCK_FILE"
  # 台账：**删掉锁之后**才写（旁路①）—— `released` 的持有者 = 刚放锁的那个人。
  _ledger_append "released" "$hname" 0 "$hname" "$pid" "$pid"
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

# ── 读出口径：`stats`（**只读、离线**）───────────────────────────────────────────
# 用法：`./scripts/machine-heavy-lock.sh stats [--since <窗口>] [--json]`
#   `--since` 收三种形态（**其余一律报错**，绝不猜 —— 猜错 = 悄悄换了时间窗而读数看起来一样）：
#     ① 相对：`24h` / `90m` / `7d`（本机时区的「现在往前推」）② ISO8601：`2026-10-03T00:00:00+08:00`
#     / `2026-10-03T00:00:00Z` / `2026-10-03T00:00`（无时区 ⇒ 按**本机**时区，读出口径写明）
#     ③ unix epoch 秒
#   三态口径：**读不到台账 ⇒ 「暂无记录」**（不是 0 分的假绿）；**半行 / 非法 JSON ⇒ 具名跳过**（出声不崩）。
#   🔴 **它不是门禁**：读数再差也 `exit 0` —— 本命令是**分母/事实**，不设阈值、不拦任何东西。
cmd_stats() {
  local since="" json=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --since)
        if [ $# -lt 2 ]; then echo "用法: $0 stats [--since <24h|ISO8601|epoch>] [--json]" >&2; return 2; fi
        since="$2"; shift 2 ;;
      --json) json=1; shift ;;
      *) echo "用法: $0 stats [--since <24h|ISO8601|epoch>] [--json]（未知参数：$1）" >&2; return 2 ;;
    esac
  done
  if [ ! -e "$LEDGER" ]; then
    if [ "$json" -eq 1 ]; then
      printf '{"ledger":"%s","exists":false,"records":0,"malformed":0,"by_kind":{},"overflow_count":0,"wait_seconds":{"n":0,"p50":null,"p95":null,"max":0},"top_requesters":[],"top_holders":[],"batch_integration":0,"empty_reason":"no-ledger-file"}\n' \
        "$(_ledger_escape "$LEDGER")"
    else
      echo "── 机器级重活锁 准入/溢出台账（只读）──"
      echo "台账文件    : ${LEDGER}"
      echo "暂无记录    : 台账文件还不存在 —— 本机还没有发生过任何 acquire/release。"
      echo "              ⚠️ 这不是「0 次溢出」，是**还没有读数**（区别很重要：0 是读数，这没有读数）。"
    fi
    return 0
  fi
  # 解析 + 聚合交给 python3（**标准库**，离线、零第三方）—— 见上面 `--since` 的形态表。
  # ⚠️ 输出是**现取**的：任何一条读不出来都只在 `malformed` 里计数，不改变别人的读数。
  #    `bash` 传参不用 `$1` 占位：`$0` 在这里就是脚本名（python 本行内不需要它）。
  MIGAO_STATS_LEDGER="$LEDGER" MIGAO_STATS_SINCE="$since" MIGAO_STATS_JSON="$json" \
    python3 -c '
import datetime, json, os, sys
from collections import Counter

path = os.environ["MIGAO_STATS_LEDGER"]
since_raw = os.environ.get("MIGAO_STATS_SINCE", "").strip()
as_json = os.environ.get("MIGAO_STATS_JSON", "0") == "1"
KINDS = ("acquired_nowait", "acquired_after_wait", "refused_busy",
         "acquire_timeout", "stale_reaped", "released", "unknown")
# 溢出 = **准入被拒** = 立即拒绝 + 等待档超时（`refused_busy` 是其中的「零等待」那一半）。
REFUSAL_KINDS = ("refused_busy", "acquire_timeout")

def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(2)

def local_tz():
    return datetime.datetime.now().astimezone().tzinfo

def zone_label():
    """本机时区的**离线**标签（`zoneinfo` 在部分环境不可用 ⇒ 失败就退回 UTC 偏移，绝不崩）。"""
    try:
        import zoneinfo
        return datetime.datetime.now().astimezone().tzinfo.key or "UTC" + tz_off
    except Exception:
        return "UTC" + tz_off

def parse_ts(raw):
    """台账的 `ts`（`%Y-%m-%dT%H:%M:%S%z`）⇒ **aware** datetime。读不出来 ⇒ None（调用方计数）。"""
    try:
        dt = datetime.datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S%z")
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=local_tz())

def parse_since(raw):
    """`--since` 的三种形态 ⇒ (epoch_seconds, 回显用原文)。**不认识的形态一律 exit 2。**"""
    if not raw:
        return None, ""
    text = raw.strip()
    unit = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if len(text) > 1 and text[-1] in unit and text[:-1].isdigit():
        return datetime.datetime.now().timestamp() - int(text[:-1]) * unit[text[-1]], text
    if text.isdigit():
        return float(text), text
    iso = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        dt = datetime.datetime.fromisoformat(iso)
    except ValueError:
        die("❌ --since 形态不认识：%r —— 只认 24h / 90m / 7d · ISO8601（带或带不带时区）· epoch 秒" % raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=local_tz())
    return dt.timestamp(), text

cutoff, since_display = parse_since(since_raw)
tz_off = datetime.datetime.now().astimezone().strftime("%z") or "?"   # 如 +0800（**不用** tzname：CST 有歧义）

records, malformed, malformed_at = [], 0, []
with open(path, "r", encoding="utf-8", errors="replace") as fh:
    for lineno, line in enumerate(fh, 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            malformed += 1                      # 半行 / 非法 JSON ⇒ **具名跳过**，不崩
            if len(malformed_at) < 5:
                malformed_at.append(lineno)
            continue
        if not isinstance(obj, dict):
            malformed += 1
            if len(malformed_at) < 5:
                malformed_at.append(lineno)
            continue
        if "_kind" in obj:                      # schema 头（不是记录）
            continue
        kind = obj.get("kind", "")
        if kind not in KINDS:                   # 旧格式 / 手写 fixture ⇒ `unknown`，**不猜**
            kind = "unknown"
        ts = parse_ts(obj.get("ts", ""))
        if cutoff is not None and (ts is None or ts.timestamp() < cutoff):
            continue
        records.append({
            "kind": kind,
            "req": str(obj.get("req", "")),
            "holder": str(obj.get("holder", "")),
            "holder_pid": str(obj.get("holder_pid", "")),
            "wait": obj.get("wait_seconds") if isinstance(obj.get("wait_seconds"), int) else 0,
            "surface": str(obj.get("surface", "")),
        })

by_kind = Counter(r["kind"] for r in records)
waits = sorted(r["wait"] for r in records)
def pct(values, p):
    if not values:
        return None
    return values[max(0, min(len(values) - 1, (p * len(values) + 99) // 100 - 1))]
wait_stats = {
    "n": len(waits),
    "p50": pct(waits, 50),
    "p95": pct(waits, 95),
    "max": max(waits) if waits else 0,
}
overflow = sum(by_kind.get(k, 0) for k in REFUSAL_KINDS)
top_req = Counter(r["req"] for r in records if r["req"]).most_common(5)
top_holder = Counter(r["holder"] for r in records if r["holder"]).most_common(5)
batch_n = sum(1 for r in records if r["surface"] == "batch-integration")

if as_json:
    print(json.dumps({
        "ledger": path, "exists": True, "utc_offset": tz_off, "since": since_display or None,
        "records": len(records), "malformed": malformed,
        "by_kind": {k: by_kind.get(k, 0) for k in KINDS if by_kind.get(k, 0)},
        "overflow_count": overflow,
        "refusal_kinds": {k: by_kind.get(k, 0) for k in REFUSAL_KINDS if by_kind.get(k, 0)},
        "wait_seconds": wait_stats,
        "top_requesters": [{"name": n, "count": c} for n, c in top_req],
        "top_holders": [{"name": n, "count": c} for n, c in top_holder],
        "batch_integration": batch_n,
    }, ensure_ascii=False, sort_keys=True))
else:
    print("── 机器级重活锁 准入/溢出台账（只读；口径见 docs/wiki/Development.md）──")
    print("台账文件    : %s" % path)
    print("时区        : %s（本机）—— 台账 `ts` 带该偏移；`--since` 不带时区时按它解释" % zone_label())
    if since_display:
        print("时间窗      : --since %s" % since_display)
    print("记录条数    : %d（时间窗内）" % len(records))
    if malformed:
        print("损坏行跳过  : %d 条（行号 %s%s）—— **出声不崩**：坏行只让它自己读不出来"
              % (malformed, ", ".join(str(n) for n in malformed_at),
                 " …" if malformed > len(malformed_at) else ""))
    if not records:
        print("暂无记录    : 时间窗内没有**任何**记录 —— 这不是「0 次溢出」，是**没有读数**。")
        sys.exit(0)
    print("按 kind     :")
    for k in KINDS:
        if by_kind.get(k, 0):
            print("  %-20s %d" % (k, by_kind[k]))
    print("溢出（准入被拒）次数 : %d / %d 次 acquire 尝试（%.1f%%）   ← **本台账的核心读数**"
          "（refused_busy=%d + acquire_timeout=%d）"
          % (overflow, len(records), 100.0 * overflow / len(records),
             by_kind.get("refused_busy", 0), by_kind.get("acquire_timeout", 0)))
    print("  处置口径  : 溢出 ⇒ **改走 CI**（推一次即可，CI 是权威）＋ 在 PR body 写"
          "「本机未跑 + 理由 + CI 覆盖清单」。不许静默排队。")
    print("wait_seconds: n=%d p50=%s p95=%s max=%s"
          % (wait_stats["n"], wait_stats["p50"], wait_stats["p95"], wait_stats["max"]))
    print("top 请求者  : %s" % (", ".join("%s×%d" % (n, c) for n, c in top_req) or "（无）"))
    print("top 持有者  : %s" % (", ".join("%s×%d" % (n, c) for n, c in top_holder) or "（无）"))
    print("批次记录    : %d 条（surface=batch-integration）—— 「批次粒度」重启条件的读数之一" % batch_n)
' || return $?
  return 0
}

# ── dispatch（is-callable 形态：`MIGAO_HEAVY_LIB=1` 时只装函数，供判据 source）──────
# 判据需要直接调 `_runner_of_command` / `_command_in_roots` 这类纯函数（零子进程、零时钟），
# 故留一个「只装不上膛」的开关；默认（不带该变量）行为一字不变。
if [ "${MIGAO_HEAVY_LIB:-}" = "1" ]; then
  return 0 2>/dev/null || true
else
  case "${1:-}" in
    acquire|release|status|stats)
      sub="$1"; shift
      "cmd_${sub}" "$@"
      # ⚠️ **不在本进程退出时自动删锁**：本脚本的 `$$` 与调用方的
      # `$PPID` 不是同一个进程，自动删会把「调用方还在跑」的活锁误删成空闲 ⇒ 准入当场失效。
      # 释放只有两条路：① 调用方显式 `release`（或 `trap … EXIT`）② 下一次 `acquire` 发现
      # 持有者 PID 已死（陈旧锁）时回收。调用方忘释放的最坏后果 = 一次「陈旧锁」，
      # 而**不是**「两把重活同时在跑」——失效方向选安全的那一边。
      exit "$?"
      ;;
    *)
      echo "用法: $0 {status|acquire <名字> [--wait <秒>]|release|stats [--since <窗口>] [--json]}" >&2
      exit 2
      ;;
  esac
fi
