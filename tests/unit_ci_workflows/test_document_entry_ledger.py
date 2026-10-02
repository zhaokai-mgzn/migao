# case_ids: UI-078
"""单据入口台账守卫（issue #5939）—— 治「单据做完了，大菜单里没有它」。

## 病（用户原话 + 现场读数）

2026-10-02 用户报障：「**我让你开发过发货单的，但是在大菜单上没见到这个单据**」。
核对（零成本、可复算）：

```
git log -S "发货单" -- frontend/admin-web/src/config/menu.ts     # ⇒ 空（从未进过菜单）
git log -S "发货单" -- backend/.../controller/MenuController.java # ⇒ 空
```

发货单**本身做完了**（纸面 #3768、数据面 #5648、打印矩阵 #5651/#5914 全在），
但它只挂在**订单详情**里 ⇒ 想知道「这个月发过哪些货」必须先知道是哪张订单。
**没有任何东西会因此变红**：三源同构守卫比的是「三处菜单是否一致」，不是「单据是否有入口」；
菜单项数守卫比的是「21 项一项不少不减」，那 21 项里本来就没有它。

## 它判什么（三条不变量）

真值源 = `frontend/admin-web/src/lib/print-doc.ts` 的 `PRINT_TARGETS`
（**全仓唯一的可打印单据清单** —— 每份纸质单据都必须在那里登记一个 target），
对照台账 `tests/unit_ci_workflows/document_entry_ledger.json`：

1. **未登记即红**：`PRINT_TARGETS` 里的每个单据都必须在台账里**显式声明入口形态**
   （`menu:<菜单路径>` 或 `embedded:<承载页的菜单路径>`）—— 「这张单据用户从哪进得来」是
   一个**必须被回答**的问题，不是可以默认「反正订单详情里有」的问题（本缺陷的成因正是后一种默认）；
2. **陈旧登记即红**：台账里不得留 `PRINT_TARGETS` 已经没有的条目（两向相等，不是子集）；
3. **声明必须可达**：`menu:` 的路径必须在 `config/menu.ts` 里**真实存在**；`embedded:` 的承载页
   必须是某个菜单路径（或其子孙）—— 「写了入口、入口不存在」比「没写入口」更坏（它看起来已经处理过了）。

另有两条卫生判据：台账不得为空（fail-closed：**清空台账不能消红**）；
每条必须写 `name` 与 `why`（`why` 留空 = 没有真的决定过入口形态，只是把字段填满了）。

## 红证（判别力自证，全部在内存里做，不写仓内文件）

见 `TestDiscriminatingPower`：摘掉菜单项 / 台账漏登记 / 台账陈旧登记 / 声明指向不存在的菜单路径 /
声明指向不可达页面 / 台账清空 / entry 形态非法 —— **七种坏形态各自判红**；
对照读数：只在 `menu.ts` 末尾加一段无关注释 ⇒ **不红**（证明判据在判语义，不是判「文件变了没有」）。

## 边界（照实登记，不粉饰）

- 它**判不了**「这个入口形态选得对不对」（发货单该不该独立成项是**产品裁定** —— 本单就是用户拍的；
  台账只保证「有人显式决定了、且声明的东西真实可达」）；
- 它**只覆盖 `PRINT_TARGETS` 登记过的单据**：一个没有任何纸质单据的业务对象（如「售后工单」）
  不在射程 —— 那类对象的入口由菜单三源同构守卫 + 面包屑覆盖判据（PG-038）承担；
- `embedded:` 的 `why` 是**人工说明**，机器只保证它非空。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PRINT_DOC_TS = REPO_ROOT / "frontend/admin-web" / "src" / "lib" / "print-doc.ts"
MENU_TS = REPO_ROOT / "frontend/admin-web" / "src" / "config" / "menu.ts"
LEDGER_PATH = Path(__file__).with_name("document_entry_ledger.json")

_PRINT_TARGETS = re.compile(r"export const PRINT_TARGETS\s*=\s*\[(.*?)\]\s*as const", re.S)
_STRING = re.compile(r"'([A-Za-z0-9_]+)'")
_MENU_PATH = re.compile(r"path:\s*'([^']+)'")

#: 允许的入口形态（两种；多一种都要先想清楚「谁在用」）
ENTRY_KINDS = ("menu", "embedded")


def print_targets(src: str | None = None) -> list[str]:
    """可打印单据清单（真值源 = `print-doc.ts` 的 `PRINT_TARGETS`）；解析不出来 ⇒ fail-closed。"""
    text = src if src is not None else PRINT_DOC_TS.read_text(encoding="utf-8")
    match = _PRINT_TARGETS.search(text)
    if match is None:
        raise AssertionError("print-doc.ts 里找不到 PRINT_TARGETS（fail-closed：不许静默当空）")
    targets = _STRING.findall(match.group(1))
    if not targets:
        raise AssertionError("PRINT_TARGETS 解析出 0 个单据（fail-closed）")
    return targets


def menu_paths(src: str | None = None) -> set[str]:
    """侧边栏菜单路径集合（真值源 = `config/menu.ts` 的 `path:` 字面量）。"""
    text = src if src is not None else MENU_TS.read_text(encoding="utf-8")
    paths = set(_MENU_PATH.findall(text))
    if not paths:
        raise AssertionError("menu.ts 里解析出 0 个 path（fail-closed）")
    return paths


def load_ledger(path: Path | None = None) -> dict:
    """读声明台账；缺文件 ⇒ 抛（fail-closed，不静默当空）。"""
    return json.loads((path or LEDGER_PATH).read_text(encoding="utf-8"))


def reachable(host: str, paths: set[str]) -> bool:
    """`host` 是否可从某个菜单路径到达（相等，或是它的子孙）。"""
    return any(host == p or host.startswith(p.rstrip("/") + "/") for p in paths)


def entry_problems(targets, paths, ledger) -> list[str]:
    """三条不变量 + 两条卫生判据的**全部**问题（空列表 = 绿）。"""
    out: list[str] = []
    documents = ledger.get("documents") or {}
    names = {str(d.get("name") or "").strip() for d in documents.values()}
    whys = {str(d.get("why") or "").strip() for d in documents.values()}

    # 卫生判据 ①：清空台账不能消红
    if not documents:
        return ["台账 `documents` 为空（fail-closed：清空台账不能消红）"]
    if "" in names:
        out.append("有单据没写 `name`")
    if "" in whys:
        out.append("有单据没写 `why`（入口形态必须是被决定过的，不是把字段填满）")

    # 判据 1：未登记即红
    for target in targets:
        if target not in documents:
            out.append(
                f"`{target}` 在 PRINT_TARGETS 里、但台账里没有入口声明 ⇒ 未登记即红"
                "（「这张单据用户从哪进得来」必须显式回答）"
            )
    # 判据 2：陈旧登记即红（两向相等）
    for target in documents:
        if target not in targets:
            out.append(f"`{target}` 是陈旧登记（PRINT_TARGETS 里已没有这个单据）")

    # 判据 3：声明必须可达
    for target, doc in documents.items():
        entry = str(doc.get("entry") or "").strip()
        if ":" not in entry:
            out.append(f"`{target}` 的 entry `{entry}` 形态非法（应为 `menu:<path>` / `embedded:<path>`）")
            continue
        kind, host = entry.split(":", 1)
        if kind not in ENTRY_KINDS:
            out.append(f"`{target}` 的 entry 类型 `{kind}` 不认识（只认 {' / '.join(ENTRY_KINDS)}）")
            continue
        if kind == "menu" and host not in paths:
            out.append(f"`{target}` 声明了独立菜单入口 `{host}`，但 menu.ts 里没有这个 path（入口不存在）")
        if not reachable(host, paths):
            out.append(f"`{target}` 的入口 `{entry}` 在 menu.ts 里不可达（用户从菜单进不去）")
    return out


def _live(documents: dict | None = None) -> tuple[list[str], set[str], dict]:
    ledger = load_ledger()
    if documents is not None:
        ledger = {**ledger, "documents": documents}
    return print_targets(), menu_paths(), ledger


# ══════════════════════════════════════════════════════════════════════════════
# 判据本体
# ══════════════════════════════════════════════════════════════════════════════


def test_every_print_target_declares_a_reachable_entry() -> None:
    """不变量 1~3：现取 vs 台账 —— 必须零问题。"""
    targets, paths, ledger = _live()
    assert entry_problems(targets, paths, ledger) == []


def test_ledger_is_not_empty() -> None:
    """fail-closed：清空台账不能消红（否则「删掉台账」就是最省事的消红手段）。"""
    assert len(load_ledger()["documents"]) >= 5


def test_shipment_has_a_menu_entry_now() -> None:
    """本单的实例判据：发货单**必须是独立菜单项**，且路径真实存在于菜单。"""
    targets, paths, ledger = _live()
    assert "shipment" in targets
    assert ledger["documents"]["shipment"]["entry"] == "menu:/shipments"
    assert "/shipments" in paths


def test_every_document_entry_is_reachable() -> None:
    """逐条复算可达性（与不变量 3 同一函数，报错具名到单据）。"""
    _, paths, ledger = _live()
    unreachable = {
        target: doc["entry"]
        for target, doc in ledger["documents"].items()
        if not reachable(str(doc["entry"]).split(":", 1)[1], paths)
    }
    assert unreachable == {}


# ══════════════════════════════════════════════════════════════════════════════
# 判别力自证（红证；全部在内存里做，不写仓内文件）
# ══════════════════════════════════════════════════════════════════════════════


class TestDiscriminatingPower:
    """七种坏形态各自判红 + 一条对照读数（只改注释 ⇒ 不红）。"""

    def test_missing_ledger_entry_goes_red(self) -> None:
        targets, paths, ledger = _live(
            {k: v for k, v in load_ledger()["documents"].items() if k != "shipment"}
        )
        problems = entry_problems(targets, paths, ledger)
        assert any("shipment" in p and "未登记" in p for p in problems)

    def test_stale_ledger_entry_goes_red(self) -> None:
        documents = dict(load_ledger()["documents"])
        documents["legacy_doc"] = {"name": "早已删除的单据", "entry": "menu:/orders", "why": "陈旧"}
        _, paths, ledger = _live(documents)
        assert any("legacy_doc" in p and "陈旧" in p for p in entry_problems(print_targets(), paths, ledger))

    def test_menu_entry_that_does_not_exist_goes_red(self) -> None:
        documents = dict(load_ledger()["documents"])
        documents["shipment"] = {"name": "发货单", "entry": "menu:/nowhere", "why": "x"}
        _, paths, ledger = _live(documents)
        problems = entry_problems(print_targets(), paths, ledger)
        assert any("/nowhere" in p for p in problems)

    def test_embedded_entry_that_is_not_reachable_goes_red(self) -> None:
        documents = dict(load_ledger()["documents"])
        documents["labels"] = {"name": "洗水码", "entry": "embedded:/not-a-page", "why": "x"}
        _, paths, ledger = _live(documents)
        problems = entry_problems(print_targets(), paths, ledger)
        assert any("不可达" in p for p in problems)

    def test_empty_ledger_goes_red(self) -> None:
        _, paths, ledger = _live({})
        assert entry_problems(print_targets(), paths, ledger) == [
            "台账 `documents` 为空（fail-closed：清空台账不能消红）"
        ]

    def test_malformed_entry_goes_red(self) -> None:
        documents = dict(load_ledger()["documents"])
        documents["shipment"] = {"name": "发货单", "entry": "shipment", "why": "x"}
        _, paths, ledger = _live(documents)
        assert any("形态非法" in p for p in entry_problems(print_targets(), paths, ledger))

    def test_removing_the_menu_item_goes_red(self) -> None:
        """🔴 **本缺陷的原始形态**：单据声明了独立菜单入口，而菜单里没有它 ⇒ 必红。"""
        original = MENU_TS.read_text(encoding="utf-8")
        menu_src = original.replace("path: '/shipments'", "path: '/shipments-disabled'")
        # 变异自证：注入必须先真的改到东西（否则「没红」会被误读成「判据判不了」）
        assert menu_src != original
        targets, paths, ledger = _live()
        problems = entry_problems(targets, menu_paths(menu_src), ledger)
        assert any("/shipments" in p for p in problems)

    def test_unrelated_comment_does_not_go_red(self) -> None:
        """对照读数：只加一段与单据无关的注释 ⇒ 不红（判据在判语义，不是判「文件变了没有」）。"""
        menu_src = MENU_TS.read_text(encoding="utf-8") + "\n// 与单据入口无关的注释\n"
        targets, paths, ledger = _live()
        assert entry_problems(targets, menu_paths(menu_src), ledger) == []
