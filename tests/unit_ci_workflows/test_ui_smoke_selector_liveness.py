# case_ids: MC-012
"""商家冒烟 spec 的**选择器活性 / role 活性 / name 可匹配性**与**登录步骤归因**守卫（issue #6779 + #6785）。

## 病灶（issue #6779，2026-10-12 实跑读数）

在 `origin/main` 之上真跑 `node scripts/ui-smoke-merchant/spec.mjs`（栈：admin-api:8090 + admin-web:3001）：

    ===== 汇总: 7/34 通过，27 失败 =====
    ❌ 01-login  超时: waiting for getByText('手机号登录').first() to be visible
    ❌ 02-dashboard  看板失败: waiting for getByText('经营看板') … navigated to "http://localhost:3001/login"

通过的是 7 条**未登录面**（官网四页 / 注册 / 登录页渲染）⇒ 真因是**登录步骤**等一个
已不存在的文案：登录页（`frontend/admin-web/src/app/login/page.tsx`）自 issue #5485 起是两个
tab（「员工登录」默认 / 「管理员登录」），**全文件没有「手机号登录」**。
27 条已登录旅程随即被弹回 `/login`，长得像「产品大面积回归」。

## 四道判据

- **判据 A（文案活性，issue #6779）**：spec 里 `expectText(...)` / `getByText(...)` / `getByRole(..., {name})` 的
  **文案字面量**必须能在**被驱动面**（`frontend/admin-web/src/**` + 同套件的 `criteria.mjs`）里
  **逐字取到**（按空白无关比对；正则选择器按 `|` 分组，**任一分组**能取到才算活 —— 与 Playwright
  的运行语义一致，存活的备选项不会因同列里其它备选项过期而失效）。取不到 ⇒ 判红并**具名**报出
  「哪个字面量 / 哪一行 / 哪个文件」。**确实动态生成**的文案走登记式豁免
  （台账 `ui_smoke_selector_exemptions.json`，只许缩短 + 每条带理由 + 条目不得空转）。
- **判据 B（归因，issue #6779）**：登录步骤失败必须**自报「登录步骤失败[位置]」**，不许让 27 条旅程各自超时
  —— 用**桩 playwright + 桩页面**真跑 `spec.mjs` 钉死：① 登录步骤失败 ⇒ 输出点名登录步骤；
  ② 登录成功、后续旅程失败 ⇒ 输出**不得**归因到登录步骤（负控，判据不是恒真）。
- **判据 R（role 活性，issue #6785）**：spec 里 `getByRole(<role>, …)` 的 `<role>` 必须能在被驱动面
  **现取到** —— 原生 role 按标签名 / `<input type=…>` 判（`ROLE_DOM_PATTERNS`），ARIA role 按
  `role="<role>"` 属性判（`tablist` 下必须有 `tab`）。role 不是字面量、或没有登记现取口径 ⇒ 红（fail-closed）。
- **判据 N（name 可匹配性，issue #6785）**：`{ name, exact: true }` 必须与页面**完整可及名字**一致。
  名字由多个文本节点拼成时（登录 tab = 标题「管理员登录」+ 副标题「手机验证码」）写子串 + exact
  **永远匹配不到**，而「文案在不在源码里」这一层看不到它（这正是判据 A 的射程外）。
  ① 未登记即红；② 登记为「完整可及名字的真子串」⇒ 红并同时报出「写的名字 / 页面可及名字」；
  ③ 非 exact（正则/子串）口径要**显式登记**（登记式豁免，只许缩短）。台账 = `ui_smoke_name_registry.json`。

## 病灶（issue #6785，2026-10-12 真栈实测）

`main`（含 #6777 wrapper 修复 + #6779/#6780 选择器修复）跑 `01-login`：

    ❌ 01-login  登录步骤失败[01-login/main]: locator.waitFor: Timeout 8000ms exceeded.
       waiting for getByRole('tab', { name: '管理员登录', exact: true }).first() to be visible
    ===== 汇总: 1/2 通过，1 失败 =====（`--group 01-`）

真栈现取（只读探针 `/tmp/ui-smoke-6785/probe-login.mjs`，1440 视口）：

    getByRole('tab')                                        count=2
      「员工登录 账号密码」 role=tab aria-selected=true
      「管理员登录 手机验证码」 role=tab aria-selected=false
    getByRole('tab', { name: '管理员登录', exact: true })     count=0   ← 写的就是这一条
    getByRole('tab', { name: /管理员登录/ })                  count=1

三层根因：① 角色面**本来就是对的**（容器 `role="tablist"` + 两个 `<button role="tab" aria-selected>`，
`git show origin/main:frontend/admin-web/src/app/login/page.tsx` 逐字可核；issue #6785 原文说的
「无 `role=\"tab\"`」与 main 现取不符 —— 那是 `grep -c 'role="tab"'` 只数到 `tablist` 子串的读数）；
② 可及名字 = 标题 + 副标题 ⇒ `exact: true` 恒匹配不到；③ spec 用了 `exact: true`。

## 判别力自证（每条都能单独变红，全部走 `pytest -k` 单跑）

| 坏形态 | 判据 | 实测 |
|---|---|---|
| spec 改回 `{ name: '管理员登录', exact: true }` | 判据 N | 红：写的名字 = '管理员登录' / 页面可及名字 = '管理员登录 手机验证码' / 现取文件 |
| 摘掉被驱动面里**每一处** `role="tab"`（4 个文件） | 判据 R | 红：`getByRole('tab', …)` 的 role 取不到（0 命中）；⚠️ 只摘登录页时另有 3 处 `role="tab"` ⇒ 照旧绿 |
| role 写成变量 `getByRole(tabRole, …)` | 判据 R | 红：第一个参数不是字面量 role |
| `getByRole('treeitem', …)`（未登记口径） | 判据 R | 红：ROLE_DOM_PATTERNS 缺 `treeitem` |
| 非 exact 口径漏登记 | 判据 N | 红：具名报出哪个 matcher 未登记 |
| 台账清空 / 理由过短 / 条目空转 / 超过冻结基线 | 判据 N | 各一条红（fail-closed + 只许缩短） |
| **只改注释** | 判据 R/N | 绿（对照读数，判据不吃自己的说明文字） |

## 边界（照实登记，§19.1）

- **不真起栈、不跑 31 旅程**：判据 A/R/N 是静态面，判据 B 用桩 playwright（本机此刻另有栈在跑）。
  真栈行为面（「登录旅程真跑通」）是**流程判据**，证据在 PR body（`--group 01-` 的实测读数），
  不在本文件里 —— 静态判据**结构上**看不到真 DOM 的可及名字。
- 本判据**不改** 31 条旅程的业务断言。
- **未固化面（有意）**：① CSS / xpath 选择器（`.locator('tbody tr')` / `[data-testid=...]`）不在
  射程内 —— 断言「选择器字符串出现在源码里」会把 CSS 选择器判死，形态不同，另单另判；
  ② 选择器的**行为面**（文案与 role 都在源码里、但运行时结构/可见性变了导致选择器落空）判不了
  —— 本判据只锁「文案 / role / 名字口径是否还与被驱动面一致」这一层腐烂；③ 判据 A 只覆盖
  `expectText` / `getByText` / `getByRole`（issue #6779 的射程），`getByLabel` / `getByPlaceholder` /
  `getByTestId` 与 `locator('text=…')` 暂无调用点，出现调用点时须同批扩射程；④ 判据 N 的
  `exact_single_node` 只在「该名字确实作为**独立** JSX 文本节点出现」时判绿 —— 名字由
  `{tab.label}` 这类**标识符展开**拼成时静态面推不出完整名字，此时由台账的 `composed_of` +
  `driver_files` 现取证据承担（两段文本必须在登记的驱动文件里取到）。
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = REPO_ROOT / "scripts" / "ui-smoke-merchant" / "spec.mjs"
LEDGER = Path(__file__).resolve().parent / "ui_smoke_selector_exemptions.json"
ADMIN_WEB_SRC = REPO_ROOT / "frontend" / "admin-web" / "src"
SMOKE_MODULE = REPO_ROOT / "scripts" / "ui-smoke-merchant" / "criteria.mjs"

LIVENESS_CALLS = ("expectText", "getByText", "getByRole")
# `getByRole` 的**第一个**参数是 ARIA role（结构性关键词），不是被驱动面的文案。
ARIA_ROLES = {
    "alert", "alertdialog", "application", "article", "banner", "blockquote", "button",
    "caption", "cell", "checkbox", "code", "columnheader", "combobox", "complementary",
    "contentinfo", "definition", "dialog", "directory", "document", "feed", "figure",
    "form", "generic", "grid", "gridcell", "group", "heading", "img", "link", "list",
    "listbox", "listitem", "log", "main", "marquee", "math", "menu", "menubar",
    "menuitem", "menuitemcheckbox", "menuitemradio", "navigation", "none", "note",
    "option", "paragraph", "presentation", "progressbar", "radio", "radiogroup",
    "region", "row", "rowgroup", "rowheader", "scrollbar", "search", "searchbox",
    "separator", "slider", "spinbutton", "status", "strong", "subscript", "superscript",
    "switch", "tab", "table", "tablist", "tabpanel", "term", "textbox", "time", "timer",
    "toolbar", "tooltip", "tree", "treegrid", "treeitem",
}
# 断言里的**测试数据**（不是被驱动面的文案）：只应在台账里登记，不应静默跳过。
TEST_DATA_RE = re.compile(r"^[0-9]{6,}$|^[0-9]{11}$|^1[0-9]{10}$")

RUN_TIMEOUT_SECONDS = 120

SMOKE_DIR = REPO_ROOT / "scripts" / "ui-smoke-merchant"
LOGIN_PAGE = "frontend/admin-web/src/app/login/page.tsx"
NAME_REGISTRY = Path(__file__).resolve().parent / "ui_smoke_name_registry.json"

# ────────────────────────── 判据 R（role 活性）──────────────────────────
# `getByRole('role')` 的 role 在**被驱动面**的现取形态：原生 role ⇒ 标签名 / `<input type=…>`；
# ARIA role ⇒ `role="…"` 属性（**只有 tablist 下真有 tab 才算 ARIA 合规**）。
# 属性值引号：`"` / `'` —— 用 `chr()` 拼，避免 raw 字符串里 `\"` 把引号转义掉（实测坑）。
Q = chr(34) + chr(39)
ROLE_DOM_PATTERNS: dict[str, str] = {
    "button": r"<button\b",
    "link": r"<a\b[^>]*\bhref",
    "textbox": r"<input\b[^>]*\btype=[" + Q + r"]?\s*(text|email|search|tel|url)|<textarea\b",
    "checkbox": r"<input\b[^>]*\btype=[" + Q + r"]?\s*checkbox",
    "radio": r"<input\b[^>]*\btype=[" + Q + r"]?\s*radio",
    "combobox": r"<select\b|\brole\s*=\s*[" + Q + r"]combobox",
    "listbox": r"\brole\s*=\s*[" + Q + r"]listbox",
    "option": r"<option\b|\brole\s*=\s*[" + Q + r"]option",
    "tab": r"\brole\s*=\s*[" + Q + r"]tab[" + Q + r"]",
    "tablist": r"\brole\s*=\s*[" + Q + r"]tablist[" + Q + r"]",
    "tabpanel": r"\brole\s*=\s*[" + Q + r"]tabpanel[" + Q + r"]",
    "dialog": r"<dialog\b|\brole\s*=\s*[" + Q + r"]dialog[" + Q + r"]",
    "alert": r"\brole\s*=\s*[" + Q + r"]alert[" + Q + r"]",
    "heading": r"<h[1-6]\b|\brole\s*=\s*[" + Q + r"]heading[" + Q + r"]",
    "img": r"<img\b|\brole\s*=\s*[" + Q + r"]img[" + Q + r"]",
}

# ────────────────────────── 判据 N（name 可匹配性）──────────────────────────
NAME_RE = re.compile(r"\bname\s*:")
LITERAL_EXPR_RE = re.compile(r"\{\s*'([^']*)'\s*\}")
EXACT_RE = re.compile(r"\bexact\s*:\s*(true|!0)\b")
PUNCT_CATEGORIES = {"Po", "Ps", "Pe", "Pi", "Pf", "Pd", "Pc"}
# JSX 标签形态（含闭合标签 `</div>`）；`(?!/)` 保证 `</` 不会被当成开标签的自闭合形态。
JSX_TAG_RE = re.compile(r"</?([A-Za-z][A-Za-z0-9.]*)[^<>]*?(/?)>")


def _matcher_text(text: str) -> str:
    """把匹配器表达式归一成**人可读的名字**（用于判红文案）：`'确定'` / `/管理员登录/` ⇒ 文本。"""
    t = text.strip()
    if t.startswith("/") and t.endswith("/") and len(t) > 1:
        return t[1:-1]
    return re.sub(r"^['\"`]|['\"`]$", "", t)


def _brace_span(text: str, start: int) -> str:
    """取 `{`（`start` 指向它）起、**括号配对**的内容（含大括号）。"""
    depth = 0
    i = start
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    return text[start:]


def _options_of_args(args: str) -> str:
    """从 `getByRole` 的括号内参数里取 options 对象 `{…}`（没有则空串）。"""
    i = 0
    depth = 0
    while i < len(args):
        c = args[i]
        if c in "'\"`":
            j = i + 1
            while j < len(args) and args[j] != c:
                j += 2 if args[j] == "\\" else 1
            i = j + 1
            continue
        if c == "/" and i + 1 < len(args) and args[i + 1] not in " /":
            j = i + 1
            while j < len(args) and args[j] != "/":
                j += 2 if args[j] == "\\" else 1
            i = j + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "{" and depth == 0:
            return _brace_span(args, i)
        i += 1
    return ""


def by_role_call(line: str, start: int) -> dict | None:
    """取一处 `getByRole(...)` 的 `{role, name, exact, role_src?}`（**现取**，不写死行号）。"""
    args = line[start:]
    literals = _literal_at(line, start)
    roles = [v for k, v in literals if k == "str"]
    if not roles:
        return None
    opts = _options_of_args(args)
    # role 必须是**第一个参数**里的字面量：`getByRole(tabRole, { name: '…' })` 里第一个字符串
    # 其实是 name，不能把它当 role（否则判据 R 会去核一个不存在的 role 名）。
    role_lit = args.find("'" + roles[0] + "'")
    if role_lit < 0:
        role_lit = args.find('"' + roles[0] + '"')
    opts_at = args.find(opts) if opts else -1
    if role_lit < 0 or (opts_at >= 0 and opts_at < role_lit):
        roles = []
    role = roles[0] if roles else ""
    out: dict = {"role": role, "name": None, "name_matcher": None, "exact": False}
    nm = NAME_RE.search(opts)
    if nm:
        rest = opts[nm.end():].lstrip()
        j = 0
        if rest[:1] in "'\"`":
            q = rest[0]
            j = 1
            while j < len(rest) and rest[j] != q:
                j += 2 if rest[j] == "\\" else 1
            out["name_matcher"] = rest[:j + 1]
        elif rest[:1] == "/":
            j = 1
            while j < len(rest):
                if rest[j] == "\\":
                    j += 2
                    continue
                if rest[j] == "/":
                    break
                j += 1
            out["name_matcher"] = rest[:j + 1]
        out["name"] = _matcher_text(out["name_matcher"] or "")
        out["exact"] = bool(EXACT_RE.search(opts))
    return out


def by_role_calls(spec_text: str) -> list[dict]:
    """spec 里所有 `getByRole(<role>, …)` 调用（带行号）——判据 R/N 的输入。"""
    found: list[dict] = []
    for no, line in enumerate(spec_text.splitlines(), 1):
        for m in re.finditer(r"\bgetByRole\s*\(", line):
            call = by_role_call(line, m.end())
            if call:
                call["line"] = no
                found.append(call)
    return found


def role_liveness_failures(spec_text: str, sources: dict[str, str]) -> list[str]:
    """判据 R：`getByRole` 的 role 必须能在被驱动面**现取到**（具名报「role / 命中数 / 面」）。"""
    failures: list[str] = []
    calls = by_role_calls(spec_text)
    literal_lines = {call["line"] for call in calls if call["role"]}
    for no, line in enumerate(spec_text.splitlines(), 1):
        if re.search(r"\bgetByRole\s*\(", line) and no not in literal_lines:
            failures.append(
                f"第 {no} 行 getByRole(…) 的第一个参数**不是字面量 role**（变量 / 展开 / 换行）"
                f"⇒ 判据 R 核不了它是否真存在于 DOM，fail-closed 判红：写成字面量 role"
            )
    for call in calls:
        role = call["role"]
        if not role:
            continue  # 已按「非字面量」具名报出，不重复
        if role not in ROLE_DOM_PATTERNS:
            failures.append(
                f"第 {call['line']} 行 getByRole({role!r}, …) 的 role **没有登记现取口径**"
                f"（ROLE_DOM_PATTERNS 缺 `{role}`）⇒ 无法核它是否真存在于 DOM，fail-closed 判红："
                f"补口径（原生标签名 / `role=\"{role}\"`）后再用"
            )
            continue
        pattern = re.compile(ROLE_DOM_PATTERNS[role])
        hits = [(name, len(pattern.findall(text))) for name, text in sources.items()]
        total = sum(n for _, n in hits)
        if total == 0:
            where = "、".join(f"{name}({n})" for name, n in hits if n) or "0 命中"
            failures.append(
                f"第 {call['line']} 行 getByRole({role!r}, …) 的 role 在**被驱动面取不到**"
                f"（口径 {ROLE_DOM_PATTERNS[role]!r} / {where}）⇒ 该 selector 永不命中；"
                f"被驱动面 = {ADMIN_WEB_SRC.relative_to(REPO_ROOT)}/** + {SMOKE_DIR.relative_to(REPO_ROOT)}/**"
            )
    return failures


def _norm_segments(segments: list[str]) -> str:
    return " ".join(s.strip() for s in segments if s.strip())


_ELEMENT_CACHE: dict[str, list[tuple[int, int]]] = {}


def _jsx_tags(text: str) -> list[tuple[str, int, int, str]]:
    """现取 JSX 标签 `(tag, content_start, tag_start, kind)`；`kind ∈ {open, close, self}`。

    - **属性值里的引号**内不认 `>`：`onClick={() => switchMode(tab.key)}` 里的 `=>` 会让正则
      在错误位置收尾（实测：`<button …>` 被截断成 `<button …` 并把整个页面当它的内容）；
    - `content_start` = 该标签 `>` 之后的第一个非空白字符；`tag_start` = 该标签 `<` 的位置
      （闭合标签用它给出**开标签内容的结束位置**）。
    """
    out: list[tuple[str, int, int, str]] = []
    i, n = 0, len(text)
    while True:
        lt = text.find("<", i)
        if lt < 0 or lt + 1 >= n:
            return out
        j = lt + 1
        closing = text[j] == "/"
        if closing:
            j += 1
        if not (j < n and (text[j].isalpha() or text[j] == "_")):
            i = lt + 1
            continue
        k = j
        while k < n and (text[k].isalnum() or text[k] in "._-$"):
            k += 1
        tag = text[j:k]
        if k < n and text[k] not in " \t\r\n/>":
            i = lt + 1
            continue
        # 排除 TS 代码里的伪标签（`<T extends …>` / `a < b` / `Map<String, Foo>` 的 `>>`）：
        # 真 JSX 标签名与 `>` 之间要么什么都没有、要么以空白开始；且首个 `>` 前不能再出现 `<`。
        if k < n and text[k] not in " \t\r\n/>" :
            i = lt + 1
            continue
        if k < n and text[k] not in ">/" and not text[k].isspace():
            i = lt + 1
            continue
        quote = ""
        while k < n:
            ch = text[k]
            if ch == '"' or ch == "'":
                quote = "" if quote == ch else (ch if not quote else quote)
                k += 1
                continue
            if ch == ">" and not quote:
                break
            k += 1
        if k >= n:
            return out
        raw = text[lt:k + 1]
        kind = "close" if closing else ("self" if raw.endswith("/>") else "open")
        content_start = k + 1
        while content_start < n and text[content_start] in " \t\r\n":
            content_start += 1
        out.append((tag, content_start, lt, kind))
        i = k + 1


def _jsx_element_spans(text: str) -> list[tuple[int, int]]:
    """JSX 元素的**内容区间** `(start, end)`（不含标签本身）；`</div>` 必须有同名开标签。"""
    key = str(id(text))
    if key in _ELEMENT_CACHE:
        return _ELEMENT_CACHE[key]
    stack: list[tuple[str, int]] = []
    spans: list[tuple[int, int]] = []
    for tag, content_start, tag_start, kind in _jsx_tags(text):
        if kind == "self":
            continue
        if kind == "open":
            stack.append((tag, content_start))
            continue
        for pos in range(len(stack) - 1, -1, -1):
            if stack[pos][0] == tag:
                _, start = stack.pop(pos)
                spans.append((start, tag_start))
                break
    _ELEMENT_CACHE[key] = spans
    return spans


def _in_string_at(text: str, index: int) -> bool:
    """`index` 处的字面量是否**紧跟在引号后**（= 字符串字面量的开头）。

    只看紧邻形态（不做跨行配对）：`label: '管理员登录'` / `useState('employee')` ⇒ True；
    JSX 文本节点 `>确定<` ⇒ False。
    """
    j = index - 1
    while j >= 0 and text[j] in " \t":
        j -= 1
    return j >= 0 and text[j] in "'\"`"


def jsx_text_name(text: str, index: int, expected: str = "") -> tuple[str, bool]:
    """现取字面量所在 JSX 元素的**可及名字近似**：`(名字, ok)`。

    `ok=True` 当且仅当该元素的**完整**可及名字（本层文本节点 + `{ '…' }` 字面量表达式的拼接）
    **逐字等于** `declared` ⇒ `{ name, exact: true }` 能匹配；否则 `ok=False`（更长 / 推不出）。

    只认 JSX 元素内容区里的文本节点与 `{'…'}` 字面量；`{tab.label}` 这类标识符展开、子元素的
    内容、其它表达式一律**不展开**（宁可少算 ⇒ 名字是**下界**，只在「确实更长」时判红）。
    """
    spans = _jsx_element_spans(text)
    containing = [sp for sp in spans if sp[0] <= index < sp[1]]
    if not containing:
        return "", False
    start, end = min(containing, key=lambda sp: sp[1] - sp[0])
    parts: list[str] = []
    pos = start
    while pos < end and text[pos] != "<":
        ch = text[pos]
        if ch == "{":
            m = LITERAL_EXPR_RE.match(text, pos)
            if m:
                parts.append(m.group(1))
                pos = m.end()
                continue
            return _norm("".join(parts)), False
        if ch in "}]),:;?=<>":
            return _norm("".join(parts)), False
        if ch in "'\"`":
            j = pos + 1
            while j < end and text[j] != ch:
                j += 2 if text[j] == "\\" else 1
            parts.append(text[pos + 1:j])
            pos = j + 1
            continue
        parts.append(ch)
        pos += 1
    # JSX 文本语义：各文本节点拼接后**折掉空白**（`{' '}` 是渲染出来的空格；这里只比较字符内容）。
    name = re.sub(r"\s+", "", "".join(parts))
    if not name:
        return "", False
    # ok = 该字面量本身就是**完整**可及名字：元素文本必须就是调用方给的 expected（不长不短）
    ok = bool(expected) and expected == name
    if not expected:
        ok = text[index:index + len(name)] == name
    return name, ok


def standalone_text_name(declared: str, sources: dict[str, str]) -> str:
    """**现取**：该名字是否在被驱动面里作为**独立 JSX 文本节点**出现（返回命中的元素名，空 = 否）。

    「独立文本节点」= 元素本层可及名字**恰好等于**该名字（`>确定<`）。名字出现在字符串字面量
    （数据声明 `label: '管理员登录'`）、或元素里还有别的文本节点 ⇒ 不算 —— 那正是
    `exact: true` 匹配不到的形态（issue #6785）。
    """
    hits: list[str] = []
    for name, text in sources.items():
        idx = text.find(declared)
        while idx >= 0:
            if _in_string_at(text, idx):
                idx = text.find(declared, idx + 1)
                continue
            _, ok = jsx_text_name(text, idx, declared)
            if ok:
                return name
            hits.append(name)
            idx = text.find(declared, idx + 1)
    return ""


def driver_evidence_failures(entry: dict, sources: dict[str, str]) -> list[str]:
    """合成名字条目的**现取证据**：`driver_files` 里必须同时找得到声明的各段文本。"""
    declared = entry.get("declared", "")
    segs = [s for s in entry.get("composed_of", []) if s.strip()]
    files = entry.get("driver_files", [])
    missing_files = [f for f in files if f not in sources]
    if missing_files:
        return [f"判据 N 台账条目 {declared!r} 的 driver_files 在被驱动面不存在：{missing_files}"]
    hay = "\n".join(_norm(sources[f]) for f in files)
    miss = [s for s in segs if _norm(s) not in hay]
    if miss:
        return [
            f"判据 N 台账条目 {declared!r} 的 composed_of 段 {miss} 在 driver_files {files} 里取不到"
            f"（台账空转 / 名字已漂）"
        ]
    return []


def exact_name_failures(
    spec_text: str, sources: dict[str, str], registry: dict
) -> tuple[list[str], list[dict]]:
    """判据 N：`{ name, exact: true }` 必须与页面**完整可及名字**一致。

    返回 `(failures, resolved)`：`resolved` 是每条 exact 选择器的现取结论（供自证引用）。
    """
    entries = {e["declared"]: e for e in registry.get("exact", [])}
    haystack = [(name, _norm(text)) for name, text in sources.items()]
    failures: list[str] = []
    resolved: list[dict] = []
    for call in by_role_calls(spec_text):
        if not (call["name"] and call["exact"]):
            continue
        declared = call["name"]
        entry = entries.get(declared)
        where = f"第 {call['line']} 行 getByRole({call['role']!r}, {{ name: {call['name_matcher']}, exact: true }})"
        if entry is None:
            failures.append(
                f"{where} 未登记（未登记即红）：exact 只认**完整可及名字**，"
                f"必须在 {NAME_REGISTRY.name} 的 exact 里写清该名字由哪些文本节点拼成"
            )
            continue
        victim = [name for name, text in haystack if _norm(declared) in text]
        if not victim:
            failures.append(
                f"{where} 的 exact 名字 {declared!r} 在**被驱动面取不到**（现取到 0 个文件）⇒ 该 selector 永不命中；"
                f"被驱动面 = {ADMIN_WEB_SRC.relative_to(REPO_ROOT)}/** + {SMOKE_DIR.relative_to(REPO_ROOT)}/**"
            )
            continue
        kind = entry.get("kind")
        if kind == "exact_substring_of_composed":
            ev = driver_evidence_failures(entry, sources)
            if ev:
                failures.extend(ev)
            else:
                failures.append(
                    f"{where} 写的名字 = {declared!r}，而页面可及名字 = "
                    f"{' '.join(entry.get('composed_of', []))!r}（现取 {victim[0]}）"
                    f"⇒ 名字由多个文本节点拼成（标题+副标题），exact **匹配不到**："
                    f"改用非 exact（正则/子串）或去 ARIA 补 aria-label"
                )
            resolved.append({"line": call["line"], "declared": declared, "kind": kind, "victim": victim})
            continue
        if kind != "exact_single_node":
            failures.append(
                f"{where} 的登记 kind={kind!r} 不在支持口径内"
                f"（exact_single_node / exact_substring_of_composed）fail-closed 判红"
            )
            continue
        # exact_single_node：**现取**该名字必须真作为独立 JSX 文本节点出现（不比台账自述）。
        hit = standalone_text_name(declared, sources)
        if not hit:
            failures.append(
                f"{where} 的 exact 名字 {declared!r} 现取不到「可及名字恰等于它」的 JSX 文本节点"
                f"（页面该元素的文本更长或该名字只出现在字符串字面量里）⇒ exact **匹配不到**"
            )
        resolved.append({"line": call["line"], "declared": declared, "kind": kind, "victim": [hit or victim[0]]})
    return failures, resolved


def _line_anchor(spec_text: str, line: int) -> str | None:
    """选择器的**行锚**（该行的去空白文本）：定位用，不写死行号（改行号不失效）。"""
    lines = spec_text.splitlines()
    return _norm(lines[line - 1]) if 0 < line <= len(lines) else None


def registry_name_failures(
    spec_text: str, sources: dict[str, str], registry: dict
) -> list[str]:
    """登记台账纪律：未登记即红 / 理由过短 / 条目空转（只许缩短）/ 非 exact 口径显式登记。"""
    failures: list[str] = []
    haystack = [(name, _norm(text)) for name, text in sources.items()]
    counts = registry.get("baseline_count", {})

    exact_entries = registry.get("exact", [])
    weak = registry.get("registered_matchers", {})
    weak_matchers = list(weak.get("matchers", []))
    if len(exact_entries) > counts.get("exact", 0):
        failures.append(
            f"exact 登记条目 {len(exact_entries)} 条 > 冻结基线 {counts.get('exact', 0)} 条（台账只许缩短）"
        )
    if len(weak_matchers) > counts.get("registered_matchers", 0) or len(weak_matchers) > weak.get("baseline_count", 0):
        failures.append(
            f"非 exact 登记条目 {len(weak_matchers)} 条 > 冻结基线 "
            f"{min(counts.get('registered_matchers', 0), weak.get('baseline_count', 0))} 条（台账只许缩短）"
        )
    if not exact_entries or not weak_matchers:
        failures.append("判据 N 台账被清空（exact / 非 exact 有一类为空）——那是「静默放过」的口径，fail-closed 判红")

    for e in exact_entries:
        declared = e.get("declared", "")
        victim = [name for name, text in haystack if _norm(declared) in text]
        if not victim:
            failures.append(
                f"判据 N 台账条目 {declared!r} 在被驱动面取不到（台账空转，必须删掉）：现取到 0 个文件"
            )
        if len(str(e.get("reason", "")).strip()) < 15:
            failures.append(f"判据 N 台账条目的理由太短（等于没写理由）：{e}")
        kind = e.get("kind")
        if kind == "exact_substring_of_composed":
            failures.extend(driver_evidence_failures(e, sources))
            segs = [s for s in e.get("composed_of", []) if s.strip()]
            if len(segs) < 2:
                failures.append(f"判据 N 台账条目 {declared!r} 的 composed_of 不足 2 段（拼成可及名字的文本节点）：{e}")
            elif not _norm(declared) in _norm("".join(segs)) or _norm(declared) == _norm("".join(segs)):
                failures.append(
                    f"判据 N 台账条目 {declared!r} 不是完整可及名字 {_norm_segments(segs)!r} 的**真子串** ⇒ 空转：{e}"
                )
        elif kind == "exact_single_node":
            if not standalone_text_name(declared, sources):
                failures.append(
                    f"判据 N 台账条目 {declared!r} 声明为单节点名字，但现取不到「可及名字恰等于它」的 "
                    f"JSX 文本节点（页面该元素的文本更长）⇒ 登记已漂：{e}"
                )
        else:
            failures.append(f"判据 N 台账条目 {declared!r} 的 kind={kind!r} 不在支持口径内：{e}")

    if len(str(weak.get("_comment", "")).strip()) < 15:
        failures.append("非 exact 登记缺理由（`registered_matchers._comment`）：等于没写理由")
    for matcher in weak_matchers:
        if matcher not in spec_text:
            failures.append(f"非 exact 登记条目 {matcher!r} 已从 spec 消失（空转，必须删掉）")
    return failures


def weak_name_coverage_failures(spec_text: str, registry: dict) -> list[str]:
    """非 exact 口径要**显式登记**（登记式豁免，只许缩短）：漏登记即红。"""
    registered = set(registry.get("registered_matchers", {}).get("matchers", []))
    failures: list[str] = []
    for call in by_role_calls(spec_text):
        if not call["name"] or call["exact"]:
            continue
        if call["name_matcher"] not in registered:
            failures.append(
                f"第 {call['line']} 行 getByRole({call['role']!r}, {{ name: {call['name_matcher']} }}) "
                f"是**非 exact** 名字匹配（子串/正则）：必须显式登记进 {NAME_REGISTRY.name} 的 "
                f"registered_matchers.matchers（写清为什么不能用完整可及名字），未登记即红"
            )
    return failures


# ────────────────────────── 静态解析（文本层） ──────────────────────────
def _literal_at(line: str, start: int) -> list[tuple[str, str]]:
    """取 `start`（`(` 之后）起、**括号深度 1** 范围内的字符串/正则字面量。

    做成深度感知是为了不把后续链式调用（`.first().catch(...)`）的参数混进来。
    """
    out: list[tuple[str, str]] = []
    i, depth = start, 1
    while i < len(line):
        c = line[i]
        if c in "'\"`":
            j, buf = i + 1, ""
            while j < len(line) and line[j] != c:
                if line[j] == "\\":
                    buf += line[j:j + 2]
                    j += 2
                    continue
                buf += line[j]
                j += 1
            out.append(("str", buf))
            i = j + 1
            continue
        if c == "/" and i + 1 < len(line) and line[i + 1] not in " /":
            # 正则字面量：`/.../`（跳过 `\/` 转义）——**保留转义原文**，否则字符类/量词会被吃掉。
            j, buf, in_class = i + 1, "", False
            while j < len(line):
                ch = line[j]
                if ch == "\\":
                    buf += line[j:j + 2]
                    j += 2
                    continue
                if ch == "[":
                    in_class = True
                elif ch == "]":
                    in_class = False
                elif ch == "/" and not in_class:
                    break
                buf += ch
                j += 1
            out.append(("re", buf))
            i = j + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    return out


def selector_literals(spec_text: str) -> list[dict]:
    """spec 里所有活性面 selector 的文案字面量（带行号）——**现取**，不写死行号。"""
    found: list[dict] = []
    for no, line in enumerate(spec_text.splitlines(), 1):
        for name in LIVENESS_CALLS:
            for m in re.finditer(r"\b" + name + r"\s*\(", line):
                for kind, value in _literal_at(line, m.end()):
                    if not value:
                        continue
                    if name == "getByRole" and value in ARIA_ROLES:
                        continue
                    found.append({"line": no, "call": name, "kind": kind, "value": value})
    return found


def driven_sources() -> dict[str, str]:
    """被驱动面：admin-web 源码（页面本体）+ 冒烟套件目录（`criteria.mjs` 常量单一源 + 桩）。"""
    src: dict[str, str] = {}
    for path in sorted(ADMIN_WEB_SRC.rglob("*")):
        if path.is_file() and path.suffix in (".tsx", ".ts", ".jsx", ".js"):
            src[str(path.relative_to(REPO_ROOT))] = path.read_text(encoding="utf-8", errors="replace")
    for path in sorted(SMOKE_DIR.iterdir()):
        if path.is_file() and path.name != "spec.mjs":
            src[str(path.relative_to(REPO_ROOT))] = path.read_text(encoding="utf-8", errors="replace")
    return src


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _split_alternatives(re_src: str) -> list[str]:
    """按**顶层** `|` 切正则（跳过 `\\|` 转义与 `[...]` 字符类内的 `|`）。"""
    parts, buf, i, in_class = [], "", 0, False
    while i < len(re_src):
        c = re_src[i]
        if c == "\\":
            buf += re_src[i:i + 2]
            i += 2
            continue
        if in_class:
            if c == "]":
                in_class = False
            buf += c
        elif c == "[":
            in_class = True
            buf += c
        elif c == "|":
            parts.append(buf)
            buf = ""
        else:
            buf += c
        i += 1
    parts.append(buf)
    return [p for p in (p.strip() for p in parts) if p]


def _alt_candidates(alt: str) -> list[str]:
    """一个备选项的**字面文本**候选（去掉纯形态量词后的文本）。

    例：`JG-\\d{8}-\\d+` ⇒ 剥掉数字量词 ⇒ `JG--` ⇒ 折掉空段 ⇒ `JG-`；纯 `\\d+` 形态 ⇒ 空 ⇒ 不是候选
    （它没有可现取的字面部分，只能走 `_structured_match` 的结构面比对）。
    """
    expanded = re.sub(r"\\d\{(\d+)\}", "-", alt)
    expanded = re.sub(r"\\d\+|\\d", "-", expanded)
    expanded = re.sub(r"\\s\*|\\s\+|\?", "", expanded)
    key = _norm(re.sub(r"\\(.)", lambda m: "" if m.group(1) in "ds" else m.group(1), expanded))
    key = key.replace("^", "").replace("$", "")
    # 折掉 `--` 这类由「被剥掉的数字段」留下的空段，但保留段间分隔符（`JG-` / `A-B` 形态）。
    key = re.sub(r"-{2,}", "-", key)
    if not re.search(r"[^\W_-]", key, re.UNICODE) or len(re.sub(r"[^\w]", "", key, re.UNICODE)) < 2:
        return []
    return [key]


def _structured_match(alt: str, text: str) -> bool:
    """字面部分不完整的形态正则（如 `[A-Z]{2}-\\d{8}-\\d+`）与源码的结构面比对。

    口径（保守，宁缺勿滥）：字面的**分隔符序列**必须逐一出现；按分隔符切出的每一段，
    源码里的对应段必须是**数字串**且长度落在 `\\d{n}` / `\\d+` 声明的范围内（`\\d+` 下界 1）。
    这样 `/JG-\\d{8}-\\d+/` 只有源码里真有 `JG-<8位数字>-<数字>` 才判活 —— 实测示例：
    `frontend/admin-web/src/**` 的 `[A-Z]{2}-\\d{8}-\\d+`（`ORDER_NO_SHAPE`）与实测号
    `JG-20260918-9049` 逐段吻合。
    """
    if "|" in alt or not re.search(r"\\d|\[[^\]]*\]", alt):
        return False
    seps = [c for c in re.sub(r"\\(.)", r"\1", alt) if not c.isalnum()]
    if not seps:
        return False
    sep_cls = "[" + re.escape("".join(dict.fromkeys(seps))) + "]"
    segs = [s for s in re.split(sep_cls, alt)]
    bounds = [
        (int(m.group(1)), int(m.group(1))) if m.group(1) else (1, None)
        for m in re.finditer(r"\\d(?:\{(\d+)\}|\+)?", alt)
    ]
    if not segs or len(bounds) < len(segs) - 1:
        return False
    for m in re.finditer(sep_cls, text):
        pos, ok = m.start(), True
        for i, (lo, hi) in enumerate(bounds, start=1):
            run = re.match(r"[^" + re.escape("".join(dict.fromkeys(seps))) + r"]*", text[pos + 1:])
            piece = run.group(0) if run else ""
            if not piece.isdigit() or len(piece) < lo or (hi is not None and len(piece) > hi):
                ok = False
                break
            pos += 1 + len(piece)
        if ok:
            return True
    return False


def liveness_failures(spec_text: str, sources: dict[str, str], exempt: set[str]) -> list[str]:
    """判据 A 本体：返回**具名**失效清单（空 = 合规）。

    - 字符串字面量：空白无关逐字现取（`确 定` 与 `确定` 是同一个按钮文案）；
    - 正则字面量：按 `|` 分组，**任一分组**取到即算活（与 Playwright 语义一致）；
    - 只有字面部分的正则走逐字现取；纯形态正则（`JG-\\d{8}-\\d+`）走 `_structured_match`。
    """
    haystack = [(name, _norm(text)) for name, text in sources.items()]
    failures: list[str] = []
    for item in selector_literals(spec_text):
        value = item["value"]
        if value in exempt:
            continue
        if item["kind"] == "str":
            if item["call"] == "getByRole" and value in ARIA_ROLES:
                continue
            keys = [_norm(value)]
        else:
            keys = []
            for alt in _split_alternatives(value):
                keys.extend(_alt_candidates(alt))
        hit = any(candidate in text for candidate in keys for _, text in haystack)
        if not hit and item["kind"] == "re":
            hit = any(
                _structured_match(alt, text)
                for alt in _split_alternatives(value)
                for _, text in haystack
            )
        if hit:
            continue
        failures.append(
            f"第 {item['line']} 行 {item['call']}({value!r}) 在**被驱动面取不到**"
            f"（候选 {keys or '（纯形态正则，走结构面比对）'}）⇒ 该 selector 永不命中；被驱动面 = "
            f"{ADMIN_WEB_SRC.relative_to(REPO_ROOT)}/** + {SMOKE_MODULE.relative_to(REPO_ROOT)}"
        )
    return failures


def load_ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def _exempt_set(ledger: dict) -> set[str]:
    return {e["literal"] for e in ledger["exemptions"]}


# ────────────────────────── 判据 A ──────────────────────────
def test_liveness_failures_are_empty_on_current_spec():
    """① 说真话的那条：当前 spec 的 selector 文案必须全部能在被驱动面现取到。"""
    spec = SPEC.read_text(encoding="utf-8")
    failures = liveness_failures(spec, driven_sources(), _exempt_set(load_ledger()))
    assert failures == [], "冒烟 spec 里有取不到文案的 selector（改 UI 文案后必须同批改 selector）：\n" + "\n".join(
        f"  - {f}" for f in failures
    )


def test_stale_login_literal_would_be_caught():
    """② 判别力自证（注入式红证）：把登录文案改回已不存在的「手机号登录」⇒ 当场红且具名。

    用**真 spec 文本的内存变异**（只把登录 tab 的现取文案换掉，其余一字不动）。
    """
    spec = SPEC.read_text(encoding="utf-8")
    stale = spec.replace("'管理员登录'", "'手机号登录'")
    assert stale != spec, "注入未生效：spec 里找不到 `'管理员登录'` ⇒ 本条自证不成立，不得读成通过"
    # 夹具自证：改前的现取文案**确实**能在被驱动面找到（否则这条红证可能只是「两边都取不到」）。
    assert "管理员登录" in "\n".join(driven_sources().values()), "夹具不成立：管理员登录 在被驱动面也取不到"
    failures = liveness_failures(stale, driven_sources(), _exempt_set(load_ledger()))
    assert any("手机号登录" in f for f in failures), f"注入后判据未红（判别力失效）：{failures}"
    assert "login/page.tsx" in "\n".join(failures) or "frontend/admin-web" in "\n".join(failures), (
        f"判红未点名『哪个字面量 / 哪个文件』：{failures}"
    )


def test_comment_only_edit_does_not_trip_the_criterion():
    """③ 对照读数：**只改注释** ⇒ 不红（判据不吃自己的说明文字）。"""
    spec = SPEC.read_text(encoding="utf-8")
    commented = "// 说明：历史上这里等的是旧文案（已随 #5485 改版下线）\n" + spec
    assert liveness_failures(commented, driven_sources(), _exempt_set(load_ledger())) == []


def test_exemptions_are_registered_and_live():
    """④ 台账纪律：未登记即红 / 每条必须带理由 / 条目不得空转（只许缩短）。"""
    ledger = load_ledger()
    spec = SPEC.read_text(encoding="utf-8")
    assert ledger["exemptions"], "豁免台账被清空 —— 那是「静默跳过」的口径，判红（fail-closed）"
    assert len(ledger["exemptions"]) <= ledger["baseline_count"], (
        f"豁免条目 {len(ledger['exemptions'])} 条 > 冻结基线 {ledger['baseline_count']} 条（台账只许缩短）"
    )
    for e in ledger["exemptions"]:
        assert {"literal", "reason"} <= set(e), f"豁免条目缺字段：{e}"
        assert len(e["reason"].strip()) >= 15, f"豁免理由太短（等于没写理由）：{e}"
        assert any(tag in e["reason"] for tag in ("动态", "测试数据")), (
            f"豁免理由必须写明该字面量属动态生成面（含『动态』或『测试数据』）：{e}"
        )
        assert e["literal"] in spec, f"豁免条目引用的字面量已从 spec 消失 ⇒ 台账空转，必须删掉：{e['literal']!r}"


def test_failures_name_literal_and_file():
    """⑤ 判红必须可归因（「哪个字面量 / 哪个文件」都在文案里）。"""
    spec = SPEC.read_text(encoding="utf-8")
    injected = spec.replace("expectText(page, '经营看板')", "expectText(page, '根本不存在的看板文案')")
    assert injected != spec, "注入未生效：找不到 `expectText(page, '经营看板')`"
    failures = liveness_failures(injected, driven_sources(), _exempt_set(load_ledger()))
    joined = "\n".join(failures)
    assert "根本不存在的看板文案" in joined and "frontend/admin-web" in joined, f"判红文案缺『字面量/文件』：{failures}"


# ────────────────────────── 判据 R / N 的承载（issue #6785）──────────────────────────
def name_registry() -> dict:
    return json.loads(NAME_REGISTRY.read_text(encoding="utf-8"))


def spec_text() -> str:
    return SPEC.read_text(encoding="utf-8")


def test_role_of_getbyrole_is_live_on_the_driven_surface():
    """⑧ 判据 R（说真话的那条）：spec 里 `getByRole(<role>, …)` 的 role 必须现取到。"""
    failures = role_liveness_failures(spec_text(), driven_sources())
    assert failures == [], "冒烟 spec 有 role 在**被驱动面取不到**的 selector（改页面 role/结构后必须同批改 selector）：\n" + "\n".join(
        f"  - {f}" for f in failures
    )


def test_role_liveness_would_be_caught():
    """⑨ 判据 R 判别力自证：**真语料全量变异**（摘掉被驱动面里每一处 `role="tab"`）⇒ 红且具名。

    这条同时就是 issue #6785 的形态锁：页面把 tab 的 role 摘掉（`tablist` 下没有 `tab`）⇒ 当场红。
    ⚠️ 必须摘**全部 4 个文件**：只改 login/page.tsx 时别的页面仍提供 `role="tab"` ⇒ 判据**照旧绿**
    （实测：只改登录页，orig total=5 / mut total=4 ⇒ 红不了）。这正是「role 活性」的全局口径。
    """
    src = driven_sources()
    assert LOGIN_PAGE in src, f"夹具不成立：被驱动面里没有 {LOGIN_PAGE}"
    before = role_liveness_failures(spec_text(), src)
    assert before == [], f"夹具不成立：现状应当绿（否则共因干扰）：{before}"
    mutated, touched = {}, []
    for name, text in src.items():
        fixed = text.replace('role="tab"', 'role="tabX"')
        mutated[name] = fixed
        if fixed != text:
            touched.append(name)
    assert touched, "注入未生效：被驱动面里找不到 `role=\"tab\"`"
    after = role_liveness_failures(spec_text(), mutated)
    assert after, f"注入后判据未红（判别力失效）：改过 {len(touched)} 个文件仍绿"
    joined = "\n".join(after)
    assert "'tab'" in joined and "0 命中" in joined, f"判红未具名（role / 命中数）：{after}"


def test_role_liveness_fail_closed_on_unregistered_role():
    """⑩ 未登记 role 口径 ⇒ 红（fail-closed）：新 role 不许静默放过。"""
    spec = spec_text()
    injected = spec.replace("getByRole('tab'", "getByRole('treeitem'")
    assert injected != spec, "注入未生效：spec 里找不到 getByRole('tab'"
    failures = role_liveness_failures(injected, driven_sources())
    assert any("treeitem" in f and "ROLE_DOM_PATTERNS" in f for f in failures), (
        f"未登记的 role 未判红（静默放过）：{failures}"
    )


def test_getbyrole_role_must_be_a_literal():
    """⑪ spec 的 `getByRole` 第一个参数必须是**字面量** role（否则角色面不可核，fail-closed）。"""
    spec = spec_text()
    injected = spec.replace("getByRole('tab'", "getByRole(tabRole")
    assert injected != spec, "注入未生效：spec 里找不到 getByRole('tab'"
    failures = role_liveness_failures(injected, driven_sources())
    assert any("非字面量" in f or "字面量" in f for f in failures), (
        f"非字面量 role 未被判红（静默跳过 = 覆盖缺口）：{failures}"
    )


# ────────────────────────── 判据 N（name 可匹配性，issue #6785）──────────────────────────
def test_exact_names_match_the_full_accessible_name():
    """⑫ 判据 N：`{ name, exact: true }` 必须与页面**完整可及名字**一致（issue #6785 的正题）。"""
    failures, resolved = exact_name_failures(spec_text(), driven_sources(), name_registry())
    assert failures == [], "冒烟 spec 有 exact 名字与页面可及名字不一致的 selector：\n" + "\n".join(
        f"  - {f}" for f in failures
    )
    assert resolved, "判据 N 空转：当前 spec 里一条 exact 名字都没解析到（夹具失效）"


