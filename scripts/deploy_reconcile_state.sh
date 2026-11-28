#!/usr/bin/env bash
# 值守面状态台账：**每条对账腿恰好一行**（issue #5935；消费点在 `.github/workflows/deploy-reconcile.yml`
# 的 `Reconcile deploys` 步，由它 `source` 本文件）。
#
# 用法（在被 source 的 shell 里，取 `$0` = 那份 workflow 文件）：
#   source scripts/deploy_reconcile_state.sh
#   watchdog_note <腿> <状态> <依据>            # 每条腿**至少**调一次（整行替换，不追加）
#   watchdog_abort <腿> ratelimited|aborted <原因>   # 单腿失败**只中止它自己**（issue #9310）
#   watchdog_is_ratelimited <rc> <输出>         # 限流识别面（rc≠0 **且** 输出含 rate limit/403）
#
# ## 病（现取读数，不是推断）
# run `36911070357`（2026-10-01T19:00:20Z，main HEAD `3fa84ab`）的对账步**六条腿全部**报
# 「目标 workflow … 不在 main 上」、间隔 ≈58ms，随后值守面报「5 条腿读不到对账状态 ⇒ 判定不可用」。
# 真因不是「漏落状态」，而是**落的状态是错的**、且**没有任何东西会因此变红**：
# 那条前置判据写作 `gh workflow view "$wf" --ref main`，而 gh 要求 `--ref` **必须**搭 `--yaml`
# ⇒ 它 100% 失败（本机复现：stderr `--yaml required when specifying --ref`、退出 1、耗时 0.063s）。
# ⇒ 6/6 条腿命中**同一条**坏分支 ⇒ 形态学判据看不见（「落了错的状态」与「落对了」长得一样）。
#
# ## 本文件锁什么
# ① **腿清单只有一个来源**：本步自己的 `reconcile_one` 调用（从 workflow 文件里现取）——
#    **不另立第二份清单**（第二份清单 = 迟早脱钩的真相源）。
# ② **先落 `unrecorded` 种子**：任一腿若在本轮**从未**被记过，它留着的就是 `unrecorded`
#    而不是「空」⇒ 使唤方可以**具名**判红（`reconcile_one` 中途崩了也照样抓得到）。
# ③ **恰好一行/腿**：`watchdog_note` 整行替换（不是追加）⇒ 重复调用不会长出第二行。
#
#
# ## 调用方的**弃权闸**（issue #5935 本 PR 首轮 CI 实测；正文里只留一行指针，理由在这里）
# 对账步的 `checkout` 是 **`ref: main`**（对账基准必须是 main HEAD）⇒ **「新增这条腿的那个 PR」里
# 本文件还不在 main 上**。两种坏修法都**实测**过：
#   ① 裸 `source` ⇒ `scripts/deploy_reconcile_state.sh: No such file or directory` ⇒
#      **整个对账步 rc=1**（而其它五条腿本来是对的）—— run `36943682332` 逐字；
#   ② 只加 `if [ -f … ]` 包起来 ⇒ 函数**一个都没定义** ⇒ 循环里 `on_main: command not found`
#      ⇒ **rc=127**（本机判据当场红）。
# ⇒ 正确姿势（调用方已落码，同 `.github/scripts/mechanism_liveness.sh`）：**载不进就弃权** ——
#   `::warning::` + `exit 0` + **不 dispatch 任何东西**。这与 issue #5668 那条前置判据治的是**同一形态**：
#   「**还轮不到我**」不许让机制本身停摆。回归判据 =
#   `tests/unit_ci_workflows/test_reconcile_no_silent_skip.py::test_missing_state_script_does_not_kill_the_whole_step`。
#
# ⚠️ 与 `tests/unit_ci_workflows/test_deploy_reconcile_state.py` 的判据同批。

set -uo pipefail

