# case_ids: UI-026
"""打印**单一纸型**守卫（issue #5914）—— 让「一次打印多份单据上纸」这一类进不来。

## 病根（本单实测，不是推断）

四份单据同页共存（订单详情页）时，三条互相独立的机制同时失效：

| # | 形态 | 实测读数（真实 Chromium） |
|---|---|---|
| ① | `window.print()` 与 `setState(target)` 写在**同一个事件处理器**里 | `at-call:TARGET_MISSING` / `beforeprint:TARGET_MISSING` ⇒ 目标单据拿不到 `visibility: visible` ⇒ **首次打印空白纸** |
| ② | 每份单据都**无条件**发表自己的 `@page` | 同一文档多条 `@page` ⇒ **最后声明的那条赢**：点「打印发货单」出纸 240.96×140.04mm（= 销售单的三联纸），6 页 |
| ③ | 非目标单据只是 `visibility: hidden` | **仍占版面高度** ⇒ 空白页（#3896 的同一病根） |

⇒ 冻结口径：**一次打印只允许一份单据在版面上**：`window.print()` 只有一个入口（且在目标提交之后
调用），`@page` 只在本次目标是本单据时发表，打印态显形规则按 `[data-print-target]` 限定。

## 冻结判据（五条，逐条可红）

| # | 判据 | 红证（怎么让它**单独**变红） |
|---|---|---|
| C1 | `window.print()` 在 `src/**` 里**恰好**出现在唯一入口文件里 | 任何页面/组件里再写一处裸 `window.print()` ⇒ 红 |
| C2 | 每份受管单据的 `@page` **条件化到本次目标**（`printTarget === '<target>' && … printPageRule(…)`） | 去掉条件（退回无条件发表）⇒ 红 |
| C3 | 每份受管单据的打印态显形规则带 `[data-print-target='<target>']` | 把限定去掉（退回 `.x-print-area { display:block }`）⇒ 红 |
| C4 | 🔴 **纸面读的订单字段必须在详情 DTO 里真的下发**（`OrderDetailResponse`） | 删掉 DTO 的 `createdByName` ⇒ 红（这正是本单修的那个「纸面印 `未采集`」的病根） |
| C5 | 注入式红证 + **内容指纹**自证（禁 mtime / size，issue #4260） | 注入未生效 ⇒ 红（红证自己是空断言） |

⚠️ **判据按「去注释后的代码」判定**：各单据的文件头**用注释解释**这些坑（会写出反例），
按原文判定会把解释性注释判成违规 = 假红。故本文件自带字符串感知的注释剥离器
（与 `test_print_media_matrix_guard.py` 的同名实现各自独立：共享实现会引入「谁先 import 谁生效」
的隐式耦合）。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "frontend" / "admin-web" / "src"

#: `window.print()` 的**唯一**入口（新增第二处 ⇒ 红）。这条例外台账**只许缩短**。
PRINT_ENTRY_FILES: tuple[str, ...] = ("frontend/admin-web/src/lib/print-doc.ts",)

#: 受管单据：（文件, 本次打印目标位）
#: 🔴 新增可打印单据必须在这里登记 —— 未登记的单据不会发表纸型，**打印时什么也不出**（静默不出纸）。
PRINT_DOC_TARGETS: tuple[tuple[str, str], ...] = (
    ("frontend/admin-web/src/components/orders/ShipmentDoc.tsx", "shipment"),
    ("frontend/admin-web/src/components/orders/QuotationDoc.tsx", "quotation"),
    ("frontend/admin-web/src/components/orders/ProcessingDoc.tsx", "processing"),
    ("frontend/admin-web/src/components/orders/SalesDoc.tsx", "sales"),
    ("frontend/admin-web/src/components/production/TaskCardPrint.tsx", "labels"),
)

#: C4 的判定面：订单详情页挂在纸面上的四份单据（洗水码读的是部位/快照，不读 `Order` 详情）
ORDER_SURFACE_DOCS: tuple[str, ...] = (
    "frontend/admin-web/src/components/orders/ShipmentDoc.tsx",
    "frontend/admin-web/src/components/orders/QuotationDoc.tsx",
    "frontend/admin-web/src/components/orders/ProcessingDoc.tsx",
    "frontend/admin-web/src/components/orders/SalesDoc.tsx",
)

DETAIL_DTO = "backend/admin-api/src/main/java/com/migao/admin/dto/OrderDetailResponse.java"

#: C4 的**豁免台账**（纸面读了、但详情 DTO 有意不下发的字段）：**只许缩短**，每条必须写明理由。
#: 空表 = 没有豁免（当前状态）。
ORDER_FIELD_EXEMPTIONS: tuple[tuple[str, str], ...] = ()

_TS_SUFFIXES = (".ts", ".tsx")
_SKIP_DIRS = {"node_modules", ".next", "coverage", "dist", "build"}

#: `window.print()` 调用（`window.print()` / `window.print ()`）
_WINDOW_PRINT_RE = re.compile(r"window\s*\.\s*print\s*\(")
#: C2：`printTarget === '<x>' && … printPageRule(…)`（同一个表达式里的条件发表）
_CONDITIONAL_PAGE_RE = re.compile(
    r"printTarget\s*===\s*'(?P<target>[a-z-]+)'\s*&&[\s\S]{0,200}?printPageRule\s*\("
)
#: C3：`.<…>-print-area[data-print-target='<x>'] { … display: block`
_QUALIFIED_DISPLAY_RE = re.compile(
    r"-[a-z-]*print-area\[data-print-target='(?P<target>[a-z-]+)'\]\s*\{[^}]*display:\s*block"
)
#: C4：`order.<ident>`（属性读取）
_ORDER_FIELD_RE = re.compile(r"\border\.([A-Za-z_][A-Za-z0-9_]*)\b")
#: Java DTO 字段声明：`private <Type> <name>;`
_JAVA_FIELD_RE = re.compile(r"private\s+[A-Za-z_][\w.<>\[\]]*\s+([A-Za-z_][A-Za-z0-9_]*)\s*;")


def _read(rel: str) -> str:
    """读受管文件；**不存在 ⇒ 直接失败**（路径漂移不得退化成静默跳过 = 空跑通过）。"""
    path = REPO_ROOT / rel
    if not path.is_file():
        raise AssertionError(f"受管文件不存在：{rel} —— 路径漂移 / 文件被删 ⇒ 红（**不得**静默跳过）")
    return path.read_text(encoding="utf-8")


def _strip_comments(src: str) -> str:
    """剥掉 `//` 与 `/* */` 注释（**字符串字面量内的不剥**，含模板串）。"""
    out: list[str] = []
    i, n = 0, len(src)
    quote: str | None = None
    while i < n:
        ch = src[i]
        if quote is not None:
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
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _src_files() -> list[Path]:
    """`src/**` 下的 TS/TSX 文件（跳过构建产物目录）。"""
    files: list[Path] = []
    for path in sorted(SRC.rglob("*")):
        if not path.is_file() or path.suffix not in _TS_SUFFIXES:
            continue
        if _SKIP_DIRS & set(path.parts):
            continue
        files.append(path)
    return files


def _fingerprint(text: str) -> str:
    """内容指纹（issue #4260 红证卫生：**禁 mtime / size** —— 它们会被同秒写入骗过）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── 判据本体（纯函数，便于注入式红证）─────────────────────────────────────────

