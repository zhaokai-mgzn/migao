# case_ids: UI-040, UI-053, UI-062
"""打印单据**共享隔离约定**守卫（issue #4983；机制来自 #4965 的实测）。

## 病根（实测，不是推断）

打印隔离的选择器若按「**自己那一份**」写 —— `body > *:not(.<自己>-print-area) { display:none !important }`
—— 在**同一页挂两份打印单据**时，每一份都会把**对方**整份藏掉（对方也是 `body > *` 下的非自己子级）。

#4965 实测形态：locator 已解析出 `data-print-target="shipment"`，元素却仍 `hidden`；第一版按
「visibility 同特异性」修是**错的**，真因就是这条。修法 = **共享标记类**：所有门户式单据容器都带
`print-doc`，隔离选择器统一为 `body > *:not(.print-doc)`。

## 冻结口径

**门户式（`createPortal` 到 `document.body`）打印单据**必须同时满足：
1. 容器（`className=` 且含 `-print-area` 的那一行）**带共享标记类 `print-doc`**；
2. 隔离选择器**恰好**是 `body > *:not(.print-doc)` —— **不得**出现 `body > *:not(.<自己>-print-area)`。

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| C1 | 每个受管门户式单据的容器带 `print-doc` | 去掉 `print-doc` ⇒ 必红 |
| C2 | 隔离选择器 = 共享写法，且不含「自己那一份」的写法 | 改回老写法 ⇒ 必红 |
| C3 | **反空跑**：登记表非空 + 每个登记路径**存在**（路径漂移不得静默跳过） | 清空登记表 / 改坏路径 ⇒ 必红 |
| C4 | **已登记的非符合形态仍须非符合**（死亡条件） | 给它加上 `print-doc` ⇒ 必红（必须销账并转正） |
| C5 | 注入式红证 + **内容指纹**自证（禁 mtime/size，issue #4260） | 注入未生效 ⇒ 必红 |
| C6 | **纸面收款码只属于报价单**（issue #7589）：其余受管单据的去注释代码里不得出现收款码痕迹 | 往销售单加回收款码块 ⇒ 必红 |
| C7 | C6 的注入式红证 + 负控：注入 `usePaymentQrcodes` ⇒ 必红；允许清单内的报价单**确实**在印码且不被误判红 | 红证空跑 / 白名单空转 ⇒ 必红 |

⚠️ **为什么 C4 是反向判据**：非符合登记表若只许"加了就红、永远留着"，就会退化成**永久豁免**
（本仓反复登记的反模式）。它必须有**死亡条件** —— 这里就是「它一旦符合新约定 ⇒ 登记必须销账并转正」。
⚠️ **判据按「去注释后的代码」判定**：三份单据的文件头都**用注释解释**了这个坑（会写出老写法当反例），
按原文判定会把解释性注释判成违规 = 假红。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 受管的**门户式**打印单据（`createPortal` 到 `document.body` 的独立单据）
PORTALED_PRINT_DOCS: tuple[str, ...] = (
    # 发货单自 issue #7902 起整体退场（纸统一在销售订单详情的打印层出）⇒ 不再受管
    "frontend/admin-web/src/components/orders/QuotationDoc.tsx",
    "frontend/admin-web/src/components/production/TaskCardPrint.tsx",
    # issue #5651 新增的两份单据（A4 加工单 / 三联纸销售单）—— 与既有三份同一隔离约定
    "frontend/admin-web/src/components/orders/ProcessingDoc.tsx",
    "frontend/admin-web/src/components/orders/SalesDoc.tsx",
)

#: **已登记的非符合形态**（文件, 理由 + **死亡条件**）—— 逐条判断后登记，不是一律加白
KNOWN_NON_CONFORMING: tuple[tuple[str, str], ...] = (
    (
        "frontend/admin-web/src/components/orders/ProcessingOrderBlock.tsx",
        "**in-flow 打印区**（`.po-print-area` 是页面内的区块，**不是** portal 到 body 的独立单据）："
        "它用的是**已废弃**的 `body * { visibility: hidden }` 形态 —— 既有门户式单据注释里明写该形态的"
        "病根（隐藏元素**仍占版面高度** ⇒ 按隐藏内容高度分页、打出空白第二页，issue #3896）。"
        "本单不改它：它印的是「页面里的加工单区块」而不是独立单据，改成门户式属**产品裁定**"
        "（且它与门户式单据共页时还有一条**既有**缺陷：点它自己的「打印」会被门户单据的 "
        "`body > *:not(.print-doc)` 把整个外壳 `display:none` 掉 —— 已登记在 issue #4983，本单不修）。"
        "**死亡条件**：它一旦改成 `createPortal` 到 body 的独立单据（或开始使用 `print-doc` / 共享选择器）"
        "⇒ 本守卫 C4 判红 ⇒ **必须把这条销账并转入 `PORTALED_PRINT_DOCS`**。",
    ),
)

#: 共享标记类与共享隔离选择器（唯一写法）
SHARED_MARKER = "print-doc"
SHARED_SELECTOR = "body > *:not(.print-doc)"

#: 「自己那一份」的违规写法（`body > *:not(.<x>-print-area)`）—— **只在去注释后的代码里查**
_SELF_SELECTOR_RE = re.compile(r"body\s*>\s*\*\s*:\s*not\(\s*\.[a-zA-Z-]*-print-area\s*\)")
#: 容器行：`className=` 且含 `-print-area`（CSS 块里的 `.x-print-area { … }` 不含 `className=` ⇒ 天然排除）
_CONTAINER_RE = re.compile(r"className=.*-print-area")


def _read(rel: str) -> str:
    """读一个受管文件；**不存在 ⇒ 直接失败**（路径漂移不得退化成静默跳过 = 空跑通过）。"""
    path = REPO_ROOT / rel
    if not path.is_file():
        raise AssertionError(f"受管文件不存在：{rel} —— 路径漂移 / 文件被删 ⇒ 红（**不得**静默跳过）")
    return path.read_text(encoding="utf-8")


def _strip_comments(src: str) -> str:
    """剥掉 `//` 与 `/* */` 注释（**字符串字面量内的不剥**，含模板串）。

    判据不得把注释里的反例（三份单据的文件头都在解释「老写法为什么错」）判成违规 —— 那是假红，
    会逼人删掉解释性注释。字符串感知是必须的：`'https://…'` 里的 `//` 不是注释。
    """
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


def _container_line(code: str) -> str:
    """该单据的**容器行**（`className=` 且含 `-print-area`）；找不到 ⇒ `""`（判据据此判红）。"""
    for line in code.splitlines():
        if _CONTAINER_RE.search(line):
            return line.strip()
    return ""


def _doc_problems(code: str) -> list[str]:
    """单个门户式单据的违规（C1 容器缺标记类 / C2 用了「自己那一份」的选择器）。纯函数，便于注入式红证。"""
    problems: list[str] = []
    container = _container_line(code)
    if container == "":
        problems.append("找不到容器行（`className=` 且含 `-print-area`）—— 形态漂移，判据无从判定")
    elif SHARED_MARKER not in container:
        problems.append(f"容器行缺共享标记类 `{SHARED_MARKER}`：{container}")
    if SHARED_SELECTOR not in code:
        problems.append(f"隔离选择器不是共享写法 `{SHARED_SELECTOR}`（打印时会与兄弟单据互相藏掉）")
    hit = _SELF_SELECTOR_RE.search(code)
    if hit:
        problems.append(f"出现「自己那一份」的隔离选择器 `{hit.group(0)}` ⇒ 会把兄弟单据整份 display:none")
    return problems


def _fingerprint(text: str) -> str:
    """内容指纹（issue #4260 红证卫生：**禁 mtime / size** —— 它们会被同秒写入骗过）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── C1 / C2：每个门户式单据都符合共享约定 ─────────────────────────────────────

