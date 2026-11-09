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
# ## 就绪前置判定（`--require-ready`，默认**开启**；issue #6055 / PR #6056）
#
#   治的形态（2026-10-02 实测）：`#6003` / `#6005` 这类**与 base 冲突（GitHub 侧 DIRTY）**的包被拉进批次
#   ⇒ 集成结果必然红、且红在**别人**身上（面级归因指向错误对象）⇒ 白烧一次全量。
#   「一次全量」这么贵 ⇒ 先把「明知会红」的包挡在门外。
#
#   跑那一次全量**之前**，逐包做三条判定（任一不就绪 ⇒ **拒绝**，exit 3，**不跑**全量）：
#     ① **无冲突**（离线可判，必做）：`git merge-tree --write-tree <base> <head>`
#        （**只读**：不落工作区、不改索引）。有冲突 ⇒ 提示先同步主线。
#     ② **required 全绿**（需 `gh` + 网络）：`gh pr list --head <branch> --state open` 取 PR 号，
#        再 `gh pr checks <PR> --json name,state,bucket`；有 `fail` / `cancel` / `pending`
#        ⇒ 提示等 CI 或先修红；**`skipping` 与 `state=CANCELLED` 都不算红**（本仓 CI 按变更面**有意跳过**无关腿，
#        见 #6160/#6170；把它当红会让单模块包**恒不就绪** ⇒ 本条修的是 issue #6216），
#        但 skipping **只计数、不静默**（输出里显式写「另有 N 条 skipping」）；
#        **找不到对应 PR** ⇒ 提示先开 PR。
#     ③ **auto-merge 未 arm**（需 `gh` + 网络；issue #6212）：`gh pr view <PR> --json autoMergeRequest`
#        非 null ⇒ **不就绪**，并给可复制的解除命令 + **回读**命令（`--check-arm`，见「用法」）。
#        为什么这条必须进这道门：本仓 `automerge.yml` 恰在「**非 draft**」时 arm 原生 auto-merge，
#        而本判定 ② 又要求非 draft（draft 的 leg 不全 ⇒ pending）⇒「集成期非 draft」这个前提本身
#        就打开了「跑全量期间被秒合」的窗口（实测：转 ready → arm **17 秒**、arm → 合并 **4 分 26 秒**，
#        人来不及在窗口内核实）。且 `--disable-auto` **不是**可靠控制 —— 一次 push 触发的 `synchronize`
#        会让 `automerge.yml` **重新 arm**（#4829 实证）；`block/merge` 标签也拦不住**已 arm** 的
#        auto-merge。⇒ 唯一可靠的做法是**跑之前就判**：已 arm ⇒ 拒绝（先 disarm，再回读确认）。
#
#   三态口径（**不许糊**）：
#     - **明确不就绪** ⇒ 拒绝（exit 3）+ 逐包打印**判定依据**（哪条不满足 / 现取读数 / 下一步命令）；
#     - **无法判定**（`gh` 不存在 / 无凭据 / 网络不可用 / 取不到 base ref / `gh` 输出不可解析 /
#       读不到 `autoMergeRequest` —— 读不到**不许**当「未 arm」）
#       ⇒ **fail-closed 拒绝**（exit 3），输出里**具名**写「无法判定 ≠ 就绪」；
#     - 只有**显式** `--no-require-ready` 才跳过这套判定（逃生口；跳过时**必须打印**未跑声明）。
#
# ## 用法
#
#   ./scripts/batch-gate.sh <branch> [<branch> ...]   # 建临时集成 worktree → 串行 merge → **一次** gate → 逐包归因
#   ./scripts/batch-gate.sh --in <worktree> <branch> ...   # 在**既有**集成 worktree 里只跑那一次（环境已备时用）
#   ./scripts/batch-gate.sh --keep <branch> ...       # 保留集成 worktree（默认结束即删）
#   ./scripts/batch-gate.sh --install-deps <branch> ...  # 集成工作区缺前端依赖 ⇒ **先 npm ci 备妥**再跑（默认只判不装）
#   ./scripts/batch-gate.sh --base <ref> <branch> ... # 换基准（默认 origin/main）
#   ./scripts/batch-gate.sh --no-require-ready <branch> ...  # 逃生口：跳过就绪判定（人类明知故犯时用）
#   ./scripts/batch-gate.sh --check-arm <PR> [<PR> ...]  # **回读** auto-merge 解除结果（幂等只读；disarm 后当场核对）
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
#   3 = 无法判定（分支不存在 / 包不就绪 / 就绪判定无法判定 / 建不出 worktree / gate 自己 exit 3 /
#       **环境缺失**：集成工作区缺前端依赖且本批命中该面 —— 见下节「归因分层」）
#       —— **不得当 0 读**
#
#   `--check-arm` **不复用**上面三态（它是回读，不是批次结论）：
#     0 = 未 arm（可进批次）｜1 = **仍 arm**（解除没生效）｜3 = 无法判定（读不到 ≠ 未 arm）
#
# ## 归因分层（**环境缺失 / 代码问题 / 无法判定 —— 三者不许混**；issue #6834）
#
#   批次结论必须一眼分清「谁的锅」，否则人会去查错对象（本单就是这么白烧了一次全量）：
#
#   | 归因 | 含义 | 退出码 | 承载体 |
#   |---|---|---|---|
#   | **环境缺失** | 集成工作区缺**依赖**（新检出没有 `node_modules`；不是任何包的代码问题） | **3** | 第 2.5 段的依赖备妥判定（具名「环境缺失」） |
#   | **代码问题** | 判据**真跑**且真红（整合冲突 / gate 非零） | **1** | 第 2 段的 merge / 第 3 段的 gate |
#   | **无法判定** | 读不到分支 / 就绪判定跑不动 / 建不出 worktree / gate 自己 exit 3 | **3** | `die`、就绪判定、第 3 段 |
#
#   ⚠️ 环境缺失**不**落到 1：落到 1 就等于对读者宣布「这批包里有代码问题」，而归因段会把矛头指向
#   「碰了那个面的包」（issue #6834 的现场读数正是如此）。它也不落到 0 —— 「没判定」不是「通过」。
#   两种「3」靠**输出里的具名词**区分（`环境缺失` vs `无法判定`），故本命令的每一条 3 都必须带具名理由。
#
# ## 集成工作区的依赖备妥（issue #6834）
#
#   病（2026-10-13 实测读数）：集成工作区是 `git worktree add` 出来的**新检出** ⇒ 没有 `node_modules`
#   （未跟踪目录不随 worktree 复制）⇒ 变更集命中 `frontend/admin-web/**` / `frontend/bmini-app/**` 时，
#   `verify-all.sh gate` 的那两条腿走 report_strict ⇒ **fail-closed 记 ❌** ⇒ 整批 exit 1。
#   那是**假红**：看起来像「这批包里有人把代码改坏了」，真因是**工作区没装依赖**。
#
#   所以 merge 之后、跑 gate 之前先判一次（**判决点在任何判据之前** = 不烧那一次全量）：
#     · 变更集**命中**需要 `node_modules` 的面（`admin-web` / `bmini-app`；探针与 gate 档 report_strict
#       **同源**：`admin-web-tsc` 探 `.bin/tsc`，`bmini-app` 探 `.bin/{tsc,jest,taro}`）且缺 ⇒
#       **具名「环境缺失」+ exit 3**（默认**不装**：装是写盘动作、首次几分钟，不该藏在「跑一下」里）；
#     · 变更集**不命中**这两个面 ⇒ **不拦**（负控：不该拦的别拦 —— 那两条腿本来就不派发）；
#     · 显式 `--install-deps` ⇒ 在**集成工作区**里 `npm ci` 备妥后继续；备妥失败仍 **fail-closed**
#       （具名「环境缺失」+ exit 3）—— 「装不上」不许退化成「那就跳过这条腿」。
#
#   ⛔ **禁止**把主检出的 `node_modules` 软链进来。issue #6834 的正文把它列为「最便宜」的选项，但本仓
#   已两次实测它是**陷阱**：① issue #5930 —— `npm ci` 的第一步就是删 `node_modules`，穿过软链会把
#   **主检出**的依赖清空（仓外发生、git 看不见、没有任何判据会红）；② issue #5241 —— Turbopack 拒绝
#   指向项目根之外的 `node_modules`（`next dev` 先 ✓ Ready 再 FATAL）。故本命令一律**真装**
#   （`npm ci --prefer-offline`：锁文件决定内容，npm 全局缓存让重复安装变快），并**先摘掉**存量软链
#   （自愈；`rm -f` 只摘链接本身、不跟随目标）。同一口径见 `scripts/ui_smoke_merchant.sh` 的依赖准备段
#   与 `https://github.com/zhaokai-mgzn/migao/wiki/Development` 的「worktree 依赖准备」。
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
#   - **依赖备妥只覆盖两个模块目录**（照实登记）：判定按 `frontend/admin-web/**` / `frontend/bmini-app/**`
#     前缀匹配，而 `verify-all.sh` 的 `admin_web_face_paths()` / `bmini_face_paths()` 还含**跨目录输入**
#     （如 `backend/ai-agent-service/app/api/chat.py` 是 bmini 测试现取的真值）⇒ 只碰这些跨目录输入的
#     批次**仍会**撞上 gate 的 fail-closed 红。这是**有意**的窄面：宁可漏报一次（后果 = 回到本单修前的
#     形态，人看得到 fail-closed 文案），也不把面判宽后**误拦**本来能跑的批次。
#     重启条件 = 这类跨目录输入再被实测撞上（届时把该路径加进依赖表并同步 `verify-all.sh`）。
#   - 依赖备妥**不判**「装得对不对」：`npm ci` 成不成由 npm 决定（锁文件决定内容）；备妥后仍缺可执行
#     文件 ⇒ 照样**具名拒绝**（fail-closed），不许记成通过。
#   - 本脚本**不改**任何门禁的通过条件、不新增豁免；CI 仍是权威。
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${BATCH_GATE_BASE:-origin/main}"
KEEP=0
IN_WT=""
BRANCHES=()
CHECK_ARMS=()
READY=1
INSTALL_DEPS=0

