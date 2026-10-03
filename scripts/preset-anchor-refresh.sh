#!/usr/bin/env bash
# =============================================================================
# preset-anchor-refresh.sh — 活锚自愈：把**专职只读镜像**刷到**预设仓**的 `main`（issue #4026 / 迁移单 #6020）
#
# 🔴 S4（issue #6020）改了什么：预设的权威源已迁到**独立预设仓**
#   `zhaokai-mgzn/migao-agent-presets`（本仓不再承载 `.agent-presets/migao/**`）⇒
#     · 镜像默认路径 `$HOME/migao-preset-anchor` → **`$HOME/migao-dev-preset-anchor`**
#       （`MIGAO_PRESET_MIRROR` 覆盖）；
#     · 镜像的**克隆源 = 预设仓**（`MIGAO_PRESET_REPO_URL` 覆盖，默认 SSH URL）；
#     · 软链目标 = **镜像的仓根**（不再是 `<镜像>/.agent-presets/migao`）。
#   既有不变量一条未放宽：仍然只刷**独立克隆**（拒 worktree）、仍对就地编辑 fail-closed、
#   仍做内容逐字节 + sha 双读、刷新后仍**必须**自检（`--no-check` 才跳过）。
#
# 为什么刷的是「独立克隆」而不是任何开发工作区：
#   · 普通 worktree（`migao-wt/*`）在 `dev-worktree.sh rm` / `git worktree prune` 的**清理半径**内，
#     当活锚会被删没 ⇒ 软链悬空 ⇒ **DSH 静默加载不到研发模式**（issue #3956 实证：一次
#     `rm -rf … migao-preset-live …` 把当时的活锚目标硬删了，不报错、只是「模式不见了」）；
#   · 主工作区/开发 worktree 会被**切分支**、会被 fetch/merge/checkout 改动，且常常落后 main
#     （实测落后 42 个提交）⇒ 改进到不了加载点（本单的病灶）。
#   ⇒ 活锚目标必须是**专职只读镜像**（独立克隆），本脚本负责让它跟随预设仓 main。
#
# 「镜像上丢弃本地改动为何安全」（前提，写在这里以免读者以为这是通用做法）：
#   镜像**不承载任何开发改动** —— 开发改动永远在**预设仓**的工作区/分支里，不在镜像里
#   ⇒ 镜像上唯一合法的内容就是预设仓的 `origin/main`。**即便如此**，本脚本也不做 `reset --hard`
#   之类的破坏性动作，而是：① 先核镜像形态；② 已跟踪文件一脏就 **fail-closed 停手**（那意味着有人
#   就地编辑了活锚 =「藏在软链目标里的第三份副本」，必须人工看清再处置）；③ 再 `fetch` +
#   `checkout --detach origin/main` 前进（镜像没有分支状态，故不用 merge）。
#
# 用法：
#   ./scripts/preset-anchor-refresh.sh                  # 刷新默认镜像 ~/migao-dev-preset-anchor
#   MIGAO_PRESET_MIRROR=<路径> ./scripts/preset-anchor-refresh.sh
#   ./scripts/preset-anchor-refresh.sh --repo <基线仓>   # **仅拓扑 B（兼容窗口）**：自检的基线仓
#                                                        # （拓扑 A 下自检的对照恒 = 镜像自身，见 ⑤.6）
#   ./scripts/preset-anchor-refresh.sh --ref <ref>       # 指定基线 ref（默认 origin/main）
#   ./scripts/preset-anchor-refresh.sh --no-check        # 只刷新、不自检（默认**必须**自检）
#   MIGAO_PRESET_REPO_URL=<url|路径> ./scripts/preset-anchor-refresh.sh
#
# 退出码：0 = 刷新后自检绿；1 = 镜像形态不对 / 有就地编辑 / 刷新失败 / 刷新后仍红；2 = 环境或用法错误
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIRROR="${MIGAO_PRESET_MIRROR:-$HOME/migao-dev-preset-anchor}"
LIVE="${MIGAO_PRESET_LIVE:-$HOME/.dsh/.agent-presets/migao}"
# 预设仓（权威源）。镜像已经建好的机器上以其自身 remote 为准（它才是真正被跟随的上游）。
REPO_URL="${MIGAO_PRESET_REPO_URL:-git@github.com:zhaokai-mgzn/migao-agent-presets.git}"
BASELINE="${MIRROR}"
BASELINE_FROM_FLAG=0
REF="origin/main"
RUN_CHECK=1

