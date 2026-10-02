#!/usr/bin/env bash
# =============================================================================
# batch-gate.sh — 批次统一验证入口：**N 个包只跑一次全量 `gate`**（issue #6012）
#
# ## 治的形态（2026-10-02 17:24–17:29 CST 现场，读数现取，不是推断）
#
#   机器级重活锁：1 个 `gate` 持锁、**7 个 gate 在跑**（6 个在排队：已等 40 / 31 / 20 / 12 / 7 / 2 分钟）、
#   日志里最高排队读数 `已等 2354s / 上限 2400s`；`load average` **21.6 / 43.6 / 61.3**（8 核）。
#   ⇒ 类级病 = **「每个包各自跑一遍全量」× 「本机 8 核只装得下一份全量」**。
#   排他锁（`machine-heavy-lock.sh`，#5814/#5863）治的是 CPU 争用，治不了「份数」。
#
#   本命令治**份数**：把 N 个包合到一个**集成工作区**，全量只跑**一次**。
#   实测对照（同一天）：现状 = N × gate（单包进程寿命 49 分钟，其中 33 分钟在等锁）；
#   本命令 = merge N 次 + gate **1** 次。
#
# ## 为什么「一次」是这条命令的全部意义
#
#   `gate` 档里唯一的重活是 `ci workflow helper 判据集`（整目录 `tests/unit_ci_workflows`），
#   而它的触发面 = 变更集命中 `.github/**` 或 `tests/unit_ci_workflows/**` —— 今天的包**几乎每个**
#   都在加类级判据/台账（AGENTS.md 铁律 8）⇒ 每包都必然触发那条最重的腿。故「N 份全量」是
#   **结构性**的，不是偶发。集成层本来就是这些判据互相影响的地方 ⇒ 一次跑在**合起来之后**更有效。
#
# ## 就绪前置判定（`--require-ready`，默认**开启**；issue #6028）
#
#   治的形态（2026-10-02 实测）：`#6003` / `#6005` 这类**与 base 冲突（GitHub 侧 DIRTY）**的包被拉进批次
#   ⇒ 集成结果必然红、且红在**别人**身上（面级归因指向错误对象）⇒ 白烧一次全量。
#   「一次全量」这么贵 ⇒ 先把「明知会红」的包挡在门外。
#
#   跑那一次全量**之前**，逐包做两条判定（任一不就绪 ⇒ **拒绝**，exit 3，**不跑**全量）：
#     ① **无冲突**（离线可判，必做）：`git merge-tree --write-tree <base> <head>`
#        （**只读**：不落工作区、不改索引）。有冲突 ⇒ 提示先同步主线。
#     ② **required 全绿**（需 `gh` + 网络）：`gh pr list --head <branch> --state open` 取 PR 号，
#        再 `gh pr checks <PR> --json name,state,bucket`；有 `fail` / `pending` ⇒ 提示等 CI 或先修红；
#        **找不到对应 PR** ⇒ 提示先开 PR。
#
#   三态口径（**不许糊**）：
#     - **明确不就绪** ⇒ 拒绝（exit 3）+ 逐包打印**判定依据**（哪条不满足 / 现取读数 / 下一步命令）；
#     - **无法判定**（`gh` 不存在 / 无凭据 / 网络不可用 / 取不到 base ref / `gh` 输出不可解析）
#       ⇒ **fail-closed 拒绝**（exit 3），输出里**具名**写「无法判定 ≠ 就绪」；
#     - 只有**显式** `--no-require-ready` 才跳过这套判定（逃生口；跳过时**必须打印**未跑声明）。
#
# ## 用法
#
#   ./scripts/batch-gate.sh <branch> [<branch> ...]   # 建临时集成 worktree → 串行 merge → **一次** gate → 逐包归因
#   ./scripts/batch-gate.sh --in <worktree> <branch> ...   # 在**既有**集成 worktree 里只跑那一次（环境已备时用）
#   ./scripts/batch-gate.sh --keep <branch> ...       # 保留集成 worktree（默认结束即删）
#   ./scripts/batch-gate.sh --base <ref> <branch> ... # 换基准（默认 origin/main）
#   ./scripts/batch-gate.sh --no-require-ready <branch> ...  # 逃生口：跳过就绪判定（人类明知故犯时用）
#
#   环境变量：`MIGAO_HEAVY_WAIT=<秒>`（默认 2700）—— 透传给 gate 的排队上限。
#
#   ⚠️ **就绪判定只有一个逃生口**：显式 `--no-require-ready`（可见、在命令行里、必打印未跑声明）。
#   有意**不做**环境变量逃生口：本命令**没有**任何程序化调用点（过渡期不存在），多一个环境变量
#   只会多一个**无判据的分支** + 一个静默逃生口；本仓刚按 #6056 删掉一个不可见的环境变量逃生口
#   （`MIGAO_BATCH_GATE_SKIP_READY`，YAGNI + 不可见）—— 这里沿用同一口径。
#
# ## 批次标记（`migao-package-heavy-entry-allow`，issue #6084）
#
#   本命令是**合法**在 worktree 里跑全量的那一方 ⇒ 它必须留下**可现取的证据**，否则
#   `verify-all.sh` 的角色判定（见 `verify-all.sh` 的 `package_heavy_guard`）只能靠猜。
#   故本命令在它造出的 / `--in` 指到的工作区里写一个标记文件，路径由 `git rev-parse --git-path`
#   现取（默认落在该工作树的**管理目录** `.git/worktrees/<name>/` 下 —— **不在工作树里**，
#   因此不进 `git status`、不会被 `git add -A` 提交，`git worktree remove` 时随之消失）。
#   ⛔ 有意**不**用名字前缀（`--in <任意路径>` 形态不叫 `batch-*` ⇒ 按名字判会误拒合法的集成面）
#   与环境变量（**可被子包自己 export** ⇒ 等于让被判对象自报「我是谁」）。
#
# ## 退出码（三态，与 merge_gate.py / stranding-check.sh 同口径）
#
#   0 = 那一次 gate 全绿
#   1 = 红（**整合冲突** / gate 非零）—— 冲突时**不跑** gate：「没跑」必须长得像「没跑」
#   3 = 无法判定（分支不存在 / 包不就绪 / 就绪判定无法判定 / 建不出 worktree / gate 自己 exit 3）
#       —— **不得当 0 读**
#
# ## 边界（照实登记）
#
#   - **就绪判定 ≠ 合并后 main 健康**：`merge-tree` 判的是「此刻 head vs base 的文本冲突」，
#     不含语义冲突、不含 CI 之后的 base 前进（判定与跑全量之间主线仍可能动）。
#   - **「无法判定即拒绝」会挡住合法场景**（照实登记）：`gh` 未登录 / 断网 / API 限流时，
#     **即使完全就绪的批次也会被拒**。出口 = 修好凭据/网络重跑，或人类显式 `--no-require-ready`。
#   - **要求的口径** = `gh pr checks <PR>` 报出的**全部** check（非仅 required 集合）—— 比对「只在
#     required 集合上判」更严；更严是**安全**方向，代价 = 可能挡住「required 全绿而非 required 有
#     存量债」的批次（同 `migao-dev-flow` §2.2 v1.98.0 的存量债形态）。
#   - 归因是**面级映射**（算的是「这个包碰没碰失败腿的触发面」），**不是**「这个包就是真凶」的证明；
#     面内多于一个包时**不许**指认唯一真凶，具名打印 `无法唯独归因`。
#   - 集成 worktree 里 merge ≠ GitHub squash 合并后的 main，是**起飞前**的近似（冲突照实报）。
#   - 本脚本**不自己拿锁**：那一次全量由 `verify-all.sh gate` 自己 acquire/release（#5814 接线）。
#   - 本脚本**不改**任何门禁的通过条件、不新增豁免；CI 仍是权威。
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${BATCH_GATE_BASE:-origin/main}"
KEEP=0
IN_WT=""
BRANCHES=()
READY=1

