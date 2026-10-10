# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 `_migration_paths.py` / `_source_parsing.py` 的同款声明。）
r"""类级元守卫：`order_logistics` 的**每一个「读-改-写」写面**都必须补「首次发货时刻」（issue #6276）。

## 病根（一类缺陷，不是一个缺陷）

issue #6276（真库读数：`order_logistics` 全表 29 行、`shipped_at` 非空仅 16 行）的根因不是
「某一行写错了」，而是**写出路径少写一处**：

> `OrderLogisticsWriter.upsert` 的 `shipped_at` **只在新建行的分支里写**；走 **update 分支**
> （已有物流行、再改物流/发货）时**不补写** ⇒ 「台账行先存在、之后才发货」的单永远为空。

本单修了两条 update 路径（`OrderLogisticsWriter` / `OrderController.updateLogistics`）并新增
`OrderLogisticsMapper#backfillShippedAtIfAbsent`。**但只修这两处 = 没修这一类**：
下一次有人给物流加第三个写面（或把某条 update 路径抽出去），同一个缺口会**静默重来**
（库里多出一批 `shipped_at IS NULL` 的行，而没有任何东西会变红 —— 这正是本单要防的形态）。

## 判据形态（识别式 + 按文件配对）

**真值源 = 现取的仓内源码面**（`backend/admin-api/src/main/java/**`），读法走既有共享实现
`_source_parsing.java_code()`（**引号感知**地剥注释 ⇒ 注释里提一句不算命中，同 #5323 的纪律）。

**「物流写面」的识别式**（现取，不写死文件清单）：

```
findall(r"\b\w*[Ll]ogistics\w*\s*\.\s*updateById\s*\(")      # 形如 logistics.updateById( / orderLogisticsService.updateById(
  ∪ findall(r"\bupdateById\s*\(\s*\w*[Ll]ogistics\w*\s*\)")   # 形如 updateById(logistics)
```

只认**变量名含 `logistics`** 的调用（本仓两条真实写面都长这样：`OrderController` 的
`orderLogisticsService.updateById(logistics)`、`OrderLogisticsService` 的
`orderLogisticsMapper.updateById(logistics)`）。

🔴 **为什么不做「泛型仓储类的所有 `updateById`」**（如实登记，§19.1）：试过，**射程过宽**——
`OrderService` / `OrderShipmentService` / `DailyBriefingService` 里改的是 `order` / `shipment` / `tenant`
（另一个域的对象，与本不变量无关），会变成「要么误伤、要么被迫加豁免台账」。
**射程的代价**：新写面若用**不含 `logistics` 的变量名**（如 `row.updateById(...)`）就漏过。
**这段缺口由什么兜住**：本单的两条实例判据是**行为面**的（真库 + mock，按真值判定，
不看变量名）——本元守卫只负责让「**忘记补写**」这个形态在源码面上可见；
两者合起来才覆盖这一类（缺任一半都不是固化）。

## 红了怎么办

在**那个文件**的 `updateById` **之前**加一行
`…backfillShippedAtIfAbsent(orderId, tenantId)`（本单的两条先例见 PR body）。
不许在台账里把它登记成例外 —— 本判据**没有豁免台账**（这族只有「补上」一种正确出口）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tests"))

from unit_ci_workflows._source_parsing import java_code  # noqa: E402

MAIN_JAVA = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java"

#: 物流写面的识别式（**现取**源码文本，不写死文件清单 ⇒ 新文件自动进射程）。
LOGISTICS_UPDATE_PATTERNS = (
    # `logistics.updateById(` / `orderLogisticsService.updateById(`（`\b` 防 `xlogisticsXxx` 过宽）
    re.compile(r"\b\w*[Ll]ogistics\w*\s*\.\s*updateById\s*\("),
    # `updateById(logistics)` / `updateById(orderLogistics)`
    re.compile(r"\bupdateById\s*\(\s*\w*[Ll]ogistics\w*\s*\)"),
)
#: 补「首次发货时刻」的**唯一**实现名（`OrderLogisticsMapper#backfillShippedAtIfAbsent`）。
BACKFILL_ANCHOR = "backfillShippedAtIfAbsent"


def is_logistics_update_site(code: str) -> bool:
    """代码文本里（注释已剥）是否存在 `OrderLogistics` 行的更新写面。"""
    return any(pattern.search(code) for pattern in LOGISTICS_UPDATE_PATTERNS)


def _java_sources() -> list[Path]:
    return sorted(MAIN_JAVA.rglob("*.java"))


def _code(path: Path) -> str:
    return java_code(path.read_text(encoding="utf-8"))


def update_paths_missing_backfill(sources: dict[str, str]) -> list[str]:
    """{仓库相对路径: 源码原文} → 缺补写锚点的「物流更新写面」文件。**

    🔴 两个判定都必须读**剥掉注释**之后的文本（`java_code`）—— 否则注释里提一句
    `backfillShippedAtIfAbsent` 就能把判据喂绿（#5323 家族），而注释里的示例调用也会被误判成写面。

    纯函数（便于注入式判别力自证）：不读盘、不做 IO。
    """
    return sorted(
        path for path, source in sources.items()
        if is_logistics_update_site(java_code(source)) and BACKFILL_ANCHOR not in java_code(source)
    )


def live_sources() -> dict[str, str]:
    """现取源码面：{仓库相对路径: **源码原文**}（剥注释交给 `update_paths_missing_backfill` 收口）。"""
    return {str(path.relative_to(REPO_ROOT)): path.read_text(encoding="utf-8")
            for path in _java_sources()}


# ══════════════════════════════════════════════════════════════════════════════
# 判据 1：现取源码面上，每一个物流「读-改-写」写面都带补写锚点
# ══════════════════════════════════════════════════════════════════════════════

def test_every_order_logistics_update_site_backfills_first_ship_moment():
    sources = live_sources()
    missing = update_paths_missing_backfill(sources)
    assert missing == [], (
        "这些文件里有 `OrderLogistics` 的更新写面（`updateById`），却没有补「首次发货时刻」的锚点\n"
        "  ⇒ 老行（`shipped_at IS NULL`）经这条路径**永远补不上**，而库里不会因此报任何错（静默数据质量回归）。\n"
        f"  缺锚点的文件（{len(missing)}）：{missing}\n"
        f"  修法：在那里的 `updateById` **之前**加一行 `…{BACKFILL_ANCHOR}(orderId, tenantId)`\n"
        "        （唯一实现 = `backend/admin-api/src/main/java/com/migao/admin/mapper/"
        "OrderLogisticsMapper.java`）"
    )


def test_scan_surface_is_not_empty():
    """反空跑：射程空集时上面的绿是**假绿**（路径漂移 / 读法失效都会让它恒绿）。"""
    sources = live_sources()
    assert len(sources) > 100, f"源码面只读到 {len(sources)} 个 .java 文件 ⇒ 路径漂移，判据已失效"
    assert BACKFILL_ANCHOR in sources[
        "backend/admin-api/src/main/java/com/migao/admin/mapper/OrderLogisticsMapper.java"
    ], "唯一实现点必须在这个文件里（否则上面的判据在守一个不存在的东西）"


def test_both_known_update_paths_are_in_scope_and_compliant():
    """两侧先例（本单修的两条 update 路径）必须**在射程内且合规** —— 防判据偷偷把它们排除掉。"""
    sources = live_sources()
    for rel in (
        "backend/admin-api/src/main/java/com/migao/admin/service/OrderLogisticsWriter.java",
        "backend/admin-api/src/main/java/com/migao/admin/controller/OrderController.java",
    ):
        assert rel in sources, f"{rel} 不在射程内 ⇒ 判据没在守本单修的那两条路径"
        assert BACKFILL_ANCHOR in sources[rel], f"{rel} 的补写锚点被摘掉了"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 2：判别力自证（四种坏形态在内存语料上各自判红 / 合规语料判绿）
# ══════════════════════════════════════════════════════════════════════════════

def test_guard_has_discriminating_power():
    compliant = {
        "A.java": ("public class A { void f(OrderLogistics logistics) {"
                   " mapper.backfillShippedAtIfAbsent(o, t); mapper.updateById(logistics); } }"),
    }
    assert update_paths_missing_backfill(compliant) == [], "合规语料被误判 ⇒ 判据会挡住正常开发"

    # ① 新增了一个忘记补写的物流写面（本单要防的**主形态**，两种调用形状各一）
    assert update_paths_missing_backfill(
        {"B.java": "orderLogisticsService.updateById(logistics);"}) == ["B.java"], \
        "「写了物流行却没补首次发货时刻」读不出来 ⇒ 本判据是空断言"
    assert update_paths_missing_backfill(
        {"B2.java": "orderLogisticsMapper.updateById(orderLogistics);"}) == ["B2.java"], \
        "另一种调用形状（接收者带 logistics）漏读 ⇒ 射程不全"
    # ② 补写锚点被改名 / 摘掉
    assert update_paths_missing_backfill(
        {"C.java": "OrderLogisticsArea a; a.updateById(logistics);"}) == ["C.java"], \
        "锚点缺失没被报出"
    # ③ **注释里提一句不算兑现**（引号感知剥注释；同 #5323 家族）——
    #    锚点只出现在**注释**里、代码里只有物流写面 ⇒ 必须判红。
    #    若剥注释失效（把注释当代码读），锚点就会被"读到" ⇒ 本断言变成 []（空集），当场红。
    assert update_paths_missing_backfill(
        {"D.java": "// 这里本该调 backfillShippedAtIfAbsent\nlogistics.updateById(row);"}
    ) == ["D.java"], "注释里的锚点被当成真调用 ⇒ 判据可被文案喂绿"
    # ③' 反向对照：**代码里真有**锚点（注释里那句不算）⇒ 判绿
    assert update_paths_missing_backfill(
        {"D2.java": "// 这里本该调 backfillShippedAtIfAbsent\n"
                    "mapper.backfillShippedAtIfAbsent(o, t); logistics.updateById(row);"}
    ) == [], "真调用与注释被混淆 ⇒ 两个方向至少有一个读错"
    # ④ 与物流无关的 updateById 不得误伤（否则射程过宽、会被迫加豁免台账）
    #    —— 这三行是**现取**的真实形态：OrderService / OrderShipmentService / DailyBriefingService
    #    里改的是 order / shipment / tenant（另一个域的对象）。
    assert update_paths_missing_backfill(
        {"E.java": "orderMapper.updateById(order); orderShipmentMapper.updateById(shipment);"
                   " tenantMapper.updateById(tenant);"}) == [], "非物流写面被误判 ⇒ 射程过宽"


def test_scan_surface_covers_both_directions():
    """扫描器失明自证：现取源码面里**同时**存在「有锚点的文件」与「有物流写的文件」。

    唯一允许「有锚点、但不是物流写面」的文件 = **锚点自己的声明处**
    （`OrderLogisticsMapper`：它声明 `backfillShippedAtIfAbsent`，自己不写物流行）。
    """
    sources = live_sources()
    mapper = "backend/admin-api/src/main/java/com/migao/admin/mapper/OrderLogisticsMapper.java"
    with_anchor = {p for p, c in sources.items() if BACKFILL_ANCHOR in c}
    with_update = {p for p, c in sources.items() if is_logistics_update_site(c)}
    assert with_anchor, "一个带锚点的文件都读不到 ⇒ 扫描器失明"
    assert with_update, "一个物流更新写面都读不到 ⇒ 扫描器失明"
    assert mapper in with_anchor, "锚点声明处必须读到（否则 BACKFILL_ANCHOR 名字漂移）"
    assert mapper not in with_update, "锚点声明处不应被当成物流写面（否则调用方漏判会更早暴露）"
    assert with_anchor - {mapper} <= with_update, (
        "带锚点却不在物流写面里的文件（除锚点声明处外）："
        f"{sorted(with_anchor - {mapper} - with_update)}"
    )


if __name__ == "__main__":  # pragma: no cover - 人工排查入口
    raise SystemExit(pytest.main([__file__, "-q"]))