WATCHDOG_STATE="${WATCHDOG_STATE:-.deploy-watchdog-state.tsv}"
# 腿清单的**唯一来源** = 本 workflow 里的 `reconcile_one <腿> <workflow> <路径> [<附加>]` 调用。
# 正则**必须**与 `tests/unit_ci_workflows/test_swas_deploy_ci_hardening.py` 的 `parse_reconcile_calls`
# 同形（`^\s*reconcile_one\s+(\S+)\s+(\S+)\s+`），否则两处会各读出一套腿。
LEGS="$(grep -oE '^ *reconcile_one +[^ ]+' "$0" | awk '{print $2}' | sort -u)"
: > "$WATCHDOG_STATE" 2>/dev/null || echo "::warning::值守面状态文件不可写——本轮按「判不了」（fail-closed）处理，不影响对账"
for _s in $LEGS; do
  printf '%s\t%s\t%s\n' "$_s" unrecorded '本轮未落状态' >> "$WATCHDOG_STATE" 2>/dev/null
done
# 对账腿数（`--seen` 的**现取**来源）：不许把 6 写死在别处 —— 新加一条腿时它自己会跟上
# （写死 = 读数与事实相反，issue #5264 的形态）。
SEEN=0; for _s in $LEGS; do SEEN=$((SEEN + 1)); done

# ── 判据 ③（前置）：目标 workflow 必须**已在 default branch 上**（issue #5668 / #5935） ──
# 为什么需要（**实测**，issue #5668 的 PR 首轮）：**新增一条腿的那个 PR 里**，被对账的 workflow 还没合并到
# main ⇒ `gh workflow run <wf> --ref main` 返回「HTTP 404: workflow … not found on the default branch」
# ⇒ `set -euo pipefail` 下**整个对账 step 非零退出**，把同轮其它腿的结果一起染红（而它们本来是对的）。
# ⇒ 显式 warn + 落 summary + **不** dispatch（fail-open 的另一面：本检查自己出错绝不停掉对账）。
#
# 🔴 判据用 `git cat-file` 而不是 `gh`：**本函数的前身正是 issue #5935 的现场根因** ——
# 它写作 `gh workflow view "$wf" --ref main`，而 gh 要求 `--ref` **必须**搭 `--yaml`
# ⇒ **100% 失败**（本机实测：stderr `` `--yaml` required when specifying `--ref` ``、退出 1、0.063s；
# run `36911070357` 里六条腿各报一次、每条 ≈58ms）⇒ **六条腿全部**被误记成「不在 main 上」，
# 而六份 workflow 都在 main 上、对账步 rc=0。**问错对象的判据比没有判据更糟**：它把「读不到状态」
# 伪装成一条像样的状态，且 6/6 命中同一分支 ⇒ 形态学判据全都看不见。
# ⇒ 换成本步**已有的只读对象**：对账步 checkout 是 `ref: main` + `fetch-depth: 0` ⇒ `HEAD` 就是
#    main 的 HEAD（`--ref main` 想查的正是这棵树），git 直接问它，不依赖 gh 的参数面与网络。
# 三态（**判据 1 的正例锚 / 负例锚**，见 tests/unit_ci_workflows/test_deploy_reconcile_state.py）：
#   文件在 HEAD 里 ⇒ 0；HEAD 有效但它不在 ⇒ 1（= 真的「还没上 main」）；HEAD 本身取不到 ⇒ 3（机制故障）。
# 🔴 **别写 `[ $? = 1 ]`**：`git cat-file -e` 对「路径不存在」返回的是 **128**（不是 1），
#    而且它还会把 fatal 打到 stderr —— 「按退出码猜」在这里必错（本函数第一版就是这么写错的）。
#    ⇒ 用 `git cat-file -e "HEAD:$p"` 的**存在性**判「在不在」，用 `git rev-parse --verify` 单独判「HEAD 有没有」。
on_main() {
  # ⚠️ 用 `if` 而不是 `&&`/`||` 链：调用方带 `set -e` 时，`if` 的**条件位置**是抑制的
  #    ⇒ 「取不到 HEAD」是**本函数返回 3**，而不是让 `set -e` 把整步就地打死（那样 3 这个值就没人看得见）。
  if ! git rev-parse -q --verify HEAD >/dev/null 2>&1; then return 3; fi
  if git cat-file -e "HEAD:.github/workflows/$1" 2>/dev/null; then return 0; fi
  if git ls-tree -r --name-only HEAD -- ".github/workflows/$1" 2>/dev/null | grep -qxF ".github/workflows/$1"; then return 0; fi
  return 1
}
# 落「这一轮**弃权**」这一条状态 + 出声（`on_main` 真返回 1 时才该调）。
# ⚠️ 状态值**必须与 `unrecorded` 区分开**：本腿是**主动弃权**（目标 workflow 还没在 main 上、本轮不对账），
# 不是「状态机没记它」。两态混同会两头都错：把它当机制故障 ⇒ 「新增腿的那个 PR」每轮判红（噪声，issue #5668 的契约）。
on_main_absent() {   # $1=腿 $2=workflow，消费 `$SUMMARY` / `$NOTARGET` 由调用方持有
  echo "::warning::$1：目标 workflow $2 不在 main 上（多为「新增腿的那个 PR」）——本轮不对账"
  echo "| $1 | ⚠️ \`$2\` 尚未在 main 上（新增腿的那个 PR；dispatch 会 404） | **不补**（合并后自然接上） |" >> "$SUMMARY"
  watchdog_note "$1" notarget "目标 workflow $2 不在 main 上"
  return 0
}