def test_c1_c2_portaled_print_docs_follow_the_shared_convention():
    """C1 + C2：每个受管门户式单据 ① 容器带 `print-doc` ② 隔离选择器 = `body > *:not(.print-doc)`。"""
    offenders: list[str] = []
    for rel in PORTALED_PRINT_DOCS:
        for problem in _doc_problems(_strip_comments(_read(rel))):
            offenders.append(f"{rel}: {problem}")
    assert offenders == [], (
        "门户式打印单据没有遵守**共享隔离约定**（issue #4983）—— 按「自己那一份」写选择器会让"
        "同页的两份单据**互相藏掉**（#4965 实测：`data-print-target` 已置位却仍 hidden）：\n  "
        + "\n  ".join(offenders)
        + f"\n修法：容器加 `{SHARED_MARKER}`，隔离选择器统一 `{SHARED_SELECTOR}`"
    )


# ── C3：反空跑 ───────────────────────────────────────────────────────────────

def test_c3_registry_is_not_vacuous():
    """C3：登记表非空 + 每个登记路径**存在**（判据不得在空表 / 漂移路径上静默通过）。"""
    # 下界与成员数**必须同步**（#5007②，判据 = test_gate_coverage_and_same_source.py 的
    # `test_frozen_declarations_are_pinned_exactly` + declaration_gate_registry.json 的逐项成员）
    # issue #7902：发货单退场 ⇒ 门户式单据 5 → 4（报价单 / 加工单 / 销售单 / 洗水唛）。
    assert len(PORTALED_PRINT_DOCS) >= 4, (
        "受管门户式单据清单被清空/缩短到 <5 ⇒ 本守卫会空跑通过（判据必须能判红）"
    )
    for rel in PORTALED_PRINT_DOCS:
        _read(rel)  # 不存在 ⇒ 抛错（不静默跳过）
    for rel, reason in KNOWN_NON_CONFORMING:
        assert len(reason.strip()) >= 20, f"`{rel}` 的非符合登记没写理由/死亡条件"
        _read(rel)


