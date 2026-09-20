# case_ids: PG-018, PG-035
"""去部位化（issue #4883 / #4885）**跨语言同口径**守卫：Python 真值源的收敛规则 ≡ Java `collapseToLogical`。

## 为什么需要它

`GET /api/admin/production/operation-positions` 的形状从「30 逻辑工序 × 4 部位 = 120 行」变成
「**一道逻辑工序一行**」，取**哪一行**由 Java 侧 `ProductionOperationQueryService#collapseToLogical`
的三档顺序决定（**适用行优先 → 布帘列优先 → `position` → `id`**）。而本模块（`app/production/routing.py`）
是**真值源**、Java 必须与它逐字一致 —— 该收敛规则在真值源侧原本**没有对侧** ⇒ 改错 Java 那一份，
**没有任何东西会红**。（既有范式：`build_route_v2` ↔ Java `buildRoute` 两侧各有跨语言判据。）

## 判据（每条都独立可红）

1. **不是空跑**：`collapse_to_logical()` 的键集 = 冻结行表里出现的**全部**逻辑工序名
   （条数从行表现场派生，**不写死数字**）；
2. 🔴 **「取布帘价」的直觉在这里是错的**：`帘头制作` 的布帘格是 `(None, False)`（明确不做）、
   帘头格是 `(2.0, True)` ⇒ 幸存必须是 **`帘头 / 2.0`**。若把「布帘列优先」提到「适用行优先」
   之前 ⇒ 得到 `None` = **把有价的工序判成未定价**（工人白干、且与「显式 0 元」同族不可区分）；
3. 🔴 **未定价不得被回落**：`打包`（4 部位全 `applicable=True`、`unit_price=None`）幸存 =
   `布帘 / None` —— **不是** `0.0`，也不是 `OPERATION_CATALOG` 的行价（issue #4696 红线）；
4. **输入序无关**：行表倒序 / 打乱后结果**逐键相同**（收敛必须由判据决定，不能由输入序决定 ——
   否则同一道工序两次刷新取到不同的价）；
5. **空输入** ⇒ `{}`（不是异常，也不是造出一个空名键）；
6. **跨语言**：Java 源码里 `COLLAPSE_PRICE_SOURCE_POSITION` 的字面量与 Python 侧**逐字同值**，
   且 `beatsForCollapse` 的两档顺序（适用 → 布帘列）与 Python 侧**同序**（解析 Java 源码，
   与 `tests/unit_ci_workflows/test_v97_orphan_positions_cleanup.py` 同范式）。
"""
from __future__ import annotations

import random
import re
from pathlib import Path

from app.production.routing import (
    COLLAPSE_PRICE_SOURCE_POSITION,
    OPERATION_CATALOG,
    _POSITION_PRICE_ROWS,
    collapse_to_logical,
)

JAVA_SERVICE = ("backend/admin-api/src/main/java/com/migao/admin/service/"
                "ProductionOperationQueryService.java")


def _repo_root() -> Path:
    """仓库根（从本文件逐级上溯，找到 `backend/admin-api` 为止）。"""
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        if (parent / "backend" / "admin-api").is_dir():
            return parent
    raise AssertionError("找不到仓库根目录（backend/admin-api 不存在）")


def test_every_logical_operation_gets_exactly_one_survivor():
    """判据 1：逐逻辑工序非空跑 —— 键集 = 冻结行表里的全部逻辑工序名。"""
    expected = {row[0] for row in _POSITION_PRICE_ROWS}
    got = collapse_to_logical()
    assert set(got) == expected, (
        f"收敛的键集与冻结行表不一致：缺 {sorted(expected - set(got))} / 多 {sorted(set(got) - expected)}")
    assert len(got) == len(expected), "同一逻辑工序被收敛出多条（收敛没有生效）"
    for logical, survivor in got.items():
        assert survivor["position"] in {row[1] for row in _POSITION_PRICE_ROWS if row[0] == logical}, (
            f"{logical} 的幸存行部位不属于它自己的行：{survivor}")


