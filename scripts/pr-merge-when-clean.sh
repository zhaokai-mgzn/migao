#!/usr/bin/env bash
# case_ids: MC-012
#
# pr-merge-when-clean.sh — 把「PR 已绿、只等 main 不动」这串手工动作收敛成一条命令（issue #7206）。
#
# ## 病（实测读数，不是推测）
#
# main 开了 `strict = true`（合并瞬间必须与 main 同版本），而 main 高频前进（2026-10-17 夜：
# 6 小时 8 次合并）。于是落地变成**竞速**：
#
#     PR 检查全绿 → mergeStateStatus = BEHIND → 合不了
#     ⇒ 手工 update-branch → CI 重跑 ~8-10 min → 期间 main 又动 ⇒ 再 BEHIND
#
# 实测：单条 PR 耗 7 轮（#7188）；一晚 4 条 PR 各撞 1~3 轮（#7164 / #7166 / #7175 / #7188）。
# `land` 帮不上这类场合：它要求**已注册的 worktree**，且 `wait-merge` 是**单发读**（读到 OPEN 即停，
# 不猜合并）—— 设计正确，但把 BEHIND 的重试留给人和 agent 手工做。
#
# ## 判什么（三态退出码，与 `land` / `merge_gate` 同口径）
#
#   0 = 已合并（观察到 state=MERGED）
#   1 = **不能合并**：required 判据非绿 / update-branch 冲突 / merge 被拒 —— 具名打印，不重试、不猜
#   3 = **无法判定**：gh 读不到 / 超时 / 读到自相矛盾的状态 —— 「看不了」绝不谎报成 0
#
# ## 顺序即安全顺序
#
#   ① 只在 **没有任何非绿判据** 时才 update-branch（否则 update 会带着红跑一轮，白等一轮 CI）
#   ② 只在 **CLEAN 且无 pending** 时才调 `gh pr merge`（GitHub 自己还会再拦一道，双保险）
#   ③ **冲突即停**：`update-branch` 报 422/merge conflict ⇒ 立刻 1，**不**退化成「本地硬 rebase」
#      （那会把「需要人看冲突」偷换成「脚本替你解冲突」）
#
# ## 用法
#
#   ./scripts/pr-merge-when-clean.sh 7188                 # 默认最多 6 轮、每轮 40s
#   ./scripts/pr-merge-when-clean.sh 7188 --max-attempts 3 --poll-seconds 15
#   ./scripts/pr-merge-when-clean.sh 7188 --dry-run       # 只读：打印一次判定，零动作
#
# 环境变量（测试用）：PMWC_POLL_SECONDS / PMWC_MAX_ATTEMPTS 与命令行同效，命令行优先。

set -uo pipefail

PR=""
MAX_ATTEMPTS="${PMWC_MAX_ATTEMPTS:-6}"
POLL_SECONDS="${PMWC_POLL_SECONDS:-40}"
WAIT_TIMEOUT="${PMWC_WAIT_TIMEOUT:-1800}"   # 等 pending 的上限（秒）；**不**消耗轮次
SECONDS=0
DRY_RUN=0
RESOLVE_STALE=0
DIAGNOSED_BLOCKED=0
GIT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

usage() {
  sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

while [ $# -gt 0 ]; do
  case "$1" in
    --help|-h) usage ;;
    --dry-run) DRY_RUN=1; shift ;;
    --resolve-stale-threads) RESOLVE_STALE=1; shift ;;
    --max-attempts) MAX_ATTEMPTS="${2:-6}"; shift 2 ;;
    --poll-seconds) POLL_SECONDS="${2:-40}"; shift 2 ;;
    --timeout) WAIT_TIMEOUT="${2:-1800}"; shift 2 ;;
    -*) echo "未知参数：$1（--help 看用法）" >&2; exit 1 ;;
    *) PR="$1"; shift ;;
  esac
done