def test_composed_accessible_name_evidence_is_live_on_the_real_login_page():
    """⑬ 判据 N 的数据源自证：登录 tab 的完整可及名字各段**现取**自 `frontend/admin-web/src/app/login/page.tsx`。

    真栈对照读数（issue #6785，2026-10-12 19:04 +08，`/tmp/ui-smoke-6785/probe-login.mjs`）：
    `getByRole('tab')` count=2（「员工登录 账号密码」/「管理员登录 手机验证码」）、
    `{ name: '管理员登录', exact: true }` count=**0**、`{ name: /管理员登录/ }` count=**1**。
    """
    src = driven_sources()
    entry = next(e for e in name_registry()["exact"] if e["declared"] == "管理员登录")
    assert driver_evidence_failures(entry, src) == [], "台账的 composed_of 证据现取不到（夹具失效）"
    assert standalone_text_name("管理员登录", src) == "", (
        "夹具失效：登录页上「管理员登录」不该是**独立**的 JSX 文本节点（它是 tab 标题，还有副标题）"
    )
    assert standalone_text_name("确定", src), "夹具失效：「确定」应当是独立的 JSX 文本节点（Modal.tsx）"


def test_exact_name_mismatch_would_be_caught():
    """⑭ 判据 N 判别力自证（真页面源码）：元素文本比名字长 ⇒ 现取判「不匹配」，等长才判「匹配」。

    ⚠️ 「确定」这个名字在**别的页面**（AfterSalesDetail.tsx）也是独立文本节点 ⇒ 全局摘一个文件
    inherently 绿（实测：只改 Modal.tsx，standalone 仍命中 AfterSalesDetail）——所以本条直接对
    `Modal.tsx` 的那一处现取，用同一处的**修前/修后**做对照（不依赖全量语料）。
    """
    page = "frontend/admin-web/src/components/ui/Modal.tsx"
    text = driven_sources()[page]
    idx = text.find("确定")
    assert idx >= 0, f"夹具不成立：{page} 里找不到「确定」"
    assert jsx_text_name(text, idx, "确定") == ("确定", True), f"现状应当匹配：{jsx_text_name(text, idx, '确定')}"
    mutated = text.replace(">确定<", ">确定提交<")
    assert mutated != text, "注入未生效：找不到 `>确定<`"
    longer, ok = jsx_text_name(mutated, mutated.find("确定"), "确定")
    assert longer == "确定提交" and not ok, f"名字更长时判据未红（判别力失效）：{(longer, ok)}"
    spec = spec_text()
    assert spec.count("'确定', exact: true") == 1, "夹具不成立：spec 里 exact 的「确定」选择器不是唯一一处"