while [ $# -gt 0 ]; do
  case "$1" in
    --in)   IN_WT="${2:-}"; [ -n "$IN_WT" ] || { echo "用法: $0 --in <worktree>" >&2; exit 2; }; shift 2 ;;
    --base) BASE="${2:-}"; [ -n "$BASE" ] || { echo "用法: $0 --base <ref>" >&2; exit 2; }; shift 2 ;;
    --keep) KEEP=1; shift ;;
    --require-ready)    READY=1; shift ;;
    --no-require-ready) READY=0; shift ;;
    # --help = 文件头**全部**注释行（写到「第一行非注释」为止）。⛔ 别写死行数区间：
    # 头部长一英寸就被静默截断（本包加「就绪判定」段后就截到了「## 退出码」标题、0/1/3 三态看不见了）。
    -h|--help) awk '/^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"; exit 0 ;;
    -*)     echo "未知参数：$1（用法见 $0 --help）" >&2; exit 2 ;;
    *)      BRANCHES+=("$1"); shift ;;
  esac
done

if [ "${#BRANCHES[@]}" -eq 0 ]; then
  echo "用法: $0 <branch> [<branch> ...] ｜ $0 --in <worktree> <branch> ..." >&2
  echo "      （本命令的全部意义 = 让这批包的全量**只跑一次**，见文件头）" >&2
  exit 2