def _window_print_files(files: dict[str, str]) -> list[str]:
    """C1：`src/**` 里出现 `window.print(` 的文件（去注释后判定）。"""
    return sorted(rel for rel, code in files.items() if _WINDOW_PRINT_RE.search(_strip_comments(code)))


def _page_problems(rel: str, target: str, code: str) -> list[str]:
    """C2 + C3：`@page` 必须条件化到本次目标；打印态显形规则必须按目标限定。"""
    problems: list[str] = []
    conditional = [m.group("target") for m in _CONDITIONAL_PAGE_RE.finditer(code)]
    if not conditional:
        problems.append(
            "找不到「`printTarget === '<target>' && … printPageRule(…)`」这样的**条件化纸型**声明"
            " —— `@page` 是**文档级**规则，同页多份单据并存时最后声明的那条赢（实测点「打印发货单」"
            "会按销售单的三联纸出纸 = 打废纸）"
        )
    elif target not in conditional:
        problems.append(f"纸型条件化到了 {conditional}，与登记的目标位 `{target}` 不一致")
    qualified = [m.group("target") for m in _QUALIFIED_DISPLAY_RE.finditer(code)]
    if target not in qualified:
        problems.append(
            f"打印态显形规则没有按 `[data-print-target='{target}']` 限定"
            "（实测口径见 {qualified or '（一处都没有）'}）—— 不限定 ⇒ 非目标单据也占版面（空白页）"
        )
    return problems