while [ $# -gt 0 ]; do
  case "$1" in
    --repo)   [ $# -ge 2 ] || { echo "❌ --repo 缺参数" >&2; exit 2; };   BASELINE="$2"; BASELINE_FROM_FLAG=1; shift 2 ;;
    --mirror) [ $# -ge 2 ] || { echo "❌ --mirror 缺参数" >&2; exit 2; }; MIRROR="$2";   shift 2 ;;
    --ref)    [ $# -ge 2 ] || { echo "❌ --ref 缺参数" >&2; exit 2; };    REF="$2";      shift 2 ;;
    --no-check) RUN_CHECK=0; shift ;;
    -h|--help) sed -n 's/^# \{0,1\}//p' "$0" | sed -n '/^preset-anchor-refresh.sh/,/^====/p'; exit 0 ;;
    *) echo "❌ 未知参数：$1（用法见脚本头部）" >&2; exit 2 ;;
  esac
done

bootstrap_hint() {
  cat <<EOF

  当前没有可用的只读镜像（${MIRROR}）。**不要**把活锚指向开发工作区 —— 它会被切分支/被清理，
  且落后 main 时改进到不了加载点。建专职镜像（换机 / 新队友，一次性；克隆源 = **预设仓**）：

    git clone --no-checkout "${REPO_URL}" "\$HOME/migao-dev-preset-anchor"
    git -C "\$HOME/migao-dev-preset-anchor" checkout --detach origin/main
    # 确认镜像在位、preset.yml 可读后**再**换链。备份只对**真目录**（旧拓扑）做 ——
    # 新拓扑下活锚是**软链**，\`mv\` 它只会把软链挪成一堆 \`.bak\`（实测：清出过两个 6 周前的 .bak）：
    if [ -d "\$HOME/.dsh/.agent-presets/migao" ] && [ ! -L "\$HOME/.dsh/.agent-presets/migao" ]; then
      mv "\$HOME/.dsh/.agent-presets/migao" "\$HOME/.dsh/.agent-presets/migao.bak-\$(date +%Y%m%d-%H%M%S)"
    fi
    ln -sfn "\$HOME/migao-dev-preset-anchor" "\$HOME/.dsh/.agent-presets/migao"

  注意：S4 起预设内容在**预设仓仓根**（\`preset.yml\` 直接在仓根），软链指向**仓根**，
  不再有 \`.agent-presets/migao\` 这一层。详见根 AGENTS.md「开发环境准备」与预设仓 README.md。
EOF
}

echo "🔄 活锚自愈刷新（只读镜像 → ${REF}）"
echo "   镜像：${MIRROR}"

# ① 镜像缺失 ⇒ 用**预设仓**克隆一份（**只在新机上发生**；已有镜像一律不重建，避免误伤活锚）。
#    ⚠️ 探测必须用 `git rev-parse --git-dir`，**不能**用 `[ -d <mirror>/.git ]`：
#    linked worktree 的 `.git` 是个**文件**（gitdir 指针）⇒ 用目录判会把它读成「不是检出」，
#    从而**跳过下面那条「拒绝 worktree 当活锚」的护栏**（#3956 的形态会被放进来）。
if [ ! -e "${MIRROR}" ]; then
  echo "ℹ️  镜像不存在 —— 从预设仓克隆一份（${REPO_URL}）"
  if ! git clone -q --no-checkout "${REPO_URL}" "${MIRROR}"; then
    echo "❌ 克隆预设仓失败（离线 / 无权限？）：${REPO_URL}"
    bootstrap_hint
    exit 1
  fi
  git -C "${MIRROR}" config user.email >/dev/null 2>&1 || git -C "${MIRROR}" config user.email "preset-anchor@localhost"
  git -C "${MIRROR}" config user.name  >/dev/null 2>&1 || git -C "${MIRROR}" config user.name  "preset-anchor"
elif ! git -C "${MIRROR}" rev-parse --git-dir >/dev/null 2>&1; then
  echo "❌ 镜像路径存在但不是 git 检出：${MIRROR}"
  echo "   它可能是手抄副本（没有跟随机制）或旧布局残留 ⇒ 人工看清再处置，本脚本不覆盖它。"
  bootstrap_hint
  exit 1
fi

# 镜像已经建好的机器上，以**它自己的** origin 为权威（它才是被跟随的上游）；取不到则沿用变量。
MIRROR_ORIGIN="$(git -C "${MIRROR}" remote get-url origin 2>/dev/null || true)"
[ -n "${MIRROR_ORIGIN}" ] && REPO_URL="${MIRROR_ORIGIN}"

# ② 形态核验：必须是**独立克隆**（git-common-dir 就是它自己的 .git）。
#    被注册的 worktree 其 common dir 指向**主仓库**的 .git ⇒ 它属于「可丢弃」语义，拒当活锚。
COMMON="$(git -C "${MIRROR}" rev-parse --git-common-dir 2>/dev/null || echo '')"
case "${COMMON}" in
  /*) COMMON_ABS="${COMMON}" ;;
  "") COMMON_ABS="" ;;
  *)  COMMON_ABS="${MIRROR%/}/${COMMON}" ;;
esac
if [ "${COMMON_ABS}" != "${MIRROR%/}/.git" ]; then
  echo "❌ 拒绝刷新：${MIRROR} 不是**独立克隆**（git-common-dir=${COMMON_ABS:-读不到}）"
  echo "   它很可能是某个仓库的 worktree —— 那在 dev-worktree.sh rm / git worktree prune 的清理半径内，"
  echo "   当活锚会被删没 ⇒ 软链悬空 ⇒ DSH 静默加载不到研发模式（issue #3956）。"
  echo "   请改用独立克隆（见 --help 末段的一次性建镜像命令）。"
  exit 1
fi

# ③ 就地编辑检查（fail-closed）：已跟踪文件脏 = 有人把活锚当编辑副本用（「藏在软链目标里的第三份副本」）
DIRTY="$(git -C "${MIRROR}" status --porcelain --untracked-files=no 2>/dev/null || true)"
if [ -n "${DIRTY}" ]; then
  echo "❌ 拒绝刷新：镜像里有**已跟踪文件的本地改动**（$(printf '%s\n' "${DIRTY}" | wc -l | tr -d ' ') 处）—— 不静默覆盖："
  printf '%s\n' "${DIRTY}" | sed 's/^/     /'
  echo "   活锚必须**只读**：改研发模式请**到预设仓**改 + 走 PR。人工看清后再处置（例如先"
  echo "   \`git -C \"${MIRROR}\" diff\` 看是谁改了什么，确认可弃后 \`git -C \"${MIRROR}\" checkout --detach ${REF}\`）。"
  exit 1
fi

BEFORE="$(git -C "${MIRROR}" rev-parse --short HEAD 2>/dev/null || echo '?')"

# ④ 前进：fetch + checkout --detach（不用 merge —— 镜像没有分支状态，它就是 detached 的）
if ! git -C "${MIRROR}" fetch --prune origin "${REF#origin/}"; then
  echo "❌ fetch origin ${REF#origin/} 失败（离线 / 无权限？）—— 镜像未刷新"
  exit 1
fi
if ! git -C "${MIRROR}" checkout --detach "${REF}"; then
  echo "❌ checkout --detach ${REF} 失败 —— 镜像未刷新（上面是 git 原始输出）"
  exit 1
fi
AFTER="$(git -C "${MIRROR}" rev-parse --short HEAD)"
echo "✅ 镜像已跟随 ${REF}：${BEFORE} → ${AFTER}"
git -C "${MIRROR}" log --oneline -1 | sed 's/^/   /'
if [ "${BEFORE}" = "${AFTER}" ]; then
  echo "   （本来就在 ${REF} 上，无变化）"
fi

# ⑤ 一致性提示：刷新的是镜像，但**真正生效的是活锚**（软链解析到哪，就用哪）。
#    S4 起软链目标 = 镜像的**仓根**（旧口径是 `<镜像>/.agent-presets/migao`）。
RESOLVED="$(readlink "${LIVE}" 2>/dev/null || echo '')"
case "${RESOLVED}" in
  "${MIRROR%/}") : ;;
  *) echo "⚠️ 注意：活锚（${LIVE}）并不指向本镜像的**仓根**（readlink=${RESOLVED:-未接线}）"
     echo "   ⇒ 刷新本镜像**不会**让活锚跟上；换链见 AGENTS.md「开发环境准备」（先备份、再 ln -sfn，"
     echo "      目标是 \`${MIRROR}\` 这个**仓根**，不是 \`<镜像>/.agent-presets/migao\`）。" ;;
esac

# ⑤.6 🔴 自检的**对照对象按拓扑选**（issue #6178 —— 本单病灶：空比对报绿）。
#      活锚目标 = **预设仓检出**（`preset.yml` 在仓根；= 当前拓扑 A）时，对照**必须是预设仓的
#      `${REF}`（= 镜像自身，它刚被刷到预设仓 main）**：此时 `--repo <业务仓>` 只会解析出 **0 个文件**
#      （业务仓已不再承载 `.agent-presets/**`，`git ls-tree -r origin/main --name-only .agent-presets`
#      = 0）⇒ 比对面是**空集** ⇒ 任何内容都能过 ⇒ 一个**永远绿的空检查**（本单实测：
#      `✅ 活锚新鲜：内容与 origin/main 逐字节一致（0 个文件）` + `✅ 自检绿` + exit 0）。
#      ⇒ 拓扑 A 下**不看 `--repo`**（显式给了也**出声**说明被忽略，不静默改写人的参数）。
#      拓扑 B（活锚仍是业务仓里的 preset 子树，兼容窗口）保持历史口径：对照 = `--repo`（默认镜像）。
CHECK_BASELINE="${BASELINE}"
if [ -f "${MIRROR%/}/preset.yml" ]; then
  CHECK_BASELINE="${MIRROR}"
  if [ "${BASELINE_FROM_FLAG}" = "1" ] && [ "${BASELINE%/}" != "${MIRROR%/}" ]; then
    echo "ℹ️  自检对照按拓扑选：镜像（${MIRROR}）的仓根**就是** preset 目录 ⇒ 拓扑 A，"
    echo "    对照 ref = 预设仓的 \`${REF}\`（镜像自身）；`--repo ${BASELINE}` 这一项**不参与比对**"
    echo "    （拿业务仓当对照会解析出空比对面 ⇒ 恒绿 = 假绿，issue #6178；要比它请显式跑"
    echo "    \`scripts/preset-anchor-check.sh --repo <仓> --anchor-base <前缀>\`）。"
  fi
fi

# ⑤.5 基线仓先 fetch：自检读的是**基线仓的** `${REF}` —— 拿**未 fetch 的旧 ref** 自检，会把
#      「刚合并的预设改动」读成「活锚落后」（2026-09-28 实测：`land` 的 ⑦ 步因此判红，
#      而活锚其实只差一次 fetch）。fetch 非破坏性；失败只降级为「可能对着旧 ref 判」，不静默。
if [ "${RUN_CHECK}" = "1" ]; then
  if ! git -C "${CHECK_BASELINE}" fetch --quiet origin "${REF#origin/}" 2>/dev/null; then
    echo "⚠️  基线仓（${CHECK_BASELINE}）fetch ${REF} 失败（离线 / 无权限？）⇒ 下面的自检可能对着**旧** ref 判"
  fi
fi

# ⑥ 自检（默认必须跑）：刷新后仍红 = 刷新没解决问题（例如活锚根本指向别处）
if [ "${RUN_CHECK}" = "1" ]; then
  echo
  CHECK="${ROOT}/scripts/preset-anchor-check.sh"
  [ -x "${CHECK}" ] || { echo "❌ 自检脚本不可执行：${CHECK}" >&2; exit 2; }
  set +e
  # `--anchor-base` 这里按**历史默认值**传：判定本体在拓扑 A 下会把它归位到**仓根**（issue #6178），
  # 拓扑 B（兼容窗口）则照旧用 `.agent-presets/migao`。口径只放判定本体一处，本脚本不复制。
  "${CHECK}" --anchor "${LIVE}" --repo "${CHECK_BASELINE}" --ref "${REF}" --anchor-base ".agent-presets/migao"
  rc=$?
  set -e
  if [ "${rc}" != "0" ]; then
    echo
    echo "❌ 刷新后自检仍红（exit ${rc}）—— 见上方判定输出：镜像刷了，但**活锚**没有因此变新鲜"
    echo "   （常见原因：活锚指向别处 / 活锚是手抄副本 / 基线仓的 ${REF} 本身没 fetch）。"
    exit 1
  fi
  echo
  echo "✅ 活锚自愈完成：镜像已跟随 ${REF}，且自检绿（对照 = 预设仓 ${REF}，非空比对面）。"
fi
