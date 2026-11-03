#!/usr/bin/env python3
"""batch_merge_lib.py — 多 PR **集中合**（batch merge）的单一实现（issue #8523）。

## 为什么（读数，不是推断）

分支保护是 `strict=true` ⇒ 每个 PR 各跑一轮 **28** 个 required job。**5 个 PR = 5×28 job**，
而**集中合成 1 个 PR = 1×28**。⇒ 多 PR 同批落地时，批次合并是**默认路径**（不是"省事的野路子"）。
什么时候**不该**用 ⇒ `docs/wiki/Development.md` 的「批次合并（默认路径）」。

## 今晚人工做过一次（PR #8519），踩的四个坑 = 本工具存在的**全部**理由

1. **冲突全在"追加型台账"上**：`.github/cases/*.yml`（各 PR 往末尾追加条目）、
   `tests/agent_eval/eval_cases/**` + `docs/testing/mibao-verification-cases.md`（生成物）、
   `tests/unit_ci_workflows/case_machine_fail_channel_baseline.json`（锚点）。
   🔴 **不要解冲突**：`git checkout --ours/--theirs` 会把冲突标记留成嵌套垃圾（实测把锚点 JSON 写坏过）。
   ⇒ 本工具**不解冲突**，而是**从 `origin/main` 重建再重放**：
      · 只追加型台账 = 取 main 版 + 按序并上各分支相对 merge-base 的**新增块**；
      · 两个生成物 = **一律重渲染**（源改了就该重渲染，逐行合并没有意义）；
      · 锚点 = **取 main 版**，跑判据拿**实测读数**，再追加一行 `history` + 把 `entries` 对齐实测。
   未知冲突面（既不是追加型台账也不是生成物）⇒ **fail-closed**：报出文件清单与出口，**不猜**。

2. **用例号必然互撞**（堆叠 PR 常同占一个号）⇒ 检测重复 `id`，对**后合入者让号**
   （改 `id` + claim 文件名/内容 + 声明该号的测试文件头 `# case_ids:` + 重渲染），并打印「谁让给谁」。

3. **`--no-commit` 合并后不提交就合下一支 ⇒ 全线 rc=128**；且 worktree 里 `.git` 是**文件**不是目录
   ⇒ 判「是否在合并中」**只能**用 `git rev-parse -q --verify MERGE_HEAD`
   （`Path(".git")/"MERGE_HEAD"` 在 worktree 里**永远不存在**）。本工具的每支合并都以
   「`in_merge_progress()` 必须为真 ⇒ 提交 ⇒ 必须为假」这一对断言收口。

4. **批量 PR body 不能带关闭关键词**（`pr_body_guard` 口径：命中数 ≠ 本意条数即拒）⇒
   本工具生成的 body **一律零关闭词**（生成后**当场**用 `pr_body_guard.find_close_keywords()` 断言 0 条，
   非 0 即 fail-closed **不建 PR**）；issue / 原 PR 由值守面在合并后按证据关闭。

## CLI（入口 = `scripts/batch-merge.sh`）

    ./scripts/batch-merge.sh <PR号> [<PR号> ...] [--branch batch/<日期>] [--dry-run] [--no-push] [--force-branch]

## 三态退出码

| 码 | 含义 |
|---|---|
| `0` | 成功（`--dry-run` 时 = 计划已打印，**零落盘**） |
| `1` | 判红（校验不过 / 未知冲突 / 判据复核失败 …）—— 冲突面已 `git merge --abort`；**不推送、不建 PR**（本地分支可能停在集成分支上，人工核对后重跑） |
| `2` | 用法错误 |

## 可注入点（判据用；沿用 `MG_GH_BIN` / `NCI_GH_BIN` / `SBT_GH_BIN` 先例）

- `BATCH_MERGE_GH_BIN` = `gh` 可执行文件路径（默认 `gh`）——判据用它替身「离线 / 只读 PR 元数据」；
- `BATCH_MERGE_TODAY` = 覆盖分支名日期与锚点 `history.date`（判据钉死日期，避免跨零点抖动）。

## 覆盖面（照实登记，§19.1 —— 本工具**盖不到**什么）

- ❌ **不关闭原 PR / issue**：合批落地后原 PR 的提交已进 main，需值守面按证据关闭（本工具只打印提醒）；
- ❌ **不做冲突的语义合并**：非追加型/非生成物/非锚点的冲突一律 fail-closed（那需要人判断业务语义）；
- ❌ **让号只用批次内现取的 `max+1`**：看不见批次**之外**的在飞 PR ⇒ 仍可能与外部在飞包撞号
  （`scripts/next_case_id.py` 是本仓的取号单一实现，但它要联网；批次内用 `max+1` 是**有意取舍**：
  可见性与零依赖，冲突仍由「后合入者让号」在**下一次**合入时收口）；
- ❌ **不跑全量 gate**：只跑定点判据（锚点判据 + 渲染器自检）；全量仍由集成分支的 CI 承担；
- ❌ **`--no-push` 时也跳过 `gh pr create`**（分支没上远端就开不了 PR，不制造半成品）。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ── 仓库内固定路径（单一真值源；改这里就改了全部消费点）─────────────────────────
CASES_DIR = ".github/cases"
CLAIMS_DIR = ".github/cases/claims"
ANCHOR = "tests/unit_ci_workflows/case_machine_fail_channel_baseline.json"
ANCHOR_TEST = "tests/unit_ci_workflows/test_case_machine_fail_channel.py"
RENDER = ".github/render_cases.py"
EVAL_OUT = "tests/agent_eval/eval_cases"
CASEBOOK = "docs/testing/mibao-verification-cases.md"

#: 生成物前缀（冲突时**一律重渲染**，逐行合并没有意义）
GENERATED_PREFIXES = (EVAL_OUT + "/", CASEBOOK)

PR_FIELDS = "number,state,isDraft,headRefName,baseRefName,headRefOid,title,url"

GH_BIN_ENV = "BATCH_MERGE_GH_BIN"
TODAY_ENV = "BATCH_MERGE_TODAY"

#: `cases/*.yml` 的条目起始行（块 = 从这行到下一个同类行或文件尾）
BLOCK_RE = re.compile(r"(?m)^  - id: (?P<id>[A-Za-z]+-\d+)[ \t]*$")
#: `# case_ids:` 声明行（与 `.github/growth_gate.py` 的注释形态同口径：`#` / `//` / JSDoc `*`）
DECL_LINE_RE = re.compile(r"^[ \t]*(?:#|//|\*)[ \t]*case_ids[ \t]*[:=]", re.M)
TEST_EXTS = (".py", ".ts", ".tsx", ".js", ".mjs", ".java")
#: 「追加型台账」= `.github/cases/<domain>.yml`（各 PR 往末尾追加条目；取并集是**唯一**安全解）
APPEND_ONLY_RE = re.compile(r"^\.github/cases/[^/]+\.ya?ml$")


class BatchError(RuntimeError):
    """判红（可解释、可行动）。`main()` 捕获后 exit 1。"""


# ══════════════════════════════════════════════════════════════════════════════
# 薄壳：git / gh / 子进程
# ══════════════════════════════════════════════════════════════════════════════

def _today() -> str:
    """分支名的日期 / 锚点 `history.date`（可注入 ⇒ 判据不跨零点抖动）。"""
    return os.environ.get(TODAY_ENV) or _dt.date.today().isoformat()


def run(cmd, cwd=None, check=True) -> subprocess.CompletedProcess:
    p = subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None,
                       text=True, capture_output=True)
    if check and p.returncode != 0:
        raise BatchError(f"命令失败（rc={p.returncode}）：{' '.join(str(c) for c in cmd)}\n"
                         f"{p.stdout}{p.stderr}")
    return p


def git(repo, *args, check=True) -> subprocess.CompletedProcess:
    return run(["git", "-C", str(repo), *args], check=check)


def git_out(repo, *args) -> str:
    return git(repo, *args).stdout.strip()


def in_merge_progress(repo) -> bool:
    """「是否处于合并中」—— **只认 `MERGE_HEAD`**（铁律：不看 `.git/MERGE_HEAD` 路径）。

    worktree 里 `.git` 是**文件**（`gitdir: …`）⇒ `Path(repo)/".git"/"MERGE_HEAD"` **永远不存在**
    ⇒ 用路径判据的工具会在冲突未收尾时继续合下一支（实测 rc=128 全线）。
    """
    return git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False).returncode == 0


def repo_root(cwd=None) -> Path:
    p = run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, check=False)
    if p.returncode != 0:
        raise BatchError(f"当前目录不是 git 工作区（{cwd or os.getcwd()}）：{p.stderr.strip()}")
    return Path(p.stdout.strip())


# ══════════════════════════════════════════════════════════════════════════════
# 1. 校验：PR 元数据（`gh` 可注入）
# ══════════════════════════════════════════════════════════════════════════════

def gh_bin() -> str:
    return os.environ.get(GH_BIN_ENV) or "gh"


def pr_info(number: int) -> dict:
    """`gh pr view <n> --json …` ⇒ dict。**只读**。"""
    p = run([gh_bin(), "pr", "view", str(number), "--json", PR_FIELDS], check=False)
    if p.returncode != 0:
        raise BatchError(f"读不到 PR #{number}（gh 退出码 {p.returncode}）：{p.stderr.strip()}\n"
                         f"   ⇒ 「看不了」不得当「没问题」：先 `gh auth status` / 确认 PR 号存在。")
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError as e:
        raise BatchError(f"PR #{number} 的 gh 输出不是 JSON（{e}）：{p.stdout[:200]}")


def validate(infos) -> list[str]:
    """每条 PR 的拒绝理由（空 = 全部可合批）。

    · `state` 必须 `OPEN`；② **draft 先拒绝并说明**（draft 合进去等于偷偷合一份未评审内容）；
    · `baseRefName` 必须 `main` —— base 不是 main 的 PR 是**堆叠 PR**，合批会把依赖顺序抹掉。
    """
    errs = []
    for i in infos:
        n = i.get("number")
        if str(i.get("state") or "").upper() != "OPEN":
            errs.append(f"#{n}: state={i.get('state')} ≠ OPEN（已合并/已关闭的 PR 不该再进批次）")
        if i.get("isDraft"):
            errs.append(f"#{n}: 是 **draft** —— 先 `gh pr ready {n}` 再合批"
                        f"（draft = 作者还在改；合进批次等于偷偷合入未评审内容）")
        if str(i.get("baseRefName") or "") != "main":
            errs.append(f"#{n}: base={i.get('baseRefName')} ≠ main —— 堆叠 PR 请先单独合入底座"
                        f"（合批会把「谁依赖谁」的顺序抹掉）")
        if not i.get("headRefOid"):
            errs.append(f"#{n}: 读不到 head sha（gh 输出缺 headRefOid）")
    return errs


def pr_table(infos) -> str:
    rows = [f"{'PR':>7}  {'base':<6}  {'head sha':<12}  head 分支 / 标题"]
    for i in infos:
        rows.append(f"{'#' + str(i.get('number')):>7}  {str(i.get('baseRefName')):<6}  "
                    f"{str(i.get('headRefOid'))[:10]:<12}  {i.get('headRefName')} — {i.get('title')}")
    return "\n".join(rows)


# ══════════════════════════════════════════════════════════════════════════════
# 2/3. 重建 + 逐支合并（冲突按「重建重放」四条处置）
# ══════════════════════════════════════════════════════════════════════════════

def fetch_pr_ref(repo, info) -> str:
    """把 PR 的内容取到本仓的临时 ref（`refs/batch-merge/pr-<n>`）。

    先试 GitHub 的 `refs/pull/<n>/head`（= PR **真身**，fork PR 也拿得到），
    取不到再退回同仓分支名（离线夹具 / 非 GitHub remote 走这条腿）。
    """
    n = info["number"]
    dest = f"refs/batch-merge/pr-{n}"
    tried = []
    for src in (f"refs/pull/{n}/head", f"refs/heads/{info.get('headRefName')}"):
        p = git(repo, "fetch", "origin", f"+{src}:{dest}", check=False)
        tried.append(f"{src} → rc={p.returncode}")
        if p.returncode == 0:
            return dest
    raise BatchError(f"取不到 PR #{n} 的内容：\n  " + "\n  ".join(tried))


def conflicted_files(repo) -> "list[str]":
    out = git(repo, "diff", "--name-only", "--diff-filter=U").stdout
    return [ln for ln in out.splitlines() if ln.strip()]


def stage_text(repo, stage: int, path: str) -> str:
    """冲突三方的 blob（stage 1 = base / 2 = ours / 3 = theirs）。取不到 ⇒ 空串。"""
    p = git(repo, "show", f":{stage}:{path}", check=False)
    return p.stdout if p.returncode == 0 else ""


def split_blocks(text: str):
    """`cases/*.yml` → [(id, 块文本)]（块 = 该 `- id:` 行到下一个同类行/文件尾）。"""
    starts = list(BLOCK_RE.finditer(text))
    out = []
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        out.append((m.group("id"), text[m.start():end]))
    return out


def added_blocks(base_text: str, theirs_text: str):
    """`theirs` 相对 `base` **新增**的块（按 `theirs` 里的出现顺序）——「重放」的输入。"""
    base = set(theirs for _, theirs in split_blocks(base_text))
    return [(cid, blk) for cid, blk in split_blocks(theirs_text) if blk not in base]


def union_cases_yaml(base_text: str, ours_text: str, theirs_text: str) -> str:
    """只追加型台账的**并集**：ours（= main 侧）+ theirs 的新增块，按序追加、逐字节去重。

    ⚠️ 为什么不是 `--ours` / `--theirs`：`--theirs` 会**丢掉 main 后来加的条目**，
    `--ours` 会**丢掉本 PR 的条目**；两者还会在再次合并时把冲突标记留成嵌套垃圾。
    """
    text = ours_text
    for _cid, blk in added_blocks(base_text, theirs_text):
        if blk in text:                                    # 幂等：同一块不重复追加
            continue
        if text and not text.endswith("\n"):
            text += "\n"
        text += blk if blk.endswith("\n") else blk + "\n"
    return text


def resolve_conflicts(repo, paths) -> "list[str]":
    """按「重建重放」四条处置冲突；返回**处置说明**。未知面 ⇒ fail-closed。"""
    notes, unknown = [], []
    for path in paths:
        if APPEND_ONLY_RE.match(path):
            text = union_cases_yaml(stage_text(repo, 1, path), stage_text(repo, 2, path),
                                    stage_text(repo, 3, path))
            (Path(repo) / path).write_text(text, encoding="utf-8")
            notes.append(f"{path}: 只追加型台账 ⇒ 取 main 版 + 并上本支新增块（重放）")
        elif path.startswith(GENERATED_PREFIXES):
            text = stage_text(repo, 2, path)                # ours；稍后**一律重渲染**
            (Path(repo) / path).write_text(text, encoding="utf-8")
            notes.append(f"{path}: 生成物 ⇒ 保留 ours 占位，最后**重渲染**")
        elif path == ANCHOR:
            text = stage_text(repo, 2, path)                # main 侧；稍后按**实测**重锚
            (Path(repo) / path).write_text(text, encoding="utf-8")
            notes.append(f"{path}: 锚点 ⇒ 取 main 版占位，最后按**实测读数**重锚")
        else:
            unknown.append(path)
    if unknown:
        raise BatchError(
            "遇到**未知冲突面**（既不是追加型台账、也不是生成物/锚点）⇒ 拒绝自动解冲突：\n  "
            + "\n  ".join(unknown)
            + "\n   出口：① 先单独把这个 PR 的冲突解掉（`git merge origin/main`）再合批；"
              "② 或确认它属于哪一类处置，再补 `batch_merge_lib.py` 的处置规则"
              "（本工具**不做**语义合并 —— 那需要人判断业务）。")
    git(repo, "add", "--", *paths)
    return notes


def commit_merge(repo, info, ref) -> None:
    """提交当前合并 —— 提交**前后**都用 `MERGE_HEAD` 落断言（每支必须成功提交）。"""
    if not in_merge_progress(repo):
        raise BatchError(
            f"合 #{info['number']} 之后**没有 MERGE_HEAD** ⇒ 这次 merge 没留下待提交的合并"
            f"（通常是该 PR 的内容已在 main：`--no-ff` 也会报 Already up to date）。\n"
            f"   出口：把 #{info['number']} 从批次里去掉（它已经落地了）。")
    sha = git_out(repo, "rev-parse", ref)[:12]
    git(repo, "commit", "-m",
        f"merge: #{info['number']} {info.get('headRefName')} ({sha}) — {info.get('title')}")
    if in_merge_progress(repo):
        raise BatchError(f"提交 #{info['number']} 之后仍处于合并中 —— 现场脏了，"
                         f"拒绝继续合下一支（否则下一支必然 rc=128）")


# ══════════════════════════════════════════════════════════════════════════════
# 4. 用例号：检测重复 id + 后合入者让号
# ══════════════════════════════════════════════════════════════════════════════

def corpus_ids(repo) -> "set[str]":
    root = Path(repo) / CASES_DIR
    ids = set()
    for f in sorted(root.glob("*.yml")):
        ids |= {cid for cid, _ in split_blocks(f.read_text(encoding="utf-8"))}
    return ids


def allocate_free_id(prefix: str, taken) -> str:
    """批次内取号 = `max+1`（**不填历史空档**：空档可能是别的在飞包刻意占的）。"""
    nums = []
    for i in taken:
        head, _, tail = str(i).partition("-")
        if head == prefix and tail.isdigit():
            nums.append(int(tail))
    return f"{prefix}-{max(nums) + 1 if nums else 1:03d}"


def plan_renames(added, taken):
    """`added` = [(path, id, 块文本)]（本支相对 merge-base 的新增），`taken` = 合入前已有 id。

    规则 = **后合入者让号**：`taken` 里已经有的 id，本支让出去。
    """
    out, seen = [], set(taken)
    for path, cid, blk in added:
        if cid in seen:
            new = allocate_free_id(cid.split("-")[0], seen)
            out.append((path, cid, new, blk))
            seen.add(new)
        else:
            seen.add(cid)
    return out


def apply_renames(repo, renames) -> None:
    """在**已合并**的工作树上改 `- id:`（块文本必须在文件里**唯一**定位）。"""
    for path, old, new, blk in renames:
        p = Path(repo) / path
        text = p.read_text(encoding="utf-8")
        at = text.find(blk)
        if at < 0:
            raise BatchError(f"让号失败：在 {path} 里定位不到 `{old}` 的用例块 "
                             f"（块首行 {blk.splitlines()[0] if blk else '?'}）——"
                             f"冲突处置留下的版本与分支内容不一致，请人工核对后重跑")
        if text.find(blk, at + 1) >= 0:
            raise BatchError(f"让号失败：{path} 里 `{old}` 的用例块**不唯一**（内容完全相同的两条）"
                             f"⇒ 无法判断改哪一条。出口：把两条用例的标题/内容区分开再合批")
        new_blk = blk.replace(f"- id: {old}", f"- id: {new}", 1)
        p.write_text(text[:at] + new_blk + text[at + len(blk):], encoding="utf-8")


def sync_claims(repo, renames, pr: int) -> "list[str]":
    """claim 文件：文件名 + `id` 字段都要跟让号走（`<pr>-<ID>.json`）。

    ⚠️ **只动本支自己的 claim**（`<pr>-`）：同一个号可能同时被**别的在飞分支**占着，
    那些 claim 不是本次让号的对象（改它们 = 替别人改号）。
    """
    notes = []
    claims = Path(repo) / CLAIMS_DIR
    if not claims.is_dir():
        return notes
    for _path, old, new, _blk in renames:
        for f in sorted(claims.glob(f"{pr}-{old}.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("id") != old:
                continue
            data["id"] = new
            target = f.with_name(f.name.replace(f"-{old}.json", f"-{new}.json"))
            f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if target != f:
                f.rename(target)
                git(repo, "add", "--", str(f.relative_to(repo)), str(target.relative_to(repo)),
                    check=False)
            notes.append(f"claim {f.name} → {target.name}")
    return notes


def renumber_decl_lines(text: str, mapping) -> str:
    """只改**声明行**里的号（`# case_ids:` / `// case_ids:` / JSDoc `* case_ids:`）。

    正文 / `merge_log` 里的"提及"不动 —— 与 growth gate「只认注释起始的声明行」同口径；
    改多了会把历史记录改写成假的。
    """
    out = []
    for line in text.splitlines(keepends=True):
        if DECL_LINE_RE.match(line):
            for old, new in mapping.items():
                line = re.sub(rf"(?<![\w-]){re.escape(old)}(?![\w-])", new, line)
        out.append(line)
    return "".join(out)


def sync_declarations(repo, renames, files) -> "list[str]":
    """声明该号的测试文件头同步（`# case_ids:`）。

    ⚠️ 只改**本支自己带来的**文件（`files` = 本支相对 merge-base 的变更集）：
    同一个号可能被别的在飞分支写在**它自己的**测试文件头里，改那些 = 替别人改号
    （且下一个 PR 合进来时会变成两处冲突）。
    """
    mapping = {old: new for _p, old, new, _b in renames}
    if not mapping:
        return []
    changed = []
    for rel in files:
        if not rel.endswith(TEST_EXTS) or rel.startswith("tests/agent_eval/"):
            continue
        p = Path(repo) / rel
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new_text = renumber_decl_lines(text, mapping)
        if new_text != text:
            p.write_text(new_text, encoding="utf-8")
            changed.append(rel)
    return changed


# ══════════════════════════════════════════════════════════════════════════════
# 5. 生成物重渲染 + 锚点按**实测**重锚
# ══════════════════════════════════════════════════════════════════════════════

def render(repo) -> str:
    """两个生成物**一律重渲染**（源改了，逐行合并没有意义）。"""
    script = Path(repo) / RENDER
    if not script.is_file():
        raise BatchError(f"找不到渲染器 {RENDER} ⇒ 生成物无法重渲染（拒绝把未重渲染的现场推出去）")
    p = run([sys.executable, str(script), "--cases", CASES_DIR,
             "--out-eval", EVAL_OUT, "--out-md", CASEBOOK], cwd=repo, check=False)
    if p.returncode != 0:
        raise BatchError(f"重渲染失败（rc={p.returncode}）：\n{p.stdout}{p.stderr}")
    return p.stdout.strip()


def _load_module(path: Path, name: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise BatchError(f"无法加载模块：{path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def measure_anchor(repo) -> dict:
    """**实测读数** —— 直接调判据文件自己的测量函数（不另写一份实现）。

    「以实测为准」：锚点写什么由**跑出来的读数**决定，不抄任何 PR 里写的数字。
    """
    test = Path(repo) / ANCHOR_TEST
    if not test.is_file():
        raise BatchError(f"找不到锚点判据 {ANCHOR_TEST} ⇒ 无法取实测读数（拒绝按「猜」重锚）")
    mod = _load_module(test, "_batch_merge_anchor_probe")
    cases = mod._real_cases()                                # 判据自己的读法（含 fail-closed 断言）
    return {
        "no_channel_total": len(mod.no_channel_cases(cases, mod.REPO_ROOT)),
        "backend_contract_scoring_zero": mod.scoring_zero_total(cases),
    }


def reanchor(anchor: dict, measured: dict, note: str, sha: str, day: str) -> dict:
    """`entries` 对齐实测 + **追加一行** `history`（`anchor_drift` 的规则 ②④）。"""
    out = dict(anchor)
    history = list(anchor.get("history") or [])
    row = {"sha": sha[:12], "date": day, **measured,
           "note": (note or "").strip() or "批次合并：读数由实测重锚（无 note —— 属缺省文案）"}
    out["history"] = history + [row]
    out["entries"] = dict(measured)
    return out


def write_anchor(repo, measured: dict, note: str) -> dict:
    path = Path(repo) / ANCHOR
    anchor = json.loads(path.read_text(encoding="utf-8"))
    sha = git_out(repo, "rev-parse", "origin/main")
    new = reanchor(anchor, measured, note, sha, _today())
    path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"before": (anchor.get("entries") or {}), "after": measured}


def verify_anchor(repo) -> str:
    """以**实测为准**的收口断言：跑锚点判据（非零 ⇒ 不许推送）。"""
    p = run([sys.executable, "-m", "pytest", ANCHOR_TEST, "-q"], cwd=repo, check=False)
    if p.returncode != 0:
        raise BatchError("锚点判据复核失败（实测与重锚结果对不上）：\n"
                         f"{p.stdout[-4000:]}{p.stderr[-2000:]}")
    return p.stdout.strip().splitlines()[-1] if p.stdout.strip() else "ok"


# ══════════════════════════════════════════════════════════════════════════════
# 6. PR body（**零关闭关键词**）
# ══════════════════════════════════════════════════════════════════════════════

def _guard():
    """复用 `scripts/pr_body_guard.py` 的关闭关键词口径（**同一实现**，不另写一份）。"""
    path = Path(__file__).resolve().parent / "pr_body_guard.py"
    if not path.is_file():
        raise BatchError(f"缺少守卫 {path} ⇒ 无法断言「body 零关闭词」（fail-closed，不建 PR）")
    return _load_module(path, "_batch_merge_body_guard")


def find_close_keywords(text: str):
    """⇒ [(行号, 命中行)]（口径 = `pr_body_guard.CLOSE_KEYWORD_RE`）。"""
    return _guard().find_close_keywords(text)


def build_pr_body(infos, branch: str, renames, anchor_delta, measured, rendered: bool) -> str:
    """批次 PR 的 body —— **零关闭词**（issue / 原 PR 由值守面在合并后按证据关闭）。"""
    lines = [f"批次合并：{len(infos)} 个 PR 一次进 main（分支 `{branch}`）", ""]
    lines += ["## 合入清单（按合入顺序）", ""]
    for i, info in enumerate(infos, 1):
        lines.append(f"{i}. #{info.get('number')} `{info.get('headRefName')}` — {info.get('title')}"
                     f"（head {str(info.get('headRefOid'))[:10]}）")
    lines += ["", "## 合批做的三件事", "",
              "1. **冲突处置 = 从 `origin/main` 重建 + 重放**（不做 `--ours/--theirs` 解冲突）："
              "只追加型台账（`.github/cases/*.yml`）取 main 版并按序并上各分支的新增块；"
              "两个生成物（`tests/agent_eval/eval_cases/**`、`docs/testing/mibao-verification-cases.md`）"
              "**一律重渲染**；锚点 `tests/unit_ci_workflows/case_machine_fail_channel_baseline.json` "
              "取 main 版后按**实测读数**重锚。", ""]
    if renames:
        who = "；".join(f"#{pr} `{old}` → `{new}`" for pr, old, new in renames)
        lines.append(f"2. **用例号让号**（后合入者让号）：{who}。claim 文件名/内容、声明该号的测试文件头 "
                     f"`# case_ids:`、渲染物**同步改**。")
    else:
        lines.append("2. **用例号**：本批无重复 `id`（检测过，无需让号）。")
    lines.append(
        f"3. **生成物重渲染 + 锚点实测重锚**：`no_channel_total` = {measured.get('no_channel_total')} / "
        f"`backend_contract_scoring_zero` {anchor_delta.get('before', {}).get('backend_contract_scoring_zero')}"
        f" → {anchor_delta.get('after', {}).get('backend_contract_scoring_zero')}；复核 = "
        f"`python3 -m pytest tests/unit_ci_workflows/test_case_machine_fail_channel.py -q`"
        f"{'（已通过）' if rendered else ''}。")
    lines += ["", "## 为什么走批次（而不是逐个合）", "",
              "分支保护 `strict=true` ⇒ 每个 PR 各跑一轮 **28** 个 required job。"
              f"{len(infos)} 个 PR 逐个合 = **{len(infos)}×28** job；本批 = **1×28**。", "",
              "## 归因提示（批次合并的代价，先写在前面）", "",
              "批次内的判据红/绿**不指向单个 PR**：本 PR 合并后若某判据变红，先看 "
              "`git log --oneline` 里本批的 `merge: #<PR> …` 提交定位，再回原 PR 的讨论线。"
              "强依赖链 / 需要逐个归因 / 单 PR 时**不要**用批次。", "",
              "## 关闭口径", "",
              "本 body **零关闭关键词**（`pr_body_guard` 口径：命中数须等于本意条数，多关闭词会被拒）。"
              "原 PR 与相关 issue 由值守面在合并后按证据逐个关闭 —— 本工具不自动关任何单。", ""]
    return "\n".join(lines)


def assert_zero_close_keywords(body: str) -> None:
    hits = find_close_keywords(body)
    if hits:
        raise BatchError("生成的 body 命中了关闭关键词（必须是 **0** 条）：\n  "
                         + "\n  ".join(f"第 {no} 行: {raw}" for no, raw in hits)
                         + "\n   出口：改 `build_pr_body()` 的措辞（把关键词与号**拆开**写）。")


# ══════════════════════════════════════════════════════════════════════════════
# 编排
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_clean(repo) -> None:
    if in_merge_progress(repo):
        raise BatchError("当前已在**合并中**（MERGE_HEAD 存在）—— 先把这一轮 merge 收尾再合批")
    dirty = git_out(repo, "status", "--porcelain")
    if dirty:
        raise BatchError("工作区不干净（合批会把自己的改动混进 merge commit）：\n  "
                         + "\n  ".join(dirty.splitlines()[:20])
                         + "\n   出口：先 commit 或换一个干净 worktree（`./scripts/dev-worktree.sh add <branch>`）")


def _branch_exists(repo, branch: str) -> "str | None":
    if git(repo, "rev-parse", "-q", "--verify", f"refs/heads/{branch}", check=False).returncode == 0:
        return "本地"
    if git(repo, "rev-parse", "-q", "--verify", f"refs/remotes/origin/{branch}",
           check=False).returncode == 0:
        return "远程 origin"
    return None


def dry_run(infos, branch: str, repo) -> int:
    print("── 批次合并计划（--dry-run：**只打印，零落盘**）──")
    print(pr_table(infos))
    existed = _branch_exists(repo, branch)
    warn = (f"  ⚠️ 已存在（{existed}）⇒ 真跑会被拒（除非 --force-branch）" if existed else "  ✅ 尚不存在")
    print(f"\n集成分支: {branch}  ← 从 origin/main 重建{warn}")
    for i, info in enumerate(infos, 1):
        print(f"  {i}. 合 #{info['number']} → merge --no-ff --no-commit → 冲突按「重建重放」处置 → "
              f"提交（每支都必须成功提交）")
    print("\n  4. 重复用例号检测 + 后合入者让号（claim / 文件头 / 渲染同步）")
    print("  5. 重渲染生成物 + 锚点按实测重锚 + 跑锚点判据复核")
    print("  6. push 分支 + `gh pr create --draft`（body 零关闭词）")
    print("\n本次**没有**创建分支、没有提交、没有推送、没有动远端。")
    return 0


def main(argv=None, cwd=None) -> int:
    ap = argparse.ArgumentParser(
        prog="batch-merge", description="多 PR 集中合（batch merge）：从 origin/main 重建 + 重放")
    ap.add_argument("prs", nargs="+", type=int, metavar="PR号")
    ap.add_argument("--branch", default="", help="集成分支名（默认 batch/<日期>）")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，零落盘")
    ap.add_argument("--no-push", action="store_true", help="不推送、不开 PR（本地演练）")
    ap.add_argument("--force-branch", action="store_true", help="集成分支已存在时覆盖（默认拒绝）")
    args = ap.parse_args(argv)

    branch = args.branch or f"batch/{_today()}"
    try:
        infos = [pr_info(n) for n in args.prs]
        errs = validate(infos)
        if errs:
            raise BatchError("校验不过（先修好再合批）：\n  " + "\n  ".join(errs))
        repo = repo_root(cwd)
        if args.dry_run:
            return dry_run(infos, branch, repo)

        _ensure_clean(repo)
        existed = _branch_exists(repo, branch)
        if existed and not args.force_branch:
            raise BatchError(f"集成分支 {branch} 已存在（{existed}）—— 拒绝覆盖已存在的集成分支。\n"
                             f"   出口：换个 `--branch`；或确认要重建时加 `--force-branch`")
        git(repo, "fetch", "origin", "--prune")

        print(f"── 重建集成分支 {branch}（from origin/main）──")
        git(repo, "checkout", "-B", branch, "origin/main")

        renames_all = []
        for info in infos:
            n = info["number"]
            print(f"\n── 合 #{n} {info.get('headRefName')} ──")
            ref = fetch_pr_ref(repo, info)
            merge_base = git_out(repo, "merge-base", "HEAD", ref)
            taken = corpus_ids(repo)
            added = []
            rels = {n for n in git_out(repo, "ls-tree", "-r", "--name-only", ref,
                                       "--", CASES_DIR).splitlines()
                    if n.endswith((".yml", ".yaml"))}
            rels |= {rel for rel in git_out(repo, "ls-files", CASES_DIR).splitlines()
                     if rel.endswith(".yml")}
            for rel in sorted(rels):
                theirs = git(repo, "show", f"{ref}:{rel}", check=False)
                if theirs.returncode != 0:
                    continue                                  # 本支没碰这个文件
                base_proc = git(repo, "show", f"{merge_base}:{rel}", check=False)
                base = base_proc.stdout if base_proc.returncode == 0 else ""
                added += [(rel, cid, blk) for cid, blk in added_blocks(base, theirs.stdout)]
            branch_files = git_out(repo, "diff", "--name-only", merge_base, ref).splitlines()
            renames = plan_renames(added, taken)

            p = git(repo, "merge", "--no-ff", "--no-commit", ref, check=False)
            if p.returncode != 0:
                conflicts = conflicted_files(repo)
                if not conflicts:
                    git(repo, "merge", "--abort", check=False)
                    raise BatchError(f"合 #{n} 失败且**没有冲突文件**（rc={p.returncode}）：\n"
                                     f"{p.stdout}{p.stderr}")
                print("   冲突：" + " / ".join(conflicts))
                try:
                    for note in resolve_conflicts(repo, conflicts):
                        print("   ⇒ " + note)
                except BatchError:
                    git(repo, "merge", "--abort", check=False)
                    raise

            applied = []
            if renames:
                apply_renames(repo, renames)
                claims = sync_claims(repo, renames, n)
                decls = sync_declarations(repo, renames, branch_files)
                for rel, old, new, _blk in renames:
                    print(f"   🔁 让号：#{n} `{old}` → `{new}`（后合入者让号）")
                    applied.append((n, old, new))
                    renames_all.append((n, old, new))
                for c in claims:
                    print("      " + c)
                if decls:
                    print("      文件头 case_ids 同步：" + ", ".join(decls))

            # 工具内部实现（含冲突处置/让号/重命名的暂存）：此处是**唯一**允许 `git add -A` 的地方，
            # 且 `_ensure_clean()` 已断言合批开始前工作区逐字节干净 ⇒ 不会夹带别人的改动。
            git(repo, "add", "-A")
            commit_merge(repo, info, ref)

        print("\n── 重渲染生成物 ──")
        print("   " + render(repo).replace("\n", "\n   "))

        print("\n── 锚点：取 main 版 + 按**实测**重锚 ──")
        git(repo, "checkout", "origin/main", "--", ANCHOR)
        measured = measure_anchor(repo)
        print(f"   实测：{measured}")
        delta = write_anchor(repo, measured, note=_anchor_note(infos, measured))
        print(f"   锚点：{delta['before']} → {delta['after']}")
        print("   复核：" + verify_anchor(repo))
        git(repo, "add", "--", ANCHOR, EVAL_OUT, CASEBOOK)
        git(repo, "commit", "-m",
            f"chore(batch): 重渲染生成物 + 锚点按实测重锚（{len(infos)} 个 PR 的批次合并）")
        if in_merge_progress(repo):
            raise BatchError("清理提交之后仍处于合并中 —— 现场脏了，拒绝推送")

        body = build_pr_body(infos, branch, renames_all, delta, measured, rendered=True)
        assert_zero_close_keywords(body)
        git_dir = Path(git_out(repo, "rev-parse", "--absolute-git-dir"))
        body_file = git_dir / "batch-merge-pr-body.md"
        body_file.write_text(body, encoding="utf-8")
        print(f"\n── PR body 已写：{body_file}（关闭关键词命中 0 条）──")

        if args.no_push:
            print("\n--no-push：不推送、不建 PR（分支已在本地：%s）" % branch)
            return 0

        git(repo, "push", "-u", "origin", branch)
        title = f"chore(batch): 批次合并 {len(infos)} 个 PR（{branch}）"
        p = run([gh_bin(), "pr", "create", "--draft", "--base", "main", "--head", branch,
                 "--title", title, "--body-file", str(body_file)], cwd=repo, check=False)
        if p.returncode != 0:
            raise BatchError(f"`gh pr create` 失败（rc={p.returncode}）：{p.stderr.strip()}\n"
                             f"   分支已推送：{branch}；body 在 {body_file}（可手工补开 draft PR）")
        print(p.stdout.strip())
        print("\n⚠️ 原 PR / 相关 issue **本工具不自动关闭** —— 合并后由值守面按证据逐个关闭。")
        return 0
    except BatchError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1


def _anchor_note(infos, measured) -> str:
    prs = " / ".join("#" + str(i["number"]) for i in infos)
    return (f"批次合并（{len(infos)} 个 PR：{prs}）：合并前从 `origin/main` 重建集成分支，"
            f"锚点取 main 版后**按实测重锚**（不抄任何单支 PR 里写的数字）。"
            f"实测 `no_channel_total` = {measured.get('no_channel_total')}、"
            f"`backend_contract_scoring_zero` = {measured.get('backend_contract_scoring_zero')}。"
            f"复核 = `python3 -m pytest tests/unit_ci_workflows/test_case_machine_fail_channel.py -q`。")


if __name__ == "__main__":
    sys.exit(main())
