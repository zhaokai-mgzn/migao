# case_ids: PG-058
"""`set_overview` 的**逐字形状**在仓里有**两处真值源** ⇒ 必须逐字一致（issue #5685 的类级固化）。

## 病根（本守卫的由来，实测）

`set_overview.positions[]` 的形状在仓里被**逐字写了两份**：

① **契约台账** `docs/wiki/CONTRACT-LEDGER.md`（「扫码解析 + 工序推断」那一行）；
② **行为用例** `.github/cases/processing-order.yml`（`PG-058` 的 data_check）。

2026-09-27 给 `positions[]` 追加 `remark`（issue #5685）时，**两处都改才对齐**；而实测：
**只改一处不会有任何东西变红**（`test_contract_ledger_reject_codes.py` / `truths.py` / Case Trust 全绿）
⇒ 真值源静默漂移 —— 正是本仓最忌讳的形态（**绿了，但两份真相**）。

⇒ 本守卫把这条「两处副本」钉成机械判据：**键序列表逐字相等**（顺序也算 —— 它是契约形状，不是集合）。
Java 侧的实现键集另由 `ProcessingSetReadServiceTest.POSITION_KEYS` 钉（`positions[]` 的键集冻结，
新增/删除键都会红），两侧合起来才是完整闭环。

## 自证（防空跑）

两处**任一缺席** ⇒ fail-closed 判红（不许把「形状被删了」读成「一致」）；解析器的判别力由
`test_guard_detects_injected_drift` 用注入串证明。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LEDGER = REPO / "docs/wiki/CONTRACT-LEDGER.md"
CASES_DIR = REPO / ".github/cases"

#: `set_overview` 的逐字形状（只吃 `positions[]` 那一层；内层 `operations[]` 另有
#: `ProcessingSetReadServiceTest.OPERATION_KEYS` 钉，不在此重复）。
SHAPE_RE = re.compile(
    r"set_overview = \{set_no, set_index, positions:\[\{(?P<keys>[^}]*)\}")


def shape_key_lists(text: str) -> list:
    """文本里每一处逐字形状的 `positions[]` **键序**（纯函数，供注入自证复用）。

    ⚠️ 只在 `positions[]` 这一层切分：`operations:[{…}]` 是**内层**（另由
    `ProcessingSetReadServiceTest.OPERATION_KEYS` 钉），在此截断 —— 否则内层键会被并进本层。
    """
    out = []
    for match in SHAPE_RE.finditer(text):
        raw = match.group("keys").split("operations:[{")[0]
        out.append(tuple(key.strip() for key in raw.split(",") if key.strip()))
    return out


def ledger_shape_key_lists() -> list:
    """台账里的逐字形状（按行号顺序）。"""
    return shape_key_lists(LEDGER.read_text(encoding="utf-8"))


def case_shape_key_lists() -> list:
    """用例库里的逐字形状 → `[(文件名, 键序), …]`（按文件名排序）。"""
    out = []
    for path in sorted(CASES_DIR.glob("*.yml")):
        out += [(path.name, keys) for keys in shape_key_lists(path.read_text(encoding="utf-8"))]
    return out


def test_both_truth_sources_declare_the_shape():
    """fail-closed：两处**都必须**有逐字形状（缺席 ⇒ 判据会空跑，不许读成「一致」）。"""
    ledger = ledger_shape_key_lists()
    cases = case_shape_key_lists()
    assert ledger, (
        "`docs/wiki/CONTRACT-LEDGER.md` 里找不到 `set_overview` 的逐字形状 "
        "（`set_overview = {set_no, set_index, positions:[{…}`）⇒ 本判据会空跑："
        "形状被删/改写成散文了？")
    assert cases, (
        "`.github/cases/*.yml` 里找不到 `set_overview` 的逐字形状 ⇒ 本判据会空跑："
        "用例里的形状被删/改写成散文了？")


def test_shape_is_identical_across_truth_sources():
    """判据：台账 ↔ 用例库 的 `positions[]` 键序**逐字相等**（多一个/少一个/换序都红）。"""
    ledger = ledger_shape_key_lists()
    cases = case_shape_key_lists()
    assert len(set(ledger)) == 1, (
        f"台账里出现了**多份不同**的 `set_overview` 形状：{sorted(set(ledger))} "
        "—— 同一形状在台账内部就不一致（先对齐台账再谈对齐用例）")
    want = ledger[0]
    drifted = {name: keys for name, keys in cases if keys != want}
    assert drifted == {}, (
        f"`set_overview.positions[]` 的形状在两处真值源之间漂移：\n"
        f"  台账（`docs/wiki/CONTRACT-LEDGER.md`）= {want}\n"
        f"  用例库 = {drifted}\n"
        "  ⇒ 两处必须同批改（issue #5685 的 `remark` 就是这么漏的：只改一处，没有任何判据会红）")


def test_guard_detects_injected_drift():
    """注入式自证：少一个键 / 换序 / 形状被删 ⇒ 判据必须能红（否则它是空断言）。"""
    base = ("set_overview = {set_no, set_index, positions:[{order_item_id, position_kind, "
            "position_name, remark, operations:[{operation_id}]}]}")
    assert shape_key_lists(base), "解析器读不出合规形状 ⇒ 判据本身是空断言"
    assert shape_key_lists(base.replace(", remark", "")) != shape_key_lists(base), (
        "少一个键（本单的真实漂移形态）没被照出来 ⇒ 判据是空断言")
    assert shape_key_lists(base.replace("position_kind, position_name", "position_name, position_kind")) \
        != shape_key_lists(base), "换序没被照出来 ⇒ 判据是空断言"
    assert shape_key_lists(base.replace("set_overview = {", "见散文描述：")) == [], (
        "形状被改写成散文后仍能解析 ⇒ 空跑闸门失效")