def test_composed_exact_name_is_caught_on_real_corpus():
    """⑮ 未修形态的具名红（**真语料**）：把 spec 的登录 tab 选择器改回 `exact: true` ⇒
    判据 N 当场红并同时报出「写的名字 / 页面可及名字」。"""
    spec = spec_text()
    injected = spec.replace(
        "getByRole('tab', { name: /管理员登录/ })",
        "getByRole('tab', { name: '管理员登录', exact: true })",
    )
    assert injected != spec, "注入未生效：spec 里找不到非 exact 的登录 tab 选择器"
    failures, _ = exact_name_failures(injected, driven_sources(), name_registry())
    joined = "\n".join(failures)
    assert failures, "未修形态未被判红（本单的正题失守）"
    assert "管理员登录" in joined and "手机验证码" in joined, f"判红未报出「写的名字 / 页面可及名字」：{failures}"
    assert "exact" in joined, f"判红未点明 exact 口径：{failures}"


def test_name_registry_is_live_and_shrink_only():
    """⑯ 判据 N 台账纪律：未登记即红 / 理由过短即红 / 条目空转即红 / 只许缩短 / 清空即红。"""
    spec = spec_text()
    registry = name_registry()
    failures = registry_name_failures(spec, driven_sources(), registry)
    assert failures == [], "判据 N 台账自身不合规：\n" + "\n".join(f"  - {f}" for f in failures)
    base = registry["baseline_count"]
    weak = registry["registered_matchers"]
    assert len(registry["exact"]) <= base["exact"], "exact 台账超过冻结基线（只许缩短）"
    assert len(weak["matchers"]) <= base["registered_matchers"], "非 exact 台账超过冻结基线（只许缩短）"

    # ① 清空 ⇒ 红 ② 理由过短 ⇒ 红 ③ 条目空转（declared 已从页面消失）⇒ 红
    emptied = {**registry, "exact": []}
    assert registry_name_failures(spec, driven_sources(), emptied), "台账清空未判红（fail-closed 失效）"
    empty_weak = copy.deepcopy(registry)
    empty_weak["registered_matchers"]["matchers"] = []
    assert registry_name_failures(spec, driven_sources(), empty_weak), "非 exact 台账清空未判红"
    short = copy.deepcopy(registry)
    short["exact"][0]["reason"] = "太短"
    assert registry_name_failures(spec, driven_sources(), short), "理由过短未判红"
    vacuous = copy.deepcopy(registry)
    vacuous["exact"][0]["declared"] = "根本不存在的可及名字"
    assert registry_name_failures(spec, driven_sources(), vacuous), "台账空转（declared 取不到）未判红"
    stale_weak = copy.deepcopy(registry)
    stale_weak["registered_matchers"]["matchers"].append("/早已删掉的按钮/")
    assert registry_name_failures(spec, driven_sources(), stale_weak), "非 exact 条目空转（spec 里没有）未判红"
    # ④ 基线只许缩短：假装基线比条目少 ⇒ 红
    shrunk = copy.deepcopy(registry)
    shrunk["baseline_count"] = {"exact": 0, "registered_matchers": 0}
    assert registry_name_failures(spec, driven_sources(), shrunk), "超过冻结基线未判红"


