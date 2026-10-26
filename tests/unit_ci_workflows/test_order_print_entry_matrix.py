# case_ids: MC-085
"""订单详情**打印入口收口**守卫（issue #6434 → **#7544 改判**）—— 让「又一个打印入口」进不来。

## 这条判据的改判史（为什么口径反过来了）

- **#6434（2026-10-06）**：四个打印按钮原先在 `status === 'shipped'` / `completed` 两个分支里各写一份
  字面量 ⇒ 待付款 / 待发货 / 生产中**一个按钮都没有**。当时修法 = 收敛成
  `PRINT_TARGETS_BY_STATUS` **一张「状态 × 可打单据」表**，本守卫钉的就是那张表。
- **#7544（2026-10-23，用户逐字）**：「这几个打印按钮**不要跟状态挂钩**，允许任何状态都能进行打印这些单据，
  另外把按钮**收拢到一个打印统一入口**中」。⇒ 状态矩阵本身就是病根的另一半：
  `closed` / `refund` 两个状态**一张都打不出来**，而四个按钮常驻把操作行铺满。

**现在的口径**：页面上只有**一个**「打印」入口（页面级、**不在任何状态分支里**），
进来后在纸面自检层里以**单据标签**选（销售单 / 报价单 / 发货单），先预览再出纸。

**#7870（2026-10-26，用户逐字）**：「加工单打印移到加工单和水洗唛放一起，也想订单一样统一收口到打印按钮」
⇒ 加工单（A4）**退出订单详情页**，改由「加工单生产明细」页（`/processing-orders/{id}/production`）
的**同一个**「打印」入口承载（单据标签 = 水洗唛 / 加工单）。⇒ 本守卫补 G7/G8 两条：
订单详情页**不得**再出现加工单打印；生产明细页**必须**是它唯一的入口（且与洗水唛同层）。

## 冻结判据（每条都能单独变红，见 `TestDiscriminatingPower`）

| # | 判据 | 红证（怎么让它**单独**变红） |
|---|---|---|
| G1 | 页面里**不得**再有「状态 → 可打单据」矩阵（打印与状态解耦） | 把 `PRINT_TARGETS_BY_STATUS` 那段加回去 ⇒ 红 |
| G2 | 「打印」入口**恰好一处**，且**不在** `StatusSection`（状态分支）里 | 把入口塞进 `StatusSection` ⇒ 红；复制成两处 ⇒ 红 |
| G3 | 页面里**不得**手写打印按钮文案（文案只能来自 `PRINT_TARGET_SPECS[*].title`） | 写回 `<button>打印销售单</button>` ⇒ 红 |
| G4 | 打印层的单据选择器必须**接线**：`docs={ORDER_PRINT_DOCS}` + `onSelect={selectPreview}`，且清单里每份单据都是**真实 target** | 摘掉 `docs=` ⇒ 红；清单里写 `'sale'`（错键）⇒ 红 |
| G5 | 「作业单」区块**不再**有第二个打印入口（打印只剩一处） | 在 `ProcessingOrderBlock` 里加回 `onPrintProcessing` ⇒ 红 |
| G6 | 判别力自证 + **对照读数**（只加注释 ⇒ 不红） | 注入未生效 ⇒ 红（红证自己是空断言） |
| G7 | 订单详情页**不再**承载加工单打印（`<ProcessingDoc>` / `previewTarget === 'processing'` / 清单含 `processing` 任一出现） | 把加工单标签加回 `ORDER_PRINT_DOCS` 或把 `<ProcessingDoc>` 挂回页面 ⇒ 红 |
| G8 | 「加工单生产明细」页 = 加工单打印**唯一**入口，且与水洗唛**同层**（单据标签 = `labels` + `processing`、`docs` / `onSelect` 接线、`<ProcessingDoc>` 页级挂载 + 预览副本各一处） | 摘掉 `['labels','processing']` 里的 `processing` / 摘掉 `docs=` / 删掉页级挂载 ⇒ 红 |

⚠️ **判据按「去注释后的代码」判定**：页面文件用注释解释这些坑（会**写出**几个按钮名），
按原文判定会把解释性注释判成违规 = 假红。故本文件自带字符串感知的注释剥离器。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE_REL = "frontend/admin-web/src/app/(dashboard)/orders/[id]/OrderDetail.tsx"
#: 加工单（A4）打印自 issue #7870 起搬到「加工单生产明细」页 —— 这是它的**唯一**入口所在文件
PRODUCTION_PAGE_REL = (
    "frontend/admin-web/src/app/(dashboard)/processing-orders/[id]/production/page.tsx"
)
#: 生产明细页的唯一打印入口锚点
PRODUCTION_ENTRY_MARKER = 'data-testid="production-print-button"'
PRINT_DOC_REL = "frontend/admin-web/src/lib/print-doc.ts"
BLOCK_REL = "frontend/admin-web/src/components/orders/ProcessingOrderBlock.tsx"

#: 页面里**不许**手写的按钮文案（必须来自 `PRINT_TARGET_SPECS[*].title`）
HANDWRITTEN_LABELS: tuple[str, ...] = ("打印发货单", "打印报价单", "打印加工单", "打印销售单")

#: 唯一入口的锚点（`data-testid` 是给单测与 e2e 的共同抓手）
ENTRY_MARKER = 'data-testid="order-print-entry"'

#: 订单详情必须能打的**三份**单据（顺序不钉；集合不齐 ⇒ 商家少一张纸）。
#: 🔴 `processing` 自 issue #7870 起**不在此列** —— 它随「加工单生产明细」页走（G7/G8 钉住）。
REQUIRED_ORDER_DOCS: tuple[str, ...] = ("shipment", "quotation", "sales")

#: 生产明细页必须同时给出的**两份**纸（水洗唛 = 任务卡，加工单 = A4）
REQUIRED_PRODUCTION_DOCS: tuple[str, ...] = ("labels", "processing")


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def strip_comments(src: str) -> str:
    """字符串感知地剥掉注释（`//` 行注释、`/* */` 块注释、JSX `{/* */}`）。

    保留字符串字面量内容（判据只看代码里有没有手写按钮文案 / 有没有矩阵，不解析语义）。
    """
    out: list[str] = []
    i, n = 0, len(src)
    quote: str | None = None
    while i < n:
        ch = src[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(src[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
            continue
        if src.startswith("/*", i):
            end = src.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def print_targets(print_doc_src: str) -> list[str]:
    """现取 `lib/print-doc.ts` 的 `PRINT_TARGETS`（真值在那边，不在这里硬编码）。"""
    m = re.search(r"export const PRINT_TARGETS\s*=\s*\[([^\]]*)\]", print_doc_src)
    if not m:
        raise AssertionError(f"{PRINT_DOC_REL} 里找不到 `PRINT_TARGETS`（判据 fail-closed）")
    targets = re.findall(r"'([a-z]+)'", m.group(1))
    if not targets:
        raise AssertionError("`PRINT_TARGETS` 一个成员都没解析出来（判据 fail-closed）")
    return targets


# ============== G1：打印与订单状态解耦 ==============


def legacy_status_matrix(page_src: str) -> list[str]:
    """G1：页面里残留的「状态 → 可打单据」矩阵形态。

    两种都算：`PRINT_TARGETS_BY_STATUS`（#6434 的载体）与任何 `Record<OrderStatus, …>` 声明 ——
    后者是同族的换名写法（把矩阵加回来同样违反「不跟状态挂钩」）。
    """
    code = strip_comments(page_src)
    hits: list[str] = []
    if "PRINT_TARGETS_BY_STATUS" in code:
        hits.append("PRINT_TARGETS_BY_STATUS")
    if re.search(r"Record<\s*OrderStatus", code):
        hits.append("Record<OrderStatus")
    return hits


# ============== G2：唯一入口、且不在状态分支里 ==============


def entry_count(page_src: str) -> int:
    """G2：页面里「打印」入口的处数（去注释后数锚点）。"""
    return strip_comments(page_src).count(ENTRY_MARKER)


def entry_inside_status_section(page_src: str) -> bool:
    """G2：入口是否落进了 `StatusSection`（= 状态分支所在的那个组件）。

    🔴 用**组件边界**而不是「是否在某个 `status === …` 之后」判定：后者会被页面里
    任意一处状态判断误伤（本页还有 `refundAmount` / `workOrderKind` 等状态派生分支）。
    """
    code = strip_comments(page_src)
    pos = code.find(ENTRY_MARKER)
    if pos < 0:
        return False
    section = code.find("function StatusSection(")
    return section >= 0 and pos > section


# ============== G3：不手写按钮文案 ==============


def handwritten_labels(page_src: str) -> list[str]:
    """G3：页面代码里手写的打印按钮文案（注释不算）。"""
    code = strip_comments(page_src)
    return [label for label in HANDWRITTEN_LABELS if label in code]


# ============== G4：选择器接线 + 清单合法 ==============


def order_print_docs(page_src: str) -> list[str]:
    """G4：解析页面里的 `ORDER_PRINT_DOCS` 清单（唯一声明处）。"""
    m = re.search(r"const ORDER_PRINT_DOCS\s*=\s*\[([^\]]*)\]", strip_comments(page_src))
    if not m:
        raise AssertionError(
            f"{PAGE_REL} 里找不到 `ORDER_PRINT_DOCS` —— 可打印单据清单必须是**一处**声明，"
            "不是散在各状态分支里的按钮"
        )
    docs = re.findall(r"'([a-z]+)'", m.group(1))
    if not docs:
        raise AssertionError("`ORDER_PRINT_DOCS` 解析出 0 条（判据 fail-closed）")
    return docs


def missing_required_docs(page_src: str) -> list[str]:
    """G4：清单里缺的必打单据。"""
    return sorted(set(REQUIRED_ORDER_DOCS) - set(order_print_docs(page_src)))


def unknown_docs(page_src: str, print_doc_src: str) -> list[str]:
    """G4：清单里写了 `PRINT_TARGETS` 之外的目标位（错键 ⇒ 该单据永远选不中）。"""
    return sorted(set(order_print_docs(page_src)) - set(print_targets(print_doc_src)))


def selector_wiring(page_src: str) -> list[str]:
    """G4：打印层的选择器接线（`docs=` + `onSelect=`）。返回**缺失**的那几项。"""
    code = strip_comments(page_src)
    missing: list[str] = []
    if "docs={ORDER_PRINT_DOCS}" not in code:
        missing.append("docs={ORDER_PRINT_DOCS}")
    if "onSelect={selectPreview}" not in code:
        missing.append("onSelect={selectPreview}")
    return missing


# ============== G5：作业单区块不再自带打印入口 ==============


def block_print_entry(block_src: str) -> list[str]:
    """G5：`ProcessingOrderBlock` 里残留的打印入口（prop 或其按钮）。"""
    code = strip_comments(block_src)
    hits: list[str] = []
    if "onPrintProcessing" in code:
        hits.append("onPrintProcessing")
    if re.search(r"<Button[^>]*>\s*打印\s*</Button>", code):
        hits.append("打印 button")
    return hits


# ============== G7 / G8：加工单打印的唯一入口在生产明细页 ==============


def order_page_processing_leaks(page_src: str) -> list[str]:
    """G7：订单详情页里残留的「加工单打印」痕迹（去注释后判定）。"""
    code = strip_comments(page_src)
    hits: list[str] = []
    if "<ProcessingDoc" in code:
        hits.append("<ProcessingDoc")
    if re.search(r"previewTarget\s*===\s*'processing'", code):
        hits.append("previewTarget === 'processing'")
    if re.search(r"printTarget\s*===\s*'processing'", code):
        hits.append("printTarget === 'processing'")
    docs = order_print_docs(page_src)
    if "processing" in docs:
        hits.append("ORDER_PRINT_DOCS 含 processing")
    return hits


def production_print_docs(page_src: str, print_doc_src: str) -> list[str]:
    """G8：生产明细页单据标签清单（`printDocs` 声明体里出现的、`PRINT_TARGETS` 内的目标位）。

    🔴 **不用「引号解析正则」**（`re.findall(r"'([a-z]+)'")` 那类）：它会把注释 / 字符串里的
    字面量一并算进来（正是 `test_guard_parsing_is_comment_aware.py` 的 `quote-parse` 面），
    且每新增一处就抬高台账里的一笔债务（只许缩短）。这里改成
    「剥注释 → 取 `printDocs` 声明块 → 拿 `PRINT_TARGETS`（**现取**）逐个做子串判定」。
    """
    code = strip_comments(page_src)
    m = re.search(r"const printDocs\s*=([\s\S]{0,400}?)\n\s*\)", code)
    if not m:
        raise AssertionError(
            f"{PRODUCTION_PAGE_REL} 里找不到 `printDocs` —— 本页可打印单据清单必须是**一处**声明"
        )
    block = m.group(1)
    return sorted(t for t in print_targets(print_doc_src) if f"'{t}'" in block)


def production_selector_wiring(page_src: str) -> list[str]:
    """G8：生产明细页打印层的选择器接线（`docs=` + `onSelect=`）。返回**缺失**项。"""
    code = strip_comments(page_src)
    missing: list[str] = []
    if "docs={printDocs}" not in code:
        missing.append("docs={printDocs}")
    if "onSelect={selectPreview}" not in code:
        missing.append("onSelect={selectPreview}")
    return missing


def processing_doc_mounts(page_src: str) -> int:
    """G8：生产明细页里 `<ProcessingDoc` 的处数（页级挂载 1 + 预览副本 1）。"""
    return len(re.findall(r"<ProcessingDoc\b", strip_comments(page_src)))


class TestProductionPrintEntry:
    """G7 / G8 的**真语料**判据（订单详情页 + 生产明细页两份语料）。"""

    def test_g7_order_page_no_longer_prints_processing_doc(self) -> None:
        leaks = order_page_processing_leaks(_read(PAGE_REL))
        assert leaks == [], (
            f"订单详情页又出现了加工单打印痕迹 {leaks} —— issue #7870 起加工单（A4）只在"
            "「加工单生产明细」页打印（一份单据只有一个打印入口）"
        )

    def test_g8_production_page_is_the_single_entry(self) -> None:
        page = _read(PRODUCTION_PAGE_REL)
        assert strip_comments(page).count(PRODUCTION_ENTRY_MARKER) == 1, (
            f"{PRODUCTION_PAGE_REL} 的「打印」入口应恰好 1 处（{PRODUCTION_ENTRY_MARKER}）"
        )
        doc_lib = _read(PRINT_DOC_REL)
        docs = production_print_docs(page, doc_lib)
        missing = sorted(set(REQUIRED_PRODUCTION_DOCS) - set(docs))
        assert missing == [], (
            f"生产明细页的单据标签缺 {missing} —— 加工单与水洗唛必须**同层**可选（issue #7870）"
        )
        unknown = sorted(set(docs) - set(print_targets(doc_lib)))
        assert unknown == [], f"单据标签里出现了 `PRINT_TARGETS` 之外的目标位 {unknown}"
        wiring = production_selector_wiring(page)
        assert wiring == [], f"生产明细页的打印层选择器没接线，缺 {wiring}"
        assert processing_doc_mounts(page) == 2, (
            "加工单纸面应有**两处** `<ProcessingDoc>`：页级挂载（真正上纸的那一份）+ 预览副本"
            f"（`inline`）；实测 {processing_doc_mounts(page)} 处 —— 缺页级那份 = 打印出空白纸"
        )


class TestRealSources:
    """真语料判据（页面 + 打印入口 lib + 作业单区块三份语料）。"""

    def test_g1_no_status_matrix(self) -> None:
        hits = legacy_status_matrix(_read(PAGE_REL))
        assert hits == [], (
            f"页面里又出现了「状态 → 可打单据」矩阵 {hits} —— issue #7544 的口径是"
            "**打印不跟订单状态挂钩**（任何状态都能打）；矩阵一回来，"
            "`closed` / `refund` 这类状态就又会变成死路"
        )

    def test_g2_single_entry_outside_status_branches(self) -> None:
        page = _read(PAGE_REL)
        count = entry_count(page)
        assert count == 1, (
            f"「打印」入口有 {count} 处（应恰好 1 处）—— 多个入口正是 #7544 要消掉的形态；"
            "要打哪一份由打印层里的单据标签选"
        )
        assert not entry_inside_status_section(page), (
            "「打印」入口落进了 `StatusSection`（状态分支所在组件）—— "
            "它必须挂在页面级（与订单状态无关），否则某个状态区又会漏挂/多挂"
        )

    def test_g3_no_handwritten_labels(self) -> None:
        written = handwritten_labels(_read(PAGE_REL))
        assert written == [], (
            f"页面里出现了手写的打印按钮文案 {written} —— 单据名必须取 "
            "`PRINT_TARGET_SPECS[*].title`（与纸面自检层同一份真值）"
        )

    def test_g4_selector_is_wired_and_valid(self) -> None:
        page = _read(PAGE_REL)
        doc_lib = _read(PRINT_DOC_REL)
        missing = missing_required_docs(page)
        assert missing == [], f"可打印单据清单里缺了 {missing}（商家会少一张纸）"
        unknown = unknown_docs(page, doc_lib)
        assert unknown == [], (
            f"清单里出现了 `PRINT_TARGETS` 之外的目标位 {unknown} —— 错键 ⇒ 该单据永远选不中"
        )
        wiring = selector_wiring(page)
        assert wiring == [], (
            f"打印层的单据选择器没接线，缺 {wiring} —— "
            "「入口 → 预览 → 选单据」这条链断在任何一环，商家就只剩默认那一份能打"
        )

    def test_g5_work_order_block_has_no_print_entry(self) -> None:
        hits = block_print_entry(_read(BLOCK_REL))
        assert hits == [], (
            f"「作业单」区块里又有打印入口 {hits} —— 同页两个打印入口正是 #7544 要消掉的形态"
            "（加工单走页面级「打印」→ 选「加工单」）"
        )


class TestDiscriminatingPower:
    """判别力自证：每条判据在**内存变异**上单独变红，并给「只加注释 ⇒ 不红」的对照读数。"""

    PAGE = _read(PAGE_REL)
    PRINT_DOC = _read(PRINT_DOC_REL)
    BLOCK = _read(BLOCK_REL)

    def test_g1_readding_matrix_is_red(self) -> None:
        mutated = self.PAGE.replace(
            "const ORDER_PRINT_DOCS",
            "const PRINT_TARGETS_BY_STATUS: Record<OrderStatus, PrintTarget[]> = { closed: [] }\n"
            "const ORDER_PRINT_DOCS",
        )
        assert mutated != self.PAGE, "注入未生效（锚点漂移）⇒ 红证自己是空断言"
        assert "PRINT_TARGETS_BY_STATUS" in legacy_status_matrix(mutated)
        assert legacy_status_matrix(self.PAGE) == []  # 对照：原文不红

    def test_g2_second_entry_is_red(self) -> None:
        duplicated = self.PAGE.replace(
            "<StatusSection",
            f"<span {ENTRY_MARKER} />\n      <StatusSection",
            1,
        )
        assert duplicated != self.PAGE, "注入未生效（锚点漂移）⇒ 红证自己是空断言"
        assert entry_count(duplicated) == 2
        assert entry_count(self.PAGE) == 1  # 对照

    def test_g2_entry_inside_status_section_is_red(self) -> None:
        # 把入口从页面级搬进 `StatusSection` 的**函数体**（= 回退成「跟状态走」的形态）
        mutated = self.PAGE.replace(ENTRY_MARKER, 'data-testid="moved-away"', 1)
        mutated = mutated.replace(
            "  const refunded = (order.refundAmount ?? 0) > 0",
            '  const movedEntry = <span data-testid="order-print-entry" />\n'
            "  const refunded = (order.refundAmount ?? 0) > 0",
            1,
        )
        assert mutated != self.PAGE, "注入未生效（锚点漂移）"
        assert entry_inside_status_section(mutated) is True
        assert entry_inside_status_section(self.PAGE) is False  # 对照

    def test_g3_handwritten_label_is_red(self) -> None:
        mutated = self.PAGE.replace(
            "        <Button\n          variant=\"secondary\"",
            "        <button>打印销售单</button>\n        <Button\n          variant=\"secondary\"",
            1,
        )
        assert mutated != self.PAGE, "注入未生效（锚点漂移）⇒ 红证自己是空断言"
        assert handwritten_labels(mutated) == ["打印销售单"]
        assert handwritten_labels(self.PAGE) == []  # 对照

    def test_g4_broken_wiring_is_red(self) -> None:
        assert "docs={ORDER_PRINT_DOCS}" in strip_comments(self.PAGE)
        missing_docs = self.PAGE.replace("docs={ORDER_PRINT_DOCS}", "")
        assert selector_wiring(missing_docs) == ["docs={ORDER_PRINT_DOCS}"]
        missing_select = self.PAGE.replace("onSelect={selectPreview}", "")
        assert selector_wiring(missing_select) == ["onSelect={selectPreview}"]
        assert selector_wiring(self.PAGE) == []  # 对照
        # 错键（`'sale'`）⇒ unknown_docs 判红（对照读数：原文是空集）
        wrong_key = self.PAGE.replace(
            "const ORDER_PRINT_DOCS = ['sales'", "const ORDER_PRINT_DOCS = ['sale'"
        )
        assert wrong_key != self.PAGE, "注入未生效（锚点漂移）"
        assert unknown_docs(wrong_key, self.PRINT_DOC) == ["sale"]
        assert unknown_docs(self.PAGE, self.PRINT_DOC) == []
        # 缺一份必打单据 ⇒ missing_required_docs 判红
        dropped = self.PAGE.replace(
            "const ORDER_PRINT_DOCS = ['sales', 'quotation', 'shipment']",
            "const ORDER_PRINT_DOCS = ['sales', 'quotation']",
        )
        assert dropped != self.PAGE, "注入未生效（锚点漂移）"
        assert missing_required_docs(dropped) == ["shipment"]

    def test_g5_block_print_entry_is_red(self) -> None:
        mutated = self.BLOCK.replace(
            "  onReloadReady,",
            "  onPrintProcessing,\n  onReloadReady,",
            1,
        )
        assert mutated != self.BLOCK, "注入未生效（锚点漂移）⇒ 红证自己是空断言"
        assert block_print_entry(mutated) == ["onPrintProcessing"]
        assert block_print_entry(self.BLOCK) == []  # 对照

    def test_g7_readding_processing_doc_is_red(self) -> None:
        """G7 红证：把加工单标签加回订单详情页的清单 ⇒ 必红；对照 = 原文为空集。"""
        mutated = self.PAGE.replace(
            "const ORDER_PRINT_DOCS = ['sales', 'quotation', 'shipment']",
            "const ORDER_PRINT_DOCS = ['sales', 'processing', 'quotation', 'shipment']",
        )
        assert mutated != self.PAGE, "注入未生效（锚点漂移）⇒ 红证自己是空断言"
        assert "ORDER_PRINT_DOCS 含 processing" in order_page_processing_leaks(mutated)
        assert order_page_processing_leaks(self.PAGE) == []  # 对照

    def test_g8_dropping_either_doc_is_red(self) -> None:
        """G8 红证：生产明细页少一份纸 / 选择器断线 / 缺页级挂载 ⇒ 各自单独变红。"""
        prod = _read(PRODUCTION_PAGE_REL)
        doc_lib = _read(PRINT_DOC_REL)
        no_processing = prod.replace("['labels', 'processing']", "['labels']", 1)
        assert no_processing != prod, "注入未生效（锚点漂移）"
        assert "processing" not in production_print_docs(no_processing, doc_lib)
        assert "processing" in production_print_docs(prod, doc_lib)  # 对照
        no_docs = prod.replace("docs={printDocs}", "", 1)
        assert production_selector_wiring(no_docs) == ["docs={printDocs}"]
        assert production_selector_wiring(prod) == []  # 对照
        # 对照读数：只加注释 ⇒ 不红
        commented = prod.replace(
            "const printDocs", "// 说明：这里给出 labels + processing 两份纸\n  const printDocs", 1
        )
        assert production_print_docs(commented, doc_lib) == production_print_docs(prod, doc_lib)

    def test_g6_comment_only_change_is_not_red(self) -> None:
        """对照读数：只往页面里加**注释**（哪怕注释里写满按钮名 / 旧矩阵名）⇒ 一条判据都不该红。"""
        mutated = self.PAGE.replace(
            "const ORDER_PRINT_DOCS",
            "// 说明：改前这里是 PRINT_TARGETS_BY_STATUS 矩阵，按钮叫 打印发货单 / 打印报价单 / "
            "打印加工单 / 打印销售单\nconst ORDER_PRINT_DOCS",
        )
        assert mutated != self.PAGE, "注入未生效（锚点漂移）"
        assert handwritten_labels(mutated) == []
        assert legacy_status_matrix(mutated) == []
        assert entry_count(mutated) == 1
