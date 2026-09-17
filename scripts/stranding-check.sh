#!/usr/bin/env bash
# stranding-check.sh — §17.3「交付物搁浅」的**内容级**检测（issue #4065）
#
# 病根：native auto-merge **秒合** ⇒ PR 的 headRefOid 之后再推的 commit **不进 main**
#       （squash 只带走**合并那一刻**的树）⇒ 「CI 绿 / auto-merge 绿」而「交付物不在 main」。
#       实证两次：#3842（3 个 commit 搁浅）→ 跟随 #3847；更早 #3819 → #3826。
#
# 用法:
#   ./scripts/stranding-check.sh --pr <n> [--tip <ref>]         # 主用法：已合并 PR
#   ./scripts/stranding-check.sh --branch <ref> [--base <ref>]  # 无 PR 元数据：判该 ref 自身改动在不在 base 上
#   选项: --base <ref>（默认 origin/main）/ --repo <dir>（默认当前 git 顶层）/ --quiet
#   环境变量: SC_REPO=<dir> / SC_GH_BIN=<gh 路径>（测试用替身）
#
# 退出码（与仓内既有三态口径一致，如 eval_slot_status.sh / llm_sink_check.py）:
#   0 = 无搁浅 ； 1 = 检出搁浅（列出 文件 + PR + sha）； 3 = **无法判定**（缺 gh / 缺网络 / PR 元数据不全）
#   —— 「看不了」**不得**当「没问题」：一切读不到关键输入的情形一律 3，绝不返回 0。
#
# ── 判据（内容级；**commit 可达性不是判据** —— squash 重写历史，`git merge-base --is-ancestor`
#    与 `git branch -r --contains` 会把**已交付**判成搁浅 ⇒ 假警报）────────────────────────────
#   ① 「所推 sha」怎么取：优先**远端分支 ref**（一次 `git fetch origin refs/heads/<headRefName>` 同时取
#      tip sha（FETCH_HEAD）与对象）。
#      ⚠️ 实测（#4065，对 #3842）：GitHub 的 `headRefOid` / PR commits 在合并后**冻结** ——
#      #3842 的 headRefOid 至今仍是 `0b551697`（合并那一刻的 tip），而后推的 3 个 commit 只在
#      **分支 ref** 上看得见（`fix/case-trust-gate` = `9ef7ecc9`，提交时间 00:15:04Z > mergedAt 00:12:17Z）。
#      只读 `gh pr view --json headRefOid` 会**永远看不到**搁浅 ⇒ 必须读分支 ref。
#      分支已被删（auto-delete 常态）⇒ 退到 `refs/pull/<n>/head`（= headRefOid）并**如实标注盲区**。
#   ② 比对锚点 = **该 PR 在 main 上的合并点**（`mergeCommit.oid`，即 squash commit）。逐文件比内容：
#        `git show <所推 sha>:<path>` vs `git show <合并点>:<path>`（用 blob sha = 文件内容 sha1，
#        等价于 `shasum` 且省一次管道；DIFF 时另打 `shasum` 原文当证据）。
#      再与**当前** `origin/main` 比一份作证据：`MAIN=SAME` / `DIFF-LATER`（main 后来被别的 PR 改过）
#      / `MISSING`（main 上已无此路径）。
#      **为什么锚点是「合并点」而不是「当前 main」**：「当前 main 逐字节等于所推 sha」不是判据 ——
#      后续 PR 改过同一文件就会不等（`DIFF-LATER`，**已交付**），而跟随 PR 补齐后又会变等
#      （#3842 若拿「当前 main」判，今天会假绿）。合并点是 **main 上的不可变事实**。
#   ③ 区分「分支陈旧」与「真搁浅」（两级判据；`h`=所推 sha 的 blob，`m`=合并点，`f`=fork）：
#      · `h == m` ⇒ `LANDED`；
#      · `h != m` 且 `h == f`（fork = merge-base(合并点, 所推 sha)）⇒ 这个文件**分支根本没动**、
#        是 base 自己前进了 ⇒ `STALE-BRANCH`，**无害，不报红**；
#      · `h != m` 且分支动过 ⇒ **再比一次内容**：把「分支相对 fork 的新增行」逐行在**合并点内容**里找，
#        全在 ⇒ `LANDED-MERGED`（改动交付了；该文件同时被 base 的**并发改动**并入 /
#        或由别的 PR 以不同形态落地）⇒ **不报红**（实证 #4127 的 `docs/sql/schema.sql`：
#        合并点 = main 版 + 本 PR 的 hunk，与分支 tip 逐字节不同，只比 blob 必假红）；
#      · 仍不全在 ⇒ `STRANDED`（若该内容现已由跟随 PR 补齐 ⇒ 标注 `STRANDED-BACKFILLED`，
#        **仍计入红**：机制**发生过**，这就是 §17.3 要显形的形态）。
#   ④ 「合并后无新 push」⇒ **直接判无搁浅（不许报红）**：判定 = 分支 ref tip != headRefOid，
#      或 tip 的提交时间 > mergedAt。此路径下 main 上的路径缺失只作 ⚠️ 提示（可能是后续 PR 删/改名），
#      不判搁浅。残留盲区：分支已删且后推 commit 也随之不可见 ⇒ 本项看不到（如实打印，见 ①）。
#
# ── 边界（不得越级读结论）────────────────────────────────────────────────────────────
#   · 只答「**所推 sha 的文件内容有没有随该 PR 进 main**」，**不答**「能力可达 / 语义正确」。
#   · 交付物清单 = PR body 里反引号路径（过滤到真实存在于任一树者）∪ `gh pr view --json files`
#     ∪ 「合并点→所推 sha」改动的文件；**不做**散文计数核对（如 body 写「规则 9 条」而 main 只有 6 条
#     —— 那需要解析散文，属人核，见 issue #4065 的「未做」）。
#   · 退出码 1 是「**该 PR 的所推内容未随它落地**」，不等于「现在 main 上一定没有」（可能已被跟随 PR 补齐）。
#
# ── 落码状态登记（照实，别把「脚本存在」读成「有门禁」）──────────────────────────────
#   · **未接 CI required check**：现为人工 / `batch-integrate-check.sh --pr` 集成环节调用。
#   · 自测红证：`tests/unit_ci_workflows/test_stranding_check.py`。
set -uo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="${SC_REPO:-$(git rev-parse --show-toplevel 2>/dev/null || echo "$SELF_DIR/..")}"
GH_BIN="${SC_GH_BIN:-gh}"
BASE="${SC_BASE:-origin/main}"
UI_LANG=en_US.UTF-8

