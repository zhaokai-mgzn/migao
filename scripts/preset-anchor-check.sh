#!/usr/bin/env bash
# =============================================================================
# preset-anchor-check.sh — 活锚新鲜度自检（**红就停**；issue #4026 / 迁移单 #6020）
#
# 判的是什么：**DSH 真正加载的那份内容**（软链 `~/.dsh/.agent-presets/migao` 解析出的 preset 目录）
# 是否就是**预设仓 `zhaokai-mgzn/migao-agent-presets` 的 `main`** —— 内容逐字节 + 检出 sha 两面都核。
#
# 🔴 S4（issue #6020）：预设的**权威源**已从业务仓 `.agent-presets/migao/**` 迁到**独立预设仓**，
#   本仓**不再承载**预设内容。因此：
#     · 活锚 = 软链 → **专职只读镜像的仓根**（`$HOME/migao-dev-preset-anchor`，旧口径是
#       `<镜像>/.agent-presets/migao`）；
#     · 基线 = **预设仓的 `origin/main`**（旧口径是业务仓的 origin/main）；
#     · 镜像的克隆源 = **预设仓**（`MIGAO_PRESET_REPO_URL` 覆盖）。
#   按 `#6020` 的顺序铁律，换链（S3）在迁移 PR 合并之后做 ⇒ **换链之前跑本脚本会红**，
#   那是「旧镜像 + 新脚本」的**预期过渡态**，不是回归。
#
# 为什么单靠 `preset-guard` / 预设仓自己的 CI 不够：那两条只查**仓内**内容（版本单调、沿革不回流），
# **查不出活锚落后** —— 实测活锚曾指向一个落后 `origin/main` **42 个提交**的主工作区：
# 内容当时恰好一致（无害），但只要下一次有人改预设并合并，改进就**永远到不了加载点**，
# 后续所有会话读到的仍是旧模式。这就是「迭代了但模式没进化」的确切机制。
#
# ⚠️ 「镜像自己有没有跟上远端」是**另一条**判据，且它必须用**远端**当参照物：镜像既当活锚
#   （只读、绝不 fetch）又当基线的话，拿它自己量自己是恒等的 ⇒ 落后永远判不出来。故本脚本用
#   `git ls-remote <预设仓> main`（**只读远端、不写入镜像**）取远端 sha 传给判定本体。
#   取不到（离线 / 无权限）⇒ 退到镜像本地已知的 ref，并**降级出声**，不静默当通过。
#
# 用法（在任一 migao 工作区根目录执行；**开工第一件事** + 提交前）：
#   ./scripts/preset-anchor-check.sh                    # 核本机活锚 vs 预设仓 main
#   ./scripts/preset-anchor-check.sh --fetch            # 先把镜像 fetch 到预设仓 main 再核
#   ./scripts/preset-anchor-check.sh --anchor <路径>     # 核指定路径（**显式 ⇒ 一律判定**）
#   ./scripts/preset-anchor-check.sh --repo <基线仓> --ref <ref>
#   MIGAO_PRESET_LIVE=<路径> ./scripts/preset-anchor-check.sh
#   MIGAO_PRESET_MIRROR=<路径> ./scripts/preset-anchor-check.sh
#   MIGAO_PRESET_REPO_URL=<url|路径> ./scripts/preset-anchor-check.sh
#
# 退出码（**三态**，与 `scripts/agent-presets-guard.py` / `scripts/drift_audit.py` 同口径）：
#         0 = 绿（新鲜）**或** ⏭️ 未跑判定（本机没接线 / 与基线仓**有证据地**不同源）；
#         1 = 红（落后 / 悬空 / 内容不同 / **镜像不在远端 main 上** / 技能加载不了）；
#         3 = **无法判定**（基线 ref 取不到 ⇒ 连「能不能比」都判不了 —— **不得当 0 读**；issue #5430）；
#         2 = 环境或用法错误（找不到 python3 等）。
# ⚠️ `⏭️ 未跑判定` 与 `3 无法判定` **都不是**「通过」，读输出时别把它们混起来（本仓库「空跑=假绿」同族）。
#
# 判定本体在 `scripts/agent-presets-guard.py` 的 `anchor` 子命令（三态与判据写在那里的文件头），
# 本脚本只是入口 —— 判据只放一处，避免第二份口径。
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ANCHOR="${MIGAO_PRESET_LIVE:-$HOME/.dsh/.agent-presets/migao}"
MIRROR="${MIGAO_PRESET_MIRROR:-$HOME/migao-dev-preset-anchor}"
# 基线仓 = 预设仓的本地检出（默认就是镜像）。S4 起预设内容在**仓根**（不再有 `.agent-presets/migao` 层）。
REPO="${MIGAO_PRESET_BASELINE:-$MIRROR}"
REPO_URL="${MIGAO_PRESET_REPO_URL:-git@github.com:zhaokai-mgzn/migao-agent-presets.git}"
REF="origin/main"
FETCH=0