def test_exact_name_must_be_registered():
    """⑰ 未登记即红：spec 里出现新的 exact 名字而台账没有 ⇒ 具名报出该选择器所在行。"""
    spec = spec_text()
    injected = spec.replace(
        "getByRole('button', { name: /登\\s*录|登录/ }).last()",
        "getByRole('button', { name: '登录', exact: true }).last()",
    )
    assert injected != spec, "注入未生效：spec 里找不到登录按钮选择器"
    failures, _ = exact_name_failures(injected, driven_sources(), name_registry())
    assert any("未登记" in f for f in failures), f"未登记的 exact 名字未判红：{failures}"


def test_non_exact_name_must_be_registered():
    """⑱ 非 exact 口径要**显式登记**（只许缩短）：去掉台账里的那条 ⇒ 红；补回 ⇒ 绿。"""
    spec = spec_text()
    registry = name_registry()
    assert weak_name_coverage_failures(spec, registry) == [], "夹具不成立：现状非 exact 已全部登记"
    without = copy.deepcopy(registry)
    without["registered_matchers"]["matchers"] = [
        m for m in without["registered_matchers"]["matchers"] if m != "/获取验证码/"
    ]
    failures = weak_name_coverage_failures(spec, without)
    assert failures and "非 exact" in "\n".join(failures), f"未登记的非 exact 口径未判红：{failures}"
    assert "获取验证码" in "\n".join(failures), f"判红未具名（哪个 matcher）：{failures}"