# 记一条腿的状态（**整行替换**：同一腿重复调用不会长出第二行）。
watchdog_note() {
  awk -F'\t' -v OFS='\t' -v s="$1" -v st="$2" -v w="$3" \
    '$1 == s { $2 = st; $3 = w } 1' "$WATCHDOG_STATE" > "$WATCHDOG_STATE.tmp" 2>/dev/null \
    && mv "$WATCHDOG_STATE.tmp" "$WATCHDOG_STATE" \
    || echo "::warning::值守面状态写入失败（$1=$2）"
  return 0
}

# ── 单腿中止（issue #9310）：`ratelimited` / `aborted` 两态 —— **一条腿失败不许打死整步** ──────
# 病（现取读数）：run `46094064167` 的 `Reconcile and dispatch missing deploys` 步是 `set -euo pipefail`，
# 而循环里的 `gh workflow run` 被 **HTTP 403 installation rate limit** 打掉 ⇒ **整步在第 1 条腿退出**
# ⇒ 后 4 条腿的种子位仍是 `unrecorded` ⇒ 值守面 fail-closed 报「5 条腿读不到对账状态（机制故障）」。
# ⇒ 逐腿兜底：一条腿失败**只中止它自己**，且**必须落一个具名状态**（再也不许留 `unrecorded` 当结论）。
#
# 识别面（**只有这两条**；未覆盖的情形落 `aborted`，**不是** `ratelimited`）：
#   退出码非 0 **且** 输出含 `rate limit` / `Rate limit` / `RATE_LIMIT` / `rate-limit` **或** `403`。
# 为什么是双判据（而不是只认退出码 / 只认文案）：gh 的 stderr 文案**不稳定**（版本 / 语言 /
# primary vs secondary rate limit）；只认退出码会把「凡 dispatch 失败都叫限流」—— 那会让**真机制故障**
# 静默落进「本轮被限流」，比原缺陷更糟。
watchdog_is_ratelimited() {   # $1=退出码 $2=输出（stdout+stderr）⇒ 0=限流
  [ "${1:-0}" != "0" ] || return 1
  case "${2:-}" in
    *"rate limit"* | *"Rate limit"* | *"RATE_LIMIT"* | *"rate-limit"* | *403*) return 0 ;;
  esac
  return 1
}