while [ $# -gt 0 ]; do
  case "$1" in
    --fetch) FETCH=1; shift ;;
    --anchor) [ $# -ge 2 ] || { echo "❌ --anchor 缺参数（用法见脚本头部）" >&2; exit 2; }; ANCHOR="$2"; shift 2 ;;
    --repo)   [ $# -ge 2 ] || { echo "❌ --repo 缺参数（用法见脚本头部）" >&2; exit 2; };   REPO="$2";   shift 2 ;;
    --ref)    [ $# -ge 2 ] || { echo "❌ --ref 缺参数（用法见脚本头部）" >&2; exit 2; };    REF="$2";    shift 2 ;;
    -h|--help) sed -n 's/^# \{0,1\}//p' "$0" | sed -n '/^preset-anchor-check.sh/,/^====/p'; exit 0 ;;
    *) echo "❌ 未知参数：$1（用法见脚本头部）" >&2; exit 2 ;;
  esac
done

PY="$(command -v python3.11 || command -v python3 || true)"
if [ -z "${PY}" ]; then
  echo "❌ 找不到 python3 —— 无法判定活锚新鲜度（fail-closed，判定不得退化成放行）：" >&2
  echo "   人工兜底：readlink \"\$HOME/.dsh/.agent-presets/migao\" 后与预设仓的" >&2
  echo "   \`git show origin/main:skills/migao-dev-flow/SKILL.md\` 的 version 对一下（在预设仓检出里跑）" >&2
  exit 2
fi

GUARD="${ROOT}/scripts/agent-presets-guard.py"
[ -f "${GUARD}" ] || { echo "❌ 判定本体缺失：${GUARD}" >&2; exit 2; }

# 🔴 镜像必须**只读且绝不 fetch**：它是活锚的软链目标，就地写它 = 在 DSH 正加载的那份内容上动手。
#   故「把镜像刷到预设仓 main」这条自愈**只在这里**（`--fetch`，人显式要求），其余一律只读。
if [ "${FETCH}" = "1" ]; then
  if ! git -C "${REPO}" rev-parse --git-dir >/dev/null 2>&1; then
    echo "⚠️ --fetch 跳过：${REPO} 不是 git 检出（取不到它的 origin/main）—— 按下面的判定输出处置"
  elif git -C "${REPO}" fetch --prune origin main 2>/dev/null; then
    echo "已 fetch 预设仓 main（${REPO} 的 origin/main → $(git -C "${REPO}" rev-parse --short origin/main 2>/dev/null || echo '?'))"
  else
    echo "⚠️ fetch 预设仓 main 失败（离线 / 无权限？）—— 下面按**本地已知的** origin/main 判定"
  fi
fi

# 镜像相对**远端** main 落后与否（换链后「活锚 ⇄ 镜像」是同一份，旧判据失去第二视角 ⇒ 这里补上
# 一条**新增**判据；既有判据一条不放宽）。`ls-remote` **只读远端**、不写镜像 ⇒ 与「镜像只读」不冲突；
# 取不到时**出声降级**（只跳过这一条），不静默当成通过。
REMOTE_ARGS=()
if git -C "${REPO}" rev-parse --git-dir >/dev/null 2>&1; then
  REMOTE_SHA="$(git ls-remote "${REPO_URL}" main 2>/dev/null | awk '{print $1}' | head -1 || true)"
  if [ -n "${REMOTE_SHA}" ]; then
    REMOTE_ARGS=(--remote-sha "${REMOTE_SHA}")
  else
    echo "⚠️ 取不到预设仓 main 的远端 sha（${REPO_URL}：离线 / 无权限 / 仓名变了）"
    echo "   ⇒ 这一轮**判不了「镜像有没有落后远端」**（其余判据照常跑）—— 这不是「通过」。"
  fi
fi

# `--anchor` 一律显式传给判定本体：显式 ⇒ **一律判定**（不因「与基线仓不同源」跳过）
# `--anchor-base ''`：S4 起预设内容在**预设仓仓根**（不再有 `.agent-presets/migao` 这一层）。
exec "${PY}" "${GUARD}" --repo "${REPO}" anchor \
  --anchor "${ANCHOR}" \
  --anchor-base "" \
  --ref "${REF}" \
  --expected-remote "${REPO_URL}" \
  ${REMOTE_ARGS[@]+"${REMOTE_ARGS[@]}"}