def _order_field_problems(
    rel: str, code: str, dto_fields: set[str], exemptions: frozenset[str]
) -> list[str]:
    """C4：纸面读的 `order.<x>` 必须真的在详情 DTO 里（否则纸面只会永远印缺值占位）。"""
    used = sorted(set(_ORDER_FIELD_RE.findall(code)))
    missing = [name for name in used if name not in dto_fields and name not in exemptions]
    if not missing:
        return []
    return [
        f"{rel} 读了 `order.{name}`，但 `{DETAIL_DTO}` **没有**这个字段"
        " —— 服务端不下发 ⇒ 纸面只会永远印缺值占位（本单修的正是这一类：制单人）"
        for name in missing
    ]


# ── C1 ────────────────────────────────────────────────────────────────────────

def test_c1_window_print_has_exactly_one_entry():
    """C1：`window.print()` 在 `src/**` 里恰好出现在唯一入口文件里（其余一律走 `usePrintDoc`）。"""
    files = {
        str(path.relative_to(REPO_ROOT)): path.read_text(encoding="utf-8") for path in _src_files()
    }
    hits = _window_print_files(files)
    assert hits == sorted(PRINT_ENTRY_FILES), (
        "`window.print()` 的调用点不在冻结清单里（issue #5914）：\n"
        f"  实测 = {hits}\n  期望 = {sorted(PRINT_ENTRY_FILES)}\n"
        "修法：改用 `lib/print-doc.ts` 的 `usePrintDoc().requestPrint(target)` —— 同 tick 调 "
        "`window.print()` 会让**首次打印变成空白纸**（处理器返回前 React 还没提交 `data-print-target`）；"
        "确要新增入口，必须同时更新 PRINT_ENTRY_FILES 的台账与理由"
    )


# ── C2 + C3 ──────────────────────────────────────────────────────────────────

def test_c2_c3_every_doc_page_rule_is_conditional_and_qualified():
    """C2 + C3：受管单据的纸型条件化 + 打印态显形按目标限定。"""
    offenders: list[str] = []
    for rel, target in PRINT_DOC_TARGETS:
        for problem in _page_problems(rel, target, _strip_comments(_read(rel))):
            offenders.append(f"{rel}: {problem}")
    assert offenders == [], (
        "可打印单据没有遵守「一次只有一份上纸」的冻结口径（issue #5914）：\n  "
        + "\n  ".join(offenders)
    )


def test_c2_c3_registry_is_not_vacuous():
    """登记表非空 + 路径存在（判据不得在空表 / 路径漂移上静默通过）。"""
    assert len(PRINT_DOC_TARGETS) >= 5, (
        f"受管单据清单被缩短到 {len(PRINT_DOC_TARGETS)} 条 ⇒ 本守卫会空跑通过"
    )
    for rel, target in PRINT_DOC_TARGETS:
        _read(rel)
        assert re.fullmatch(r"[a-z][a-z-]*", target), f"{rel} 的目标位形态不合法：{target!r}"


# ── C4 ────────────────────────────────────────────────────────────────────────

def test_c4_paper_fields_must_be_present_in_the_detail_dto():
    """C4：纸面读的订单字段必须在 `OrderDetailResponse` 里真的下发（豁免台账只许缩短）。"""
    dto_fields = set(_JAVA_FIELD_RE.findall(_read(DETAIL_DTO)))
    assert len(dto_fields) >= 15, (
        f"从 {DETAIL_DTO} 只解析出 {len(dto_fields)} 个字段 ⇒ 解析口径失效，C4 会空跑通过"
    )
    exemptions = frozenset(name for name, _ in ORDER_FIELD_EXEMPTIONS)
    for _, reason in ORDER_FIELD_EXEMPTIONS:
        assert len(reason.strip()) >= 20, "C4 的豁免必须写明理由（谁看 / 什么时候能销账）"
    offenders: list[str] = []
    for rel in ORDER_SURFACE_DOCS:
        offenders += _order_field_problems(rel, _strip_comments(_read(rel)), dto_fields, exemptions)
    assert offenders == [], (
        "纸面读了服务端**没有下发**的字段（issue #5914：加工单「制单人」印成「未采集」的病根）：\n  "
        + "\n  ".join(offenders)
        + f"\n修法：在 {DETAIL_DTO} 声明该字段（实体同名即可，`BeanUtils.copyProperties` 会带出）；"
        "确属有意不下发 ⇒ 登记进 ORDER_FIELD_EXEMPTIONS 并写明理由"
    )


