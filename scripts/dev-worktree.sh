#!/usr/bin/env bash
# =============================================================================
# dev-worktree.sh — MIGAO 多分支并行开发工作区管理（git worktree 快捷封装）
#
# 背景：本地开多个分支做开发/验证时，反复 `git checkout` 切换会把工作区文件
# 整体替换为旧分支内容，未提交改动还会被静默携带 → 「切换分支后功能退化」。
# git worktree 让每个分支拥有独立工作目录（node_modules/dist 互不干扰），
# 切换零污染。本脚本封装常用操作。
#
# 用法（在 migao 仓库根目录执行）：
#   ./scripts/dev-worktree.sh add <branch> [路径]   # 为分支创建独立工作区（默认 ../migao-wt/<分支>）
#   ./scripts/dev-worktree.sh list                  # 列出所有工作区
#   ./scripts/dev-worktree.sh rm <分支|路径> [--delete-branch]  # 移除工作区（可选连带删分支）
#
# 环境变量：
#   MIGAO_WT_BASE=...  # 覆盖工作区根目录（默认仓库父目录下的 migao-wt/）
#
# 注意：本脚本需兼容 macOS 自带 bash 3.2 —— `$var` 后紧跟非 ASCII 字符会被
# 并入变量名（如 `$path（` → `path<0xE3>` 报 unbound variable），
# 因此所有后跟中文的变量一律用 ${var} 显式包裹。
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WT_BASE="${MIGAO_WT_BASE:-$ROOT/../migao-wt}"

usage() {
  sed -n 's/^# \{0,1\}//p' "$0" | sed -n '/^dev-worktree.sh/,/^===/p' | head -20
  exit 1
}

# 分支名 → 工作区目录名：feat/xiaobu-voice-holdtalk → xiaobu-voice-holdtalk
slug() { echo "$1" | sed -E 's#^(feat|fix|chore|docs|test|refactor)/##; s#/#-#g'; }

cmd_add() {
  [ $# -ge 1 ] || usage
  local branch="$1"
  local path="${2:-$WT_BASE/$(slug "$branch")}"

  # 建 worktree 前先提醒主工作区未提交改动（防被静默携带/混淆）
  if [ "$(git -C "$ROOT" status --porcelain | wc -l | tr -d ' ')" -gt 0 ]; then
    echo "⚠️  主工作区有未提交改动，建议先 commit/stash 再建 worktree："
    git -C "$ROOT" status --short | head -10
  fi

  # 分支必须存在（本地或远程），否则给出创建提示
  if ! git -C "$ROOT" show-ref --verify --quiet "refs/heads/$branch" \
     && ! git -C "$ROOT" show-ref --verify --quiet "refs/remotes/origin/$branch"; then
    echo "❌ 分支 ${branch} 不存在（本地/远程均无）。请先创建并推送，或指定已存在的分支。"
    echo "   远程存在但本地无分支时，脚本会自动创建跟踪分支。"
    exit 1
  fi
  local branch_arg
  if git -C "$ROOT" show-ref --verify --quiet "refs/heads/$branch"; then
    branch_arg="$branch"
  else
    branch_arg="--track $branch origin/$branch"
  fi

  if [ -e "$path" ]; then
    echo "❌ 目标路径已存在：${path}"
    exit 1
  fi
  mkdir -p "$(dirname "$path")"
  git -C "$ROOT" worktree add "$path" $branch_arg
  echo
  echo "✅ 工作区就绪：${path}（分支 ${branch}）"
  echo "   ⚠️  worktree 是独立目录，首次使用需自行安装依赖："
  echo "      cd ${path}"
  [ -f "$ROOT/package.json" ] && echo "      npm ci"
  [ -d "$ROOT/frontend/mini-app" ] && echo "      cd frontend/mini-app && npm ci"
  echo "   ⚠️  build 产物（dist/）不入库，worktree 之间互不影响。"
}

cmd_list() {
  git -C "$ROOT" worktree list
}

cmd_rm() {
  [ $# -ge 1 ] || usage
  local target="$1"
  local delete_branch=0
  for a in "$@"; do [ "$a" = "--delete-branch" ] && delete_branch=1; done

  local path=""
  local branch=""
  if [ -d "$target" ]; then
    path="$target"
    branch="$(git -C "$path" branch --show-current 2>/dev/null || true)"
  else
    # target 视为分支名：porcelain 按 worktree/HEAD/branch 分组，branch 是块尾，向前 2 行找 worktree
    local line
    line="$(git -C "$ROOT" worktree list --porcelain | grep -B2 "^branch refs/heads/$target$" | grep '^worktree' | head -1 || true)"
    [ -z "$line" ] && { echo "❌ 找不到 worktree：${target}"; exit 1; }
    path="${line#worktree }"
    branch="$target"
  fi

  git -C "$ROOT" worktree remove "$path" --force
  echo "✅ 已移除工作区：${path}"

  if [ "$delete_branch" = "1" ] && [ -n "$branch" ]; then
    # 分支可能同时被其他 worktree 使用，检查后再删
    if git -C "$ROOT" show-ref --verify --quiet "refs/heads/$branch" \
       && ! git -C "$ROOT" worktree list --porcelain | grep -q "^branch refs/heads/$branch$"; then
      git -C "$ROOT" branch -D "$branch"
      echo "✅ 已删除分支：${branch}"
    else
      echo "ℹ️  分支 ${branch} 仍被其他工作区引用，未删除"
    fi
  fi
}

case "${1:-}" in
  add)  shift; cmd_add "$@" ;;
  list) cmd_list ;;
  rm)   shift; cmd_rm "$@" ;;
  *)    usage ;;
esac
