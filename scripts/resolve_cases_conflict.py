#!/usr/bin/env python3
"""resolve_cases_conflict.py — `.github/cases/*.yml` 合并冲突的**唯一解法**（`migao-dev-flow` §34.15）。

## 病（2026-11-05 一晚实测 8+ 次手写同一段脚本，不是推演）

`.github/cases/*.yml` 是**单一共享写面**：每个包都在文件**末尾**追加自己的 case 块
⇒ **main 一前进，所有在飞分支都冲突**（生成物已按 #8704 出库，但**源文件仍是共享写面**）。
一晚手写了 8 次以上同一段 Python，每次都踩同一批坑：

| # | 坑 | 后果 |
|---|---|---|
| 1 | **用字符串比较号段**（`cid >= "MC-221"`） | 误抓 `PK-*` / `SP-*` / `WH-*` / `QC-*`（`"PK" > "MC"`）⇒ 把别人的块追加一遍 |
| 2 | 抓到的块**残缺** | `render_cases.py` 抛 `KeyError: 'title'`，而报错指向渲染器、不指向你写的那一行 |
| 3 | 忘了重建后跑 `generated_artifacts_freshness.py --write` | 生成物陈旧 ⇒ CI 判红（红的信息指向生成物，不指向你改的块） |
| 4 | 重建后**没验证**「main 的 id 集合 ⊆ 结果」+「无重复 id」 | 静默丢 main 的用例 / 留下重复块（§34.1 第三条，今晚三次救场） |

### 坑 2 的真正成因（本次实测，写在这里防下一次误判）

按「从**工作树**的冲突文件里按行区间取块」会**结构性**产生残缺块：git 把两侧的追加区
按**公共行**对齐，常见形态是**拆成多个冲突 hunk**（实测 fixture：`- id:` / `legacy_id:` /
`title:` 落在第一个 hunk，`user_inputs:` 之后落在第二个）⇒ 块在第一个 `=======` 处被截断
成「只有 id + title 的半块」，**而 `title:` 检查会通过** ⇒ 写出一份看起来合法、实际半截的用例。
⇒ 本工具**不读工作树的那份带标记文件**，改读索引里**双方各自的完整体**
（`git show :2:<path>` / `:3:<path>` = 未冲突的一侧），从根上消掉这个形态。

## 算法（三步，全部机械）

1. **重建**（对每个 `git diff --name-only --diff-filter=U -- '.github/cases/*.yml'` 命中的文件）：
   - **底 = `git show <base>:<path>`**（`<base>` 缺省 `origin/main`）—— **main 是唯一真值基线**；
   - 两方的完整体 = 索引 stage 2 / 3（merge 时 `:2:` = 本分支；rebase 时本分支在 `:3:`
     ⇒ **两侧都取**，不猜「哪一侧是我」，凡不在 main 里的块都必须留在结果里）；
   - **本分支独有的 case 块** = （两侧 id 并集）**减去** main 侧的 id 集合
     ⚠️ **集合差，不是字符串比较号段**（号段比较会按字典序误抓别的前缀）；
     按 `<前缀>-<数字>` **解析后按前缀分组、按数字排序**；块按**行区间**提取
     （`- id: <X>` → 下一个 `- id:` 之前；同时以冲突标记为兜底边界）；
   - **完整性**：块里必须有 `title:`，否则**不追加**、非零退出并点名该 id；
   - **输出** = main 的全文 + 追加块（块之间一个空行）。
2. **重建后自动校验**（任一不过 ⇒ **不写文件**、非零退出）：
   `yaml.safe_load` 能解析 · 无重复 id · main 的 id 集合 ⊆ 结果 ·
   本分支独有的 id 全在结果里 · 条数 = main 条数 + 追加块数 · 结构解析与 YAML 解析的 id 序列一致。
3. **写完后跑生成物刷新**（`scripts/generated_artifacts_freshness.py --write`），
   失败则**回滚文件**（逐字节还原）并非零退出。

## 用法

```bash
python3 scripts/resolve_cases_conflict.py                 # 重建当前所有冲突的 cases 文件（默认）
python3 scripts/resolve_cases_conflict.py --check         # 只报不改（CI / 预检）
python3 scripts/resolve_cases_conflict.py --base origin/main
python3 scripts/resolve_cases_conflict.py --no-generate   # 跳过第 3 步（夹具 / 临时仓）
```

## 三态退出码（与 `scripts/next_case_id.py` / `scripts/merge_gate.py` 同口径）

| 码 | 含义 |
|---|---|
| `0` | 冲突已机械解开（`--check` = 判定「可机械解」或「当前没有 cases 冲突」） |
| `1` | **有问题**：残缺块 / 重号 / 会丢 main 的 id / 生成物刷新失败（文件已回滚） |
| `3` | **无法判定**：`git` 不可用 / 取不到 main 基线 / 环境缺 PyYAML（**不是通过**，fail-closed） |

## 有意不做（边界，照实登记 §19.1）

- **只做「追加」**：本分支**改动**（modify/modify）main 已有块的冲突**拒绝机械解**并点名该 id
  —— 那需要逐块看双方语义，正是「整文件取自己那版会静默回退别人的修复」（§34.3 第 3 条）的现场。
  delete/modify 这类「索引里少一个 stage」的冲突同样拒绝。
- **不动索引**：不 `git add`。写完打印下一步命令 —— 回滚语义因此是干净的
  （文件字节回滚即完整回滚，索引仍是冲突态）。
- 不猜「哪个块算我的」：判据只有一条 —— **id 集合差**。
- 不处理「main 删了某条用例、而本分支还留着它」：那会被当成「不在 main 里的块」追加回去。
  本工具只保证 main ⊆ 结果，**不保证 main 的删除被继承**（这类冲突请人工看）。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple, Sequence

CASES_GLOB = ".github/cases/*.yml"
DEFAULT_BASE = "origin/main"
GENERATOR_REL = "scripts/generated_artifacts_freshness.py"

RC_OK, RC_PROBLEM, RC_UNDECIDABLE = 0, 1, 3

#: 冲突标记（git 一律写在**第 0 列**；`|||||||` = diff3 的公共祖先段）。
#: 块区间以它为兜底边界：即使某天有人把带标记的文件喂进来，也不会把别人的行吞进块里。
_MARKERS = ("<<<<<<<", "|||||||", "=======", ">>>>>>>")

#: 块头：`  - id: MC-221`（缩进随文件，不写死 2 空格）
_ID_RE = re.compile(r"^(?P<indent>[ \t]*)-\s+id:\s*(?P<cid>[^\s#]+)")
#: 块内**必须**有的字段（`title: >` 这种块标量头也算 —— 后面还有内容行）。
#: 只收 `title:` + `user_inputs:` 两个：**现取语料实测**（2026-11-05，`origin/main` 的 257 条）
#: `title:` 缺 0 条、`user_inputs:` 缺 0 条，而 `expectations:` **有 1 条**合法缺（`MC-139`）⇒
#: 收 `expectations:` 会把合法块判成残缺（假红）。
#: 🔴 **两个字段而不是一个**：git 按公共行对齐会拆多 hunk（`migao-dev-flow` §34.16 ③）⇒
#: 「id + legacy_id + title」这种半块**含 `title:` 但丢了后面一切**，只查 `title:` 照样放行。
_REQUIRED_FIELDS = ("title", "user_inputs")
# ⚠️ **刻意不用正则解析 id**（`str.rpartition` 就够）：本仓 `scripts/**` 里「用例号形态的
# 正则字面量 + 号空间后继运算」是**第二份算号实现**的指纹（判据 =
# `tests/unit_ci_workflows/test_next_case_id_allocator.py::test_only_one_allocation_implementation_in_scripts`）。
# 本工具**不算号**（唯一与号相关的动作是**报错时叫人去** `scripts/next_case_id.py` 让号）⇒
# 不写那种正则就不进指纹面，也不必去动那份「取号实现点」冻结台账（那本账只登记**真的**算号器）。


class Block(NamedTuple):
    """一个 case 块：`cid` + **原文行区间**（去掉尾部空行，保留缩进）。"""

    cid: str
    text: str


class Plan(NamedTuple):
    """一个文件的处置方案（`--check` 只打印它，不落盘）。"""

    rel: str
    main_text: str
    original: bytes
    blocks: list[Block]
    result: str
    problems: list[str]


# ═══════════════════════════════════════════════════════════════════════════
# 一、结构解析（零依赖：行区间 + 前缀/数字）
# ═══════════════════════════════════════════════════════════════════════════


def _is_marker(line: str) -> bool:
    return line.startswith(_MARKERS)


def parse_blocks(text: str) -> list[Block]:
    """把文件文本切成 case 块（**行区间**，不是 AST）。

    区间终点 = 下一个 `- id:` 行 **或** 冲突标记（谁先到谁算），尾部空行去掉
    —— 追加时要「块之间一个空行」，靠的就是这里不留尾空行。
    """
    lines = text.splitlines()
    heads = [(i, m.group("cid")) for i, ln in enumerate(lines) if (m := _ID_RE.match(ln))]
    blocks: list[Block] = []
    for pos, (start, cid) in enumerate(heads):
        stop = heads[pos + 1][0] if pos + 1 < len(heads) else len(lines)
        for j in range(start + 1, stop):
            if _is_marker(lines[j]):
                stop = j
                break
        body = lines[start:stop]
        while body and not body[-1].strip():
            body.pop()
        blocks.append(Block(cid, "\n".join(body)))
    return blocks


def ids_in_order(text: str) -> list[str]:
    return [b.cid for b in parse_blocks(text)]


def split_case_id(cid: str) -> tuple[str, int] | None:
    """把 `MC-041` 解析成 `("MC", 41)`（`<前缀>`、`<数字>`）；解析不了 ⇒ `None`。

    解析得通才能**按前缀分组、组内按数字**排序 —— 直接比字符串会按字典序把
    `MC-1000` 排到 `MC-999` 前面，也会把 `PK-*` 排在 `MC-*` 之后当成「更大的号段」。
    """
    prefix, sep, digits = cid.rpartition("-")
    if not sep or not prefix or not digits.isdigit():
        return None
    return prefix, int(digits)


def case_sort_key(cid: str) -> tuple[int, str, int, str]:
    """**按 `<前缀>-<数字>` 解析后**排序：先前缀分组，组内按数字。

    不可解析的 id 排在解析得通的后面（按字面），**绝不**因此被丢掉 —— 丢 id 会被
    `check_document` 抓住，但排序本身不该制造丢件。
    """
    parts = split_case_id(cid)
    if parts is None:
        return (1, cid, 0, cid)
    return (0, parts[0], parts[1], cid)


def prefix_counts(ids: Sequence[str]) -> dict[str, int]:
    """按前缀分组计数（报告用：一眼看出「我的块属于哪个前缀、会不会抓错别的前缀」）。"""
    out: dict[str, int] = {}
    for cid in ids:
        parts = split_case_id(cid)
        key = parts[0] if parts else cid
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


# ═══════════════════════════════════════════════════════════════════════════
# 二、选块 + 拼装 + 校验（纯函数：判据直接喂合成语料）
# ═══════════════════════════════════════════════════════════════════════════


def _has_field(text: str, field: str) -> bool:
    """块里有没有 `field:`（值可以另起行 —— 块标量头 `title: >` 也算有）。"""
    # 冒号后可以**为空**（`user_inputs:` 的值在下一行的列表项里）⇒ 只判键行在不在
    return re.search(rf"^[ \t]+{re.escape(field)}:", text, re.MULTILINE) is not None


def select_unique(main_ids: Sequence[str], side_blocks: Sequence[Block]) -> list[Block]:
    """**本分支独有**的块 = id **不在 main 集合里**的块。

    ⚠️ 这是本工具最容易被写错的一行（也是它存在的第一个理由）：
    历史写法是**字符串比较号段**（`cid >= "MC-221"`），而 id 是 `<前缀>-<数字>` 形态
    ⇒ 字典序会按**前缀**分段（`"PK" > "MC"`），把 `PK-*` / `SP-*` / `WH-*` / `QC-*`
    **整块误抓**成「我的」并追加一遍。判据 = 集合差，**没有任何号段阈值**。
    """
    main_set = set(main_ids)
    return [b for b in side_blocks if b.cid not in main_set]


def select_branch_blocks(main_text: str,
                         sides: Sequence[tuple[str, str]]) -> tuple[list[Block], list[str]]:
    """挑出**不在 main 里**的 case 块（= 两侧 id 并集 **减去** main id 集合）。

    `sides` = `[(来源名, 该侧完整体文本)]`（索引 stage 2 / 3；夹具直接给干净文本）。
    返回 `(按前缀分组 / 组内按数字排序的块列表, 问题列表)`；有问题时**调用方不许落盘**。

    四条拒绝（都是真实踩过的形态）：

    1. 同一 id 在两侧给出了**不同**的块 ⇒ 无法判定该用哪份（§34.1 坑 3：重放产生重复块）；
    2. 本分支/对侧**改动**了 main 已有的块（modify/modify）⇒ 只做追加，语义合并必须人工；
    3. 块残缺（没有 `title:`）⇒ 点名 id（坑 2：`KeyError: 'title'`）；
    4. 底（main）自身重复 id ⇒ 不猜该保留哪一条。
    """
    problems: list[str] = []
    main_blocks = parse_blocks(main_text)
    main_ids = [b.cid for b in main_blocks]
    main_set = set(main_ids)
    main_by_id = {b.cid: b.text for b in main_blocks}

    dup_main = sorted({c for c in main_ids if main_ids.count(c) > 1})
    if dup_main:
        problems.append(
            f"底（main）自身含重复 id：{', '.join(dup_main)} ⇒ 本工具不猜该保留哪一条，先修 main")

    picked: dict[str, Block] = {}
    changed: list[str] = []
    for label, text in sides:
        side_blocks = parse_blocks(text)
        for block in side_blocks:
            if (block.cid in main_set and block.text != main_by_id[block.cid]
                    and block.cid not in changed):
                changed.append(block.cid)
        # ① **集合差**（不是 `cid >= "MC-221"`：见 `select_unique` 的 docstring）
        for block in select_unique(main_ids, side_blocks):
            seen = picked.get(block.cid)
            if seen is not None and seen.text != block.text:
                problems.append(
                    f"`{block.cid}` 在两侧是**两份不同**的块（{label} 与另一侧）⇒ 无法判定该用哪一份"
                    "（重复块是重建类器具的已知坑，§34.1）⇒ 先人工去重")
                continue
            picked.setdefault(block.cid, block)

    if changed:
        problems.append(
            f"改动了 main 已有的 case 块：{', '.join(changed)} ⇒ 本工具只做「追加」，"
            "这种 modify/modify 冲突必须人工逐块合并（整文件取自己那版会静默回退别人的修复）")

    # ② 完整性：必需字段必须在场（不止 `title:` —— 半块含 title 却丢其余，见 §34.16 ③）
    for block in picked.values():
        missing = [f for f in _REQUIRED_FIELDS if not _has_field(block.text, f)]
        if missing:
            problems.append(
                f"`{block.cid}` 的块缺 {' / '.join('`' + f + ':`' for f in missing)}"
                "（残缺块不追加 —— 追加会在渲染时抛 KeyError，或写进一条只有 id 的幽灵用例）"
                "⇒ 请把该 case 块补全后再跑")

    blocks = sorted(picked.values(), key=lambda b: case_sort_key(b.cid))
    return blocks, problems


def build_document(main_text: str, blocks: Sequence[Block]) -> str:
    """`main 的全文` + 追加块（**块之间一个空行**）。"""
    head = main_text.rstrip("\n")
    if not blocks:
        return head + "\n"
    return head + "\n\n" + "\n\n".join(b.text.strip("\n") for b in blocks) + "\n"


def _load_yaml(text: str) -> tuple[dict | None, str | None]:
    """`yaml.safe_load`（缺 PyYAML ⇒ 返回「不可判定」，**不许**降级成宽松解析）。"""
    try:
        import yaml
    except ImportError:
        return None, ("本环境没有 PyYAML ⇒ 无法做 `yaml.safe_load` 校验"
                      "（三态 3：无法判定，不是通过）")
    try:
        doc = yaml.safe_load(text)
    except Exception as exc:                                    # noqa: BLE001 —— 任何解析失败都是问题
        return None, f"`yaml.safe_load` 解析失败：{exc}"
    if not isinstance(doc, dict) or not isinstance(doc.get("cases"), list):
        return None, ("解析结果不是 mapping，或 `cases` 不是列表 ⇒ 不是合法的用例文件")
    return doc, None


def check_document(main_text: str, blocks: Sequence[Block], result_text: str) -> list[str]:
    """重建后的**五条校验**（任一不过 ⇒ 调用方不写文件、非零退出）。

    1. `yaml.safe_load` 能解析；2. 无重复 id；3. main 的 id 集合 ⊆ 结果；
    4. 本分支独有的 id 全在结果；5. 条数 = main 条数 + 追加块数。
    """
    problems: list[str] = []
    main_ids = ids_in_order(main_text)
    block_ids = [b.cid for b in blocks]
    result_ids = ids_in_order(result_text)
    result_set = set(result_ids)

    lost = [c for c in main_ids if c not in result_set]
    if lost:
        tail = " …" if len(lost) > 10 else ""
        problems.append(f"丢了 main 的 {len(lost)} 个 id：{', '.join(lost[:10])}{tail}"
                        " ⇒ 拒绝写入（main ⊆ 结果 是硬条件）")

    missing = [c for c in block_ids if c not in result_set]
    if missing:
        problems.append(f"丢了本分支独有的 {len(missing)} 个 id：{', '.join(missing)}"
                        " ⇒ 拒绝写入（自己的块也不许丢）")

    dups = sorted({c for c in result_ids if result_ids.count(c) > 1})
    if dups:
        problems.append(f"结果含重复 id：{', '.join(dups)} ⇒ 重号必须**让号**"
                        "（`python3 scripts/next_case_id.py <前缀>`）后再重建")

    clash = [c for c in block_ids if c in set(main_ids)]
    if clash:
        problems.append(f"追加块的 id 已在 main 里：{', '.join(clash)} ⇒ 这是**重号**，不是新用例；"
                        "别让工具猜、去让号（`python3 scripts/next_case_id.py <前缀>`）")

    expected = len(main_ids) + len(block_ids)
    if len(result_ids) != expected:
        problems.append(f"条数不符：main {len(main_ids)} + 追加 {len(block_ids)} = {expected}，"
                        f"结果却是 {len(result_ids)} ⇒ 拒绝写入")

    doc, err = _load_yaml(result_text)
    if err:
        problems.append(err)
    else:
        yaml_ids = [str(c.get("id") or "") for c in doc["cases"] if isinstance(c, dict)]
        if yaml_ids != result_ids:
            problems.append(
                f"结构解析与 YAML 解析的 id 序列不一致（结构 {len(result_ids)} 条 / YAML "
                f"{len(yaml_ids)} 条）⇒ 行区间口径已漂移，拒绝写入")
    return problems


# ═══════════════════════════════════════════════════════════════════════════
# 三、git 读面（只读：`show` / `diff` / `rev-parse`，不写 .git、不动索引）
# ═══════════════════════════════════════════════════════════════════════════


def _git(repo: Path, *args: str) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    except FileNotFoundError:
        return 127, "", "git 不可用"
    return (proc.returncode,
            proc.stdout.decode("utf-8", "replace"),
            proc.stderr.decode("utf-8", "replace"))


def repo_root() -> Path | None:
    rc, out, _ = _git(Path.cwd(), "rev-parse", "--show-toplevel")
    return Path(out.strip()) if rc == 0 and out.strip() else None


def unmerged_case_files(repo: Path) -> list[str]:
    """`git diff --name-only --diff-filter=U -- '.github/cases/*.yml'`（仓相对路径）。"""
    rc, out, err = _git(repo, "diff", "--name-only", "--diff-filter=U", "--", CASES_GLOB)
    if rc != 0:
        raise RuntimeError(f"`git diff --diff-filter=U` 失败（rc={rc}）：{err.strip()}"
                           "⇒ 无法判定当前冲突面")
    return [ln.strip() for ln in out.splitlines() if ln.strip().endswith(".yml")]


def base_text(repo: Path, base: str, rel: str) -> str | None:
    """`git show <base>:<path>` —— **main 是唯一真值基线**；取不到 ⇒ None（不可判定）。"""
    rc, out, _ = _git(repo, "show", f"{base}:{rel}")
    return out if rc == 0 else None


def side_texts(repo: Path, rel: str) -> tuple[list[tuple[str, str]], list[str]]:
    """索引里**双方各自的完整体** `:2:` / `:3:`（未冲突的一侧）。

    ⚠️ **不读工作树的带标记文件**（见模块 docstring：git 会把追加区拆成多个 hunk，
    按行区间从带标记文件取块会得到**被 `=======` 截断的半块**，而 `title:` 检查照样通过）。
    merge 时本分支在 `:2:`、rebase 时在 `:3:` ⇒ **两侧都取**，不猜哪一侧是「我」：
    凡不在 main 里的块都必须留在结果里，这本来就是「保住双方」的正确语义。
    """
    problems: list[str] = []
    stages: dict[int, str] = {}
    for stage in (2, 3):
        rc, out, _ = _git(repo, "show", f":{stage}:{rel}")
        if rc == 0:
            stages[stage] = out
    if len(stages) < 2:
        problems.append(
            f"索引里只有 {len(stages)} 个 stage（{sorted(stages) or '无'}）⇒ delete/modify 这类"
            "「少一侧」的冲突本工具不机械解，请人工处理")
    return [(f"stage{n}", stages[n]) for n in sorted(stages)], problems


# ═══════════════════════════════════════════════════════════════════════════
# 四、编排：plan → （校验）→ 落盘 → 生成腿 → 失败回滚
# ═══════════════════════════════════════════════════════════════════════════


def make_plan(repo: Path, rel: str, base: str) -> Plan | None:
    """算出一个文件的处置方案；底取不到 ⇒ None（调用方判 3）。"""
    main = base_text(repo, base, rel)
    if main is None:
        return None
    path = repo / rel
    original = path.read_bytes() if path.is_file() else b""
    sides, problems = side_texts(repo, rel)
    blocks: list[Block] = []
    if not problems:
        blocks, problems = select_branch_blocks(main, sides)
    result = build_document(main, blocks)
    if not problems:
        problems = check_document(main, blocks, result)
    return Plan(rel, main, original, blocks, result, problems)


def _report(plan: Plan, base: str) -> None:
    main_ids = ids_in_order(plan.main_text)
    added = [b.cid for b in plan.blocks]
    print(f"\n── {plan.rel} ─────────────────────────────────────────────")
    print(f"   底（{base}）：{len(main_ids)} 条 · 前缀 {prefix_counts(main_ids)}")
    if added:
        print(f"   本分支独有（按前缀分组 / 组内按数字排序）：{len(added)} 条")
        print(f"     分组 {prefix_counts(added)}")
        print(f"     依次 {', '.join(added)}")
    else:
        print("   本分支独有：0 条")
    if plan.problems:
        for p in plan.problems:
            print(f"   ✗ {p}")
    else:
        print(f"   ✓ 重建结果可写：{len(ids_in_order(plan.result))} 条"
              f"（= main {len(main_ids)} + 追加 {len(added)}）")


def _regenerate(repo: Path, generator: Path) -> tuple[int, str]:
    """第 3 步：`generated_artifacts_freshness.py --write`（失败 ⇒ 调用方回滚）。"""
    cmd = [sys.executable, str(generator), "--write", "--repo", str(repo)]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    return proc.returncode, (proc.stdout + proc.stderr).decode("utf-8", "replace")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="`.github/cases/*.yml` 合并冲突的一键解法："
                    "以 main 为底 + 追加不在 main 里的块 + 校验 + 刷新生成物")
    ap.add_argument("--repo", default="", help="仓根（缺省 = 当前 git 仓库根）")
    ap.add_argument("--base", default=DEFAULT_BASE,
                    help=f"真值基线 ref（缺省 {DEFAULT_BASE}；main 是唯一真值基线）")
    ap.add_argument("--check", action="store_true", help="只报不改（CI / 预检）")
    ap.add_argument("--no-generate", action="store_true",
                    help=f"跳过第 3 步（{GENERATOR_REL} --write）—— 夹具 / 临时仓用")
    ap.add_argument("--generator", default="",
                    help=f"生成器路径（缺省 <repo>/{GENERATOR_REL}；红证用它替身失败）")
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve() if args.repo else repo_root()
    if repo is None:
        print("✗ 取不到 git 仓库根 ⇒ 无法判定（三态 3）")
        return RC_UNDECIDABLE

    try:
        files = unmerged_case_files(repo)
    except RuntimeError as exc:
        print(f"✗ {exc}（三态 3）")
        return RC_UNDECIDABLE

    if not files:
        print(f"✓ 当前没有未解决的 `.github/cases/*.yml` 冲突"
              f"（git diff --diff-filter=U 为空）· repo={repo} · base={args.base}")
        return RC_OK

    plans: list[Plan] = []
    undecidable: list[str] = []
    for rel in files:
        plan = make_plan(repo, rel, args.base)
        if plan is None:
            undecidable.append(rel)
            continue
        plans.append(plan)
        _report(plan, args.base)

    if undecidable:
        for rel in undecidable:
            print(f"\n✗ {rel}：`git show {args.base}:{rel}` 取不到底 ⇒ 无法判定"
                  "（add/add 或基线 ref 不存在；本工具不机械解，先确认基线）")
        return RC_UNDECIDABLE

    bad = [p for p in plans if p.problems]
    if bad:
        print(f"\n✗ {len(bad)}/{len(plans)} 个文件**未通过校验** ⇒ 一个字都没写（fail-closed）。")
        print("   修法：按上面具名的问题逐条修"
              "（残缺块补 title / 重号让号 / modify-modify 人工合并）")
        return RC_PROBLEM

    if args.check:
        print(f"\n✓ --check：{len(plans)} 个冲突文件都可机械解（未写任何文件）")
        return RC_OK

    written: list[tuple[Path, Plan]] = []
    for plan in plans:
        path = repo / plan.rel
        path.write_bytes(plan.result.encode("utf-8"))
        written.append((path, plan))
        print(f"✎ 写入 {plan.rel}：{len(plan.original)} → {len(path.read_bytes())} 字节")

    def _rollback() -> None:
        for path, plan in written:
            path.write_bytes(plan.original)

    if not args.no_generate:
        generator = Path(args.generator) if args.generator else repo / GENERATOR_REL
        if not generator.is_file():
            _rollback()
            print(f"✗ 生成器不存在：{generator} ⇒ 已回滚（三态 3：无法判定生成物是否新鲜）")
            return RC_UNDECIDABLE
        rc, out = _regenerate(repo, generator)
        if rc != 0:
            _rollback()
            print(f"✗ 生成物刷新失败（rc={rc}）⇒ **已回滚**（文件逐字节还原到写前）")
            for line in out.strip().splitlines()[-15:]:
                print(f"   │ {line}")
            return RC_PROBLEM
        print(f"✓ 生成物已刷新（{GENERATOR_REL} --write，rc=0）")

    print("\n✓ 冲突已机械解开。下一步（本工具**不动索引**）：")
    for path, _plan in written:
        print(f"   git add {path.relative_to(repo)}")
    print("   git commit --no-edit        # merge 收尾；rebase 用 `git rebase --continue`")
    return RC_OK


if __name__ == "__main__":                                  # pragma: no cover
    sys.exit(main())