PR=""; BRANCH=""; TIP=""; QUIET=""
while [ $# -gt 0 ]; do
  case "$1" in
    --pr)     PR="${2:?--pr 需要 PR 号}"; shift 2 ;;
    --branch) BRANCH="${2:?--branch 需要一个 ref}"; shift 2 ;;
    --tip)    TIP="${2:?--tip 需要一个 ref/sha}"; shift 2 ;;
    --base)   BASE="${2:?--base 需要一个 ref}"; shift 2 ;;
    --repo)   REPO="${2:?--repo 需要目录}"; shift 2 ;;
    --quiet)  QUIET=1; shift ;;
    --help|-h) sed -n 's/^# \{0,1\}//p' "$0" | sed -n '1,20p'; exit 0 ;;
    *) echo "❌ 未知参数: $1（--help 看用法）" >&2; exit 3 ;;
  esac
done
[ -n "$PR" ] || [ -n "$BRANCH" ] || { echo "❌ 需要 --pr <n> 或 --branch <ref>（--help 看用法）" >&2; exit 3; }

cd "$REPO" 2>/dev/null || { echo "❌ 无法进入仓库目录: $REPO" >&2; exit 3; }
git rev-parse --git-dir >/dev/null 2>&1 || { echo "❌ 不是 git 仓库: $REPO" >&2; exit 3; }

