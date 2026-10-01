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
#   4. merge/rebase origin/main。冲突时**只有**「未合并文件集合恰好 == {CHANGELOG.md}」才尝试
#      自动解（保留两侧条目 + 空行分隔 + 去标记，见下「CHANGELOG.md 冲突自动解」）；
#      任何别的形态、或解完没过三条内容级验证 ⇒ **还原成冲突态** + 打印提示 + 退出 1
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
# CHANGELOG.md 冲突自动解（铁律 10：一晚做过 ≥3 次的动作串 ⇒ 必须收敛成**一条命令**）：
#   一晚 4 次、每次逐字相同的动作串 = `sync-main.sh --rebase` 停下 → 冲突文件恰好只有
#   CHANGELOG.md → 保留两侧条目、去掉 `<<<<<<<` / `=======` / `>>>>>>>` → 复核「一条不丢、
#   无重复」→ `git add` → `rebase --continue` → 重跑 sync-main。现折叠进本脚本的冲突路径
#   （**不是**新加一条命令 —— 那只是把重复挪个地方）。
#   · 射程**不许扩大**：只有「未合并文件集合 == {CHANGELOG.md}」才尝试；其余形态交人工。
#   · 三条内容级验证（**写盘之前**跑完；不过 ⇒ python 非零退出，工作树一个字节都没动）：
#     A 无残留冲突标记（`<<<<<<<` / `=======` / `>>>>>>>`，含 diff3 的 `|||||||`）
#     B `### ` 标题集合 == 索引 `:2:` ∪ `:3:`（一条不丢）+ 不得比两侧更多地重复某一条
#     C `:2:` / `:3:` 的每一行都在解后文本里**按原序**出现（除冲突块插入点外逐字保留）
#   · 失败即还原 + 非零退出（冲突态备份逐字节回写），交人工按老办法处理 —— **绝不静默丢内容**。
#   · 已知边界（如实登记）：C 是**保守判据** —— 某侧在冲突区**之外**合法删过一行时它会判红
#     （假红 ⇒ 退回人工路径，不产错内容）；`--continue` 必须带 `GIT_EDITOR=true`，否则非交互
#     环境下 git 直接报「Terminal is dumb, but EDITOR unset」而失败（本机实测）。
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

# CHANGELOG 冲突自动解的射程**硬编码**成这一个文件：多一个文件都不接管（见文件头）
CHANGELOG_FILE="CHANGELOG.md"

MODE="merge"
AUTO_COMMIT=1
for arg in "$@"; do
  case "$arg" in
    --rebase)   MODE="rebase" ;;
    --no-commit) AUTO_COMMIT=0 ;;
    -h|--help)  sed -n 's/^# \{0,1\}//p' "$0" | sed -n '/^sync-main.sh/,/^===/p' | head -25; exit 0 ;;
    *) echo "❌ 未知参数: ${arg}（支持 --rebase / --no-commit）" >&2; exit 1 ;;
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

# ── CHANGELOG.md 冲突自动解（射程硬编码 = 只认这一个文件）────────────────────
# 只在「未合并文件集合恰好 == {CHANGELOG.md}」时尝试；其余形态 `return 1`
# （调用方按原样打印提示并 exit 1）。解法与三条判据在**同一个 python 进程**里
# ⇒ 不存在「判据读的是另一份东西」的漂移面。
autoresolve_changelog_conflict() {
  local unmerged="" backup=""
  unmerged="$(git diff --name-only --diff-filter=U)"
  if [ "${unmerged}" != "${CHANGELOG_FILE}" ]; then
    echo "ℹ️ 未合并文件不是「恰好 ${CHANGELOG_FILE}」（现取：$(echo "${unmerged}" | tr '\n' ' ')）⇒ 不自动解（交人工）" >&2
    return 1
  fi
  # 冲突态备份（逐字节）：验证不过 / 写入或 add 失败时用它还原
  backup="$(mktemp "${TMPDIR:-/tmp}/sync-main-changelog-conflict.XXXXXX")" || return 1
  if ! cp "${CHANGELOG_FILE}" "${backup}"; then
    rm -f "${backup}"
    return 1
  fi
  if ! python3 - "${CHANGELOG_FILE}" <<'PY'
import re
import subprocess
import sys
from collections import Counter

FILE = sys.argv[1]
MARKER = re.compile(r"^(<{7}|={7}|>{7}|\|{7})")


def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)