fi

TMP="$(mktemp -d)"
WT=""
OWNS_WT=0
cleanup() {
  if [ "$OWNS_WT" = 1 ] && [ "$KEEP" = 0 ]; then
    git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

# 无法判定 ⇒ 出声 + 非零（**不是**「通过」）
die() { echo "❌ $*" >&2; echo "exit=3（无法判定 —— 不是「通过」）" >&2; exit 3; }

#: 批次集成 worktree 的**标记文件名** —— 与 `verify-all.sh` 的角色判定共用同一个约定
#: （那边只读、这边只写；名字变了两边一起变）。
MARKER_NAME="migao-package-heavy-entry-allow"

# ── 1.4) 给集成工作区**留标记**（issue #6084）─────────────────────────────────
#
# 为什么要有这个标记：`verify-all.sh` 现在会**拒绝**在**子包 worktree** 里直跑全量（那一次全量
# 属于**批次**）。而本命令恰恰是**合法**在 worktree 里跑全量的那一方 ⇒ 必须在它造出的（或
# `--in` 指到的）工作区里留下**可现取的证据**，否则角色判定只能靠猜。
#
# 为什么是**标记文件**、不是名字前缀 / 环境变量（与 `verify-all.sh` 同一段理由，这里只留结论）：
#   · 名字前缀会漂 —— `--in <任意路径>` 建出来的集成工作区**不叫** `batch-*`；
#   · 环境变量可被**被判对象自己 export** ⇒ 等于让「我是谁」自报，判据就没意义了（本仓刚按
#     #6056 删掉一个不可见的环境变量逃生口）。
# 位置由 `git rev-parse --git-path` 现取（= `.git/worktrees/<name>/…`）：**不在工作树里**
# ⇒ 不进 `git status` / 不会被 `git add -A` 提交 / `git worktree remove` 时随之消失。
#
# 幂等：标记已存在 ⇒ 内容一字不改（重复调用等价）。写不进去 ⇒ `die`（无法判定，不是「没标记」）：
# 让「标记没留成」退化成「拒绝跑全量」，正是本块要防的方向。
mark_package_heavy_entry() {
  local wt="$1" marker
  marker="$(git -C "$wt" rev-parse --git-path "$MARKER_NAME" 2>/dev/null || true)"
  [ -n "$marker" ] || die "取不到集成工作区的标记路径（git rev-parse --git-path ${MARKER_NAME}）：${wt}"
  [ -e "$marker" ] && return 0                        # 幂等
  printf 'batch-integration\n# 由 scripts/batch-gate.sh 写入（issue #6084）：本工作区被授权跑那一批**唯一一次**全量。\n# 读取方 = verify-all.sh 的 package_heavy_guard（只读）。删除本文件 ⇒ 该工作区立刻被当成子包 worktree 拒绝。\n' \
    > "$marker" 2>/dev/null || die "标记写不进去：${marker}（工作区：${wt}）"
  echo "  🔑 已留批次标记：${marker}（= 本工作区被授权跑那一次全量；verify-all.sh 的判别读它，不读名字）"
}

# ── 1) 解析每个包分支到 commit（本地优先，其次 origin/<branch>）────────────────
for b in "${BRANCHES[@]}"; do
  sha="$(git -C "$ROOT" rev-parse --verify --quiet "${b}^{commit}" \
      || git -C "$ROOT" rev-parse --verify --quiet "origin/${b}^{commit}" || true)"
  # ⚠️ 变量后紧跟中文必须用 ${var} 包裹：macOS bash 3.2 会把中文首字节并入变量名（同 dev-worktree.sh）
  [ -n "$sha" ] || die "分支不存在（本地与 origin 都没有）：${b}"
  printf '%s\t%s\n' "$b" "$sha" >> "$TMP/branches.tsv"
done

BASE_SHA="$(git -C "$ROOT" rev-parse --short "$BASE" 2>/dev/null || echo '?')"
echo "批次数：${#BRANCHES[@]} 个包｜基准：${BASE}@${BASE_SHA}"
echo "包：${BRANCHES[*]}"

# ══════════════════════════════════════════════════════════════════════════════
# 1.5) **就绪前置判定**（issue #6028）—— 在跑那一次全量**之前**
#
#   为什么放在这里：全量是这一批**唯一一次**、也是最贵的一步。明知有 DIRTY 包（与 base 冲突）
#   或 CI 未绿的包拉进来，只会「必然红 + 归因指向别人」⇒ 白烧。**拒绝必须发生在花钱之前**。
#   判定**只读**：`git merge-tree --write-tree` 不落工作区、不改索引；`gh` 只查不写。
#   三态各写一行到 ready.txt（`o` 就绪 / `x` 明确不就绪 / `?` **无法判定**），供下面统一打印与判红。
# ══════════════════════════════════════════════════════════════════════════════
READY_TXT="$TMP/ready.txt"
: > "$READY_TXT"
ready_ok()    { printf 'o\t%s\t%s\n' "$1" "$2" >> "$READY_TXT"; }
not_ready()   { printf 'x\t%s\t%s\n' "$1" "$2" >> "$READY_TXT"; }
undecidable() { printf '?\t%s\t%s\n' "$1" "$2" >> "$READY_TXT"; }

#: 同步主线的出口命令（真可行动）
SYNC_CMD='./scripts/sync-main.sh --rebase'

#: gh 输出 → 单值。三态：0 = 正常（stdout 是结论）；2 = **输出不可解析**（= 无法判定）
#: ⚠️ 空白输入（含 `<<<""` 送来的**单个换行**）必须走「无法判定」，不许当成空数组 —— 那是假绿方向。
_gh_json_pick() {
  python3 -c '
import json, sys
raw = sys.stdin.read()
if not raw.strip():
    sys.exit(2)
try:
    data = json.loads(raw)
except Exception:
    sys.exit(2)
if not isinstance(data, list):
    sys.exit(2)
if len(sys.argv) > 1 and sys.argv[1] == "numbers":
    nums = [i.get("number") for i in data if isinstance(i, dict) and isinstance(i.get("number"), int)]
    print(nums[0] if nums else "")
else:
    if not data:
        print("EMPTY"); raise SystemExit(0)
    fail = [i.get("name", "?") for i in data
            if (i.get("bucket") or "") in ("fail", "cancel", "cancelled", "skipping")]
    pend = [i.get("name", "?") for i in data if (i.get("bucket") or "") == "pending"]
    if fail:
        print("FAIL " + str(len(data)) + " 条 check；红：" + "、".join(fail[:6]))
    elif pend:
        print("PENDING " + str(len(data)) + " 条 check；未完成：" + "、".join(pend[:6]))
    else:
        print("OK " + str(len(data)) + " 条 check 全绿")
' "$@"
}

check_one_package() {
  local b="$1" sha="$2" out rc prlist pr checks verdict

  # ── ① 无冲突（离线；`git merge-tree --write-tree` **只读**）──────────────────
  # 退出码语义（git-merge-tree 文档）：0 = 干净合并（stdout 是 tree oid）；
  #                                1 = 有冲突（stdout 是 tree oid、stderr 是冲突消息）；
  #                                >1 = 自身失败（base 无法解析 / 历史不相干 …）⇒ **无法判定**。
  out="$(git -C "$ROOT" merge-tree --write-tree --name-only "$BASE" "$sha" 2>"$TMP/mt.err")"
  rc=$?
  if [ "$rc" -eq 0 ]; then
    : # 无冲突，继续判 PR
  elif [ "$rc" -eq 1 ]; then
    # stdout = tree oid + 冲突路径（`--name-only` 时从第 2 行起是路径）
    local paths
    paths="$(printf '%s\n' "$out" | sed -n '2,7p' | tr '\n' ' ')"
    not_ready "$b" "与基准 ${BASE} 有冲突（git merge-tree --write-tree 退出码 1；冲突路径：${paths:-见 stderr}）｜下一步：${SYNC_CMD}"
    return
  else
    undecidable "$b" "冲突判定跑不动（git merge-tree --write-tree 退出码 ${rc}；stderr：$(head -1 "$TMP/mt.err" 2>/dev/null)）—— 无法判定 ≠ 就绪"
    return
  fi

  # ── ② required 全绿（需 gh + 网络）─────────────────────────────────────────
  if ! command -v gh >/dev/null 2>&1; then
    undecidable "$b" "gh 不存在 ⇒ 取不到该包的 PR 状态 —— 无法判定 ≠ 就绪（装好 gh 再跑，或显式 --no-require-ready）"
    return
  fi

  prlist="$(gh pr list --head "$b" --state open --json number 2>"$TMP/gh.err")"
  rc=$?
  if [ "$rc" -ne 0 ]; then
    undecidable "$b" "gh pr list 失败（无凭据 / 网络不可用？stderr：$(head -1 "$TMP/gh.err" 2>/dev/null)）—— 无法判定 ≠ 就绪"
    return
  fi
  pr="$(_gh_json_pick numbers <<<"$prlist")"
  rc=$?
  if [ "$rc" -eq 2 ]; then
    undecidable "$b" "gh pr list 输出不可解析（不是 JSON 数组）—— 无法判定 ≠ 就绪"
    return
  fi
  if [ -z "$pr" ]; then
    not_ready "$b" "没有对应的 open PR（gh pr list --head ${b} --state open 为空）｜下一步：先开 PR"
    return
  fi

  checks="$(gh pr checks "$pr" --json name,state,bucket 2>"$TMP/ghc.err")"
  rc=$?
  if [ "$rc" -ne 0 ]; then
    undecidable "$b" "gh pr checks ${pr} 失败（无凭据 / 网络不可用 / 限流？stderr：$(head -1 "$TMP/ghc.err" 2>/dev/null)）—— 无法判定 ≠ 就绪"
    return
  fi
  verdict="$(_gh_json_pick <<<"$checks")"
  rc=$?
  if [ "$rc" -eq 2 ]; then
    undecidable "$b" "gh pr checks 输出不可解析（不是 JSON 数组）—— 无法判定 ≠ 就绪"
    return
  fi
  case "$verdict" in
    "OK "*      ) ready_ok    "$b" "PR #${pr}；${verdict#OK }" ;;
    "FAIL "*    ) not_ready   "$b" "PR #${pr}；${verdict#FAIL } ｜下一步：等 CI 或先修红（gh pr checks ${pr}）" ;;
    "PENDING "* ) not_ready   "$b" "PR #${pr}；${verdict#PENDING } ｜下一步：等 CI 绿（gh pr checks ${pr} --watch）" ;;
    *           ) undecidable "$b" "PR #${pr}；没有上报任何 check（起飞前的 PR？）—— 无法判定 ≠ 就绪" ;;
  esac
}

