# case_ids: MC-209
"""类级判据：**任何入库文件都不许含合并冲突标记**。

## 为什么要有这条（2026-11-05 实测，同一形态一晚上咬三次）

`git merge` 留下的 `<<<<<<<` / `=======` / `>>>>>>>` 是**语法有效但语义有毒**的内容：

1. **YAML 里** ⇒ `ScannerError`（我在重建 `.github/cases/misc.yml` 时用正则抠了自己的用例块，
   把 `=======` 一起带进文件）；
2. **JSON 里** ⇒ `json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes`
   （`case_machine_fail_channel_baseline.json` 两侧都追加了 `history` 行 ⇒ 自动合并把冲突留在文件里，
   CI 的红是**另一个测试**在解析 JSON 时报出来的 —— 症状与病因隔了三层）；
3. **代码里** ⇒ 有时甚至能「编译通过」（`<<<<<<< HEAD` 恰好落进注释或字符串）。

⇒ 它是**跨语言、跨文件类型**的一类缺陷，而现在没有任何常驻判据按**文件内容**扫它。
本仓 `scripts/sync-main.sh` 只在自己的解析流程里检查（`CHANGELOG.md` 自动解冲突那一段），
**没有**一条在 PR 上跑的全树判据 ⇒ 冲突标记可以一路进 main。

## 判据（会红）

扫 `git ls-files` 的**全部入库文件**，含三标记之一（行首起 7 个同字符 + 空格/换行）⇒ 红并具名「文件:行号」。

**边界（有意不扫的东西，照实登记）**：
- **本文件自己**必须豁免 —— 否则它一写下这些标记就自我判红（`SELF` 常量集中放，改一处即可）；
- 二进制文件跳过（按 NUL 字节判定），不做编码猜测；
- **允许出现在文档/测试里被当作字符串讨论**的情形 ⇒ 用**转义写法**（`<` × 7 拆段拼接）而不是明文，
  这条约束本身就是本判据的用法说明：要谈标记，就别写出标记。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: 本判据自己的路径（豁免面**只此一处**，让它极度显眼：想放宽必须改这里）。
SELF = "tests/unit_ci_workflows/test_no_conflict_markers_in_tree.py"

#: 四种标记的**行首前缀**（diff3 的 `|||||||` 一并覆盖）。拆段拼接：本文件不写出明文标记。
_LT = "<" * 7
_EQ = "=" * 7
_GT = ">" * 7
_PIPE = "|" * 7
MARKERS = (_LT, _EQ, _GT, _PIPE)


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout
    return [p for p in out.decode("utf-8", "surrogateescape").split("\0") if p]


def _is_binary(raw: bytes) -> bool:
    return b"\0" in raw[:8192]


def _marker_hits(path: str) -> list[str]:
    raw = (ROOT / path).read_bytes()
    if _is_binary(raw):
        return []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return []
    hits: list[str] = []
    for no, line in enumerate(text.splitlines(), start=1):
        head = line[: len(_LT)]
        if head in MARKERS and (len(line) == len(head) or line[len(head)] in " \t"):
            hits.append(f"{path}:{no}")
    return hits


def test_no_tracked_file_contains_merge_conflict_markers() -> None:
    offenders: list[str] = []
    scanned = 0
    for path in _tracked_files():
        if path == SELF:
            continue
        if not (ROOT / path).is_file():
            continue
        scanned += 1
        offenders.extend(_marker_hits(path))
    # 判据自己不能空转：扫不到文件 ⇒ 这条守着一片不存在的语料
    if scanned == 0:
        offenders.append("扫到的入库文件数为 0 ⇒ 判据失明（git ls-files 至少数百个）")
    assert offenders == [], (
        "发现合并冲突标记（入库文件不许含 `<`×7 / `=`×7 / `>`×7 / `|`×7 行首标记）：\n"
        + "\n".join(f"  · {o}" for o in offenders[:40])
    )