# 落「这条腿本轮被中止」+ **出声**（限流与真失败都必须有人看得见，**不许静默**）。
# ⚠️ 只在**还没落过状态**（仍是种子 `unrecorded`）时写：具名状态（`ratelimited` / `aborted`）不许被
#    调用处的兜底覆盖（否则「限流」会被改写成「其它失败」，两个桶当场互相污染）。
watchdog_abort() {   # $1=腿 $2=状态（ratelimited|aborted）$3=原因
  local st="${2:-aborted}" why="${3:-本轮未对账}" cur
  # 原因会进 TSV 的**一列** ⇒ 换行 / 制表符必须折平（否则一条腿变成两行，下游读到错的行）
  why="${why//$'\n'/ }" why="${why//$'\t'/ }" why="${why:0:300}"
  cur="$(awk -F'\t' -v s="$1" '$1 == s { print $2; exit }' "$WATCHDOG_STATE" 2>/dev/null || true)"
  if [ -n "$cur" ] && [ "$cur" != "unrecorded" ]; then return 0; fi
  echo "::warning::$1：本轮未对账（${st}）——${why}"
  echo "| $1 | ⚠️ 本轮未对账（\`${st}\`） | **不补**（${why}） |" >> "${SUMMARY:-/dev/null}"
  watchdog_note "$1" "$st" "$why"
  return 0
}

# 派一次补部署；失败**只中止这一条腿**（issue #9310），并把桶计数加到调用方的全局。
# 返回 0 = 派出去了 / 1 = 已落中止态（调用方 `|| return 0` 收下，接着跑**下一条腿**）。
# ⚠️ 成败**必须显式判 rc**，不能靠 `set -e`：本函数在调用处 `|| 兜底` 的**条件位**上运行，
#    bash 会把 `-e` 在整个函数体内抑制（实测）⇒ 裸命令失败会继续往后走、把这条腿误记成 `dispatched`。
watchdog_dispatch() {   # $1=腿 $2=workflow
  local wf_out wf_rc
  wf_out="$(gh workflow run "$2" --ref main --repo "${GITHUB_REPOSITORY:-}" 2>&1)" && wf_rc=0 || wf_rc=$?
  [ "$wf_rc" = "0" ] && return 0
  if watchdog_is_ratelimited "$wf_rc" "$wf_out"; then
    watchdog_abort "$1" ratelimited "gh workflow run 被限流（rc=${wf_rc}）：${wf_out}"
    RATELIMITED=$((${RATELIMITED:-0} + 1))
  else
    watchdog_abort "$1" aborted "gh workflow run 失败（rc=${wf_rc}，非限流）：${wf_out}"
    ABORTED=$((${ABORTED:-0} + 1))
  fi
  return 1
}