def test_role_and_name_criteria_are_not_vacuous_on_comment_only_edit():
    """⑲ 对照读数（判据 R/N）：**只改注释** ⇒ 不红。"""
    commented = "// 说明：历史上这里等的是 exact 文案（已随 #6785 改回非 exact）\n" + spec_text()
    assert role_liveness_failures(commented, driven_sources()) == []
    assert weak_name_coverage_failures(commented, name_registry()) == []
    assert exact_name_failures(commented, driven_sources(), name_registry())[0] == []


# ────────────────────────── 判据 B（桩 playwright 真跑 spec） ──────────────────────────
STUB_PLAYWRIGHT = r"""
// 桩 playwright（issue #6779 判据 B）：不启真浏览器，按**状态机**回应登录步骤，
// 让 spec.mjs 走到「登录步骤」并可按注入点失败。SPEC_STUB_FAIL 控制失败点：
//   空           = 登录步骤在 fill('#phone') 处失败（复现 #6779 的形态）
//   post-login  = 登录成功，02-dashboard 的首次文案等待失败（负控：归因不得落在登录步骤）
const FAIL = process.env.SPEC_STUB_FAIL || '';
class Loc {
  constructor(page, label) { this.page = page; this.label = label }
  first() { return this }
  last() { return this }
  async isVisible() { return true }
  async allTextContents() { return ['1'] }
  async waitFor() {
    if (this.label === 'text:经营看板' && FAIL === 'post-login' && this.page.url.includes('/dashboard')) {
      throw new Error('桩：看板文案等待超时')
    }
    return true
  }
  async click() {
    this.page.url = this.page.url.replace('/login', '/dashboard')
    const p = this.page
    p.context()._cookies.set('access_token', 'stub-token')
    return true
  }
  async fill() { return true }
  async count() { return 1 }
}
class Page {
  constructor(context) { this.ctx = context; this.url = ''; this.handlers = [] }
  context() { return this.ctx }
  removeAllListeners() { this.handlers = [] }
  removeListener() { return this }
  on() { return this }
  async goto(url) { this.url = String(url) }
  async reload() { return true }
  async screenshot() { return Buffer.from('') }
  async evaluate() { return 1234 }
  async waitForTimeout() { return true }
  async waitForURL() {
    if (!this.url.includes('/dashboard')) throw new Error('桩：URL 未落到 /dashboard')
    return true
  }
  getByText(t) { return new Loc(this, 'text:' + t) }
  getByRole(_role, opts) { return new Loc(this, 'role:' + ((opts || {}).name || '')) }
  locator(sel) { return new Loc(this, 'css:' + sel) }
  getByTestId(t) { return new Loc(this, 'testid:' + t) }
  fill(sel, value) {
    if (sel === '#phone' && FAIL === '') throw new Error("桩：登录步骤注入失败（fill('#phone')）")
    return Promise.resolve(true)
  }
}
class Context {
  constructor() { this._cookies = new Map(); this.pages = [] }
  async newPage() { const p = new Page(this); this.pages.push(p); return p }
  async cookies() { return [...this._cookies.entries()].map(([name, value]) => ({ name, value })) }
}
export const chromium = {
  async launch() {
    return {
      async newPage() { return new Page(new Context()) },
      async newContext() { return new Context() },
      async close() { return true },
    }
  },
}
"""