while [ $# -gt 0 ]; do
  case "$1" in
    --in)   IN_WT="${2:-}"; [ -n "$IN_WT" ] || { echo "用法: $0 --in <worktree>" >&2; exit 2; }; shift 2 ;;
    --base) BASE="${2:-}"; [ -n "$BASE" ] || { echo "用法: $0 --base <ref>" >&2; exit 2; }; shift 2 ;;
    --keep) KEEP=1; shift ;;
    --install-deps) INSTALL_DEPS=1; shift ;;
    --require-ready)    READY=1; shift ;;
    --no-require-ready) READY=0; shift ;;
    --check-arm) CHECK_ARM=1; shift ;;
    # --help = 文件头**全部**注释行（写到「第一行非注释」为止）。⛔ 别写死行数区间：
    # 头部长一英寸就被静默截断（本包加「就绪判定」段后就截到了「## 退出码」标题、0/1/3 三态看不见了）。
    -h|--help) awk '/^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"; exit 0 ;;
    -*)     echo "未知参数：$1（用法见 $0 --help）" >&2; exit 2 ;;
    # `--check-arm` 之后的位置参数 = PR 号（不是分支名）；两种形态互斥。
    *)      if [ "${CHECK_ARM:-0}" = 1 ]; then CHECK_ARMS+=("$1"); else BRANCHES+=("$1"); fi; shift ;;
  esac
