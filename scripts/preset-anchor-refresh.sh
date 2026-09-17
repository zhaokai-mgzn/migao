#!/usr/bin/env bash
# =============================================================================
# preset-anchor-refresh.sh — 活锚自愈：把**专职只读镜像**刷到 `origin/main`（issue #4026）
#
# 为什么刷的是「独立克隆」而不是任何开发工作区：
#   · 普通 worktree（`migao-wt/*`）在 `dev-worktree.sh rm` / `git worktree prune` 的**清理半径**内，
#     当活锚会被删没 ⇒ 软链悬空 ⇒ **DSH 静默加载不到研发模式**（issue #3956 实证：一次
#     `rm -rf … migao-preset-live …` 把当时的活锚目标硬删了，不报错、只是「模式不见了」）；
#   · 主工作区/开发 worktree 会被**切分支**、会被 fetch/merge/checkout 改动，且常常落后 main
#     （实测落后 42 个提交）⇒ 改进到不了加载点（本单的病灶）。
#   ⇒ 活锚目标必须是**专职只读镜像**（独立克隆），本脚本负责让它跟随 main。
#
# 「镜像上丢弃本地改动为何安全」（前提，写在这里以免读者以为这是通用做法）：
#   镜像**不承载任何开发改动** —— 开发改动永远在产品仓库的工作区/分支里，不在镜像里
#   ⇒ 镜像上唯一合法的内容就是 `origin/main`。**即便如此**，本脚本也不做 `reset --hard` 之类的
#   破坏性动作，而是：① 先核镜像形态；② 已跟踪文件一脏就 **fail-closed 停手**（那意味着有人
#   就地编辑了活锚 =「藏在软链目标里的第三份副本」，必须人工看清再处置）；③ 再 `fetch` +
#   `checkout --detach origin/main` 前进（镜像没有分支状态，故不用 merge）。
#
# 用法：
#   ./scripts/preset-anchor-refresh.sh                  # 刷新默认镜像 ~/migao-preset-anchor
#   MIGAO_PRESET_MIRROR=<路径> ./scripts/preset-anchor-refresh.sh
#   ./scripts/preset-anchor-refresh.sh --repo <基线仓>   # 指定刷新后自检的基线仓（默认：本脚本所在仓库）
#   ./scripts/preset-anchor-refresh.sh --ref <ref>       # 指定基线 ref（默认 origin/main）
#   ./scripts/preset-anchor-refresh.sh --no-check        # 只刷新、不自检（默认**必须**自检）
#
# 退出码：0 = 刷新后自检绿；1 = 镜像形态不对 / 有就地编辑 / 刷新失败 / 刷新后仍红；2 = 环境或用法错误
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIRROR="${MIGAO_PRESET_MIRROR:-$HOME/migao-preset-anchor}"
LIVE="${MIGAO_PRESET_LIVE:-$HOME/.dsh/.agent-presets/migao}"
BASELINE="${ROOT}"
REF="origin/main"
RUN_CHECK=1

while [ $# -gt 0 ]; do
  case "$1" in
    --repo)   [ $# -ge 2 ] || { echo "❌ --repo 缺参数" >&2; exit 2; };   BASELINE="$2"; shift 2 ;;
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
  且落后 main 时改进到不了加载点。建专职镜像（换机 / 新队友，一次性）：

    git clone --no-checkout <migao 仓库 URL> "\$HOME/migao-preset-anchor"
    git -C "\$HOME/migao-preset-anchor" checkout --detach origin/main
    # 确认镜像在位、preset.yml 可读后**再**换链（先备份旧锚，不要删）：
    mv "\$HOME/.dsh/.agent-presets/migao" "\$HOME/.dsh/.agent-presets/migao.bak-\$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true
    ln -sfn "\$HOME/migao-preset-anchor/.agent-presets/migao" "\$HOME/.dsh/.agent-presets/migao"

  详见根 AGENTS.md「开发环境准备」与 .agent-presets/migao/README.md。
EOF
}

echo "🔄 活锚自愈刷新（只读镜像 → ${REF}）"
echo "   镜像：${MIRROR}"

if ! git -C "${MIRROR}" rev-parse --git-dir >/dev/null 2>&1; then
  echo "❌ 镜像不存在或不是 git 检出：${MIRROR}"
  bootstrap_hint
  exit 1
fi

# ① 形态核验：必须是**独立克隆**（git-common-dir 就是它自己的 .git）。
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

# ② 就地编辑检查（fail-closed）：已跟踪文件脏 = 有人把活锚当编辑副本用（「藏在软链目标里的第三份副本」）
DIRTY="$(git -C "${MIRROR}" status --porcelain --untracked-files=no 2>/dev/null || true)"
if [ -n "${DIRTY}" ]; then
  echo "❌ 拒绝刷新：镜像里有**已跟踪文件的本地改动**（$(printf '%s\n' "${DIRTY}" | wc -l | tr -d ' ') 处）—— 不静默覆盖："
  printf '%s\n' "${DIRTY}" | sed 's/^/     /'
  echo "   活锚必须**只读**：改研发模式请改产品仓库 + 走 PR。人工看清后再处置（例如先"
  echo "   \`git -C \"${MIRROR}\" diff\` 看是谁改了什么，确认可弃后 \`git -C \"${MIRROR}\" checkout --detach ${REF}\`）。"
  exit 1
fi

BEFORE="$(git -C "${MIRROR}" rev-parse --short HEAD 2>/dev/null || echo '?')"

# ③ 前进：fetch + checkout --detach（不用 merge —— 镜像没有分支状态，它就是 detached 的）
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

# ④ 一致性提示：刷新的是镜像，但**真正生效的是活锚**（软链解析到哪，就用哪）
RESOLVED="$(readlink "${LIVE}" 2>/dev/null || echo '')"
case "${RESOLVED}" in
  "${MIRROR%/}/"*) : ;;
  *) echo "⚠️ 注意：活锚（${LIVE}）并不指向本镜像（readlink=${RESOLVED:-未接线}）"
     echo "   ⇒ 刷新本镜像**不会**让活锚跟上；换链见 AGENTS.md「开发环境准备」（先备份、再 ln -sfn）。" ;;
esac

# ⑤ 自检（默认必须跑）：刷新后仍红 = 刷新没解决问题（例如活锚根本指向别处）
if [ "${RUN_CHECK}" = "1" ]; then
  echo
  CHECK="${ROOT}/scripts/preset-anchor-check.sh"
  [ -x "${CHECK}" ] || { echo "❌ 自检脚本不可执行：${CHECK}" >&2; exit 2; }
  set +e
  "${CHECK}" --anchor "${LIVE}" --repo "${BASELINE}" --ref "${REF}"
  rc=$?
  set -e
  if [ "${rc}" != "0" ]; then
    echo
    echo "❌ 刷新后自检仍红（exit ${rc}）—— 见上方判定输出：镜像刷了，但**活锚**没有因此变新鲜"
    echo "   （常见原因：活锚指向别处 / 活锚是手抄副本 / 基线仓的 ${REF} 本身没 fetch）。"
    exit 1
  fi
  echo
  echo "✅ 活锚自愈完成：镜像已跟随 ${REF}，且自检绿。"
fi