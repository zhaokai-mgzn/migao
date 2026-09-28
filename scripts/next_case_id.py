#!/usr/bin/env python3
"""next_case_id.py — 「取下一个用例号」的**单一实现**（只读；issue #5707 / 台账 `FM-E7` + `FM-E15`）。

## 病根（这类缺陷已经复发 5~6 次，其中一次是**三个并行包同时取到 `MC-046`**）

用例号（`.github/cases/**` 里的 `- id: <PREFIX>-NNN`）此前在**每个包里手工取**：跑一次
「现取最大号 + 1」。而**唯一性判据只看已合并状态**（`tests/unit_ci_workflows/test_dev_mode_failure_modes.py`
的判据 11/12）⇒ **拦不住在飞** ⇒ 并发的几个包各自「现取」都会得到**同一个答案**：
`MC-046` 被 PR #5733 / #5734 / #5736 三包同时取到（逐字记在 MC-047 与 MC-048 的 `merge_log` 里；
更早 `UI-061` / `UI-064` / `MC-022` / `MC-023` / `BM-019` / `MC-031` / `MC-039` 等也撞过）。
既有缓解 = 「取号前也 `gh pr` 查一遍在飞 PR 的 diff」，它是**手工动作** ⇒ 并发 5~6 个包时必然失效。

## 口径（三条，缺一不可）

1. **候选 = main ∪ 全部 open PR 的分支 ∪ 本工作区**。只读 main 会漏在飞（`FM-E15` 的病根本身）；
   只读 main + 在飞会漏「本工作区已先占、但还没提交/推送」的号（那样工具会把**自己刚占的号**判成空闲）。
2. **取最小空闲号**（**不是**「最大号 + 1」）。两个理由：① 最小空闲号**幂等** —— 同一次取号在
   rebase 前后、在别的包合并后，只要那个号仍空着，答案不变（`max+1` 会随着 main 前进而漂移）；
   ② 它能**填掉历史空档**（本仓现取就有：`MC` 的 041/042/046、`DF` 的 019、`PR` 的 014…）。
   ⇒ **本工具只在「候选集之外」给号**，并在**同一次调用里**断言「返回的号 ∉ 候选集」。
3. **看不到在飞分支 ⇒ 不给号**。`gh` 不可用 / 未登录 / 离线 / 某个 PR 的内容读不到 ⇒ 打印
   「**无法判定 ⇒ 不许取号**」并 `exit 3`。**禁止**在看不到在飞分支时"乐观"给出一个号 ——
   那正是今天撞号的成因（`FM-E7` / `FM-E15` 的现场）。

## 输出（必须给人复算，不许只打印一个数字）

逐条打印：① 每个候选来源的**取法命令 + 命中的 ref + 读数**；② 每个前缀的
「已占号来源（main / PR #NNNN / 工作区）→ 现取最小空闲号」；③ 时点。

## 三态退出码（与 `scripts/merge_gate.py` / `scripts/dangling_pr_scan.py` 同口径）

| 码 | 含义 |
|---|---|
| `0` | 判定成功，已给出号 |
| `2` | 用法 / 环境错误（前缀形态不合法、找不到 `python3` 之外的依赖） |
| `3` | **无法判定** ⇒ **不许取号**（`gh` 不可用 / 未登录 / 离线 / 在飞面读不全 / 主线段取不到） |

⚠️ `3` **不得当 `0` 读**，也**不得**当成"没有在飞 PR" —— 本仓「空跑 = 假绿」同族。

## 零写（结构性保证，不是纪律）

- `gh` 只走**只读白名单**（`GH_READ_ONLY`）：`gh api` 走默认 GET，出现 `-X/--method` 写动词 ⇒ 直接报错；
- `git` 只走**只读白名单**（`GIT_READ_ONLY`）：`rev-parse` / `ls-tree` / `grep` / `show` / `cat-file`；
  **`fetch` 不在白名单里** —— 本工具不写 `.git`（改 ref 也是写），所以它读的 `origin/main` 是**本地** ref，
  口径随读数一起打印（过期的本地 ref 会让 main 侧读数偏低，见下面的「覆盖面」）；
- 不写任何文件、不打标签、不改远端。

## 注入点（判据用；沿用 `MG_GH_BIN` / `SBT_GH_BIN` / `DANGLING_GH_BIN` 先例）

- `NCI_GH_BIN` = `gh` 可执行文件路径（默认 `gh`）—— 判据用它替身「不可用 / 未登录 / 读不到」三态；
- `NCI_MAIN_REF` = 主线段 ref（默认 `origin/main`）—— 判据在 `fetch-depth: 1` 的 CI 上改用 `HEAD`，
  使三态判据**不依赖 `origin/main` 存不存在**（否则会因"取不到 ref"而**因错的原因**变绿）。

## 覆盖面（照实登记 —— 本工具**盖不到**什么）

- ❌ **看不到未 push 的本地分支**（别人的工作区）：工具只看得见 main + open PR 的分支 + **自己**的工作区；
- ❌ **看不到 force-push 之前的旧状态**：读的是 ref 的**当前**内容；
- ❌ **不是互斥锁**：两个包在**同一瞬间**调用仍会拿到同一个号 —— 本工具消灭的是
  「**看不到在飞面**」这一层（那才是 5~6 次撞号的直接成因），**不是**「并发互斥」；
- ❌ **号"空闲"≠「号在语义上合适」**：最小空闲号可能落在**历史空档**（现取如 `PP-001` / `DF-019`），
  取号方仍须判断该空档是不是「刻意保留 / 已废弃」；
- ❌ **本地 `origin/main` ref 过期时 main 侧读数是下界**（本工具刻意**不** `fetch`）；
- ❌ `gh` 抖动 / fork PR 的对象读不到 / open PR 数达到 `PR_LIST_LIMIT` ⇒ `exit 3`（fail-closed，不给号）。

### 在飞面是**怎么读的**（为什么不是「把 26 个语料文件逐个下载」）

逐 PR 先取 `gh pr diff <N> --name-only`（1 次调用）拿到**该 PR 改过的文件路径**，只对其中
`.github/cases/*.yml` 的那些按 **PR ref 读内容**（`gh api …/contents/<path>?ref=<headRefOid>`）。
理由：一个分支的语料 = 「它相对 **merge-base** 没改的文件」（那部分与 main 同源）∪「它改过的文件」，
而未改的那部分**不必下载**。实测：`dependabot/*` 这类**落后的**分支会把 26 个文件全部算成"与 main 不同"
⇒ 逐文件下载要 78 次调用、90 秒都跑不完（**本工具第一版就是这么写的，实测超时**）；
改成本口径后每个 PR 只需 1~2 次调用。

**这条口径的残差（照实登记）**：PR **未改过**的语料文件，本工具按「与 main 同源」处理 ——
若某号曾从 main 上**删掉**、却还留在一个**旧分支**里，本工具会漏掉它。
现取复核（2026-09-27）：`.github/cases/**` 里 `- id:` 行的**删除**历史 **0 次**
（`git log -p -- .github/cases/misc.yml | grep -c '^-[[:space:]]*- id:'` ⇒ `0`）⇒ 该残差**从未发生过**，
**但它不是零**（拿便宜的读法换穷举性，是有意取舍）。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

#: 本模块是「取号」的**唯一实现点**。判据
#: `tests/unit_ci_workflows/test_next_case_id_allocator.py` 按这个记号做**双向**核对
#: （`scripts/**` 里有第二处声明 ⇒ 红；记号被删 ⇒ 红），并另有一条形态指纹普查兜住「不声明也算号」。
ALLOCATION_SITE = "scripts/next_case_id.py"

#: 用例语料目录（仓库相对路径）—— 与 `test_dev_mode_failure_modes.py` 的 `CASE_CORPUS_DIR` 同口径。
CASE_CORPUS_DIR = ".github/cases"

#: 用例号行的**唯一解析口径**。与判据面 `test_dev_mode_failure_modes.py::case_id_lines` 的
#: `^\s*-\s*id:\s*([A-Z]+-\d+)\s*$` 等价 —— 由判据
#: `test_next_case_id_allocator.py::test_parse_agrees_with_the_criterion_side_parser` **在真语料上逐值对账**
#: （两处都留 = 有意取舍：那一条住在判据文件里，改它的爆炸半径比改工具大得多；⇒ **用判据钉住等价**，
#: 而不是把两边耦合成一次 import）。
CASE_ID_LINE_RE = re.compile(r"^\s*-\s*id:\s*([A-Z]+)-(\d+)\s*$", re.MULTILINE)
#: 前缀形态（与语料里的前缀集合一致：`MC` / `UI` / `API` / `PR` …）。
PREFIX_RE = re.compile(r"^[A-Z]{2,4}$")
#: 号的最小值（本仓所有前缀都从 `001` 起）。
MIN_NUMBER = 1

#: `gh` 的**只读白名单**（argv 前缀）。不在表里 ⇒ 工具自己报错，**不发出**这条命令。
GH_READ_ONLY = (("auth", "status"), ("pr", "list"), ("pr", "diff"), ("api",))
#: `gh api` 的写动词 —— 出现即拒绝（默认不带 `--method` = GET）。
GH_WRITE_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})
#: `git` 的**只读白名单**。🔴 `fetch` 刻意不在表里（它会写 `.git` 的 ref ⇒ 违反"零写"）。
GIT_READ_ONLY = ("rev-parse", "ls-tree", "grep", "show", "cat-file")

#: `gh pr list` 的分页上限；取满即认为「可能截断」⇒ fail-closed（不许拿残缺的在飞面给号）。
PR_LIST_LIMIT = 200


class Undecidable(Exception):
    """**无法判定** ⇒ 调用方必须打「不许取号」并 `exit 3`（不得退化成"乐观给号"）。"""


# ─────────────────────────────────────────────────────────────────────────────
# 只读外壳（白名单在这里，不在调用点 —— 判据能机械核这一处）
# ─────────────────────────────────────────────────────────────────────────────
def _gh_bin() -> str:
    return os.environ.get("NCI_GH_BIN") or "gh"


def gh(argv: list[str], allow_404: bool = False) -> str:
    """跑一条**只读** `gh` 命令；非只读形态 ⇒ 立刻抛错（结构性「零写」，不是纪律）。

    `allow_404=True` 表示「该路径在该 ref 上**不存在**是合法读数」（删除 / 改名），返回空串；
    其它错误码照旧 ⇒ `Undecidable`（fail-closed）。
    """
    if not any(tuple(argv[: len(p)]) == p for p in GH_READ_ONLY):
        raise AssertionError(f"拒绝执行非只读 gh 子命令（白名单 = {GH_READ_ONLY}）：{argv}")
    if any(a.upper() in GH_WRITE_METHODS for a in argv):
        raise AssertionError(f"拒绝执行 gh 写动词（{sorted(GH_WRITE_METHODS)}）：{argv}")
    try:
        proc = subprocess.run([_gh_bin(), *argv], capture_output=True, text=True)
    except (FileNotFoundError, OSError) as exc:  # gh 不在 PATH
        raise Undecidable(f"gh 不可用（{exc.__class__.__name__}: {exc}）") from exc
    if proc.returncode != 0:
        if allow_404 and "HTTP 404" in proc.stderr:
            return ""
        raise Undecidable(
            f"gh 命令失败（未登录 / 离线 / API 抖动）rc={proc.returncode}：gh {' '.join(argv)}\n"
            f"    stderr：{proc.stderr.strip()[:400]}"
        )
    return proc.stdout


def git(argv: list[str]) -> str:
    """跑一条**只读** `git` 命令；白名单外 ⇒ 立刻抛错。"""
    if not argv or argv[0] not in GIT_READ_ONLY:
        raise AssertionError(f"拒绝执行非只读 git 子命令（白名单 = {GIT_READ_ONLY}）：{argv}")
    proc = subprocess.run(["git", *argv], capture_output=True, text=True)
    if proc.returncode != 0:
        raise Undecidable(f"git 命令失败 rc={proc.returncode}：git {' '.join(argv)}\n"
                          f"    stderr：{proc.stderr.strip()[:400]}")
    return proc.stdout


# ─────────────────────────────────────────────────────────────────────────────
# 纯函数（判据全部走这里 —— 语料一律**内存构造**，不绑可变引用）
# ─────────────────────────────────────────────────────────────────────────────
def parse_ids(text: str) -> dict[str, set[int]]:
    """`- id: <PREFIX>-NNN` 行 → `{前缀: {号…}}`（唯一解析口径）。"""
    out: dict[str, set[int]] = {}
    for prefix, num in CASE_ID_LINE_RE.findall(text):
        out.setdefault(prefix, set()).add(int(num))
    return out


def merge_ids(*maps: dict[str, set[int]]) -> dict[str, set[int]]:
    """把多个来源的 `{前缀: {号…}}` 并起来（候选集 = 各来源的**并**）。"""
    out: dict[str, set[int]] = {}
    for m in maps:
        for prefix, nums in m.items():
            out.setdefault(prefix, set()).update(nums)
    return out


def min_free(used: set[int]) -> int:
    """**最小空闲号**（不是最大号 + 1）：从 `MIN_NUMBER` 起第一个不在 `used` 里的号。"""
    n = MIN_NUMBER
    while n in used:
        n += 1
    return n


def allocate(occupied: dict[str, set[int]], prefixes: list[str] | None = None) -> dict[str, int]:
    """逐前缀取**最小空闲号**，并在**同一次调用里**断言「返回的号 ∉ 候选集」。

    这个断言是**内在**的（不靠调用方记得核）：它保证「工具给出的号」与「候选集」在语义上
    不可能同时成立 —— 即「工具说空、候选集说占」这种自相矛盾会当场炸，而不是变成下游的撞号。
    """
    keys = sorted(occupied) if prefixes is None else list(prefixes)
    result: dict[str, int] = {}
    for prefix in keys:
        used = occupied.get(prefix, set())
        n = min_free(used)
        assert n not in used, (  # noqa: S101 —— 内在自证：不满足即「工具坏了」，不许静默给号
            f"内在断言失败：{prefix}-{n:03d} 落在候选集里（min_free 与内部记录自相矛盾）"
        )
        result[prefix] = n
    return result


def fmt_ids(nums: set[int]) -> str:
    """把一组号压成可读的区间串（`001-040,043,044,045,047,048`）。"""
    if not nums:
        return "—"
    parts, start, prev = [], None, None
    for n in sorted(nums):
        if start is None:
            start = prev = n
            continue
        if n == prev + 1:
            prev = n
            continue
        parts.append(f"{start:03d}" if start == prev else f"{start:03d}-{prev:03d}")
        start = prev = n
    parts.append(f"{start:03d}" if start == prev else f"{start:03d}-{prev:03d}")
    return ",".join(parts)


def fmt_id_set(nums: set[int]) -> str:
    return ",".join(f"{n:03d}" for n in sorted(nums)) or "—"


# ─────────────────────────────────────────────────────────────────────────────
# 三个候选来源
# ─────────────────────────────────────────────────────────────────────────────
class Source:
    """一个候选来源：`label`（main / PR #NNNN / 工作区）+ 取法命令 + ref + 读数。"""

    def __init__(self, kind: str, label: str, command: str, ref: str, ids: dict[str, set[int]]):
        self.kind, self.label, self.command, self.ref, self.ids = kind, label, command, ref, ids

    def contributed(self, baseline: dict[str, set[int]]) -> dict[str, set[int]]:
        """本来源相对 baseline（main）**新增**的号 —— 证据行只报这部分（main 的号不重复刷屏）。"""
        out: dict[str, set[int]] = {}
        for prefix, nums in self.ids.items():
            extra = nums - baseline.get(prefix, set())
            if extra:
                out[prefix] = extra
        return out


