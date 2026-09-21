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
#   3. 前置拒绝（仅 merge 模式）：本分支与 origin/main **都**改过受管用例面
#      （`.github/cases/**` / `.github/case-trust-baseline.json`）⇒ **拒绝 merge**，
#      打印理由与 `--rebase` 命令（见下「为什么」）
#   4. merge/rebase origin/main（冲突时中止并提示）
#   5. 合并后内容级校验：origin/main 在受管用例面上新增的**每一行**（用例条目 `- id:`、
#      销账字段块 `must_succeed` / `namespaces` / `precondition` …）必须仍在合并结果里；
#      缺任何一行 ⇒ 非零退出 + 指名文件与缺失内容
#   6. 重渲染生成物（.github/render_cases.py → eval_cases.py + casebook.md）
#   7. 有 diff → 自动提交（仅含两个生成物文件，message 标准化）：
#      "chore(cases): 合并 main 后重渲染生成物（N 条）"
#   8. 提醒 push
#
# 为什么 merge 模式要**拒绝**而不是「让 merge 更聪明」（issue #4984）：
#   分支分叉期间 main 侧把 case-trust 销账（`must_succeed` / `namespaces` /
#   `precondition` 等块）新增进 `cases/*.yml`；本分支**没有**这些块 ⇒ 三方合并把
#   「本分支缺少该块」当成**有意删除**，**无冲突**接受 ⇒ **静默回退** main 已缴的
#   case-trust 债（实测 5 个文件：−27/−25/−20/−3/−2 行），随后门禁判红且归因指向
#   错误方向（看起来像「你这个 PR 新增了违规」）。`--rebase` 把 main 当基线、把本分支
#   提交重放到其上 ⇒ main 的新增块不可能被「缺少」掉。
#   两层防护都是把**静默**换成**响亮**，不是「让 merge 更聪明」：
#     · 第 3 步是**粗粒度**（路径级）——两侧都动过受管用例面就直接停手；
#     · 第 5 步是**内容级兜底**（逐行）——兜住第 3 步被绕过的形态（`-X ours` /
#       自定义 merge driver / 人工 merge / 未来收窄前置判据）：那时 merge 会**无冲突**
#       地丢内容，只有内容级比对能判红。
#   已知边界（如实登记）：第 5 步的判据是**单向**的（只断言「main 侧新增内容仍在」），
#   因此「本分支侧删掉了 merge-base 里已有的内容」它不覆盖 —— 那一形态由第 3 步拦。
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

# 受管用例面：这些路径上的内容被静默回退会改变 case-trust 账（issue #4984）
CASE_SURFACE=(".github/cases" ".github/case-trust-baseline.json")

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

# ── 合并后内容级校验（issue #4984 第二层）─────────────────────────────────────
# 断言「origin/main 在受管用例面上新增的每一行都还在合并结果里」。
# 判据是**内容级**（逐行），不是「有没有冲突」—— 缺陷形态恰恰是**无冲突**却丢内容。
# 行级是 issue 点名两类（用例条目 `- id:` / 销账字段块 `must_succeed`·`namespaces`…）
# 的**超集**，故不再单列两条判据（判据只留一条，避免两份登记表漂移）。
case_surface_content_check() {
  if ! python3 - "$1" <<'PY'
import subprocess
import sys

BASE = sys.argv[1]
SURFACE = (".github/cases", ".github/case-trust-baseline.json")
LEDGER_FIELDS = ("must_succeed", "namespaces", "precondition", "skip_reason",
                 "expectations", "data_checks", "traces")


def added_lines(ref):
    """`git diff BASE..ref` 在受管用例面上的**新增行**（按文件分组，逐行 strip）。"""
    diff = subprocess.run(
        ["git", "diff", "--unified=0", "--no-color", BASE, ref, "--", *SURFACE],
        capture_output=True, text=True, check=True).stdout
    out, path = {}, None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            name = line[4:].strip()
            path = name[2:] if name.startswith("b/") else name
            out.setdefault(path, [])
        elif line.startswith("+") and path:
            text = line[1:].strip()
            if text:
                out[path].append(text)
    return out


def kind(text):
    if text.startswith("- id:"):
        return "用例条目"
    for field in LEDGER_FIELDS:
        if text.startswith(field + ":"):
            return "销账字段块"
    return "内容行"


added = added_lines("origin/main")
missing, checked = [], 0
for path, lines in sorted(added.items()):
    checked += len(lines)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            present = {ln.strip() for ln in fh.read().splitlines()}
    except OSError:
        missing.append((path, "<整个文件在合并结果里不存在>", "文件"))
        continue
    missing.extend((path, text, kind(text)) for text in lines if text not in present)

if missing:
    print("❌ 合并后内容级校验失败：合并结果里丢了 origin/main 在受管用例面上的内容"
          f"（{len(missing)} 处 / 共校验 {checked} 行）—— 这是**静默回退**"
          "（无冲突，但内容没了）：", file=sys.stderr)
    for path, text, what in missing:
        print(f"   · {path}（{what}）：缺  {text}", file=sys.stderr)
    print("   处置：git merge --abort 后改用 ./scripts/sync-main.sh --rebase；"
          "已提交则逐文件核 git diff origin/main -- .github/cases/", file=sys.stderr)
    sys.exit(1)
print(f"✅ 合并后内容级校验通过：origin/main 在受管用例面上新增的 {checked} 行都在")
PY
  then
    exit 1
  fi
}