if [ "$READY" = 1 ]; then
  echo "── 就绪前置判定（--require-ready 默认开启；issue #6028）──"
  if git -C "$ROOT" rev-parse --verify --quiet "${BASE}^{commit}" >/dev/null 2>&1; then
    while IFS=$'\t' read -r b sha; do
      check_one_package "$b" "$sha"
    done < "$TMP/branches.tsv"
  else
    # 取不到基准 ⇒ 两条判定都做不了 ⇒ **无法判定**（fail-closed，≠ 就绪）
    for b in "${BRANCHES[@]}"; do
      undecidable "$b" "取不到基准 ${BASE}（git rev-parse ${BASE} 失败）—— 无法判定 ≠ 就绪"
    done
  fi

  blocked=0
  while IFS=$'\t' read -r mark b why; do
    case "$mark" in
      o) echo "  ✅ ${b}：${why}" ;;
      x) echo "  ❌ ${b}（不就绪）：${why}"; blocked=1 ;;
      ?) echo "  ❓ ${b}（**无法判定 ≠ 就绪**）：${why}"; blocked=1 ;;
    esac
  done < "$READY_TXT"

  if [ "$blocked" = 1 ]; then
    echo "⛔ 有包未通过就绪判定 ⇒ **拒绝**，**没有跑**那一次全量（没跑 ≠ 通过、≠ 全绿）。"
    echo "   出口（三选一）：① 按上面逐包的「下一步」修好再重跑；② 修不了 ⇒ 把该包移出本批；"
    echo "                   ③ 人类明知故犯 ⇒ 显式 --no-require-ready（跳过判定，风险自负）"
    echo "   ⚠️ 「无法判定」是 fail-closed 的**拒绝**，不是「就绪」—— 别把 ❓ 读成 ✅。"
    exit 3
  fi
  echo "  ⇒ 全部 ${#BRANCHES[@]} 个包就绪（无冲突 + PR checks 全绿）"