def read_main(ref: str) -> tuple[Source, dict[str, str]]:
    """主线段：`git ls-tree` 取 path→blob sha（给在飞面做逐文件去重）+ `git grep` 一次取全部号。"""
    cmd_tree = f"git ls-tree -r {ref} -- {CASE_CORPUS_DIR}"
    tree = git(["ls-tree", "-r", ref, "--", CASE_CORPUS_DIR])
    blobs = {}
    for line in tree.splitlines():
        meta, _, path = line.partition("\t")
        fields = meta.split()
        if len(fields) >= 3 and path.endswith(".yml"):
            blobs[path] = fields[2]
    sha = git(["rev-parse", ref]).strip()
    grep = git(["grep", "-h", "-E",
                r"^[[:space:]]*-[[:space:]]*id:[[:space:]]*[A-Z]+-[0-9]+[[:space:]]*$",
                ref, "--", CASE_CORPUS_DIR])
    ids = parse_ids(grep)
    total = sum(len(v) for v in ids.values())
    src = Source("main", "main", cmd_tree + f"  ·  git grep … {ref} -- {CASE_CORPUS_DIR}",
                 f"{ref}@{sha[:9]}", ids)
    src.note = f"{len(blobs)} 个文件 · {total} 个号"
    return src, blobs


def read_open_prs(main_blobs: dict[str, str]) -> list[Source]:
    """全部 open PR 的分支：逐个 ref 读 `.github/cases/**` 的 `- id:`（**内容**，不是 diff）。

    读法（见文件头的「在飞面是怎么读的」）：`gh pr diff --name-only` 定出该 PR 改过的语料文件，
    再按 PR ref 逐个读**内容**。`main_blobs` 只用来在证据行里点出「哪些文件与 main 逐 blob 相同」。
    """
    raw = gh(["pr", "list", "--state", "open", "--limit", str(PR_LIST_LIMIT),
              "--json", "number,headRefName,headRefOid,isDraft"])
    try:
        prs = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Undecidable(f"gh pr list 的输出不是 JSON（{exc}）") from exc
    if not isinstance(prs, list):
        raise Undecidable("gh pr list 的输出不是数组")
    if len(prs) >= PR_LIST_LIMIT:
        raise Undecidable(
            f"open PR 数达到上限 {PR_LIST_LIMIT}（可能截断）⇒ 在飞面读不全 ⇒ 不许取号"
        )
    sources: list[Source] = []
    for pr in prs:
        num, ref_name, oid = pr.get("number"), pr.get("headRefName"), pr.get("headRefOid")
        if not num or not oid:
            raise Undecidable(f"gh pr list 返回的条目缺 number/headRefOid：{pr!r}")
        cmd = f"gh pr diff {num} --name-only  ·  gh api repos/{{owner}}/{{repo}}/contents/<path>?ref=<sha>"
        try:
            changed = [ln.strip() for ln in gh(["pr", "diff", str(num), "--name-only"]).splitlines()]
        except Undecidable as exc:
            raise Undecidable(f"PR #{num}（{ref_name}）的改动文件清单读不到 ⇒ 不许取号：{exc}") from exc
        corpus_files = [p for p in changed
                        if p.startswith(CASE_CORPUS_DIR + "/") and p.endswith(".yml")]
        ids: dict[str, set[int]] = {}
        for path in corpus_files:
            body = gh(["api", f"repos/{{owner}}/{{repo}}/contents/{path}?ref={oid}"], allow_404=True)
            if not body:  # 该 ref 上这个文件不存在（删除 / 改名）⇒ 它不再占号
                continue
            try:
                content = json.loads(body)["content"]
                text = base64.b64decode(content).decode("utf-8")
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                raise Undecidable(f"PR #{num} 的 {path} 解不开 ⇒ 不许取号：{exc}") from exc
            for prefix, nums in parse_ids(text).items():
                ids.setdefault(prefix, set()).update(nums)
        src = Source("pr", f"PR #{num}", cmd, f"{ref_name}@{oid[:9]}", ids)
        src.note = (f"本 PR 改动 {len(corpus_files)}/{len(main_blobs)} 个语料文件"
                    f" · 命中 {sum(len(v) for v in ids.values())} 个号")
        if pr.get("isDraft"):
            src.note += " · draft"
        sources.append(src)
    return sources


