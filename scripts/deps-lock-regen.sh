#!/usr/bin/env bash
# =============================================================================
# deps-lock-regen.sh — 依赖 PR 的 lock 修复（dependabot 的 lock 与 CI 的 npm 对不上）
#
# 由来（issue #7688，2026-10-25 一晚复现 5 次）
#   ① dependabot（与本机 node 24/npm 11）重新生成的 package-lock.json 比 CI 期望的**少一批条目**，
#      而 admin-web 相关腿跑 node 20.20.2 / npm 10.8.2 ⇒ `npm ci` 直接
#      `EUSAGE: package.json and package-lock.json … not in sync` ⇒ 三条 required/关键腿全红；
#   ② **顺序即安全顺序**：`gh pr update-branch`（把 main 合进 dependabot 分支）会把补齐的条目**再吃掉**
#      （lock 冲突取 main 侧）⇒ 必须「先 update-branch，再补 lock，补完立刻 push + 合」。
#      本脚本把这两步钉在一条命令里，**不许**手工拆开（拆开 = 又一轮假红）。
#
# 用法（在 PR 的分支工作区里执行；不要在 main 工作区跑）
#   ./scripts/deps-lock-regen.sh <PR号>              # 真跑：update-branch → 补 lock → 自证 → 提交推送
#   ./scripts/deps-lock-regen.sh <PR号> --print-plan # 只打印步骤顺序（零网络；判据用它钉顺序）
#   ./scripts/deps-lock-regen.sh <PR号> --dry-run    # 真跑前两步（update-branch + 补 lock + 自证），不提交
#
# 环境变量
#   NPM_FOR_LOCK  生成 lock 用的 npm 版本（默认 10.8.2 = CI 的 node 20.20.2 自带版本）
#
# 退出码
#   0 已一致或已修好并推送 / 1 用法或前置条件不满足 / 2 lock 仍不同步（自证失败，不许推）
# =============================================================================
set -uo pipefail

PR="${1:-}"
MODE="${2:-run}"
NPM_FOR_LOCK="${NPM_FOR_LOCK:-10.8.2}"

die() { echo "❌ $*" >&2; exit 1; }

[ -n "$PR" ] || die "用法：./scripts/deps-lock-regen.sh <PR号> [--print-plan|--dry-run]"
case "$MODE" in
  run|--dry-run|--print-plan) ;;
  *) die "未知参数：${MODE}（只支持 --print-plan / --dry-run）" ;;
esac
command -v gh >/dev/null || die "缺 gh"
command -v git >/dev/null || die "缺 git"

# --- PR 元数据（零写面：只读） -------------------------------------------------
BRANCH="$(gh pr view "$PR" --json headRefName -q .headRefName)" || die "读不到 PR #$PR 的分支"
DIRS="$(gh pr view "$PR" --json files -q '[.files[].path | select(endswith("/package-lock.json")) | sub("/package-lock.json$";"")] | unique | .[]')"
[ -n "$DIRS" ] || die "PR #$PR 没有改动任何 package-lock.json ⇒ 本脚本不适用（不要拿它当通用 update-branch 用）"

plan() {
  echo "PR #${PR}（分支 ${BRANCH}）的 lock 修复顺序："
  echo "  1) gh pr update-branch $PR            # 先把 main 合进来（**必须在前**：它会把之前补的 lock 条目吃掉）"
  echo "  2) git pull --ff-only                 # 把 update-branch 的结果拉到本地"
  for d in $DIRS; do
    echo "  3) (cd $d && npx -y npm@$NPM_FOR_LOCK install --package-lock-only)"
  done
  for d in $DIRS; do
    echo "  4) (cd $d && npx -y npm@$NPM_FOR_LOCK ci --dry-run)   # 自证：这一步不过就不许推"
  done
  echo "  5) git add <lock> && git commit && git push          # 补完立刻推；随后立刻合，别再 update-branch"
}

if [ "$MODE" = "--print-plan" ]; then
  plan
  exit 0
fi

# --- 前置：**写盘档**必须在 PR 的分支工作区里跑（防「改到 main 工作区」） --------
# `--print-plan` 是只读档（只读 PR 元数据 + 打印步骤）⇒ 不做这条检查，否则判据没法零网络钉顺序。
if [ "$MODE" != "--print-plan" ]; then
  CURRENT="$(git rev-parse --abbrev-ref HEAD)"
  [ "$CURRENT" = "$BRANCH" ] || die "当前分支是 ${CURRENT}，不是 PR #$PR 的 $BRANCH ⇒ 先 git checkout ${BRANCH}（或在该分支的工作区里跑）"
fi

echo "── PR #${PR}（${BRANCH}）──"
echo "① update-branch"
gh pr update-branch "$PR" >/dev/null 2>&1 || echo "   （无需更新或已是最新）"
echo "② git pull --ff-only"
git pull --ff-only >/dev/null 2>&1 || die "拉不下来（本地有未提交改动或分叉）⇒ 先处理工作区"

CHANGED=0
for d in $DIRS; do
  echo "③ 补 lock：${d}（npm $NPM_FOR_LOCK 视角）"
  ( cd "$d" && npx -y "npm@$NPM_FOR_LOCK" install --package-lock-only --no-audit --no-fund >/dev/null 2>&1 ) \
    || die "${d}：npm install --package-lock-only 失败"
  echo "④ 自证：$d → npm ci --dry-run"
  if ! ( cd "$d" && npx -y "npm@$NPM_FOR_LOCK" ci --dry-run --no-audit --no-fund >/dev/null 2>&1 ); then
    echo "❌ $d 的 lock 在 npm $NPM_FOR_LOCK 视角仍不同步（自证失败）" >&2
    exit 2
  fi
  if ! git diff --quiet -- "$d/package-lock.json"; then
    CHANGED=1
    git add "$d/package-lock.json"
  fi
done

if [ "$CHANGED" -eq 0 ]; then
  echo "✅ lock 已一致（无需提交）"
  exit 0
fi
if [ "$MODE" = "--dry-run" ]; then
  echo "（--dry-run：lock 已修好但**未提交**；真跑请去掉 --dry-run）"
  exit 0
fi
echo "⑤ 提交并推送（补完立刻推：随后立刻合，别再 update-branch）"
git -c user.name="migao-deps-lockfix" -c user.email="noreply@migao.local" \
  commit -q -m "chore(deps): 用 npm $NPM_FOR_LOCK 视角重生成 package-lock（CI 用 node 20/npm 10，npm ci 判 EUSAGE）（关联 #7688）"
git push origin "HEAD:$BRANCH" || die "推送失败"
echo "✅ 已推送（现在去合；别再对它 update-branch）"