# ── C4：已登记的非符合形态仍须非符合（死亡条件）────────────────────────────────

def test_c4_known_non_conforming_entries_must_die_when_they_conform():
    """C4：非符合登记表**只许缩短** —— 目标一旦符合新约定，登记必须销账并转正。

    判据形态 = 「反向断言」：若某个已登记的非符合文件**已经**带 `print-doc` / 共享选择器 ⇒ 判红
    （报错指向正确行动：「你修好了，请把它转入 `PORTALED_PRINT_DOCS` 并删掉这条登记」）。
    """
    stale: list[str] = []
    for rel, _reason in KNOWN_NON_CONFORMING:
        code = _strip_comments(_read(rel))
        if SHARED_MARKER in code or SHARED_SELECTOR in code:
            stale.append(rel)
    assert stale == [], (
        "非符合登记**已过期**（该文件已开始使用共享打印约定）⇒ 请把条目从 `KNOWN_NON_CONFORMING` 删掉"
        "并转入 `PORTALED_PRINT_DOCS`（登记表只许缩短）：\n  " + "\n  ".join(stale)
    )


# ── C5：注入式红证 + 内容指纹自证 ─────────────────────────────────────────────

def test_c5_injected_self_selector_is_red():
    """C5：往临时副本塞「自己那一份」的选择器 / 去掉 `print-doc` ⇒ 判据必红；并用**内容指纹**自证生效。"""
    rel = PORTALED_PRINT_DOCS[0]
    original = _strip_comments(_read(rel))
    assert _doc_problems(original) == [], (
        f"`{rel}` 原文件本应干净（C1/C2 已单独判）—— 这里先红说明判据或预期已变：\n  "
        + "\n  ".join(_doc_problems(original))
    )

    # 注入 A：隔离选择器退回「自己那一份」
    injected_a = original.replace(SHARED_SELECTOR, "body > *:not(.quotation-print-area)")
    assert injected_a != original, f"`{rel}` 里找不到注入点 `{SHARED_SELECTOR}` ⇒ 本红证会**空跑**"
    assert _fingerprint(injected_a) != _fingerprint(original), "注入后内容指纹未变（**禁 mtime/size**）"
    assert _doc_problems(injected_a), "注入「自己那一份」的选择器后判据**没判红** ⇒ 守卫是空判据"

    # 注入 B：容器去掉共享标记类
    # 注入 B：#7902 起部分单据里 `print-doc` 出现多次（容器 + 选择器）⇒ 必须**全部**去掉
    # 才等价于「容器缺共享标记类」这一形态（只去一处会让红证静默失效）
    injected_b = re.sub(r"\bprint-doc\b", "", original)
    assert injected_b != original, "找不到 `print-doc` 注入点 ⇒ 本红证会**空跑**"
    assert _doc_problems(injected_b), "去掉 `print-doc` 后判据**没判红** ⇒ 守卫是空判据"


# ── C6 / C7：纸面收款码只属于报价单（issue #7589）──────────────────────────────

