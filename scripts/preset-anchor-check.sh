#!/usr/bin/env bash
# =============================================================================
# preset-anchor-check.sh — 活锚新鲜度自检（**红就停**；issue #4026）
#
# 判的是什么：**DSH 真正加载的那份内容**（软链 `~/.dsh/.agent-presets/migao` 解析出的 preset 目录）
# 是否就是本仓库 `origin/main` 上的 `.agent-presets/migao/` —— 内容逐字节 + 检出 sha 两面都核。
#
# 为什么单靠 `preset-guard` 不够：那条只查「仓库里的 `.agent-presets/**` 版本单调性」，
# **查不出活锚落后** —— 实测活锚曾指向一个落后 `origin/main` **42 个提交**的主工作区：
# 内容当时恰好一致（无害），但只要下一次有人改预设并合并，改进就**永远到不了加载点**，
# 后续所有会话读到的仍是旧模式。这就是「迭代了但模式没进化」的确切机制。
#
# 用法（在任一 migao 工作区根目录执行；**开工第一件事** + 提交前）：
#   ./scripts/preset-anchor-check.sh                    # 核本机活锚 vs 本仓库 origin/main
#   ./scripts/preset-anchor-check.sh --fetch            # 先 fetch origin main（基线更新）再核
#   ./scripts/preset-anchor-check.sh --anchor <路径>     # 核指定路径（**显式 ⇒ 一律判定**）
#   ./scripts/preset-anchor-check.sh --repo <基线仓> --ref <ref>
#   MIGAO_PRESET_LIVE=<路径> ./scripts/preset-anchor-check.sh
#
# 退出码：0 = 绿（新鲜）**或** ⏭️ 未跑判定（本机没接线 / 与基线仓不同源）；
#         1 = 红（落后 / 悬空 / 内容不同 / 技能加载不了）；
#         2 = 环境或用法错误（找不到 python3 等）。
# ⚠️ `⏭️ 未跑判定` **不是**「通过」，读输出时别把两者混起来（本仓库「空跑=假绿」同族）。
#
# 判定本体在 `scripts/agent-presets-guard.py` 的 `anchor` 子命令（三态与判据写在那里的文件头），
# 本脚本只是入口 —— 判据只放一处，避免第二份口径。
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ANCHOR="${MIGAO_PRESET_LIVE:-$HOME/.dsh/.agent-presets/migao}"
REPO="${ROOT}"
REF="origin/main"
FETCH=0

while [ $# -gt 0 ]; do
  case "$1" in
    --fetch) FETCH=1; shift ;;
    --anchor) [ $# -ge 2 ] || { echo "❌ --anchor 缺参数（用法见脚本头部）" >&2; exit 2; }; ANCHOR="$2"; shift 2 ;;
    --repo)   [ $# -ge 2 ] || { echo "❌ --repo 缺参数" >&2; exit 2; };   REPO="$2";   shift 2 ;;
    --ref)    [ $# -ge 2 ] || { echo "❌ --ref 缺参数" >&2; exit 2; };    REF="$2";    shift 2 ;;
    -h|--help) sed -n 's/^# \{0,1\}//p' "$0" | sed -n '/^preset-anchor-check.sh/,/^====/p'; exit 0 ;;
    *) echo "❌ 未知参数：$1（用法见脚本头部）" >&2; exit 2 ;;
  esac
done

PY="$(command -v python3.11 || command -v python3 || true)"
if [ -z "${PY}" ]; then
  echo "❌ 找不到 python3 —— 无法判定活锚新鲜度（fail-closed，判定不得退化成放行）：" >&2
  echo "   人工兜底：readlink \"\$HOME/.dsh/.agent-presets/migao\" 后与" >&2
  echo "   \`git show origin/main:.agent-presets/migao/skills/migao-dev-flow/SKILL.md\` 的 version 对一下" >&2
  exit 2
fi

GUARD="${ROOT}/scripts/agent-presets-guard.py"
[ -f "${GUARD}" ] || { echo "❌ 判定本体缺失：${GUARD}" >&2; exit 2; }

if [ "${FETCH}" = "1" ]; then
  if git -C "${REPO}" fetch --quiet origin main 2>/dev/null; then
    echo "已 fetch origin main（基线更新到 $(git -C "${REPO}" rev-parse --short origin/main)）"
  else
    echo "⚠️ fetch 失败（离线 / 无权限？）—— 下面按**本地已知的** origin/main 判定"
  fi
fi

# `--anchor` 一律显式传给判定本体：显式 ⇒ **一律判定**（不因「与基线仓不同源」跳过）
exec "${PY}" "${GUARD}" --repo "${REPO}" anchor --anchor "${ANCHOR}" --ref "${REF}"