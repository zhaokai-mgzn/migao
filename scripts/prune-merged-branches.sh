#!/usr/bin/env bash
# =============================================================================
# prune-merged-branches.sh — 远程分支卫生：清掉「PR 已合并」的残留分支（**手动、attended**）
#
# 为什么需要它（本仓实测，2026-09-22）：
#   本仓的合并方式含 **squash** ⇒ 合并后原分支的提交**永远不是** `origin/main` 的祖先，
#   `git cherry` 也全是 `+` 行 ⇒ `git branch -r --merged origin/main` 在**本仓失效**
#   （实测只列出 **1** 条 = main 自己），巡检拿不到任何信号。唯一可靠的判据是
#   **GitHub 上这条分支的 PR 是否已 MERGED**（#5070 已在 `scripts/dev-worktree.sh` 的
#   `prune` 子命令里补过这条判据；本脚本**沿用同一判据形态**，不是第二套口径）。
#
# 🔴 形态：**手动触发，不做定时任务**（用户裁定 2026-09-22）。
#   定时无人值守地删远程分支不安全，且每个周期都烧 CI 分钟 ⇒ 本脚本只在本机由人跑。
#   默认 **dry-run（只打印将删什么 + 理由）**，`--apply` 才真删。
#
# 安全条件（**四条全满足才允许删**；任一不满足 ⇒ 跳过，且跳过理由逐条打印）：
#   ① 该分支存在**已合并**的 PR（`gh pr list --head <b> --state merged` 非空）
#      —— **不得**用 `--merged` / `git cherry` / commit 可达性（squash 下全失效）；
#   ② 该分支**没有** open PR（`gh pr list --head <b> --state open` 为空）；
#   ③ 该分支**不在保护名单**（默认 `main` + 长期滚动分支 `chore/flaky-ledger`；
#      `--protect` 可追加，`--protect ''` 可清空）；
#   ④ 该分支**不是当前在飞 PR 的 head**（与 ② 同源但**独立断言**：② 按分支逐个查，
#      ④ 用一次 `gh pr list --state open` 的全量 head 集合交叉核对 —— 任一条成立即跳过）。
#
# 失败即停（fail-closed）：`gh` API 失败 / 取不到 PR 列表 ⇒ **一条都不删**且非零退出。
#   **不得**退化成「删不掉就跳过」的静默（那是把"没跑"伪装成"通过"）。
#
# 幂等：重复跑不报错、不误删（已删掉的分支下次根本不在 `origin` 里）。
# 逐条留痕：每删一条打印 `branch ← merged PR #N`。
# 单次上限：默认 50（`--limit N` 可调），并打印**剩余待清理数**。
#
# 用法（本机手动）：
#   ./scripts/prune-merged-branches.sh                      # dry-run：只打印清单
#   ./scripts/prune-merged-branches.sh --apply              # 真删（≤50 条）
#   ./scripts/prune-merged-branches.sh --apply --limit 200  # 真删（≤200 条）
#   ./scripts/prune-merged-branches.sh --repo /path/to/repo # 指定仓库
#
# 退出码：0 = 成功（含 dry-run）；1 = 判据取不到 / 删除失败（fail-closed）；2 = 用法错误
# =============================================================================
set -uo pipefail

GIT_BIN="${GIT_BIN:-git}"
GH_BIN="${GH_BIN:-gh}"
PROTECT_DEFAULT="main chore/flaky-ledger"
LIMIT=50
APPLY=0
REPO="."
REMOTE="origin"
PROTECT="$PROTECT_DEFAULT"

usage() {
  sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --apply)   APPLY=1; shift ;;
    --dry-run) APPLY=0; shift ;;
    --limit)   LIMIT="${2:-}"; shift 2 ;;
    --limit=*) LIMIT="${1#*=}"; shift ;;
    --repo)    REPO="${2:-}"; shift 2 ;;
    --repo=*)  REPO="${1#*=}"; shift ;;
    --remote)  REMOTE="${2:-}"; shift 2 ;;
    --protect) PROTECT="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "❌ 未知参数：$1" >&2; usage ;;
  esac
done

case "$LIMIT" in ''|*[!0-9]*) echo "❌ --limit 必须是非负整数（得到 '$LIMIT'）" >&2; exit 2 ;; esac

# ── 取数：一次批量拿「open PR 的 head 全量集合」（安全条件 ②④ 共用）──────────
# 取不到 ⇒ fail-closed（一条都不删）。
open_out="$("$GH_BIN" pr list --state open --limit 500 --json number,headRefName 2>/dev/null)"
gh_rc=$?
if [ "$gh_rc" -ne 0 ]; then
  echo "❌ [top] 取 open PR 列表失败（gh 不可用 / 未登录 / 限流 / 网络）—— **一条都不删**（fail-closed）" >&2
  exit 1
fi
open_heads="$(printf '%s' "$open_out" | python3 -c '
import json,sys
try: rows=json.load(sys.stdin)
except Exception: sys.exit(3)
print("\n".join(sorted({r["headRefName"] for r in rows if isinstance(r,dict) and r.get("headRefName")})))
')"
py_rc=$?
if [ "$py_rc" -ne 0 ]; then
  echo "❌ [top] open PR 列表解析失败（返回体不是 JSON）—— **一条都不删**（fail-closed）" >&2
  exit 1
fi