# ── 判据 1 / 2（issue #5935）：「落状态」本身有判据 + 零动作必须归因 ─────────────────────
# `seen=6 acted=0` 且原因桶全 0 之所以出现过（run `36911070357`），是因为**状态落了、但落的是错的**
# （六条腿 100% 命中同一条坏分支）—— 形态学判据看不见「落了错的状态」。⇒ 读**状态文件的实际内容**：
# 仍是 `unrecorded` 的腿 = 本轮**从未**被记过（种子位没被替换）⇒ 由本步**自己判红并具名**，
# 不许把「缺状态」甩给下游 fail-closed 兜（判据 1）；具名清单同时进存活读数（判据 2）。
watchdog_missing() {   # 把「没落状态」的腿具名写进两个全局（调用方用 $MISS / $MISS_COUNT）
  # ⚠️ 判据面**只**是 `unrecorded`（种子位没被替换）与空：`notarget` / `deployed` / `inflight` /
  # `terminal` / `dispatched` / `ratelimited` / `aborted` 都是**已落**的合法状态 ⇒ 一条腿只要落过其中
  # 任一条就不算「没落」（`ratelimited` 另有单列 RATE：它不是机制故障，见下面那段）。
  # （把 `notarget` 也算成机制故障 = 让「新增腿的那个 PR」每轮判红 —— 那是 #5929 明确避开的噪声。）
  MISS="$(awk -F'\t' '$2 == "unrecorded" || $2 == "" { printf "%s ", $1 }' "$WATCHDOG_STATE" 2>/dev/null || true)"
  MISS="${MISS% }"; MISS_COUNT=0; for _m in $MISS; do MISS_COUNT=$((MISS_COUNT + 1)); done
  # 被限流的腿（issue #9310）：`ratelimited` 是**已落**的合法态（「本轮没对账成功」≠「状态机没记它」）
  # ⇒ **不算机制故障**，但**必须出声**（`::warning::` + summary 行）—— 静默的「本轮没对账」会被读成「没事」。
  # 判据 = tests/unit_ci_workflows/test_deploy_watchdog.py::test_all_legs_rate_limited_is_not_mechanism_failure_but_is_loud
  RATE="$(awk -F'\t' '$2 == "ratelimited" { printf "%s ", $1 }' "$WATCHDOG_STATE" 2>/dev/null || true)"
  RATE="${RATE% }"; RATE_COUNT=0; for _m in $RATE; do RATE_COUNT=$((RATE_COUNT + 1)); done
  if [ "$RATE_COUNT" -gt 0 ] && [ -z "${RATE_WARNED:-}" ]; then
    RATE_WARNED=1
    echo "::warning::本轮被限流：${RATE_COUNT} 条腿未对账（**非机制故障**）——${RATE}；下一轮对账会自然重试"
    echo "| — | ⚠️ 本轮被限流，未对账 | 🔶 \`${RATE}\`（**非机制故障**：本轮没对账成功，不是状态机没记它） |" >> "${SUMMARY:-/dev/null}"
  fi
}
# 对账步的**最后一道闸**：任一腿**没落状态**（= 种子位 `unrecorded` 没被替换）⇒ 本步判红
# （退出码 3）并**具名到腿** —— 判据 1：不许把「缺状态」甩给下游 fail-closed 兜。
# 调用点在对账步正文里、**存活读数之后** —— 先让读数（含具名清单）出去，再判红。
watchdog_missing_gate() {
  watchdog_missing
  local rc=0
  if [ "$MISS_COUNT" -gt 0 ]; then
    echo "::error::对账步没为 ${MISS_COUNT} 条腿落状态：${MISS}（机制故障，具名到腿）"
    echo "| — | ⚠️ 对账状态缺失 | 🔴 \`${MISS}\`（机制故障，具名到腿） |" >> "${SUMMARY:-/dev/null}"
    rc=3
  fi
  # 对账**中止**（`aborted`，**非**限流）⇒ 这条腿判不了 ⇒ 与本函数上面那类同属机制故障
  # （issue #9310）：逐腿兜底让**其它腿照样跑完**，但本步**最终仍必须判红** ——
  # 兜底治的是「一条腿不许打死整步」，**不是**「失败可以被放过」（fail-closed 只细化分类，不放宽）。
  ABORTED_LEGS="$(awk -F'\t' '$2 == "aborted" { printf "%s ", $1 }' "$WATCHDOG_STATE" 2>/dev/null || true)"
  ABORTED_LEGS="${ABORTED_LEGS% }"; ABORTED_COUNT=0
  for _m in $ABORTED_LEGS; do ABORTED_COUNT=$((ABORTED_COUNT + 1)); done
  if [ "$ABORTED_COUNT" -gt 0 ]; then
    echo "::error::对账步有 ${ABORTED_COUNT} 条腿**中止**（aborted，非限流）：${ABORTED_LEGS}（机制故障，具名到腿）"
    echo "| — | ⚠️ 对账中止 | 🔴 \`${ABORTED_LEGS}\`（机制故障：非限流的失败，具名到腿） |" >> "${SUMMARY:-/dev/null}"
    rc=3
  fi
  return "$rc"
}