def side(n):
    """索引第 n 侧（rebase 下 `:2:`=origin/main、`:3:`=本分支提交；merge 下方向相反 ——
    本判据只取并集与「逐侧保留」，故与方向无关）。取不到 ⇒ 无法验证 ⇒ 停手。"""
    proc = subprocess.run(["git", "show", ":%d:%s" % (n, FILE)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        die("⛔ 取不到索引第 %d 侧（git show :%d:%s）：%s" % (n, n, FILE, proc.stderr.strip()))
    return proc.stdout.split("\n")


def heads(lines):
    return [ln.rstrip("\r") for ln in lines if ln.startswith("### ")]


def first_unmatched(needle, hay):
    """`needle` 是否**按原序**逐行出现在 `hay` 里；→ 第一个对不上的元素（None = 全部命中）。"""
    j = 0
    for item in needle:
        while j < len(hay) and hay[j] != item:
            j += 1
        if j == len(hay):
            return item
        j += 1
    return None


with open(FILE, encoding="utf-8", newline="") as fh:
    work = fh.read().split("\n")
if not any(ln.rstrip("\r").startswith("<<<<<<<") for ln in work):
    die("⛔ %s 里没有冲突块（`<<<<<<<` 零命中）⇒ 不自动解" % FILE)
ours, theirs = side(2), side(3)

# ── 解法：每个冲突块保留**两侧**（标记里的原序、块之间空行分隔），其余行原样 ──
out, idx, hunks = [], 0, 0
while idx < len(work):
    if not work[idx].rstrip("\r").startswith("<<<<<<<"):
        out.append(work[idx])
        idx += 1
        continue
    hunks += 1
    idx += 1
    sides = {"ours": [], "base": [], "theirs": []}
    cur, closed = "ours", False
    while idx < len(work):
        tag = work[idx].rstrip("\r")
        if tag.startswith("|||||||") and cur == "ours":
            cur = "base"
        elif tag == "=======" and cur != "theirs":
            cur = "theirs"
        elif tag.startswith(">>>>>>>"):
            closed = True
            idx += 1
            break
        else:
            sides[cur].append(work[idx])
        idx += 1
    if not closed:
        die("⛔ 第 %d 个冲突块没有结束标记（`>>>>>>>` 缺失）⇒ 结构不合预期，不自动解" % hunks)
    kept = [s for s in (sides["ours"], sides["theirs"]) if s]
    if len(kept) == 2 and kept[0][-1].strip():
        kept.insert(1, [""])
    for block in kept:
        out.extend(block)

# ── 三条内容级验证（全部在**写盘之前**）──────────────────────────────────────
problems = []
for ln in out:                                                      # A 无残留标记
    if MARKER.match(ln.rstrip("\r")):
        problems.append("残留冲突标记：%r" % ln)
cnt, c_ours, c_theirs = Counter(heads(out)), Counter(heads(ours)), Counter(heads(theirs))
want = set(c_ours) | set(c_theirs)
lost = sorted(want - set(cnt))                                      # B 并集一条不丢
extra = sorted(set(cnt) - want)
amplified = sorted(h for h in cnt if cnt[h] > max(c_ours.get(h, 0), c_theirs.get(h, 0)))
if lost:
    problems.append("丢了 %d 条 `### ` 条目：%s" % (len(lost), " ｜ ".join(lost)))
if extra:
    problems.append("多出 %d 条两侧都没有的 `### ` 条目：%s" % (len(extra), " ｜ ".join(extra)))
if amplified:
    problems.append("这些 `### ` 条目比两侧更多地重复（并集解不得放大重复）：%s" % " ｜ ".join(amplified))
for label, lines in ((":2:", ours), (":3:", theirs)):               # C 两侧原版按原序保留
    bad = first_unmatched(lines, out)
    if bad is not None:
        problems.append("索引第 %s 侧原版的这一行在解后文本里对不上（丢了或次序被打乱）：%r"
                        % (label, bad))
if problems:
    sys.stderr.write("⛔ %s 冲突自动解**未通过**内容级验证（%d 条）—— 不写盘、保持冲突态：\n"
                     % (FILE, len(problems)))
    for item in problems:
        sys.stderr.write("   · %s\n" % item)
    sys.exit(1)

merged = "\n".join(out)
with open(FILE, "w", encoding="utf-8", newline="") as fh:
    fh.write(merged)
with open(FILE, encoding="utf-8", newline="") as fh:                # 写后回读自证（防半截写）
    if fh.read() != merged:
        die("⛔ 写入后回读与验证过的内容不一致 ⇒ 不认这次解（请人工处理）")
print("ℹ️ 自动解 %d 个冲突块：`### ` 索引 :2:=%d / :3:=%d / 并集=%d / 结果=%d"
      % (hunks, len(c_ours), len(c_theirs), len(want), len(cnt)))
PY
  then
    # 还原（此刻索引未动 ⇒ 逐字节就是冲突态）。还原**也要自证**：失败就不许删备份、
    # 也不许报告「已还原」（否则会把「备份已删 + 状态未知」这种最坏形态留在原地）。
    if cp "${backup}" "${CHANGELOG_FILE}"; then
      rm -f "${backup}"
      echo "⛔ 自动解未过内容级验证 ⇒ 已还原成冲突态（工作树与索引同停下时逐字节一致）" >&2
    else
      echo "⛔ 自动解未过内容级验证，且还原失败 ⇒ 冲突态备份留在 ${backup}，请手工恢复" >&2
    fi
    return 1
  fi
  if ! git add "${CHANGELOG_FILE}"; then
    if cp "${backup}" "${CHANGELOG_FILE}"; then
      rm -f "${backup}"
      echo "❌ git add ${CHANGELOG_FILE} 失败 ⇒ 已还原成冲突态" >&2
    else
      echo "❌ git add ${CHANGELOG_FILE} 失败，且还原失败 ⇒ 冲突态备份留在 ${backup}" >&2
    fi
    return 1
  fi
  rm -f "${backup}"
  if ! GIT_EDITOR=true git "${MODE}" --continue; then
    echo "❌ ${CHANGELOG_FILE} 已自动解并 stage，但 git ${MODE} --continue 失败 —— 请手工重跑该命令" >&2
    return 1
  fi
  echo "✅ ${CHANGELOG_FILE} 冲突已自动解（两侧条目都在 / 无残留标记 / 已过三条内容级验证）并继续 ${MODE}"
  return 0
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
CONFLICT=0
if [ "$MODE" = "rebase" ]; then
  git rebase origin/main || CONFLICT=1
else
  git merge origin/main --no-edit || CONFLICT=1
fi
if [ "${CONFLICT}" -eq 1 ]; then
  # 射程恰好 {CHANGELOG.md} 且解完过了三条内容级验证 ⇒ 自动解并继续；
  # 其余一律走下面这条与自动解引入前**逐字一致**的提示
  autoresolve_changelog_conflict || {
    echo "❌ ${MODE} 冲突，请解决后重跑本脚本" >&2
    exit 1
  }
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
