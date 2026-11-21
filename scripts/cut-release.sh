#!/usr/bin/env bash
# 把 **release 发布线**快进到 main（2026-11-21 用户裁定 A）。
#
# 口径（别读反）：
#   · `main`      = 集成线：PR、CI、评审、auto-merge 全部照旧，**不变**；
#   · `release`   = 发布线：**部署机只认它**（`prod-ops` 预设里发布身份 = `origin/release` 的 sha）；
#   · 本脚本把「发布」变成一次**显式动作**，而不是「谁合了 main 就自动上线」。
#
# 纪律：release **只能**是 main 的快进（release ⊆ main）。release 上出现 main 没有的提交
#       ⇒ 立即退出 2（那意味着发布线被旁路，先查清来源再发布）。
#
# 用法：
#   ./scripts/cut-release.sh            # 快进并打印 REL_SHA
#   ./scripts/cut-release.sh --check    # 只看差多少，不改远端
#
# 退出码：0 = 已同步/快进成功；2 = 发布线被旁路（需人工处理）；3 = 无法判定（取不到远端 ref）。
set -euo pipefail

REMOTE="${REMOTE:-origin}"
MAIN_BRANCH="${MAIN_BRANCH:-main}"
RELEASE_BRANCH="${RELEASE_BRANCH:-release}"
MODE="${1:-push}"

git fetch --quiet "$REMOTE" "+refs/heads/$MAIN_BRANCH:refs/remotes/$REMOTE/$MAIN_BRANCH" \
                           "+refs/heads/$RELEASE_BRANCH:refs/remotes/$REMOTE/$RELEASE_BRANCH" 2>/dev/null || {
  git fetch --quiet "$REMOTE" || { echo "✗ 取不到远端 $REMOTE（不得当 0 读）" >&2; exit 3; }
}

main_sha=$(git rev-parse "$REMOTE/$MAIN_BRANCH" 2>/dev/null) || { echo "✗ 取不到 $REMOTE/$MAIN_BRANCH" >&2; exit 3; }
release_sha=$(git rev-parse "$REMOTE/$RELEASE_BRANCH" 2>/dev/null || true)

if [ -z "$release_sha" ]; then
  echo "ℹ️  $RELEASE_BRANCH 尚不存在；将按 $MAIN_BRANCH 创建（${main_sha:0:7}）"
else
  if ! git merge-base --is-ancestor "$release_sha" "$main_sha"; then
    echo "✗ 发布线被旁路：$RELEASE_BRANCH 上有 $MAIN_BRANCH 没有的提交（${release_sha:0:7}）" >&2
    echo "  先查清这些提交从哪来（应为 0）；确认后手工对齐，**不要**直接覆盖远端。" >&2
    git --no-pager log --oneline "$main_sha..$release_sha" | head -10 >&2
    exit 2
  fi
  if [ "$release_sha" = "$main_sha" ]; then
    echo "✅ $RELEASE_BRANCH 已与 $MAIN_BRANCH 同步：${main_sha:0:7}"
    echo "REL_SHA=$main_sha"
    exit 0
  fi
  echo "→ $RELEASE_BRANCH ${release_sha:0:7} 落后 $MAIN_BRANCH ${main_sha:0:7}（$(git rev-list --count "$release_sha..$main_sha") 个提交）"
fi

if [ "$MODE" = "--check" ]; then
  echo "（--check：未改动远端）"
  exit 0
fi

git push --quiet "$REMOTE" "$main_sha:refs/heads/$RELEASE_BRANCH"
echo "✅ $RELEASE_BRANCH 快进完成 → ${main_sha:0:7}"
echo "REL_SHA=$main_sha"