TMPFILES=""
cleanup() { [ -n "$TMPFILES" ] && rm -f $TMPFILES; }
trap cleanup EXIT

# ── 元数据 ────────────────────────────────────────────────────────────────────────
git fetch origin --quiet 2>/dev/null || true     # 失败不致命：下面逐项验「读得到吗」，读不到就 3
git rev-parse --verify -q "$BASE^{commit}" >/dev/null || {
  echo "❌ 无法判定：读不到 base=${BASE}（缺网络 / 未 fetch / ref 不存在）" >&2; exit 3; }
BASE_SHA="$(git rev-parse "$BASE")"

META=""; MERGE_SHA=""; HEAD_REF=""; HEAD_OID=""; MERGED_AT=""; PR_STATE=""; BODY_FILE=""
if [ -n "$PR" ]; then
  command -v "$GH_BIN" >/dev/null 2>&1 || {
    echo "❌ 无法判定：找不到 gh（${GH_BIN}）—— PR 元数据读不到 ⇒ 3（不许当「没问题」）" >&2; exit 3; }
  JSON="$("$GH_BIN" pr view "$PR" --json number,state,mergedAt,mergeCommit,headRefOid,headRefName,files,body 2>&1)" || {
    echo "❌ 无法判定：gh pr view $PR 失败（缺网络 / 未登录 / PR 不存在 / 无权限）⇒ 3" >&2
    printf '%s\n' "$JSON" | head -3 >&2; exit 3; }
  META="$(mktemp)"; BODY_FILE="$META.body"; TMPFILES="$META $BODY_FILE"
  printf '%s' "$JSON" > "$META"
  read -r PR_STATE MERGED_AT MERGE_SHA HEAD_REF HEAD_OID <<EOF
$(python3 - "$META" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
def g(*ks):
    cur=d
    for k in ks:
        cur=(cur or {}).get(k) if isinstance(cur,dict) else None
    return cur or ""
print(g("state"), g("mergedAt"), g("mergeCommit","oid"), g("headRefName"), g("headRefOid"))
PY
)
EOF
  for v in "$PR_STATE" "$MERGED_AT" "$MERGE_SHA" "$HEAD_REF" "$HEAD_OID"; do
    [ -n "$v" ] || { echo "❌ 无法判定：PR #$PR 元数据不全（state/mergedAt/mergeCommit/headRefOid/headRefName 有空项）⇒ 3" >&2; exit 3; }
  done
  if [ "$PR_STATE" != "MERGED" ]; then
    echo "❌ 无法判定：PR #$PR 状态 = ${PR_STATE}（未合并 ⇒ 无「搁浅」可言；查未合并分支请用 --branch）⇒ 3" >&2; exit 3
  fi
  python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("body") or "")' "$META" > "$BODY_FILE"
fi

# ── 「所推 sha」= H ────────────────────────────────────────────────────────────────
H=""; H_SRC=""
if [ -n "$TIP" ]; then
  H="$(git rev-parse --verify -q "$TIP^{commit}" || true)"
  [ -n "$H" ] && H_SRC="--tip $TIP"
fi
if [ -z "$H" ] && [ -n "$PR" ]; then
  # ① 远端分支 ref：合并后 push **只在这里**看得见（headRefOid 已冻结，实测 #3842）
  #    一次 fetch 同时拿到 tip sha（FETCH_HEAD）与对象 —— 省掉 ls-remote 那一跳。
  FOUT="$(git fetch origin --quiet "refs/heads/$HEAD_REF" 2>&1)"; FRC=$?
  if [ $FRC -eq 0 ]; then
    RSHA="$(git rev-parse --verify -q "FETCH_HEAD^{commit}" || true)"
    [ -n "$RSHA" ] && { H="$RSHA"; H_SRC="远端分支 refs/heads/$HEAD_REF"; }
  elif printf '%s' "$FOUT" | grep -qiE "couldn't find remote ref|remote ref does not exist"; then
    :   # 分支已删（auto-delete 常态）⇒ 走 ② 退路
  else
    echo "❌ 无法判定：读远端分支 refs/heads/$HEAD_REF 失败（缺网络？）⇒ 看不到「合并后是否有新 push」⇒ 3" >&2
    printf '%s\n' "$FOUT" | head -2 >&2; exit 3
  fi