done

if [ "${CHECK_ARM:-0}" = 1 ] && [ "${#CHECK_ARMS[@]}" -eq 0 ]; then
  echo "用法: $0 --check-arm <PR> [<PR> ...]   # 回读 auto-merge 是否已解除（幂等只读）" >&2
  exit 2
fi

if [ "${CHECK_ARM:-0}" != 1 ] && [ "${#BRANCHES[@]}" -eq 0 ]; then
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

# ── 1.3) auto-merge 三态探针 + `--check-arm` 回读（issue #6212）─────────────────
#
# 为什么「解除」之后还要回读：`gh pr merge <PR> --disable-auto` **不是**一次性的可靠控制 ——
# 一次 push 触发的 `synchronize` 会让 `automerge.yml` **重新 arm**（#4829 实证）。所以
# 「我跑过 --disable-auto」不是证据，**解除后当场回读 `autoMergeRequest`** 才是。
# 回读与就绪判定 ③ 用**同一个**探针（不写第二份「算不算已 arm」的实现）⇒ 两处口径不可能漂移。
# 幂等：同一输入连跑两次结果逐字节一致（只读、零写操作）。

#: `gh pr view <PR> --json autoMergeRequest` → 三态（与就绪判定同一套口径，`3` 不许当 `0` 读）。
#: stdout = 读数：未 arm 空 / 已 arm 的 `enabledAt` / 无法判定的原因。
AUTOMERGE_PROBE='
import json, sys
raw = sys.stdin.read()
if not raw.strip():
    print("stdout 为空（取不到读数）"); sys.exit(3)