class SmokeSandbox:
    """桩 playwright 沙箱：把 spec 需要的 REPO_ROOT 指到桩上（`createRequire(REPO_ROOT/tests/package.json)`）。"""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        pkg = tmp_path / "tests/node_modules/playwright"
        pkg.mkdir(parents=True)
        (tmp_path / "tests/package.json").write_text("{}\n", encoding="utf-8")
        (pkg / "package.json").write_text('{"name":"playwright","main":"index.mjs"}\n', encoding="utf-8")
        (pkg / "index.mjs").write_text(STUB_PLAYWRIGHT, encoding="utf-8")

    def run(self, **env_extra: str) -> subprocess.CompletedProcess:
        env = {
            **os.environ.copy(),
            "REPO_ROOT": str(self.tmp),
            "BASE_URL": "http://127.0.0.1:3001",
            "OUT_DIR": str(self.tmp / "out"),
            "GROUP": "",
            "SPEC_STUB_FAIL": "",
        }
        env.update(env_extra)
        return subprocess.run(
            ["node", str(SPEC)],
            cwd=str(self.tmp),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=RUN_TIMEOUT_SECONDS,
        )


@pytest.fixture()
def smoke(tmp_path: Path) -> SmokeSandbox:
    return SmokeSandbox(tmp_path)


