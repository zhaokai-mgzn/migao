#!/usr/bin/env bash
# =============================================================================
# issue-lifecycle.sh — 「一个 issue 收尾」的**单一入口**（事件驱动清理，非定时）
#
# 用法（在任一工作区/主工作区根目录执行）：
#   ./scripts/issue-lifecycle.sh finish <分支|工作区路径> [--dry-run]  # 收尾一个包 + 自证干净
#   ./scripts/issue-lifecycle.sh prune [--apply]                       # 批量：默认 dry-run，--apply 才删
#
# 为什么是**事件驱动**而不是定时任务（用户裁定，2026-09-21）：
#   ① 无人值守地删东西**不安全**（`migao-wt/*` 就在清理半径内）；
#   ② 每个周期都烧 CI 分钟、**浪费时间成本**。
#   ⇒ 判定落在「一个包收尾」这一刻，**只由人/agent 显式调用**触发（不新增 schedule、不改 cron）。
#
# 收尾一次做完（顺序即安全顺序）：
#   ① 验证该分支的 PR **已合并**（判据 = 「有已合并 PR」，**不用** --merged / git cherry /
#      commit 可达性 —— 本仓含 squash 合并，那些手法**结构性失效**）；
#      **未合并 ⇒ fail-closed，什么都不删**（保护在飞分支）；取不到 gh ⇒ exit 3（无法判定，不得当 0 读）
#   ② 删 worktree；③ 删本地分支；④ 删远程分支（仅当 ① 成立）；
#   ⑤ 清过程产物（pr-body* / tests/tmp/* / .pytest_cache / __pycache__）——**不碰仓库资产**；
#   ⑥ 自证干净（worktree list / 本地分支 / 远程分支 三项 + 主工作区 git status）。
#
# 🔴 活锚硬保护：删除前先 `readlink "$HOME/.dsh/.agent-presets/migao"`，把解析出的目标
#   （及其父目录，当父目录是 preset 目录时）排除在外 —— 误删软链目标 ⇒ DSH **静默**加载不到
#   研发模式（issue #3956 实证）。落码在 scripts/issue_lifecycle.py 的 anchor_protected_paths()。
#
# 判定本体在 scripts/issue_lifecycle.py（可独立单测，含能**单独变红**的注入式红证）；
# 「PR 已合并」与 worktree 解析**复用** scripts/agent-presets-guard.py，不另写第二套。
# 相关的 `dev-worktree.sh rm/prune` 保持不变：`prune` 仍是**只出清单的存量体检**，
# 本脚本的 `prune --apply` 是**执行**侧（默认 dry-run，与 rm 的显式破坏性语义一致）。
#
# 环境变量：
#   MIGAO_ANCHOR=...   # 覆盖活锚路径（默认 $HOME/.dsh/.agent-presets/migao）；主要给测试注入
#   MIGAO_GH_BIN=...   # 覆盖 gh 可执行文件（替身注入点；默认 gh）
#   MIGAO_WT_BASE=...  # 同 dev-worktree.sh（本脚本只用它解析默认工作区根）
#
# 注意：本脚本需兼容 macOS 自带 bash 3.2（变量后跟非 ASCII 字符一律 ${var} 显式包裹）。
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$(command -v python3.11 || command -v python3 || true)"
if [ -z "${PY}" ]; then
  echo "❌ 找不到 python3 —— 无法执行收尾判定（fail-closed，什么都不删）。" >&2
  exit 3
fi

impl="${ROOT}/scripts/issue_lifecycle.py"
[ -f "${impl}" ] || { echo "❌ 判定本体缺失：${impl}" >&2; exit 1; }

exec "${PY}" "${impl}" "$@"
