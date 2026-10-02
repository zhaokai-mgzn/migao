#!/usr/bin/env bash
# 值守面状态台账：**每条对账腿恰好一行**（issue #5935；消费点在 `.github/workflows/deploy-reconcile.yml`
# 的 `Reconcile deploys` 步，由它 `source` 本文件）。
#
# 用法（在被 source 的 shell 里，取 `$0` = 那份 workflow 文件）：
#   source scripts/deploy_reconcile_state.sh
#   watchdog_note <腿> <状态> <依据>            # 每条腿**至少**调一次（整行替换，不追加）
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

# ── 判据 1 / 2（issue #5935）：「落状态」本身有判据 + 零动作必须归因 ─────────────────────
# `seen=6 acted=0` 且原因桶全 0 之所以出现过（run `36911070357`），是因为**状态落了、但落的是错的**
# （六条腿 100% 命中同一条坏分支）—— 形态学判据看不见「落了错的状态」。⇒ 读**状态文件的实际内容**：
# 仍是 `unrecorded` 的腿 = 本轮**从未**被记过（种子位没被替换）⇒ 由本步**自己判红并具名**，
# 不许把「缺状态」甩给下游 fail-closed 兜（判据 1）；具名清单同时进存活读数（判据 2）。
watchdog_missing() {   # 把「没落状态」的腿具名写进两个全局（调用方用 $MISS / $MISS_COUNT）
  # ⚠️ 判据面**只**是 `unrecorded`（种子位没被替换）与空：`notarget` / `deployed` / `inflight` /
  # `terminal` / `dispatched` 都是**已落**的合法状态 ⇒ 一条腿只要落过其中任一条就不算「没落」。
  # （把 `notarget` 也算成机制故障 = 让「新增腿的那个 PR」每轮判红 —— 那是 #5929 明确避开的噪声。）
  MISS="$(awk -F'\t' '$2 == "unrecorded" || $2 == "" { printf "%s ", $1 }' "$WATCHDOG_STATE" 2>/dev/null || true)"
  MISS="${MISS% }"; MISS_COUNT=0; for _m in $MISS; do MISS_COUNT=$((MISS_COUNT + 1)); done
}
# 对账步的**最后一道闸**：任一腿**没落状态**（= 种子位 `unrecorded` 没被替换）⇒ 本步判红
# （退出码 3）并**具名到腿** —— 判据 1：不许把「缺状态」甩给下游 fail-closed 兜。
# 调用点在对账步正文里、**存活读数之后** —— 先让读数（含具名清单）出去，再判红。
watchdog_missing_gate() {
  watchdog_missing
  [ "$MISS_COUNT" -gt 0 ] || return 0
  echo "::error::对账步没为 ${MISS_COUNT} 条腿落状态：${MISS}（机制故障，具名到腿）"
  echo "| — | ⚠️ 对账状态缺失 | 🔴 \`${MISS}\`（机制故障，具名到腿） |" >> "${SUMMARY:-/dev/null}"
  return 3
}