try:
    data = json.loads(raw)
except Exception:
    print("输出不可解析（不是 JSON）"); sys.exit(3)
if not isinstance(data, dict) or "autoMergeRequest" not in data:
    print("字段 autoMergeRequest 缺失"); sys.exit(3)
req = data["autoMergeRequest"]
if req is None:
    sys.exit(0)
print((req or {}).get("enabledAt") or "(enabledAt 未提供)")
sys.exit(1)
'

#: 三态探针：0 = 未 arm（就绪）｜1 = **已 arm**（不就绪；stdout = enabledAt）｜3 = 无法判定。
automerge_state() {
  local pr="$1" raw rc
  # `2>&1`：失败原因必须与 JSON 在**同一次**调用里取到（否则「无法判定」只剩一个退出码，出声不了）。
  raw="$(gh pr view "$pr" --json autoMergeRequest 2>&1)"
  rc=$?
  if [ "$rc" -ne 0 ]; then
    printf 'gh pr view %s --json autoMergeRequest 失败（rc=%s；%s）\n' \
      "$pr" "$rc" "$(printf '%s' "$raw" | head -1)"
    return 3
  fi
  printf '%s' "$raw" | python3 -c "$AUTOMERGE_PROBE"
}

if [ "${CHECK_ARM:-0}" = 1 ]; then
  echo "── auto-merge 回读（--check-arm；幂等只读，issue #6212）──"
  armed=0
  unk=0
  for pr in "${CHECK_ARMS[@]}"; do
    case "$pr" in
      ''|*[!0-9]*) die "--check-arm 只收 PR 号（纯数字），实得：${pr}" ;;
    esac
    if ! command -v gh >/dev/null 2>&1; then
      die "gh 不存在 ⇒ 回读不了 autoMergeRequest —— 无法判定 ≠ 未 arm（装好 gh 再回读）"
    fi
    info="$(automerge_state "$pr")"
    rc=$?
    case "$rc" in
      0) echo "  ✅ PR #${pr}：未 arm（= 可进批次；解除已生效 / 本就未 arm —— 幂等）" ;;
      1) echo "  ❌ PR #${pr}（**仍 arm**，enabledAt=${info}）：解除没生效 ⇒ 跑全量期间它可被秒合"
         echo "     ｜下一步：gh pr merge ${pr} --disable-auto，然后再跑一次本命令回读"
         echo "     ⚠️ 回读要放在**最后一次 push 之后**：一次 push 触发的 synchronize 会让 automerge.yml 重新 arm（#4829）"
         armed=1 ;;
      *) echo "  ❓ PR #${pr}（**无法判定 ≠ 未 arm**）：${info}"
         echo "     ｜下一步：修好 gh（凭据 / 网络 / 限流）再回读 —— 别把「读不到」当「已解除」"
         unk=1 ;;
    esac
  done
  if [ "$unk" = 1 ]; then
    echo "⛔ 回读**无法判定**（exit=3）—— 不是「已 disarm」，也不是「通过」。"
    exit 3
  fi
  if [ "$armed" = 1 ]; then
    echo "⛔ 回读发现**仍 arm**（exit=1）—— 解除没生效，别把它当已就绪。"
    exit 1
  fi
  echo "  ⇒ 全部 ${#CHECK_ARMS[@]} 个 PR 未 arm（同一输入连跑两次结果一致 = 可回读）"
  exit 0