echo "── 1/6 前置检查 ──"
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

echo "── 2/6 fetch origin/main ──"
git fetch origin main

echo "── 3/6 前置拒绝检查（仅 merge 模式）──"
BASE="$(git merge-base HEAD origin/main)" || {
  echo "❌ 无法计算 merge-base(HEAD, origin/main)：两侧可能没有共同祖先（浅克隆？）" >&2
  echo "   处置：git fetch --unshallow origin main 后重跑本脚本" >&2
  exit 1
}
if [ "$MODE" = "merge" ]; then
  OUR_CASE_CHANGES="$(git diff --name-only "$BASE" HEAD -- "${CASE_SURFACE[@]}")"
  MAIN_CASE_CHANGES="$(git diff --name-only "$BASE" origin/main -- "${CASE_SURFACE[@]}")"
  if [ -n "$OUR_CASE_CHANGES" ] && [ -n "$MAIN_CASE_CHANGES" ]; then
    echo "❌ 拒绝 merge：本分支与 origin/main **都**改过受管用例面（issue #4984）。" >&2
    echo "   受管用例面 = .github/cases/** + .github/case-trust-baseline.json" >&2
    echo "   本分支侧（${BASE:0:8}..HEAD）：" >&2
    echo "$OUR_CASE_CHANGES" | sed 's/^/     /' >&2
    echo "   main 侧（${BASE:0:8}..origin/main）：" >&2
    echo "$MAIN_CASE_CHANGES" | sed 's/^/     /' >&2
    echo "   理由：merge 会把「本分支缺少 main 新增的用例块（must_succeed / namespaces /" >&2
    echo "         precondition 等销账字段）」当成**有意删除**并**无冲突**接受 ⇒ 静默回退" >&2
    echo "         main 已缴的 case-trust 债，随后门禁判红且归因指向错误方向。" >&2
    echo "   处置：改用 rebase（main 成为基线，本分支提交在其上重放，main 的新增块不可能被缺少掉）：" >&2
    echo "       ./scripts/sync-main.sh --rebase" >&2
    exit 1
  fi
  echo "ℹ️ 未命中前置拒绝（受管用例面未被两侧同时改动）"
else
  echo "ℹ️ rebase 模式：跳过前置拒绝（rebase 不会把 main 的新增块读成删除）"
fi

echo "── 4/6 ${MODE} origin/main ──"
if [ "$MODE" = "rebase" ]; then
  git rebase origin/main || { echo "❌ rebase 冲突，请解决后重跑本脚本" >&2; exit 1; }
else
  git merge origin/main --no-edit || { echo "❌ merge 冲突，请解决后重跑本脚本" >&2; exit 1; }
fi

echo "── 5/6 合并后内容级校验（受管用例面）──"
case_surface_content_check "$BASE"

echo "── 6/6 重渲染生成物（cases/ 单一源 → 生成物）──"
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
  git add "$EVAL_OUT" "$CASEBOOK_OUT"
  CHANGES="$(git diff --cached --stat | tail -1 | grep -oE '[0-9]+ files? changed' || echo "生成物更新")"
  git commit -m "chore(cases): 合并 main 后重渲染生成物（${CHANGES}）"
  echo "✅ 已提交生成物重渲染"
fi

echo "── 完成 ──"
echo "分支 ${BRANCH} 已同步 origin/main。CI 即将重跑，请盯首轮结果（见 migao-dev-flow §11）："
echo "  gh pr checks <PR> --watch"
echo "push 分支后 CI 红了立即修复，禁止丢下红 CI 去开新任务。"