def test_c4_ledger_only_shrinks():
    """C4：豁免台账**只许缩短** —— 当前为空（= 没有豁免）。"""
    assert ORDER_FIELD_EXEMPTIONS == (), (
        "C4 的豁免台账被加长了（当前口径 = **零豁免**）：\n  "
        + "\n  ".join(f"{name}: {reason}" for name, reason in ORDER_FIELD_EXEMPTIONS)
        + "\n出口 = 把该字段补进详情 DTO，或在本条判据里**同时**给出「为什么不发」的裁定依据"
    )


# ── C5：注入式红证 + 内容指纹自证 ─────────────────────────────────────────────

def test_c5_injected_regressions_are_red():
    """C5：注入三类回归，判据必须**各自**判红；并用内容指纹自证注入生效。"""
    # ── 注入 A（C1）：在某个页面里再写一处裸 `window.print()` ──
    rel = PRINT_ENTRY_FILES[0]
    entry = _read(rel)
    assert _window_print_files({rel: entry}) == [rel], "入口文件本身本应命中 `window.print(` —— 判据或预期已变"
    injected = {rel: entry, "frontend/admin-web/src/app/(dashboard)/x/page.tsx": "const f = () => { window.print() }"}
    hits = _window_print_files(injected)
    assert hits != sorted(PRINT_ENTRY_FILES), "多一处裸 `window.print()` 却**没判红** ⇒ C1 是空判据"
    assert _fingerprint(str(sorted(injected.items()))) != _fingerprint(str(sorted({rel: entry}.items())))

    # ── 注入 B（C2 + C3）：把销售单的纸型条件化与显式限定都去掉 ──
    sales_rel, sales_target = PRINT_DOC_TARGETS[3]
    sales = _strip_comments(_read(sales_rel))
    assert _page_problems(sales_rel, sales_target, sales) == [], (
        f"`{sales_rel}` 原文件本应干净（C2/C3 已单独判）—— 这里先红说明判据或预期已变"
    )
    no_condition = re.sub(r"\{printTarget === 'sales' && ", "{", sales, count=1)
    assert _fingerprint(no_condition) != _fingerprint(sales), "注入 B 未生效（内容指纹相同）"
    assert _page_problems(sales_rel, sales_target, no_condition), "去掉纸型条件化却**没判红** ⇒ C2 是空判据"
    no_qualifier = sales.replace("-print-area[data-print-target='sales']", "-print-area", 1)
    assert _fingerprint(no_qualifier) != _fingerprint(sales), "注入 B2 未生效（内容指纹相同）"
    assert _page_problems(sales_rel, sales_target, no_qualifier), "去掉目标限定却**没判红** ⇒ C3 是空判据"

    # ── 注入 C（C4）：删掉详情 DTO 的 `createdByName`（本单修的那一处）──
    dto = _read(DETAIL_DTO)
    assert "createdByName" in dto, f"`{DETAIL_DTO}` 里没有 createdByName —— 本单的修复已被回退？"
    stripped = {name for name in _JAVA_FIELD_RE.findall(dto) if name != "createdByName"}
    doc_rel = ORDER_SURFACE_DOCS[2]
    doc_code = _strip_comments(_read(doc_rel))
    assert _order_field_problems(doc_rel, doc_code, stripped, frozenset()) != [], (
        "详情 DTO 少了 `createdByName` 却**没判红** ⇒ C4 是空判据"
    )
    assert _fingerprint(str(sorted(stripped))) != _fingerprint(
        str(sorted(_JAVA_FIELD_RE.findall(dto)))
    ), "注入 C 未生效（内容指纹相同）"