fi

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
# 1.5) **就绪前置判定**（issue #6055 / PR #6056）—— 在跑那一次全量**之前**
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
    # ⚠️ `skipping` **不是红**（issue #6216）：本仓 CI 按变更面**有意跳过**无关腿
    # （`E2E 面判定` / `bmini H5 面判定` / `mini-app 面判定`，见 #6160/#6170）——
    # 任何只动单一模块的包都必然带 skipping，把它当红 ⇒ 该包**恒不就绪** ⇒ 「一批一次全量」
    # （D 口径、issue #6012）**永远启动不了**。头注释（第 33 行）与引入该判定的 PR #6056 说明
    # 都只写 `fail`/`pending` ⇒ 判定式里的 `"skipping"` 是引入笔误。
    # 但 skipping 也**不许静默变绿**（「没跑」必须长得像「没跑」）⇒ 只计入读数、不参与红判定。
    #
    # ⚠️ 同族第二条（本单现场取证才发现的另一半）：**`CANCELLED` 且非 required 的腿**同样不是红。
    # 实例：`Post-Merge Verify (定向跑判据面)` 在 PR 上被 auto-cancel（我 force-push 后陈旧 run 被取消），
    # 而 `gh pr checks <PR> --required` 显示 **required 全绿**、GitHub 自身判 `mergeable=MERGEABLE`
    # ⇒ 它**不挡合并**。本判定的本意是「这包与 main 合并是否就绪」⇒ 把非 required 的 cancel 当红
    # 会让「rebase 过的包」恒不就绪（与 skipping 同一类恒拒绝）。
    # 判据用 **state==CANCELLED 区分**（不是把 cancel 整族放行）：
    #   · state FAILURE  → 红（哪怕 bucket 也叫 cancel/cancelled —— 真失败不许静默）
    #   · state CANCELLED → 与 skipping 同侧：不参与红判定，但**计入并打印**（不许静默）。
    def _is_cancelled(it):
        return (it.get("state") or "").upper() == "CANCELLED"

    def _is_skip(it):
        # 两种「没跑」：按面**有意跳过**（bucket=skipping）+ **被取消**（state=CANCELLED）
        return (it.get("bucket") or "") == "skipping" or _is_cancelled(it)

    fail = [i.get("name", "?") for i in data
            if ((i.get("bucket") or "") in ("fail", "cancel", "cancelled")
                or (i.get("state") or "").upper() == "FAILURE") and not _is_skip(i)]
    pend = [i.get("name", "?") for i in data if (i.get("bucket") or "") == "pending"]
    skip = [i.get("name", "?") for i in data if _is_skip(i)]
    skipnote = ("（另有 " + str(len(skip)) + " 条 skipping/cancelled："
                + "、".join(skip[:6]) + "）") if skip else ""
    if fail:
        print("FAIL " + str(len(data)) + " 条 check；红：" + "、".join(fail[:6]) + skipnote)
    elif pend:
        print("PENDING " + str(len(data)) + " 条 check；未完成：" + "、".join(pend[:6]) + skipnote)
    else:
        print("OK " + str(len(data)) + " 条 check 全绿" + skipnote)
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

  # ── ③ auto-merge **未 arm**（需 gh + 网络；issue #6212）────────────────────
  # 为什么它必须在这道门里（不是「另一条纪律」）：`automerge.yml` 恰在「**非 draft**」时 arm 原生
  # auto-merge，而 ② 又要求非 draft（draft 的 leg 不全 ⇒ pending）⇒ 集成期的就绪前提本身就打开了
  # 「跑全量期间被秒合」的窗口（实测：转 ready → arm 17 秒、arm → 合并 4 分 26 秒）。已 arm 的包
  # **跑之前**就得挡在门外；解除不可信（一次 push 就重新 arm，#4829）⇒ 出口必须带**回读**。
  am="$(automerge_state "$pr")"
  rc=$?
  if [ "$rc" -eq 1 ]; then
    not_ready "$b" "PR #${pr} 的 auto-merge **已 arm**（enabledAt=${am}）—— 已 arm 的包在跑全量期间可被秒合（实测 arm→合并 4 分 26 秒；一次 push 就重新 arm，#4829）⇒ 不就绪 ｜下一步：① gh pr merge ${pr} --disable-auto ② 当场回读（仍 arm ⇒ 非零；无法判定 ⇒ 3）：./scripts/batch-gate.sh --check-arm ${pr}"
    return
  elif [ "$rc" -ne 0 ]; then
    undecidable "$b" "PR #${pr} 的 auto-merge 状态读不到（${am}）—— 无法判定 ≠ 就绪（读不到时它**可能**已 arm，跑全量期间会被秒合）｜下一步：修好 gh/网络重跑，或显式 --no-require-ready"
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
    "PENDING "* ) not_ready   "$b" "PR #${pr}；${verdict#PENDING } ｜下一步：等 CI 绿（./scripts/wait-checks.sh ${pr} —— 三态 0/1/3，3 不得当 0 读；别用 gh pr checks --watch 的退出码当结论）" ;;
    *           ) undecidable "$b" "PR #${pr}；没有上报任何 check（起飞前的 PR？）—— 无法判定 ≠ 就绪" ;;
  esac
}

