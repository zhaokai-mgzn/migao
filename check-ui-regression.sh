#!/usr/bin/env bash
# =============================================================================
# check-ui-regression.sh — 前端 UI 回退检测（防「工作区旧 UI 覆盖验收版」复发）
#
# 背景：PR #2575 因工作区积压 142 个未提交文件（含旧版 UI），git add -A 时
# 把 main 上已验收的「织物质感」UI（neutral 暖色 token）覆盖成旧版（gray/blue）。
# 本脚本在提交/合并前检测此类回退。
#
# 检测逻辑：对关键 UI 文件，对比「工作区/HEAD」与「origin/main」的 token 数量
#   - origin/main 有 neutral（验收版），工作区/HEAD neutral=0 → 回退，BLOCK
#   - origin/main 无 neutral（main 本来就是旧版），工作区也无 → 正常
#   - 正常业务改动（加 neutral）→ 放行
#
# 用法：
#   ./check-ui-regression.sh          # 检测工作区（默认）
#   ./check-ui-regression.sh --head   # 检测当前 HEAD（CI 用）
#   ./check-ui-regression.sh --fix    # 检测并打印修复建议
# 返回码：0=无回退；1=检测到回退
# =============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# 关键 UI 文件（验收版应含 neutral 暖色 token）
KEY_UI_FILES=(
  "frontend/admin-web/src/components/ui/Button.tsx"
  "frontend/admin-web/src/components/ui/Input.tsx"
  "frontend/admin-web/src/components/ui/Modal.tsx"
  "frontend/admin-web/src/components/ui/Select.tsx"
  "frontend/admin-web/src/components/ui/Table.tsx"
  "frontend/admin-web/src/components/ui/Badge.tsx"
  "frontend/admin-web/src/components/ui/Card.tsx"
  "frontend/admin-web/src/components/layout/Sidebar.tsx"
  "frontend/admin-web/src/components/layout/Header.tsx"
  "frontend/admin-web/src/components/chat/ChatArea.tsx"
  "frontend/admin-web/src/app/globals.css"
  "frontend/admin-web/tailwind.config.ts"
)

MODE="${1:-worktree}"

# 取文件内容（worktree=工作区，head=当前 HEAD 提交）
get_content() {
  local f="$1"
  case "$MODE" in
    worktree) cat "$f" 2>/dev/null ;;
    head) git show "HEAD:$f" 2>/dev/null ;;
    *) cat "$f" 2>/dev/null ;;
  esac
}

# 确保有 origin/main 可对比
git fetch origin main --quiet 2>/dev/null || true
if ! git rev-parse origin/main >/dev/null 2>&1; then
  echo "⚠️ 无 origin/main 可对比，跳过"
  exit 0
fi

FAIL=0
REGRESSED=0
for f in "${KEY_UI_FILES[@]}"; do
  # origin/main 的 neutral 数（验收版基线）
  main_neutral=$(git show "origin/main:$f" 2>/dev/null | grep -c "neutral" || true)
  # 待检内容的 neutral 数
  cur_neutral=$(get_content "$f" | grep -c "neutral" || true)

  if [ "$main_neutral" -gt 0 ] && [ "$cur_neutral" -eq 0 ]; then
    echo "❌ UI 回退: $f（origin/main 有 neutral=${main_neutral}，当前=${cur_neutral}）"
    REGRESSED=$((REGRESSED + 1))
    FAIL=1
  elif [ "$main_neutral" -gt 0 ] && [ "$cur_neutral" -lt "$main_neutral" ] && [ "$MODE" = "worktree" ]; then
    echo "⚠️ UI token 减少: $f（main=${main_neutral} → 当前=${cur_neutral}）"
  fi
done

if [ "$FAIL" = "0" ]; then
  echo "✅ UI 无回退（${MODE}），$([ "$REGRESSED" = 0 ] && echo '关键文件与 main token 一致或为正常新增' )"
  exit 0
else
  echo ""
  echo "❌ 检测到 ${REGRESSED} 个 UI 文件回退！"
  echo "   原因：工作区/HEAD 存在旧版 UI（gray/blue），origin/main 已是验收版（neutral）"
  echo "   修复：git checkout origin/main -- <file> 恢复验收版，再重新应用业务改动"
  echo "   预防：提交前先跑 ./check-ui-regression.sh；避免 git add -A 盲目提交"
  exit 1
fi
