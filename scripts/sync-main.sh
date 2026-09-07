#!/usr/bin/env bash
# =============================================================================
# sync-main.sh — PR 分支同步 main 一条龙（fetch + merge + 重渲染生成物 + 提交）
#
# 背景（2026-09-07 复盘）：PR open→merge 长尾耗时 90% 来自两个返工模式：
#   ① CI 首轮红了无人盯 → 2 小时空窗；
#   ② merge origin/main 后 cases/ 单一源前进，生成物（eval_cases.py /
#      mibao-verification-cases.md）未同步 → CI「生成物新鲜度校验」必红
#      → 手动重渲染 + 再 push + 多跑一轮全量 CI。
# 本脚本把「同步 main + 重渲染生成物 + 提交」合成一步，杜绝②类返工。
#
# 用法（在 migao 仓库/任一 worktree 根目录执行）：
#   ./scripts/sync-main.sh            # fetch origin/main → merge → 重渲染 → 自动提交
#   ./scripts/sync-main.sh --rebase   # 用 rebase 替代 merge（提交历史更线性）
#   ./scripts/sync-main.sh --no-commit # 只 merge + 重渲染，不自动提交（人工审 diff）
#
# 行为：
#   1. 前置检查：当前在哪个分支（禁止 main）、工作区是否干净（防误带未提交改动）
#   2. git fetch origin main
#   3. merge/rebase origin/main（冲突时中止并提示）
#   4. 重渲染生成物（.github/render_cases.py → eval_cases.py + casebook.md）
#   5. 有 diff → 自动提交（仅含两个生成物文件，message 标准化）：
#      "chore(cases): 合并 main 后重渲染生成物（N 条）"
#   6. 提醒 push
#
# 环境变量：
#   RENDER_CASES_ARGS=...  # 可选，覆盖渲染器参数（默认指向仓库内单一源）
#
# 注意：本脚本需兼容 macOS 自带 bash 3.2 —— `$var` 后紧跟非 ASCII 字符会被
# 并入变量名（如 `$path（` → `path<0xE3>` 报 unbound variable），
# 因此所有后跟中文的变量一律用 ${var} 显式包裹。
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

MODE="merge"
AUTO_COMMIT=1
for arg in "$@"; do
  case "$arg" in
    --rebase)   MODE="rebase" ;;
    --no-commit) AUTO_COMMIT=0 ;;
    -h|--help)  sed -n 's/^# \{0,1\}//p' "$0" | sed -n '/^sync-main.sh/,/^===/p' | head -25; exit 0 ;;
    *) echo "❌ 未知参数: $arg（支持 --rebase / --no-commit）" >&2; exit 1 ;;
  esac
done

EVAL_OUT="tests/agent_eval/eval_cases.py"
CASEBOOK_OUT="docs/testing/mibao-verification-cases.md"

echo "── 1/5 前置检查 ──"
BRANCH="$(git branch --show-current)"
if [ -z "$BRANCH" ] || [ "$BRANCH" = "main" ]; then
  echo "❌ 请在非 main 分支上运行本脚本（当前: ${BRANCH:-detached}）" >&2
  exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "❌ 工作区有未提交改动，请先 commit/stash 再同步（防未提交改动静默携带）：" >&2
  git status --short >&2
  exit 1
fi

echo "── 2/5 fetch origin/main ──"
git fetch origin main

echo "── 3/5 ${MODE} origin/main ──"
if [ "$MODE" = "rebase" ]; then
  git rebase origin/main || { echo "❌ rebase 冲突，请解决后重跑本脚本" >&2; exit 1; }
else
  git merge origin/main --no-edit || { echo "❌ merge 冲突，请解决后重跑本脚本" >&2; exit 1; }
fi

echo "── 4/5 重渲染生成物（cases/ 单一源 → 生成物）──"
if [ ! -f ".github/render_cases.py" ] || [ ! -d ".github/cases" ]; then
  echo "ℹ️ 无 render_cases.py 或 cases/，跳过重渲染"
  exit 0
fi
python3 .github/render_cases.py \
  --cases .github/cases \
  --out-eval "$EVAL_OUT" \
  --out-md "$CASEBOOK_OUT" >/dev/null

if git diff --exit-code -- "$EVAL_OUT" "$CASEBOOK_OUT" >/dev/null 2>&1; then
  echo "✅ 生成物已是最新（无 diff），无额外提交"
else
  echo "ℹ️ 生成物有更新："
  git diff --stat -- "$EVAL_OUT" "$CASEBOOK_OUT"
  if [ "$AUTO_COMMIT" -eq 0 ]; then
    echo "ℹ️ --no-commit：请人工审 diff 后自行提交"
    exit 0
  fi
  CHANGES="$(git diff --cached --stat | tail -1 | grep -oE '[0-9]+ files? changed' || echo "生成物更新")"
  git commit -m "chore(cases): 合并 main 后重渲染生成物（${CHANGES}）"
  echo "✅ 已提交生成物重渲染"
fi

echo "── 5/5 完成 ──"
echo "分支 ${BRANCH} 已同步 origin/main。CI 即将重跑，请盯首轮结果（见 migao-dev-flow §11）："
echo "  gh pr checks <PR> --watch"
echo "push 分支后 CI 红了立即修复，禁止丢下红 CI 去开新任务。"