[ -n "$PR" ] || { echo "必须给 PR 号（--help 看用法）" >&2; exit 1; }
command -v gh >/dev/null 2>&1 || { echo "❌ 取不到 gh（无法判定 ≠ 可合并）⇒ exit 3" >&2; exit 3; }

# ── 一次读：state / mergeStateStatus / required 的非绿项 / pending 计数 ───────────────
# 返回值（单行，`|` 分隔）：STATE|MERGE_STATE|FAILED_NAMES|PENDING_COUNT|HEAD_SHA
read_once() {
  gh pr view "$PR" --json state,mergeStateStatus,headRefOid,statusCheckRollup -q '
    [ .state,
      (.mergeStateStatus // "UNKNOWN"),
      ([ .statusCheckRollup[]?
         | select((.conclusion // "") as $c
                  | ($c != "SUCCESS" and $c != "SKIPPED" and $c != "NEUTRAL" and $c != "CANCELLED" and $c != ""))
         | .name ] | join(",")),
      ([ .statusCheckRollup[]? | select((.status // "") != "COMPLETED") ] | length),
      (.headRefOid // "") ] | join("|")' 2>/dev/null
}

update_branch() {
  local head="$1"
  local out
  out=$(gh api -X PUT "repos/{owner}/{repo}/pulls/${PR}/update-branch" -f expected_head_sha="$head" 2>&1)
  local rc=$?
  if [ $rc -ne 0 ]; then
    echo "  ⛔ update-branch 失败（${rc}）：$(printf '%s' "$out" | tr '\n' ' ')"
    echo "     ⇒ 停（**不**本地硬 rebase：冲突要人看）。可手工：git fetch origin main && git merge origin/main"
    return 1
  fi
  echo "  🔄 已 update-branch（head ${head:0:9}）⇒ 等新一轮 checks"
  return 0
}

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  line=$(read_once)
  # 形状断言：期望恰好 5 个 `|` 分隔字段。形状不对（gh 版本不认 `--jq` / 输出被污染）⇒ **未判定**，
  # 不许拿半截读数往下判（否则会把「读不懂」演成「可以合」）。
  fields=$(awk -F'|' '{print NF}' <<< "$line" 2>/dev/null || echo 0)
  if [ -z "$line" ] || [ "${fields:-0}" -ne 5 ]; then
    echo "❌ 读不到 PR #$PR 的可用状态（gh 不可用 / 未登录 / 输出形状异常：字段数=${fields:-0}）⇒ 未判定（exit 3）"
    echo "   复核：gh pr view $PR --json state,mergeStateStatus,statusCheckRollup"
    exit 3
  fi
  IFS='|' read -r state merge_state failed pending head <<< "$line"
  echo "[attempt $attempt/$MAX_ATTEMPTS] state=$state mergeState=$merge_state pending=$pending 失败=${failed:-无}"

  case "$state" in
    MERGED)
      echo "✅ PR #$PR 已合并（mergedAt 见 gh pr view ${PR}）"
      exit 0 ;;
    CLOSED)
      echo "❌ PR #$PR 已 CLOSED 但未合并 ⇒ 停（fail-closed）"
      exit 1 ;;
  esac

  if [ -n "$failed" ]; then
    echo "❌ 有判据未绿：$failed ⇒ 停（不 update、不 merge、不重试 —— 先修红）"
    exit 1
  fi

  if [ "$merge_state" = "BEHIND" ]; then
    if [ "$DRY_RUN" = "1" ]; then
      echo "（--dry-run）将 update-branch（head ${head:0:9}）"
      exit 0
    fi
    update_branch "$head" || exit 1
    attempt=$((attempt + 1))
    sleep "$POLL_SECONDS"
    continue
  fi

  if [ "$merge_state" = "CLEAN" ] && [ "$pending" = "0" ]; then
    if [ "$DRY_RUN" = "1" ]; then
      echo "（--dry-run）将 gh pr merge $PR --squash"
      exit 0
    fi
    echo "  🔀 gh pr merge $PR --squash"
    merge_out=$(gh pr merge "$PR" --squash 2>&1)
    merge_rc=$?
    after=$(read_once)
    IFS='|' read -r state2 _ _ _ _ <<< "$after"
    if [ "$state2" = "MERGED" ]; then
      echo "✅ PR #$PR 已合并"
      exit 0
    fi
    if [ $merge_rc -eq 0 ]; then
      echo "  ℹ️ merge 调用成功但尚未观察到 MERGED（GitHub 侧异步）⇒ 下一轮再读"
    else
      echo "  ⚠️ gh pr merge 返回 ${merge_rc}：$(printf '%s' "$merge_out" | tr '\n' ' ')"
      # merge 被拒的常见原因是「读到 CLEAN 之后 main 又动了」⇒ 下一轮会看到 BEHIND 并 update
    fi
    attempt=$((attempt + 1))
    sleep "$POLL_SECONDS"
    continue
  fi

  # 「全绿却 BLOCKED」的头号真因（issue #7206 实测 #7188）：**未解决的评审线程**（分支保护开了
  # conversation resolution）。仓库已有判定器 `scripts/resolve_stale_bot_threads.py`（默认 dry-run）——
  # 这里**只做只读诊断 + 打印出口**，不替人做「哪些线程算陈旧」的裁定（那由该工具判）。
  if [ "$merge_state" = "BLOCKED" ] && [ "$pending" = "0" ] && [ -z "$failed" ] \
     && [ "$DIAGNOSED_BLOCKED" = "0" ] && [ -f "$GIT_ROOT/scripts/resolve_stale_bot_threads.py" ]; then
    DIAGNOSED_BLOCKED=1
    echo "  🧭 全绿却 BLOCKED ⇒ 先查「未解决的评审线程」这个头号真因："
    if [ "$RESOLVE_STALE" = "1" ] && [ "$DRY_RUN" = "0" ]; then
      ( cd "$GIT_ROOT" && python3 scripts/resolve_stale_bot_threads.py --apply "$PR" 2>&1 | tail -5 | sed 's/^/     /' )
    else
      ( cd "$GIT_ROOT" && python3 scripts/resolve_stale_bot_threads.py "$PR" 2>&1 | tail -5 | sed 's/^/     /' )
      echo "     确认可解后：$0 $PR --resolve-stale-threads（等价于 python3 scripts/resolve_stale_bot_threads.py --apply ${PR}）"
    fi
  fi

  # BLOCKED / UNKNOWN / 其他：可能仍有 pending，也可能有别的 required（review / 标签）在拦
  if [ "$SECONDS" -ge "$WAIT_TIMEOUT" ]; then
    echo "⏱ 等 pending 已超 ${WAIT_TIMEOUT}s（mergeState=${merge_state}，pending=${pending}）⇒ **未判定**（exit 3）"
    echo "   续跑：$0 $PR --timeout $((WAIT_TIMEOUT * 2))"
    exit 3
  fi
  # 注意：**等**不消耗轮次（轮次只被 update / merge 这类动作消耗）—— 一次 CI 要 8-10 min，
  # 若「等」也计数，默认 4 轮连一轮 CI 都等不完（实测 #7188：19 个 pending）。
  echo "  … mergeState=$merge_state 且无红项 ⇒ 等（pending=${pending}，已等 ${SECONDS}s/${WAIT_TIMEOUT}s）；若长期停在此，跑 gh pr view $PR --json reviewDecision,labels,mergeStateStatus 看拦在哪"
  sleep "$POLL_SECONDS"
done

echo "⏱ ${MAX_ATTEMPTS} 轮内未落地 ⇒ **未判定**（exit 3）。复核：gh pr view $PR --json state,mergeStateStatus"
echo "   续跑：$0 $PR --max-attempts $MAX_ATTEMPTS"
exit 3