#: 允许在纸面上读取 / 渲染企业收款码的单据（**唯一**一份）。
#: 销售单自 issue #7589 起不再印收款码（用户 2026-10-24 逐字「销售单打印处右下角的二维码移除掉」）；
#: 加工单的二维码已在 issue #7219 移除。这串只许**缩短**：新增任何带码单据都要先问「用户要它在纸上吗」。
PAYMENT_QR_ALLOWED_DOCS: frozenset[str] = frozenset(
    {"frontend/admin-web/src/components/orders/QuotationDoc.tsx"}
)

#: 收款码的**纸面痕迹**（读取口 / testid 前缀 / 渲染投影变量名）—— 只在**去注释后**的代码里查，
#: 否则解释性注释（本文件与各单据文件头大量提及）会被判成违规 = 假红。
_PAYMENT_QR_RE = re.compile(r"usePaymentQrcodes|sales-qr-|qrEntries")


def _payment_qr_problems(rel: str, code: str) -> list[str]:
    """该单据是否在纸面引入收款码。纯函数，便于注入式红证。允许清单内的单据恒为 `[]`。"""
    if rel in PAYMENT_QR_ALLOWED_DOCS:
        return []
    hits = sorted(set(_PAYMENT_QR_RE.findall(code)))
    return [f"{rel}: 出现收款码痕迹 {hits}"] if hits else []


def test_c6_payment_qr_belongs_to_quotation_paper_only():
    """C6：非报价单的受管纸面**不得**出现收款码 —— 销售单页脚只留温馨提示（issue #7589）。"""
    offenders: list[str] = []
    for rel in PORTALED_PRINT_DOCS:
        offenders.extend(_payment_qr_problems(rel, _strip_comments(_read(rel))))
    assert offenders == [], (
        "销售单 / 发货单 / 加工单纸面**不印企业收款码**（issue #7589 用户裁定「销售单打印处右下角的"
        "二维码移除掉」；收款码只属于报价单）：\n  "
        + "\n  ".join(offenders)
        + "\n修法：删掉该单据的 `usePaymentQrcodes` 与 QR 块；若确有新单据要带码，先加进"
        " `PAYMENT_QR_ALLOWED_DOCS`（这份清单只许缩短，加项须有用户裁定）。"
    )


def test_c7_payment_qr_guard_is_not_vacuous():
    """C7：注入式红证 —— 往销售单注入 `usePaymentQrcodes` ⇒ C6 必红；报价单（允许清单）注入后仍绿。"""
    rel = "frontend/admin-web/src/components/orders/SalesDoc.tsx"
    original = _strip_comments(_read(rel))
    assert _payment_qr_problems(rel, original) == [], (
        f"`{rel}` 原文件本应干净（C6 已单独判）—— 这里先红说明判据或预期已变：{_payment_qr_problems(rel, original)}"
    )
    injected = original + "\nconst qrcodes = usePaymentQrcodes(paymentQrcodes)\n"
    assert injected != original, "注入点没生效 ⇒ 本红证会**空跑**"
    assert _fingerprint(injected) != _fingerprint(original), "注入后内容指纹未变（**禁 mtime/size**）"
    assert _payment_qr_problems(rel, injected), "注入 `usePaymentQrcodes` 后判据**没判红** ⇒ 守卫是空判据"
    # 负控 ①：允许清单里的单据**确实**在印收款码 —— 否则白名单是空转的，且正则可能从未命中过真实代码
    allowed = "frontend/admin-web/src/components/orders/QuotationDoc.tsx"
    allowed_code = _strip_comments(_read(allowed))
    assert _PAYMENT_QR_RE.search(allowed_code), (
        "允许清单里的报价单已经不再印收款码 ⇒ `PAYMENT_QR_ALLOWED_DOCS` 必须缩短（白名单只许缩短）"
    )
    # 负控 ②：允许清单内的单据不会被 C6 判红（否则白名单失效 = 等于把报价单也砍了）
    assert _payment_qr_problems(allowed, allowed_code) == [], "允许清单内的单据被误判红 ⇒ 白名单失效"
    # 反空跑：受管清单本身不得被清空（清空后 C6 恒绿）
    assert len(PORTALED_PRINT_DOCS) >= 4, "受管清单被清空到 <4 ⇒ C6 会空跑通过"