if [ "$READY" = 1 ]; then
  echo "── 就绪前置判定（--require-ready 默认开启；issue #6055 / PR #6056）──"
  if git -C "$ROOT" rev-parse --verify --quiet "${BASE}^{commit}" >/dev/null 2>&1; then
    while IFS=$'\t' read -r b sha; do
      check_one_package "$b" "$sha"
    done < "$TMP/branches.tsv"
  else
    # 取不到基准 ⇒ 三条判定都做不了 ⇒ **无法判定**（fail-closed，≠ 就绪）
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
  echo "  ⇒ 全部 ${#BRANCHES[@]} 个包就绪（无冲突 + auto-merge 未 arm + PR checks 全绿）"
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

# ── 2.5) 集成工作区的**依赖备妥**判定（issue #6834；判在**任何判据之前** ⇒ 不烧那一次全量）────
#
# 归因分层（文件头同款，三者不许混）：本段只产**两种**结论 —— 依赖就绪（继续）与 **环境缺失**
# （具名 + exit 3）。⚠️ 判据真红（exit 1）**必须**来自第 4 段的面级归因；环境问题不许冒充代码问题，
# 反过来也不许把「没装依赖」这一态记成通过（那就是假绿）。

#: 需要 `node_modules` 的模块（**单一实现**）。探针与 `verify-all.sh` `gate` 档的两条 report_strict
#: 腿**同源**：`admin-web-tsc` 探 `node_modules/.bin/tsc`；`bmini-app` 探 `.bin/{tsc,jest,taro}`。
#: 输出 `名称<TAB>目录<TAB>工具…`。⚠️ `worker-h5` **不在表内**：它零依赖（只探 node），列进来会误拦；
#: 两处的一致性由 `tests/unit_ci_workflows/test_batch_gate.py` 的类级元守卫现取核对（漂移即红）。
deps_modules() {
  printf 'admin-web\tfrontend/admin-web\ttsc\n'
  printf 'bmini-app\tfrontend/bmini-app\ttsc jest taro\n'
}

#: 缺哪些可执行文件（stdout = 空格分隔；空 = 就绪）。探**工具**而不是探目录：目录在、工具不在
#: （装不全）是真实形态，而 gate 的 report_strict 探的也正是这些可执行文件。
deps_missing() {
  local nd="${1}/node_modules/.bin" t miss=""
  for t in $2; do [ -x "${nd}/${t}" ] || miss="${miss} ${t}"; done
  printf '%s' "${miss# }"
}

echo "── 依赖备妥判定（集成工作区的 node_modules；issue #6834）──"
CHANGE_FILES="$(git -C "$WT" diff --name-only "${BASE}...HEAD" 2>/dev/null)"
_cs_rc=$?
if [ "$_cs_rc" -ne 0 ]; then
  # 读不出来 ⇒ 无法判定（⛔ 不许把「读不到」当成「不需要依赖」：那是本单同族的假绿方向）。
  # 注：变更集**真的为空**（本批没有净改动）不是错误 —— 那时没有任何面被判据覆盖，依赖也不需要，
  #     那一次 gate 自己会按「零变更」走它的三态（exit 3），本段不替它下结论。
  die "取不到集成工作区的变更集（git diff --name-only ${BASE}...HEAD 退出码 ${_cs_rc}）—— 缺不缺依赖**判不了**（读不到 ≠ 不需要）"
fi

deps_hit=()    # 本批命中、需要 node_modules 的模块名
deps_gaps=()   # 缺依赖的模块：名称|目录|工具…|缺哪些
while IFS=$'\t' read -r _name _dir _tools; do
  _hit="$(printf '%s\n' "$CHANGE_FILES" | grep -E "^${_dir}/" || true)"
  [ -n "$_hit" ] || continue
  deps_hit+=("${_name}")
  _miss="$(deps_missing "${WT}/${_dir}" "${_tools}")"
  [ -n "$_miss" ] && deps_gaps+=("${_name}|${_dir}|${_tools}|${_miss}")
done < <(deps_modules)

if [ "${#deps_hit[@]}" -eq 0 ]; then
  # 负控：缺依赖但本批不命中这两个面 ⇒ **不拦**（那两条腿本来就不派发；拦了就是新的假红）。
  echo "  ⏭️ 无需备妥：本次变更集未命中需要 node_modules 的面（admin-web / bmini-app）—— 这不是「跳过判据」"
elif [ "${#deps_gaps[@]}" -eq 0 ]; then
  echo "  ✅ 依赖就绪：${deps_hit[*]}"
