# case_ids: MC-085
"""订单详情**打印入口矩阵**守卫（issue #6434）—— 让「又一个状态区漏挂打印入口」进不来。

## 病根（实测读数，不是推断）

订单详情页的四个纸质单据入口（发货单 / 报价单 / 加工单 / 销售单）原先在
`status === 'shipped'` 与 `status === 'completed'` 两个分支里**各写一份 JSX 字面量**
（现取 `origin/main`：`打印销售单` 只出现在这两处；`git log -S "打印销售单"` 只有一个提交 = #5669 引入）。
后果：订单停在**「待发货 / 生产中 / 待付款」**时，商家打开订单详情**一个打印按钮都没有**
（2026-10-06 用户报障），而这三张单据恰恰是发货**之前**就要用的
（销售单随货给客户、加工单下车间、报价单先行）。

⇒ 修法 = 收敛成 `PRINT_TARGETS_BY_STATUS` **一张表**（唯一声明处），按钮文案取
`PRINT_TARGET_SPECS[*].title`（与纸面自检层同一份真值）。本守卫钉住「收敛」这件事**本身**：
再抄一份字面量、或新增状态时忘了登记 ⇒ 当场红。

## 冻结判据（每条都能单独变红，见 `TestDiscriminatingPower`）

| # | 判据 | 红证（怎么让它**单独**变红） |
|---|---|---|
| G1 | 矩阵覆盖 `OrderStatus` 的**全部**取值 | 从矩阵里删掉一个状态键（如 `closed`）⇒ 红 |
| G2 | 四个「有单据可出」的状态必须**非空** | 把 `pending_shipment` 改成 `[]` ⇒ 红 |
| G3 | 页面里**不得**再出现手写的打印按钮字面量 | 把 `<PrintActions …/>` 换回 `打印销售单` 字面量 ⇒ 红 |
| G4 | 每个状态分支都要经 `<PrintActions>` 渲染（≥4 处接线）+ 定义只有一份 | 摘掉 pending_shipment 那处接线 ⇒ 红 |
| G5 | 判别力自证 + **对照读数**（只加注释 ⇒ 不红） | 注入未生效 ⇒ 红（红证自己是空断言） |

⚠️ **判据按「去注释后的代码」判定**：页面文件头用注释解释这些坑（会**写出**几个按钮名），
按原文判定会把解释性注释判成违规 = 假红。故本文件自带字符串感知的注释剥离器。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE_REL = "frontend/admin-web/src/app/(dashboard)/orders/[id]/OrderDetail.tsx"
TYPES_REL = "frontend/admin-web/src/types/index.ts"

#: 页面里**不许**手写的按钮文案（必须来自 `PRINT_TARGET_SPECS[*].title`）
HANDWRITTEN_LABELS: tuple[str, ...] = ("打印发货单", "打印报价单", "打印加工单", "打印销售单")

#: 必须有入口的状态（其余状态可以为空 —— 那是产品口径，不在这里钉）
STATUSES_REQUIRING_ENTRIES: tuple[str, ...] = (
    "pending_payment",
    "pending_shipment",
    "shipped",
    "completed",
)

#: 状态分支里 `<PrintActions>` 接线的最少处数（待付款 / 待发货 / 已发货 / 已完成）
MIN_WIRINGS = 4


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def strip_comments(src: str) -> str:
    """字符串感知地剥掉注释（`//` 行注释、`/* */` 块注释、JSX `{/* */}`）。

    保留字符串字面量内容（判据只看页面里有没有手写按钮文案，不解析语义）。
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


def order_status_members(types_src: str) -> list[str]:
    """现取 `OrderStatus` 联合类型的全部成员（真值在 `types/index.ts`，不在这里硬编码）。"""
    m = re.search(r"export type OrderStatus\s*=\s*([^\n;]+)", types_src)
    if not m:
        raise AssertionError(f"{TYPES_REL} 里找不到 `export type OrderStatus` 定义（判据 fail-closed）")
    members = re.findall(r"'([a-z_]+)'", m.group(1))
    if not members:
        raise AssertionError(f"{TYPES_REL} 的 `OrderStatus` 一个成员都没解析出来（判据 fail-closed）")
    return members


def matrix_entries(page_src: str) -> dict[str, list[str]]:
    """解析页面里的 `PRINT_TARGETS_BY_STATUS` 矩阵。"""
    m = re.search(r"const PRINT_TARGETS_BY_STATUS\s*:[^=]*=\s*\{(.*?)\n\}", page_src, re.S)
    if not m:
        raise AssertionError(
            f"{PAGE_REL} 里找不到 `PRINT_TARGETS_BY_STATUS` 矩阵 —— "
            "打印入口必须是**一张表**（唯一声明处），不是散在各状态分支里的字面量"
        )
    entries: dict[str, list[str]] = {}
    for key, arr in re.findall(r"^\s*(\w+):\s*\[([^\]]*)\]", m.group(1), re.M):
        entries[key] = re.findall(r"'([a-z]+)'", arr)
    if not entries:
        raise AssertionError("`PRINT_TARGETS_BY_STATUS` 解析出 0 条（判据 fail-closed）")
    return entries


def missing_statuses(page_src: str, types_src: str) -> list[str]:
    """G1：`OrderStatus` 里有、矩阵里没有的状态。"""
    return sorted(set(order_status_members(types_src)) - set(matrix_entries(page_src)))