def read_worktree() -> Source:
    """本工作区（**含未提交**改动）：直接读工作树的语料文件 —— 本地先占的号必须计入。"""
    root = git(["rev-parse", "--show-toplevel"]).strip()
    cmd = f"git rev-parse --show-toplevel  ·  读 {CASE_CORPUS_DIR}/*.yml（工作树，含未提交）"
    ids: dict[str, set[int]] = {}
    n_files = 0
    corpus = os.path.join(root, CASE_CORPUS_DIR)
    for name in sorted(os.listdir(corpus)) if os.path.isdir(corpus) else []:
        if not name.endswith(".yml"):
            continue
        n_files += 1
        with open(os.path.join(corpus, name), encoding="utf-8") as fh:
            for prefix, nums in parse_ids(fh.read()).items():
                ids.setdefault(prefix, set()).update(nums)
    src = Source("worktree", "工作区", cmd, root, ids)
    src.note = f"{n_files} 个文件"
    return src


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def render(sources: list[Source], baseline: dict[str, set[int]], occupied: dict[str, set[int]],
           result: dict[str, int], stamp: str) -> str:
    """人可复算的输出：来源（命令 + ref + 读数）+ 逐前缀「已占来源 → 现取最小空闲号」。"""
    out = [f"🔢 下一个用例号（只读；候选 = main ∪ 全部 open PR 的分支 ∪ 本工作区）",
           f"   时点 {stamp} · 工具 {ALLOCATION_SITE}（取号口径的单一实现）", "",
           "── 候选来源（取法 + ref + 读数）" + "─" * 30]
    for s in sources:
        out.append(f"   [{s.label}] {s.command}")
        out.append(f"        ref={s.ref} ⇒ {getattr(s, 'note', '')}")
    out += ["", "── 分配（最小空闲号；同一次调用里断言「返回的号 ∉ 候选集」）" + "─" * 8]
    for prefix in sorted(result):
        origins = []
        for s in sources:
            extra = s.contributed(baseline) if s.kind != "main" else s.ids
            if extra.get(prefix):
                origins.append(f"{s.label}:{fmt_ids(extra[prefix])}")
        used = occupied.get(prefix, set())
        n = result[prefix]
        # 「最小空闲号」可能落在**历史空档**上（不是尾部顺延）⇒ 显式标出来，取号方自己判断
        # 那个空档是不是「刻意保留 / 已废弃」（工具只保证号没被占用，不保证号在语义上合适）。
        gap = f"（历史空档：< 现取最大号 {max(used):03d}）" if used and n < max(used) else ""
        out.append(f"   {prefix} → {' · '.join(origins) or '（无）'} → 取 {prefix}-{n:03d}{gap}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="next_case_id.py",
        description="取下一个用例号（只读；候选 = main ∪ 全部 open PR 的分支 ∪ 本工作区）",
    )
    parser.add_argument("prefix", nargs="?", help="可选前缀（如 MC / UI / BM）；缺省打印全部前缀")
    args = parser.parse_args(argv)
    prefix = args.prefix.upper() if args.prefix else None
    if prefix is not None and not PREFIX_RE.match(prefix):
        print(f"❌ 前缀形态不合法：{args.prefix!r}（要 2~4 个大写字母，如 MC / UI / BM）", file=sys.stderr)
        return 2
    ref = os.environ.get("NCI_MAIN_REF") or "origin/main"
    stamp = datetime.now(timezone.utc).astimezone().strftime("%F %T %z")
    try:
        main_src, main_blobs = read_main(ref)
        sources = [main_src, *read_open_prs(main_blobs), read_worktree()]
    except Undecidable as exc:
        print("❌ 无法判定 ⇒ 不许取号")
        print(f"   原因：{exc}")
        print("   出口：① 确认 `gh auth status` 正常且能连到 GitHub；② 若只是某个 PR 读不到，"
              "把它的分支 fetch 到本地后重跑；③ 都做不到 ⇒ **手工**按 `migao-dev-flow` §26.3 的在飞面清单核一遍，"
              "**不要**凭「我看到的最大号 + 1」取号（那正是撞号的成因）。")
        return 3
    baseline = main_src.ids
    occupied = merge_ids(baseline, *(s.ids for s in sources[1:]))
    if prefix is not None:
        occupied = {prefix: occupied.get(prefix, set())}
    result = allocate(occupied, [prefix] if prefix else None)
    if not result:
        print("❌ 无法判定 ⇒ 不许取号\n   原因：候选集里一个前缀都没有（main 侧语料为空？）")
        return 3
    print(render(sources, baseline, occupied, result, stamp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