# ── 列远程分支（批量，一次 for-each-ref；**不逐分支 ls-remote**）──────────────
branches="$("$GIT_BIN" -C "$REPO" for-each-ref --format='%(refname:short)' "refs/remotes/$REMOTE" 2>/dev/null \
  | grep -v '/HEAD$' | sed "s|^$REMOTE/||" | grep -v "^$REMOTE$" | LC_ALL=C sort)"
if [ $? -ne 0 ]; then
  echo "❌ 列远程分支失败（$REMOTE 是否已 fetch？）—— **一条都不删**（fail-closed）" >&2
  exit 1
fi

in_protect() {
  local b="$1" p
  for p in $PROTECT; do [ "$b" = "$p" ] && return 0; done
  return 1
}
head_is_open() {
  printf '%s\n' "$open_heads" | grep -Fxq "$1"
}

plan=""
skipped=""
total=0
while IFS= read -r b; do
  [ -n "$b" ] || continue
  total=$((total + 1))
  if in_protect "$b"; then
    skipped="${skipped}  ⛔ ${b}（保护名单）\n"; continue
  fi
  # ④ 在飞 open PR 的 head（独立断言，全量集合交叉核对）
  if head_is_open "$b"; then
    skipped="${skipped}  ⛔ ${b}（有 open PR）\n"; continue
  fi
  # ① 已合并 PR（逐分支查；取不到 ⇒ fail-closed）
  merged_json="$("$GH_BIN" pr list --head "$b" --state merged --limit 1 --json number 2>/dev/null)"
  gh_rc=$?
  if [ "$gh_rc" -ne 0 ]; then
    echo "❌ 查 '${b}' 的已合并 PR 失败（gh API）—— **一条都不删**（fail-closed）" >&2
    exit 1
  fi
  merged_num="$(printf '%s' "$merged_json" | python3 -c '
import json,sys
try: rows=json.load(sys.stdin)
except Exception: sys.exit(3)
print(rows[0]["number"] if rows else "")
')"
  py_rc=$?
  if [ "$py_rc" -ne 0 ]; then
    echo "❌ 解析 '${b}' 的已合并 PR 失败（返回体不是 JSON）—— **一条都不删**（fail-closed）" >&2
    exit 1
  fi
  # ② 没有 open PR（逐分支独立查 —— 与 ④ 双保险）
  open_n="$("$GH_BIN" pr list --head "$b" --state open --limit 1 --json number 2>/dev/null \
    | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))')"
  gh_rc=$?
  if [ "$gh_rc" -ne 0 ]; then
    echo "❌ 查 '${b}' 的 open PR 失败（gh API）—— **一条都不删**（fail-closed）" >&2
    exit 1
  fi
  if [ "$open_n" != "0" ]; then
    skipped="${skipped}  ⛔ ${b}（有 open PR）\n"; continue
  fi
  if [ -z "$merged_num" ]; then
    skipped="${skipped}  ⛔ ${b}（无已合并 PR：从未有 PR / 仅 open / 仅 closed 未合并）\n"; continue
  fi
  plan="${plan}${merged_num}\t${b}\n"
done <<EOF
$branches
EOF

# 单次上限（按 PR 号升序取前 N —— 最老的先清，与上限语义一致）
plan_sorted="$(printf '%b' "$plan" | LC_ALL=C sort -k1,1n)"
planned="$(printf '%s\n' "$plan_sorted" | grep -c . || true)"
to_do="$(printf '%s\n' "$plan_sorted" | grep . | head -n "$LIMIT")"
done_n="$(printf '%s\n' "$to_do" | grep -c . || true)"
remaining=$((planned - done_n))

echo "🧹 远程分支卫生（repo=$REPO remote=$REMOTE 保护名单='$PROTECT'）"
echo "   远程分支总数：$total ｜ 满足删除条件：$planned ｜ 本次上限：$LIMIT ｜ 处理后剩余待清理：$remaining"
echo "   模式：$([ "$APPLY" = "1" ] && echo '🔴 APPLY（真删）' || echo '🟢 dry-run（零删除）')"
echo
if [ -n "$skipped" ]; then
  echo "── 跳过（未删）──"
  printf '%b' "$skipped"
  echo
fi
if [ -z "$to_do" ]; then
  echo "── 无待删分支（幂等：重复跑即此形态）──"
  exit 0
fi

echo "── $([ "$APPLY" = "1" ] && echo '删除' || echo '将删（dry-run，未删任何东西）') ──"
fail=0
while IFS="$(printf '\t')" read -r num br; do
  [ -n "$br" ] || continue
  if [ "$APPLY" != "1" ]; then
    echo "  🟢 ${br} ← merged PR #${num}"
    continue
  fi
  if out="$("$GIT_BIN" -C "$REPO" push "$REMOTE" --delete "$br" 2>&1)"; then
    echo "  ✅ ${br} ← merged PR #${num}"
  else
    echo "  ❌ ${br} 删除失败（merged PR #${num}）：$(printf '%s' "$out" | tail -1)" >&2
    fail=1
  fi
done <<EOF
$to_do
EOF

if [ "$fail" != "0" ]; then
  echo "❌ 有分支删除失败 —— 非零退出（不静默吞掉）" >&2
  exit 1
fi
[ "$APPLY" = "1" ] || echo "（dry-run：以上分支**均未删除**；确认后加 --apply 执行）"
exit 0