def empty_required_statuses(page_src: str) -> list[str]:
    """G2：矩阵里存在但**空**的必填状态。"""
    entries = matrix_entries(page_src)
    return [s for s in STATUSES_REQUIRING_ENTRIES if not entries.get(s)]


def handwritten_labels(page_src: str) -> list[str]:
    """G3：页面代码里手写的打印按钮文案（注释不算）。"""
    code = strip_comments(page_src)
    return [label for label in HANDWRITTEN_LABELS if label in code]


def print_actions_wirings(page_src: str) -> int:
    """G4：`<PrintActions>` 的接线处数。"""
    return strip_comments(page_src).count("<PrintActions")


class TestRealSources:
    """真语料判据（`origin/main` 上的页面 + 类型定义）。"""

    def test_matrix_covers_every_order_status(self) -> None:
        missing = missing_statuses(_read(PAGE_REL), _read(TYPES_REL))
        assert missing == [], (
            f"`PRINT_TARGETS_BY_STATUS` 漏了状态 {missing} —— 新增状态必须在矩阵里显式登记"
            "（空数组也是登记；漏登记 ⇒ 该状态下一个打印入口都没有）"
        )

    def test_statuses_requiring_entries_are_not_empty(self) -> None:
        empty = empty_required_statuses(_read(PAGE_REL))
        assert empty == [], (
            f"状态 {empty} 的打印入口集合是空的 —— 这几张单据是发货**前**就要用的"
            "（报价单先行 / 销售单随货 / 加工单下车间），清空即用户可见的功能回退"
        )

    def test_page_has_no_handwritten_print_button_labels(self) -> None:
        written = handwritten_labels(_read(PAGE_REL))
        assert written == [], (
            f"页面里出现了手写的打印按钮文案 {written} —— 文案必须取 "
            "`PRINT_TARGET_SPECS[*].title`（与纸面自检层同一份真值）；"
            "再抄一份字面量正是「另一个状态区漏挂入口」的成因"
        )

    def test_every_status_branch_renders_through_print_actions(self) -> None:
        page = _read(PAGE_REL)
        wirings = print_actions_wirings(page)
        assert wirings >= MIN_WIRINGS, (
            f"`<PrintActions>` 只有 {wirings} 处接线（应 ≥{MIN_WIRINGS}）—— "
            "待付款 / 待发货 / 已发货 / 已完成 四个状态区都要经它渲染"
        )
        assert strip_comments(page).count("function PrintActions(") == 1, (
            "`PrintActions` 渲染器必须只有一份（再来一份 ⇒ 又分叉了）"
        )


class TestDiscriminatingPower:
    """判别力自证：每条判据在**内存变异**上单独变红，并给「只加注释 ⇒ 不红」的对照读数。"""

    PAGE = _read(PAGE_REL)
    TYPES = _read(TYPES_REL)

    def test_g1_missing_status_key_is_red(self) -> None:
        mutated = self.PAGE.replace("  closed: [],\n", "")
        assert missing_statuses(mutated, self.TYPES) == ["closed"], "删掉状态键却没红 ⇒ G1 是空断言"
        assert missing_statuses(self.PAGE, self.TYPES) == []  # 对照：原文不红

    def test_g2_emptied_required_status_is_red(self) -> None:
        mutated = self.PAGE.replace(
            "  pending_shipment: ['quotation', 'processing', 'sales'],",
            "  pending_shipment: [],",
        )
        assert mutated != self.PAGE, "注入未生效（锚点漂移）⇒ 红证自己是空断言"
        assert empty_required_statuses(mutated) == ["pending_shipment"]
        assert empty_required_statuses(self.PAGE) == []  # 对照

    def test_g3_handwritten_label_is_red(self) -> None:
        mutated = self.PAGE.replace(
            "<PrintActions status={status} onOpen={onPrint} />",
            "<button>打印销售单</button>",
        )
        assert mutated != self.PAGE, "注入未生效（锚点漂移）⇒ 红证自己是空断言"
        assert handwritten_labels(mutated) == ["打印销售单"]
        assert handwritten_labels(self.PAGE) == []  # 对照

    def test_g4_removed_wiring_is_red(self) -> None:
        mutated = self.PAGE.replace(
            "<PrintActions status={status} onOpen={onPrint} />",
            "",
            1,
        )
        assert mutated != self.PAGE, "注入未生效（锚点漂移）⇒ 红证自己是空断言"
        assert print_actions_wirings(mutated) == MIN_WIRINGS - 1
        assert print_actions_wirings(self.PAGE) >= MIN_WIRINGS  # 对照

    def test_g5_comment_only_change_is_not_red(self) -> None:
        """对照读数：只往页面里加**注释**（哪怕注释里写满按钮名）⇒ 一条判据都不该红。"""
        mutated = self.PAGE.replace(
            "const PRINT_TARGETS_BY_STATUS",
            "// 说明：这些入口分别对应 打印发货单 / 打印报价单 / 打印加工单 / 打印销售单\n"
            "const PRINT_TARGETS_BY_STATUS",
        )
        assert mutated != self.PAGE, "注入未生效（锚点漂移）"
        assert handwritten_labels(mutated) == []
        # 矩阵结构判据同样不受注释影响
        assert missing_statuses(mutated, self.TYPES) == []
        assert empty_required_statuses(mutated) == []
