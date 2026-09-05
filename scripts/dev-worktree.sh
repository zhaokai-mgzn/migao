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
#   ./scripts/dev-worktree.sh list                  # 列出所有工作区 + 会话锁状态
#   ./scripts/dev-worktree.sh lock                  # 查看/清理会话锁（多会话并发时先查锁）
#   ./scripts/dev-worktree.sh rm <分支|路径> [--delete-branch]  # 移除工作区（可选连带删分支）
#
# 会话锁（v1.3，2026-09-04 新增）：
#   多 DSH 会话并行开发防踩脚 —— add 时自动在 $ROOT/.git/sessions/ 登记会话锁
#   （进程 PID + 时间戳），同一分支已有活跃锁时拒绝重复建工作区；
#   rm 自动清理；lock 子命令查看/手动清理（含失效锁）。锁目录在 .git/ 下，
#   不污染工作区、不进 git。
#
# 误删保护（v1.5，2026-09-05 新增）：
#   rm --delete-branch 曾因 worktree 分支解析歧义误删本地 main（issue #2930）：
#   ① 改为按 path 从 `git worktree list --porcelain` 权威解析该工作区 HEAD 的分支；
#   ② 主干分支（main/master）硬保护，拒绝通过 --delete-branch 删除；
#   ③ 删除前打印实际删除的分支名，便于审计。
#
# 环境变量：
#   MIGAO_WT_BASE=...  # 覆盖工作区根目录（默认仓库父目录下的 migao-wt/）
#   FORCE_LOCK=1       # 忽略会话锁强制建工作区（危险，仅确认无活跃会话时用）
#
# 注意：本脚本需兼容 macOS 自带 bash 3.2 —— `$var` 后紧跟非 ASCII 字符会被
# 并入变量名（如 `$path（` → `path<0xE3>` 报 unbound variable），
# 因此所有后跟中文的变量一律用 ${var} 显式包裹。
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WT_BASE="${MIGAO_WT_BASE:-$ROOT/../migao-wt}"
LOCK_DIR="$ROOT/.git/sessions"
mkdir -p "$LOCK_DIR"

usage() {
  sed -n 's/^# \{0,1\}//p' "$0" | sed -n '/^dev-worktree.sh/,/^===/p' | head -20
  exit 1
}

# 分支名 → 工作区目录名：feat/xiaobu-voice-holdtalk → xiaobu-voice-holdtalk
slug() { echo "$1" | sed -E 's#^(feat|fix|chore|docs|test|refactor)/##; s#/#-#g'; }

# ── 会话锁（v1.3）：锁文件 = .git/sessions/<slug>.lock，内容 "PID|时间戳|分支|工作区路径"
lock_path() { echo "$LOCK_DIR/$(slug "$1").lock"; }

# 锁是否活跃：文件存在且记录 PID 对应的进程存活
lock_alive() {
  local f; f="$(lock_path "$1")"
  [ -f "$f" ] || return 1
  local pid; pid="$(cut -d'|' -f1 "$f" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

# 登记锁（add 成功后调用）
lock_register() {
  local branch="$1" path="$2"
  echo "$$|$(date '+%Y-%m-%d %H:%M:%S')|${branch}|${path}" > "$(lock_path "$branch")"
  echo "🔒 会话锁已登记：${branch}（PID $$）"
}

# 清理锁（rm / 手动）
lock_clean() {
  local f; f="$(lock_path "$1")"
  [ -f "$f" ] && rm -f "$f"
  echo "🔓 会话锁已释放：$1"
}

# 列出全部锁（含失效标记）
lock_list() {
  [ -d "$LOCK_DIR" ] || { echo "（无会话锁）"; return 0; }
  local found=0
  for f in "$LOCK_DIR"/*.lock; do
    [ -f "$f" ] || continue
    found=1
    local pid ts branch path
    pid="$(cut -d'|' -f1 "$f" 2>/dev/null || true)"
    ts="$(cut -d'|' -f2 "$f" 2>/dev/null || true)"
    branch="$(cut -d'|' -f3 "$f" 2>/dev/null || true)"
    path="$(cut -d'|' -f4 "$f" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      echo "🔒 $(basename "$f" .lock) | PID $pid | ${ts} | ${path}"
    else
      echo "💀 $(basename "$f" .lock) | PID ${pid:-?} | ${ts} | ${path}（进程已退出，锁失效）"
    fi
  done
  [ "$found" = "0" ] && echo "（无会话锁）"
}

# 清理失效锁（进程已退出的）
lock_prune() {
  local pruned=0
  for f in "$LOCK_DIR"/*.lock; do
    [ -f "$f" ] || continue
    local pid; pid="$(cut -d'|' -f1 "$f" 2>/dev/null || true)"
    if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
      echo "🧹 清理失效锁：$(basename "$f" .lock)"
      rm -f "$f"
      pruned=$((pruned + 1))
    fi
  done
  echo "已清理 ${pruned} 个失效锁"
}

cmd_add() {
  [ $# -ge 1 ] || usage
  local branch="$1"
  local path="${2:-$WT_BASE/$(slug "$branch")}"

  # 会话锁检查（v1.3）：同一分支已有活跃会话锁 → 拒绝重复建工作区（防多会话踩脚）
  if lock_alive "$branch" && [ "${FORCE_LOCK:-0}" != "1" ]; then
    echo "❌ 分支 ${branch} 已有活跃会话锁（见下方），拒绝重复建工作区："
    lock_list
    echo "   确认无其他会话在用后：./scripts/dev-worktree.sh lock --prune 清理失效锁；"
    echo "   或确有需要：FORCE_LOCK=1 强制（危险，仅确认无活跃会话时用）。"
    exit 1
  fi

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
  lock_register "$branch" "$path"
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
  echo
  echo "── 会话锁 ──"
  lock_list
}

# 按工作区路径权威解析其 HEAD 引用的分支名（v1.5，替代 branch --show-current：
# 后者在部分 git 场景下解析歧义，曾导致 rm 误删本地 main，见 issue #2930）。
# detached HEAD 无 branch 行 → 输出空。
wt_branch_of() {
  local wt="$1"
  git -C "$ROOT" worktree list --porcelain \
    | grep -A3 "^worktree ${wt}$" \
    | grep "^branch refs/heads/" \
    | cut -d' ' -f2- \
    | sed 's#^refs/heads/##'
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
    branch="$(wt_branch_of "$path" || true)"
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

  # 会话锁清理（v1.3）：移除工作区后释放对应锁
  if [ -n "$branch" ] && lock_alive "$branch" 2>/dev/null; then
    lock_clean "$branch"
  fi

  if [ "$delete_branch" = "1" ] && [ -n "$branch" ]; then
    # 主干分支硬保护（v1.5，issue #2930）：main/master 拒绝经 --delete-branch 删除
    if [ "$branch" = "main" ] || [ "$branch" = "master" ]; then
      echo "🛡️  拒绝删除主干分支：${branch}（如需删除请手动 git branch -D ${branch} 并确认）"
      return 0
    fi
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
  lock)
    shift
    case "${1:-}" in
      --prune) lock_prune ;;
      *)       lock_list ;;
    esac
    ;;
  *)    usage ;;
esac