else
  echo "⏭️ 就绪判定未跑（--no-require-ready）—— 这不是「就绪」"
  echo "   ⇒ 本批**可能**含与基准冲突（DIRTY）或 CI 未绿的包；那次全量的红**未必**是集成引入的。"
fi

# ── 2) 集成工作区 + 串行 merge（合并串行 = §17.1 第 4 步）───────────────────────
if [ -n "$IN_WT" ]; then
  WT="$IN_WT"
  [ -d "$WT" ] || die "--in 的目录不存在：${WT}"
  echo "集成工作区（既有）：${WT}"
else
  WT="$ROOT/../migao-wt/batch-$(date +%m%d-%H%M%S)"
  git -C "$ROOT" worktree add --detach "$WT" "$BASE" >/dev/null 2>&1 \
    || die "建不出集成 worktree（${WT}；基准 ${BASE} 可解析吗）"
  OWNS_WT=1
  echo "集成工作区（临时，结束即删；--keep 保留）：${WT}"
fi
# ⚠️ 标记在**跑全量之前**留（verify-all.sh 的 package_heavy_guard 会读它）；`--in` 与自建**都要**
#    —— 两种形态都是「合法在 worktree 里跑那一次全量」。
mark_package_heavy_entry "$WT"

merge_failed=""
while IFS=$'\t' read -r b sha; do
  if git -C "$WT" merge --no-edit --no-ff "$sha" >"$TMP/merge.log" 2>&1; then
    echo "  merge ✅ ${b}"
  else
    git -C "$WT" merge --abort >/dev/null 2>&1 || true
    echo "  merge ❌ ${b}（整合冲突）—— 冲突行："
    grep -E '^CONFLICT' "$TMP/merge.log" | sed 's/^/     /' | head -10
    merge_failed="$b"
    break
  fi