fi
if [ -z "$H" ] && [ -n "$PR" ]; then
  # ② 分支已删 ⇒ refs/pull/<n>/head（= headRefOid）；盲区如实登记
  git cat-file -e "$HEAD_OID^{commit}" 2>/dev/null || git fetch origin --quiet "refs/pull/$PR/head" 2>/dev/null || true
  for cand in "refs/pull/$PR/head" "$HEAD_OID"; do
    if git rev-parse --verify -q "$cand^{commit}" >/dev/null 2>&1; then
      H="$(git rev-parse "$cand^{commit}")"; H_SRC="PR ref/headRefOid（分支已删 —— 合并后 push 在本机不可见）"; break
    fi
  done
fi
if [ -z "$H" ] && [ -n "$BRANCH" ]; then
  H="$(git rev-parse --verify -q "$BRANCH^{commit}" || true)"; H_SRC="--branch $BRANCH"
fi
[ -n "$H" ] || { echo "❌ 无法判定：读不到「所推 sha」（$BRANCH${PR:+ PR #$PR 的 head 也不可达}）⇒ 3" >&2; exit 3; }

if [ -n "$PR" ]; then
  git cat-file -e "$MERGE_SHA^{commit}" 2>/dev/null || git fetch origin --quiet "$MERGE_SHA" 2>/dev/null || true
  git cat-file -e "$MERGE_SHA^{commit}" 2>/dev/null || {
    echo "❌ 无法判定：读不到 PR #$PR 的合并点 $MERGE_SHA ⇒ 3" >&2; exit 3; }
  MERGE_SHA="$(git rev-parse "$MERGE_SHA^{commit}")"
else
  MERGE_SHA=""; MERGED_AT=""; HEAD_OID=""
fi

# ── 逐文件判定（内容级；python3 单实现，git 调用都在这里）────────────────────────────
python3 - "$REPO" "$BASE_SHA" "$H" "$H_SRC" "$MERGE_SHA" "$HEAD_OID" "$MERGED_AT" "${META:-/dev/null}" \
         "$QUIET" "$PR" "$BASE" <<'PY'
import hashlib, json, os, re, subprocess, sys

repo, base, h, h_src, merge, head_oid, merged_at, meta_path, quiet, pr, base_name = sys.argv[1:12]

def git(*args, binary=False):
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True)
    if p.returncode != 0:
        return None
    return p.stdout if binary else p.stdout.decode("utf-8", "replace")

TREES = {}
def _fill(ref):
    """一次 `ls-tree -r -z` 拿全树 ⇒ 逐文件判定不产生 N×4 次子进程（85 项时这是 10s+ 的差别）。"""
    out = git("ls-tree", "-r", "-z", ref)
    if out is None:
        return None
    d = {}
    for entry in out.split("\0"):
        if not entry or "\t" not in entry:
            continue
        meta, path = entry.split("\t", 1)
        parts = meta.split()
        if len(parts) >= 3:
            d[path] = parts[2]
    TREES[ref] = d
    return d

def blob(ref, path):
    """文件内容 sha（= git blob sha1；等价于 `git show <ref>:<path> | shasum`，省一次管道）。"""
    if not ref:
        return None
    return (_fill(ref) if ref not in TREES else TREES[ref]).get(path)

def content(ref, path):
    return git("show", f"{ref}:{path}", binary=True)

def sha1(b):
    return hashlib.sha1(b).hexdigest() if b is not None else "-"

def lines(ref, path):
    b = content(ref, path)
    return b.decode("utf-8", "replace").splitlines() if b is not None else None