def test_login_step_failure_is_attributed_to_login_step(smoke: SmokeSandbox):
    """⑥ 判据 B ①：登录步骤失败 ⇒ 输出**点名登录步骤**（27 条旅程不再各自超时）。"""
    proc = smoke.run()
    out = proc.stdout + proc.stderr
    assert "❌ 01-login" in out, f"登录旅程未按注入的形态失败（桩没走到登录步骤）：\n{out[-2000:]}"
    assert "登录步骤失败" in out, f"登录步骤失败未自报『登录步骤失败』（归因缺失，issue #6779）：\n{out[-2000:]}"
    assert "01-login" in out.split("登录步骤失败", 1)[1][:80], f"归因文案未点名位置：\n{out[-2000:]}"
    assert proc.returncode != 0, "登录步骤失败却退出 0"


def test_attribution_is_not_vacuous_when_a_later_journey_fails(smoke: SmokeSandbox):
    """⑦ 判据 B ②（负控）：登录成功、后续旅程失败 ⇒ 不得归因到登录步骤（判据非恒真）。"""
    proc = smoke.run(SPEC_STUB_FAIL="post-login")
    out = proc.stdout + proc.stderr
    assert "❌ 02-dashboard" in out, f"02-dashboard 未按注入的形态失败：\n{out[-2000:]}"
    assert "登录步骤失败" not in out, f"后续旅程的失败被误归因到登录步骤（归因判据恒真）：\n{out[-2000:]}"