done < "$TMP/branches.tsv"

if [ -n "$merge_failed" ]; then
  echo "⛔ 整合失败（${merge_failed}）⇒ **没有跑**那一次 gate。没跑 ≠ 通过。"
  echo "   出口：解冲突（./scripts/sync-main.sh --rebase 或人工）后重跑本条命令"
  [ "$OWNS_WT" = 1 ] && echo "   集成工作区：${WT}（加 --keep 可保留现场）"
  exit 1
fi

# ── 3) **那一次**全量（本命令的全部意义；锁由 verify-all.sh gate 自己拿）────────
LOG="$TMP/gate.log"
echo "── 一次 gate（本批唯一一次全量；MIGAO_HEAVY_WAIT=${MIGAO_HEAVY_WAIT:-2700}）──"
( cd "$WT" && MIGAO_HEAVY_WAIT="${MIGAO_HEAVY_WAIT:-2700}" ./verify-all.sh gate ) >"$LOG" 2>&1
gate_rc=$?
tail -30 "$LOG" | sed 's/^/  | /'

# ── 4) 逐包归因（面级映射；多于一个候选 ⇒ 不指认唯一真凶）──────────────────────
python3 - "$TMP" "$BASE" "$ROOT" "$LOG" <<'PY'
import re, subprocess, sys, pathlib