def added_lines(ref_from, ref_to, path):
    """分支自己相对 fork 新增的行（去掉 +++ 头与过短噪声行）。"""
    d = git("diff", ref_from, ref_to, "--", path) if ref_from else None
    if d is None:
        return None
    out = []
    for line in d.splitlines():
        if line.startswith("+++") or not line.startswith("+"):
            continue
        s = line[1:]
        if len(s.strip()) >= 12:
            out.append(s)
    return out

def pushed_after_merge():
    """合并后是否还有新 push。⚠️ 时间必须**归一化到同一时刻**再比 —— 提交时间是带本地时区的
    `%cI`（如 `+08:00`），mergedAt 是 UTC `Z`；直接按字符串比会跨时区误判（实测 #4127 假阳）。"""
    if not (merge and head_oid):
        return None
    if h != head_oid:
        return True
    ts = git("log", "-1", "--format=%ct", h)
    if not ts or not ts.strip().isdigit():
        return None
    import datetime as _dt
    try:
        merged_epoch = _dt.datetime.fromisoformat(merged_at.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
    return int(ts.strip()) > merged_epoch

# ── 交付物清单 ────────────────────────────────────────────────────────────────────
paths, order = set(), []
def add(p):
    if p and p not in paths and ".." not in p.split("/") and not p.startswith("/"):
        paths.add(p); order.append(p)

files_json = []
if os.path.exists(meta_path) and os.path.getsize(meta_path) > 0:
    try:
        files_json = [f.get("path") for f in (json.load(open(meta_path)).get("files") or [])]
    except Exception:
        files_json = []
body = ""
if os.path.exists(meta_path + ".body"):
    body = open(meta_path + ".body", encoding="utf-8", errors="replace").read()

declared = []
for tok in re.findall(r"`([^`\n]+)`", body):
    t = tok.strip()
    if "/" not in t or "*" in t or " " in t or t.startswith("-"):
        continue
    if not re.search(r"\.(py|sh|json|ya?ml|md|ts|tsx|js|java|sql|txt|cfg|ini)$", t):
        continue
    declared.append(t)

for p in declared:
    if blob(h, p) or blob(merge or base, p) or blob(base, p):
        add(p)
decl_set = set(paths)          # 「PR 自己声明的交付物」（body 反引号路径）—— 存在性判据只对它用
for p in files_json:
    add(p)

# 「锚点 → 所推 sha」的改动足迹（合并后 push 新增的文件也可能不在上面两份清单里）
footprint = []
if merge or base:
    d = git("diff", "--name-only", merge or base, h)
    if d is None:
        print("❌ 无法判定：git diff <锚点> <所推 sha> 失败 ⇒ 3"); raise SystemExit(3)
    footprint = [x for x in d.splitlines() if x.strip()]
for p in footprint:
    add(p)

if not order:
    print("❌ 无法判定：交付物清单为空（PR body 无路径段、gh files 为空、合并点→所推 sha 也无改动）⇒ 3")
    raise SystemExit(3)

# ── 「合并后是否有新 push」（④ 门：无 ⇒ 不存在搁浅，不许报红）──────────────────────
pushed_after = pushed_after_merge()
UNDET_PUSH = bool(merge and head_oid and pushed_after is None)
NO_PUSH = bool(merge and head_oid and pushed_after is False)   # PR 模式且合并后无新 push
ANCHOR = merge or base        # 锚点：PR 模式 = main 上的合并点；分支模式 = base 当前内容
ANCHOR_LABEL = "合并点" if merge else "base"

fork = git("merge-base", ANCHOR, h)
fork = fork.strip() if fork else None
fork = fork or None

print(f"{'PR #' + pr if pr else '分支模式'}  所推 sha={h[:8]}（来源：{h_src}）  "
      f"{ANCHOR_LABEL}={ANCHOR[:8]}{'  merge-base=' + fork[:8] if fork else '  merge-base=?'}")
print(f"交付物清单：body 声明 {len([p for p in declared if p in paths])} / gh files {len(files_json)} "
      f"/ 锚点→所推 sha 改动足迹 {len(footprint)} ⇒ 并集 {len(order)}")
if merge and head_oid:
    why = ("tip " + h[:8] + " != headRefOid " + head_oid[:8] + " / 提交时间晚于 mergedAt（均已归一化 UTC）"
           if pushed_after else "读不到提交时间 ⇒ 无法判定")
    print(f"合并后新 push：{'**有**（' + why + '）' if pushed_after else ('**?**（' + why + '）' if UNDET_PUSH else '无')}"
          + ("  ⇒ 按 §17.3：不存在搁浅（不作红判）" if NO_PUSH else ""))
    if head_oid == h and "分支已删" in h_src:
        print("  ℹ️ 所推 sha 取自 headRefOid/PR ref（分支已删）：**合并后 push 在本机不可见** —— 残留盲区，照实登记")
print()

RED, UNDET, STALE, LANDED, ANOM, notes = [], [], [], [], [], []

def mainstate(p, hb, gb):
    if gb is None:
        return "main=**无此路径**"
    if gb == hb:
        return "main=SAME"
    return "main=DIFF"

for p in order:
    hb, mb, gb = blob(h, p), blob(ANCHOR, p), blob(base, p)
    fb = blob(fork, p) if fork else None
    if hb is None and mb is None:
        notes.append(f"  · {p}: 既不在所推 sha 也不在 {ANCHOR_LABEL}（body 声明了但 PR 树里没有）⇒ 不判")
        continue
    if hb == mb:
        tag, red = "LANDED", False
        extra = ("内容与所推 sha 逐字节一致" if gb == hb else
                 "**当前 " + base_name + " 上已无此路径**（可能被后续 PR 删除/改名）" if gb is None else
                 "main 后来被别的 PR 改过 ⇒ DIFF-LATER（**已交付**，不是搁浅）")
        if gb is None and p in decl_set:
            tag = "MISSING-ON-MAIN"   # 声明的交付物当前不在 main 上（ruling #1 的存在性判据）
            red = not NO_PUSH
            if NO_PUSH:
                extra += "；本路径无合并后 push ⇒ 按 §17.3 不作红判"
    elif not fork:
        tag, red, extra = "UNDETERMINED", False, "读不到 merge-base ⇒ 无法区分「分支陈旧」与「真搁浅」"
    elif fb == hb:
        tag, red = "STALE-BRANCH", False
        extra = f"分支没动这文件（{ANCHOR_LABEL} 自己前进了）⇒ 无害，不报红"
    else:
        # 分支自己动过这文件、但内容与锚点不同 ⇒ 判「分支自己的新增内容**在不在锚点里**」（内容级）。
        # ⚠️ 为什么不能直接拿 h != m 当搁浅：squash 合入时 GitHub 会把 **main 的并发改动一起并入**
        #    该文件（实测 #4127 的 docs/sql/schema.sql：合并点内容 = main 版 + 本 PR 的 hunk，
        #    与分支 tip 逐字节不同，但**改动确实交付了**）⇒ 直接比 blob 会假红。
        addl = added_lines(fork, h, p)
        anchor_lines = lines(ANCHOR, p)
        if hb is None:                       # 分支删了这文件：删除也要在锚点里才叫落地
            landed_in_anchor = (mb is None)
        elif mb is None:                     # 分支新增的文件：锚点里根本没有 ⇒ 没落地
            landed_in_anchor = False
        elif addl is None or anchor_lines is None:
            landed_in_anchor = None
        else:
            landed_in_anchor = all(any(a in g for g in anchor_lines) for a in addl)
        if landed_in_anchor is None:
            tag, red = "UNDETERMINED", False
            extra = "读不到 diff/内容 ⇒ 无法判定本分支的改动在不在" + ANCHOR_LABEL
        elif landed_in_anchor:
            tag, red = "LANDED-MERGED", False
            extra = ("本分支的改动**已在**" + ANCHOR_LABEL + "里（该文件同时被 " + base_name +
                     " 并发改动并入 / 由别的 PR 以不同形态落地）⇒ **不是搁浅**")
        else:
            # 现在是否已由后续 PR 补齐（同一判据对「当前 main」再算一次，只作文案补充，不改判定）
            backfilled = False
            if gb is not None:
                if gb == hb:
                    backfilled = True
                elif hb is not None and addl:
                    gl = lines(base, p) or []
                    backfilled = all(any(a in g for g in gl) for a in addl)
            tag = "STRANDED-BACKFILLED" if backfilled else "STRANDED"
            red = True
            extra = ("所推内容**未随本 PR 进 " + base_name + "，但现已由后续 PR 补齐**（仍计红：机制发生过）"
                     if backfilled else
                     "所推内容未随本 PR 进 " + base_name if merge else
                     "该分支自己的内容不在 " + base_name + " 上（未交付）")
            if gb is None and not backfilled:
                extra += "，且当前 main 上无此路径"
    if red and NO_PUSH:
        ANOM.append(p)      # 合并后无 push ⇒ 按 §17.3 不作红判，但形态异常如实报出（需人核）
    if red:
        RED.append(p)
    elif tag == "UNDETERMINED":
        UNDET.append(p)
    elif tag == "STALE-BRANCH":
        STALE.append(p)
    else:
        LANDED.append(p)
    # 输出预算：红项/无法判定项**全列**（这是要人照做的）；陈旧与已交付项只列前几条 + 汇总计数
    budget = red or tag in ("UNDETERMINED", "MISSING-ON-MAIN")
    budget = budget or (tag == "STALE-BRANCH" and len(STALE) <= 3) \
                     or (tag in ("LANDED", "LANDED-MERGED") and len(LANDED) <= 5)
    if not budget:
        continue
    mark = "❌" if (red and not NO_PUSH) else ("⚠️" if red or tag in ("UNDETERMINED", "MISSING-ON-MAIN") else "✅")
    print(f"  {mark} {tag:<18} {p}")
    print(f"       └ h={str(hb)[:8]} {ANCHOR_LABEL}={str(mb)[:8]} {mainstate(p, hb, gb)}  {extra}")
    if red or tag == "UNDETERMINED":
        print(f"       └ 内容 sha1(原文) 所推={sha1(content(h, p))[:12]} "
              f"{ANCHOR_LABEL}={sha1(content(ANCHOR, p))[:12]} main={sha1(content(base, p))[:12]}")

if notes and not quiet:
    print("\n提示："); [print(n) for n in notes]

print()
if NO_PUSH:
    print(f"── 汇总：合并后无新 push ⇒ **无搁浅**（交付物 {len(order)} 项；main 上的差异均属后续 PR 演进）──")
    if ANOM:
        print(f"   ⚠️ 另有 {len(ANOM)} 项内容级形态异常（{', '.join(ANOM[:5])}）—— 合并后无 push ⇒ 按 §17.3 不作红判，需人核")
    print(f"   （LANDED {len(LANDED)} 项内容级通过"
          + (f"；STALE-BRANCH {len(STALE)} 项 = 分支陈旧 / base 前进，**无害**" if STALE else "") + "）")
    raise SystemExit(0)
if RED:
    print(f"── 汇总：**检出搁浅 {len(RED)} 项 / 共 {len(order)} 项** ⇒ §17.3：开**跟随 PR** 补齐"
          f"（**不得**向已合并分支追加 commit）──")
    for p in RED:
        print(f"     ❌ {p}")
    raise SystemExit(1)
if UNDET or UNDET_PUSH:
    print(f"── 汇总：**无法判定**（merge-base 缺失 {len(UNDET)} 项"
          f"{'；合并后 push 时间读不到' if UNDET_PUSH else ''}）⇒ 3 —— 不许当「没问题」──")
    raise SystemExit(3)
print(f"── 汇总：无搁浅（交付物 {len(order)} 项逐条内容级核对通过；LANDED {len(LANDED)}"
      f"{'；STALE-BRANCH ' + str(len(STALE)) + ' 项分支陈旧，无害' if STALE else ''}）──")
raise SystemExit(0)
PY
rc=$?
exit $rc