def test_applicable_row_wins_over_the_cloth_column():
    """判据 2：🔴 `帘头制作` 必须收敛到 `帘头 / 2.0`（**不是**布帘格的 `None`）。

    改前形态（把「布帘列优先」排在「适用行优先」之前）⇒ 这一格变 `None`，
    `ProductionOperationQueryService#collapseToLogical` 的 javadoc 逐字写着这个反例。
    """
    survivor = collapse_to_logical()["帘头制作"]

    assert survivor["position"] == "帘头", "「适用行优先」这一档丢了（布帘格是 applicable=False）"
    assert survivor["unit_price"] == 2.0, "有价工序被判成了未定价（把 2.0 换成了布帘格的 None）"
    assert survivor["applicable"] is True


def test_cloth_column_wins_when_several_rows_are_applicable():
    """判据 2b：「适用行」有多个时才由**布帘列**决胜（用户裁定「取布帘价」）。"""
    for logical in ("定型", "精裁", "裁剪", "三边"):
        survivor = collapse_to_logical()[logical]
        assert survivor["position"] == COLLAPSE_PRICE_SOURCE_POSITION, (
            f"{logical} 的幸存行不是布帘列：{survivor}")


def test_unpriced_survivor_is_not_backfilled():
    """判据 3：🔴 幸存行未定价 ⇒ 就是 `None`，**不得**回落工序库行价、更不得变成 0.0。"""
    survivor = collapse_to_logical()["打包"]

    assert survivor["position"] == COLLAPSE_PRICE_SOURCE_POSITION
    assert survivor["applicable"] is True, "`打包` 在 4 个部位都适用（套级语义由 scope 承担）"
    assert survivor["unit_price"] is None, (
        "未定价被回落了 —— `OPERATION_CATALOG['打包']['unit_price']` 是 DDL 约束的产物 0.0，"
        "回落即「未定价」静默变「真 0 元」（issue #4696）")
    assert OPERATION_CATALOG["打包"]["unit_price"] == 0.0, (
        "夹具前提变了：本判据之所以有意义，正是因为工序库行价确实是 0.0（NOT NULL DEFAULT 0 的产物）")


def test_survivor_is_independent_of_input_order():
    """判据 4：倒序 / 打乱输入 ⇒ 结果逐键相同（收敛由判据决定，不由输入序决定）。"""
    baseline = collapse_to_logical()
    reversed_rows = list(reversed(_POSITION_PRICE_ROWS))
    assert collapse_to_logical(reversed_rows) == baseline, "倒序输入改变了幸存行（收敛依赖输入序）"

    shuffled = list(_POSITION_PRICE_ROWS)
    random.Random(20260921).shuffle(shuffled)
    assert collapse_to_logical(shuffled) == baseline, "打乱输入改变了幸存行（收敛依赖输入序）"


def test_empty_input_yields_no_rows():
    """判据 5：空输入 ⇒ `{}`（不抛、也不造出一个空名键）。"""
    assert collapse_to_logical([]) == {}


def test_java_and_python_share_the_same_rule():
    """判据 6：跨语言 —— 常量逐字同值 + 两档顺序同序（解析 Java 源码，不靠人抄）。"""
    src = (_repo_root() / JAVA_SERVICE).read_text(encoding="utf-8")

    match = re.search(r'COLLAPSE_PRICE_SOURCE_POSITION\s*=\s*"([^"]+)"', src)
    assert match, "Java 侧找不到 `COLLAPSE_PRICE_SOURCE_POSITION` 的字面量（常量被改名/删除？）"
    assert match.group(1) == COLLAPSE_PRICE_SOURCE_POSITION, (
        f"两侧的取价来源部位不同值：Java={match.group(1)!r} / Python={COLLAPSE_PRICE_SOURCE_POSITION!r} —— "
        f"那会让同一张矩阵在两侧收敛出不同的价")

    body = re.search(r"private static boolean beatsForCollapse\(([\s\S]*?)\n    \}", src)
    assert body, "Java 侧找不到 `beatsForCollapse`（收敛的档序落点被搬走了？）"
    text = body.group(1)
    applicable_at = text.find("getApplicable()")
    cloth_at = text.find("COLLAPSE_PRICE_SOURCE_POSITION.equals")
    assert applicable_at >= 0 and cloth_at >= 0, (
        "Java 侧两档判据之一缺失：applicable 档=" + str(applicable_at) + " / 布帘列档=" + str(cloth_at))
    assert applicable_at < cloth_at, (
        "Java 侧的档序被改了：`布帘列优先` 跑到了 `适用行优先` **之前** ⇒ "
        "`帘头制作` 会从 `帘头/2.0` 变成 `布帘/None`（有价工序被判成未定价，工人白干）")