tmp, base, root, log_path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
branches = [ln.split("\t") for ln in pathlib.Path(tmp, "branches.tsv").read_text().split("\n") if ln]
log = pathlib.Path(log_path).read_text(errors="ignore")

#: 面 → 触发前缀（与 verify-all.sh 的 *_face_paths() 同源语义；这里是**归因用**的粗映射）
FACES = [
    ("ci workflow helper", (".github/", "tests/unit_ci_workflows/")),
    ("cases 面门禁", (".github/cases/", ".github/case-trust-", "tests/agent_eval/eval_cases.py",
                    "docs/testing/mibao-verification-cases.md")),
    ("bmini-app", ("frontend/bmini-app/", "frontend/admin-web/src/lib/print-media.json")),
    ("admin-api", ("backend/admin-api/",)),
    ("ai-agent", ("backend/ai-agent-service/",)),
    ("admin-web", ("frontend/admin-web/",)),
]

files = {}
for name, sha in branches:
    out = subprocess.run(["git", "-C", root, "diff", "--name-only", f"{base}...{sha}"],
                         capture_output=True, text=True).stdout
    files[name] = [f for f in out.split("\n") if f]

print("── 逐包改动面 ──")
for name, sha in branches:
    fs = files[name]
    print(f"  {name}: {len(fs)} 个文件" + (f"（{', '.join(fs[:4])}{' …' if len(fs) > 4 else ''}）" if fs else ""))

def candidates(prefixes):
    return [n for n, _ in branches if any(f.startswith(prefixes) for f in files[n])]

fails = [ln.strip() for ln in log.split("\n")
         if ln.strip().startswith("❌") or ln.strip().startswith("失败项:")]
print("── 逐包归因（面级映射，不是「真凶」的证明）──")
if not fails:
    print("  本次没有具名失败项（gate 全绿或未产出失败项）")
seen = set()
for f in fails:
    if f in seen:
        continue
    seen.add(f)
    hit = [name for name, segs in FACES if name in f]
    print(f"  失败项：{f}")
    if not hit:
        print("     面：**无法映射**（不认识这项）⇒ 不猜，见上面的失败项原文")
        continue
    for h in hit:
        cands = candidates(dict(FACES)[h])
        print(f"     面：{h}（触发前缀：{'、'.join(dict(FACES)[h])}）")
        if not cands:
            print("     面内包：**无**（本批没有包碰这个面 ⇒ 该红可能来自基准侧或环境）")
        elif len(cands) == 1:
            print(f"     面内包（可能引入方）：{cands[0]}")
        else:
            print(f"     面内包：{'、'.join(cands)} —— **无法唯独归因**（面内多于一个包）")
PY
attr_rc=$?

echo "── 结论 ──"
if [ "$gate_rc" -eq 0 ]; then
  echo "✅ 本批 ${#BRANCHES[@]} 个包 = **1 次** gate（绿）。判别力：包数变而 gate 调用数不变。"
  exit 0
fi
if [ "$gate_rc" -eq 3 ]; then
  echo "⚠️ 那一次 gate exit=3（**无法判定**：零变更 / 门禁未就绪等）—— 不得当「通过」读。"
  exit 3
fi
echo "❌ 那一次 gate exit=${gate_rc} ⇒ 本批未通过（逐包归因见上；面级映射 ≠ 真凶证明）"
[ "$attr_rc" -ne 0 ] && echo "   （归因段自身退出码非零：${attr_rc}）"
exit 1