elif [ "$INSTALL_DEPS" != 1 ]; then
  echo "⛔ **环境缺失**（不是「代码问题」，也不是「这批判据红」）⇒ 无法判定（exit=3）—— 那一次全量**没有跑**。"
  echo "   缺什么（集成工作区 = git worktree add 出来的新检出 ⇒ node_modules 不随 worktree 复制）："
  for _g in "${deps_gaps[@]}"; do
    IFS='|' read -r _n _d _t _m <<< "$_g"
    echo "     • ${_n}：${WT}/${_d}/node_modules/.bin/ 缺 ${_m// /、}"
  done
  echo "   为什么不跑：本批变更集命中上面这些面 ⇒ gate 的那条腿会 fail-closed 判 ❌，"
  echo "     而那是**环境**问题 ⇒ 面级归因会把矛头指向「碰了那个面的包」（issue #6834 的形态）。"
  echo "   出口（三选一；**每个都必须能照抄执行** —— 注意本命令默认结束即删工作区）："
  echo "     ① 加 --install-deps 重跑：本命令在集成工作区里 npm ci 备妥后再跑那一次全量（首次几分钟，之后命中 npm 缓存）；"
  echo "     ② 手动备妥：先用 --keep 重跑一次保住工作区，再 cd '<工作区>/<模块目录>' && npm ci，"
  echo "        之后用 --in '<工作区>' 复用（集成工作区默认结束即删 ⇒ 不 --keep 就没有可 cd 的目录）；"
  echo "     ③ 把这一批推到 CI 上判（每 PR 并行；CI 仍是权威）—— 别把「本机没装依赖」读成「这批有问题」。"
  echo "   ⚠️ 别软链主检出的 node_modules（issue #5930：npm ci 会穿过软链清空主检出依赖；issue #5241：Turbopack 拒绝根外软链）。"
  echo "   ⚠️ 「没跑」≠「通过」：本批**代码有没有问题，本次没有判定**。"
  exit 3
else
  echo "  🔧 --install-deps：在集成工作区**真装**（npm ci；禁止软链主检出，#5930 / #5241）"
  _still=()
  for _g in "${deps_gaps[@]}"; do
    IFS='|' read -r _n _d _t _m <<< "$_g"
    _target="${WT}/${_d}"
    if [ -L "${_target}/node_modules" ]; then
      echo "     • ${_n}：摘除 node_modules 软链（-> $(readlink "${_target}/node_modules")）—— npm ci 会穿过软链清空目标（#5930）"
      rm -f "${_target}/node_modules" || die "环境缺失（备妥失败）：摘不掉软链 ${_target}/node_modules"
    fi
    echo "     • ${_n}：cd '${_d}' && npm ci --no-audit --no-fund --prefer-offline（缺 ${_m// /、}）"
    if ! ( cd "$_target" && npm ci --no-audit --no-fund --prefer-offline ); then
      _still+=("${_n}|${_d}|npm ci 退出非 0")
      continue
    fi
    _miss2="$(deps_missing "$_target" "$_t")"
    [ -n "$_miss2" ] && _still+=("${_n}|${_d}|npm ci 完成但仍缺 ${_miss2// /、}")
  done
  if [ "${#_still[@]}" -gt 0 ]; then
    # ⚠️ 空值护栏 `${_still[@]+"${_still[@]}"}` 不能省：macOS 自带 bash 3.2 在 `set -u` 下展开
    # 空数组会 `unbound variable`（整脚本当场死）—— 类级判据 = test_ui_smoke_worktree_deps.py 的
    # `test_no_unguarded_empty_array_expansion_in_scripts`（issue #6777）。
    for _g in ${_still[@]+"${_still[@]}"}; do
      IFS='|' read -r _n _d _why <<< "$_g"
      echo "  ❌ ${_n}（${_d}）：${_why}"
    done
    die "环境缺失（--install-deps 备妥失败）—— 装不上就**不能**跑那一次全量：缺依赖时 gate 会把环境问题记成 ❌（issue #6834）"
  fi
  echo "  ✅ 依赖已备妥：${deps_hit[*]}"
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
    ("cases 面门禁", (".github/cases/", ".github/case-trust-", "tests/agent_eval/eval_cases/",
                    "docs/testing/mibao-verification-cases.md")),
    ("bmini-app", ("frontend/bmini-app/", "frontend/admin-web/src/lib/print-media.json",
                   "frontend/worker-h5/src/shipment.mjs")),
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
