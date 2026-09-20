#!/usr/bin/env python3
"""「用墙钟造期望值」的机械守卫（形态 A）—— issue #4717 的**测试层**部分。

## 治什么（两次真实事故，均为 required 集合里的随机红）

| 实例 | 形态 | 后果 |
|---|---|---|
| **#4713**（修于 `fbc83a163`） | 期望值取自**断言时的"现在"**（`new Date()` → `getHours():getMinutes()`），被测组件渲染的却是**消息自己的** `formatTime(created_at)`；夹具在**模块加载**时建 ⇒ 两者跨一分钟边界必红 | 两包各约 10~15% 随机红，在 required 的 `mini-app typecheck + unit tests` 里 |
| **#4717**（修于 `13f6faaa3`） | `await waitFor(A)` 后紧跟与 A **无因果关系**的同步 `expect(B)`，A/B 由**不同 commit** 产出 ⇒ commit 竞态 | 随机红，在 required 的 `admin-web typecheck + unit tests` 里 |

本模块只治**形态 A**（可机械判定）。形态 B 见下「为什么不做形态 B」。

## 判据：怎么区分「造夹具数据」与「造期望值」

一条墙钟读数是**危险**的，当且仅当它的值**流进了 `expect(...)` 的实参区间**——
即它被当成了「拿什么去比」的**参照物**；而只是喂给被测系统当**输入数据**的墙钟读数
（`created_at: new Date().toISOString()` 塞进夹具、`exp: Date.now()/1000 + 3600` 塞进 JWT
payload）不在此列：被测系统的输出由那份输入唯一决定，墙钟漂移不改变判据。

机械判定分三步（全部只看文本，无 AST 依赖）：

1. **源**：`new Date()`（**空实参**；`new Date(x)` 是解析给定时刻，不是读墙钟）与 `Date.now(`；
   注释区先被替换成等长空白 ⇒ 注释里的提及不算。
2. **冻结豁免**：出现 `useFakeTimers(` / `setSystemTime(` 的**作用域**内，墙钟已不是墙钟 ⇒ 不判。
   作用域 = 「该 `it`/`test` 块内」∪「所有 `it`/`test` 块之外」（模块级 / `describe` 级钩子）。
   ⚠️ 已知边界（照实登记）：`describe` 级 `beforeEach(useFakeTimers)` 会让**同 describe 之外**的
   用例也免检（保守方向：宁漏不误伤）。测试 T10 钉住「同文件另一条用例仍被判」以免退化成整文件免检。
3. **污点传播 + 汇**：`const/let/var NAME = <含源或含已污点标识符的右值>`、`function NAME(){...}`
   （函数体含源或已污点标识符）⇒ `NAME` 污点，迭代到不动点；**停表豁免**：右值形如
   `<墙钟读数> - <另一个读数/标识符>`（用同一只钟量**时长**）不算参照物 ⇒ 不污点
   （否则 `expect(elapsed).toBeGreaterThanOrEqual(550)` 会被误判）。任一 `expect(` 的
   配对实参区间里出现源或污点标识符 ⇒ **判红**。

⇒ 由此可区分三种现存形态（全部实测，见 `test_time_flaky_guard.py`）：
`expected = new Date().toISOString().slice(0,7)` 后 `expect(mock).toHaveBeenCalledWith({period: expected})` = **红**；
`created_at: new Date().toISOString()` 后 `render(<C message={msg} />)` = **不红**；
`const start = Date.now()` … `expect(Date.now() - start).toBeGreaterThanOrEqual(x)` = **不红**。

## 为什么不做形态 B（`await waitFor(A)` 后同步断言 B）

「B 与 A **无因果关系**」需要知道组件在哪个 commit 产出 B —— **文本判据拿不到这个信息**。
最锐利的朴素机械化（「等待的 testid 集合 ∩ 断言的 testid 集合 = ∅」）在本仓现有套件上实测命中
**127 处 / 15 个文件**，其中绝大多数是**合法且今天就是绿的**（如 `categories.test.tsx`：
`await waitFor(category-dialog)` 后 `expect(edit-1)` —— 两者由同一次点击的同一个 commit 产出）。
⇒ 做成门禁 = 一次改红 15 个文件、且此后每个正常用例都可能被判红（#4717 的教训是
「**定位机制**而非加等待」，不是「见到这个形状就红」）。
故形态 B **只做非门禁的普查**（`form_b_census()`，advisory，不参与退出码），把「为什么不假红」
变成可复现的读数而不是断言。复现：
`python3 tests/unit_ci_workflows/time_flaky_guard.py --census`。

## 不写死任何计数（#4701 / #4714 / #4742 纪律）

判据里**没有任何**「违规数 == N」。存量豁免走 `time_flaky_baseline.json`（照 `drift_audit`
的 `baseline.json` 形态）：**每条豁免都带 `reason`**，且**只许缩短**——
① 账本里记着、现在不再漂移 ⇒ 红（必须销账）；② 计数超出账本 ⇒ 红；③ 不在账本里的新命中 ⇒ 红。

## 用法

```bash
python3 tests/unit_ci_workflows/time_flaky_guard.py --check    # 门禁，0/1/3
python3 tests/unit_ci_workflows/time_flaky_guard.py --list     # 列出全部命中（含存量）
python3 tests/unit_ci_workflows/time_flaky_guard.py --census   # 形态 B 普查（advisory）
```
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = Path(__file__).resolve().parent / "time_flaky_baseline.json"

RULE = "wallclock-expected"

# 扫描面：`frontend/*/tests/**` 与 `frontend/*/src/**/*.test.*`（守卫**只读**，不改前端）
PACKAGE_GLOBS = ("tests", "src")

IDENT = r"[A-Za-z_$][\w$]*"
SOURCE_RE = re.compile(r"\bnew\s+Date\s*\(\s*\)|\bDate\s*\.\s*now\s*\(")
FREEZE_RE = re.compile(r"\b(?:useFakeTimers|setSystemTime)\s*\(")
BINDING_RE = re.compile(r"\b(?:const|let|var)\s+(" + IDENT + r")\s*=")
FUNC_DECL_RE = re.compile(r"\bfunction\s+(" + IDENT + r")\s*\(")
EXPECT_RE = re.compile(r"\bexpect\s*\(")
IDENT_RE = re.compile(IDENT)
TEST_BLOCK_RE = re.compile(r"(?<![\w$.])(?:it|test)(?:\.\w+)?\s*\(")
_TICKS = 8  # 污点不动点迭代上限（纯防御：链长超 8 跳的用例极罕见）


# ═══════════════════════════════════════════════════════════════════════════
# 文本工具（保持偏移不变，便于报行号）
# ═══════════════════════════════════════════════════════════════════════════
def blank_comments(text: str) -> str:
    """把注释内容替换成**等长空白**（`\\n` 保留）—— 注释里的 `new Date()` 不算命中。

    字符串/模板串内的 `//`、`/*` 不误判（逐字符跟踪引号状态）。
    """
    out = list(text)
    i, n, quote = 0, len(text), None
    while i < n:
        c = text[i]
        if quote is not None:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "\"'`":
            quote = c
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


def _match_pair(text: str, open_idx: int, opener: str, closer: str) -> int:
    """返回与 `text[open_idx] == opener` 配对的 `closer` 下标；不平衡则返回 `len(text)-1`。"""
    depth, i, n, quote = 0, open_idx, len(text), None
    while i < n:
        c = text[i]
        if quote is not None:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
        elif c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n - 1


def _match_paren(text: str, open_idx: int) -> int:
    return _match_pair(text, open_idx, "(", ")")


def _match_brace(text: str, open_idx: int) -> int:
    return _match_pair(text, open_idx, "{", "}")


def _statement_end(text: str, start: int) -> int:
    """右值语句的结束下标：深度 0 处的 `;` / 换行（下一行以续行符开头则继续）。"""
    depth, i, n, quote = 0, start, len(text), None
    while i < n:
        c = text[i]
        if quote is not None:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                return i
            depth -= 1
        elif c == ";" and depth == 0:
            return i
        elif c == "\n" and depth == 0:
            j = i + 1
            while j < n and text[j] in " \t":
                j += 1
            if j < n and text[j] in ".?+-|&,)]}":
                i = j
                continue
            return i
        i += 1
    return n


def _line_of(text: str, idx: int) -> int:
    return text[:idx].count("\n") + 1


# ═══════════════════════════════════════════════════════════════════════════
# 判据本体
# ═══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Finding:
    """一条命中。`key` 必须**稳定**（不含行号）—— 否则改一行就换 key，「只许缩短」失效。"""

    path: str          # 仓库相对 posix 路径
    line: int
    symbol: str        # 流进 expect 的污点标识符 / `<direct>`（源直接出现在 expect 区间里）
    snippet: str

    @property
    def key(self) -> str:
        return f"{self.path}|{RULE}|{self.symbol}"


@dataclass(frozen=True)
class FormBCandidate:
    """形态 B 的**朴素**机械化命中（advisory，不参与门禁判定）。"""

    path: str
    line: int
    awaited_ids: tuple[str, ...]
    asserted_ids: tuple[str, ...]


def iter_test_files(root: Path) -> list[Path]:
    """`frontend/*/tests/**/*.test.{ts,tsx}` ∪ `frontend/*/src/**/*.test.{ts,tsx}`。"""
    out: list[Path] = []
    frontend = root / "frontend"
    if not frontend.is_dir():
        return out
    for pkg in sorted(p for p in frontend.iterdir() if p.is_dir()):
        for sub in PACKAGE_GLOBS:
            base = pkg / sub
            if not base.is_dir():
                continue
            out += sorted(
                p for p in base.rglob("*")
                if p.is_file() and p.suffix in (".ts", ".tsx") and ".test." in p.name
            )
    return out


def _test_block_spans(text: str) -> list[tuple[int, int]]:
    """所有 `it(...)` / `test(...)` 块的 `[起, 止]`（含括号）。"""
    spans = []
    for m in TEST_BLOCK_RE.finditer(text):
        open_idx = text.find("(", m.end() - 1)
        if open_idx < 0:
            continue
        spans.append((m.start(), _match_paren(text, open_idx)))
    return spans


def _frozen_regions(text: str) -> tuple[bool, list[tuple[int, int]]]:
    """返回 `(模块级是否冻结, 已冻结的 test 块区间列表)`。"""
    blocks = _test_block_spans(text)
    file_scope = False
    frozen_blocks: list[tuple[int, int]] = []
    for m in FREEZE_RE.finditer(text):
        owner = next((b for b in blocks if b[0] <= m.start() <= b[1]), None)
        if owner is None:
            file_scope = True
        elif owner not in frozen_blocks:
            frozen_blocks.append(owner)
    return file_scope, frozen_blocks


@dataclass(frozen=True)
class Taint:
    """`names` = 可当**参照物**的墙钟派生名（已剔除停表）；`clock` = 未剔除的**超集**。

    `clock` 只用于判定「`-` 的右操作数是不是另一只读数」—— 即停表判据本身。
    """

    names: set[str]
    clock: set[str]


def analyze_taint(text: str) -> Taint:
    """含墙钟读数的绑定名 / 函数名（迭代到不动点；**停表**形态不计）。

    两阶段：先求「右值直接/间接受墙钟污染」的**超集**，再从中剔除**停表**名字
    （右值形如 `<读数> - <另一个读数|已被污染的标识符>` ⇒ 用同一只钟量**时长**，
    不是拿去当参照物）。顺序无关，避免「先处理谁」改变判定。
    """
    bindings: list[tuple[str, int, int]] = []
    for m in BINDING_RE.finditer(text):
        bindings.append((m.group(1), m.end(), _statement_end(text, m.end())))
    for m in FUNC_DECL_RE.finditer(text):
        pclose = _match_paren(text, m.end() - 1)
        brace = text.find("{", pclose)
        if brace < 0:
            continue
        bindings.append((m.group(1), brace, _match_brace(text, brace)))

    clock = _closure(bindings, text, set())
    stopwatch = {
        name for name, start, end in bindings
        if name in clock and _has_stopwatch_operand(text[start:end], clock)
    }
    stopwatch |= _stopwatch_operands(text, clock)
    return Taint(_closure(bindings, text, stopwatch), clock)


def tainted_names(text: str) -> set[str]:
    """可当参照物的墙钟派生名（`analyze_taint` 的薄封装）。"""
    return analyze_taint(text).names


def _closure(bindings, text, excluded: set[str]) -> set[str]:
    """不动点：右值含墙钟读数或含已污染标识符 ⇒ 该名字污染（`excluded` 永不入集）。"""
    tainted: set[str] = set()
    for _ in range(_TICKS):
        changed = False
        for name, start, end in bindings:
            if name in tainted or name in excluded:
                continue
            rhs = text[start:end]
            if SOURCE_RE.search(rhs) or _mentions_tainted(rhs, tainted):
                tainted.add(name)
                changed = True
        if not changed:
            break
    return tainted


def _has_stopwatch_operand(rhs: str, seed: set[str]) -> bool:
    """`-` 的右操作数**本身**是墙钟读数或已被污染的名字 ⇒ 这是量时长，不是参照物。

    （只看 `-` 后紧跟的那个 token：模板串里的 `` `${a}-${b}` `` 取到的是 `$`，不会误判 ——
    实测 `todayLocal()` 的 `` `${d.getFullYear()}-${mm}-${dd}` `` 曾被误判成停表。）
    """
    for m in re.finditer(r"-\s*(" + IDENT + r"|Date\s*\.\s*now\s*\(|new\s+Date\s*\(\s*\))", rhs):
        operand = m.group(1)
        if operand in seed or SOURCE_RE.search(operand):
            return True
    return False


# 墙钟读数**直接**出现在汇里、且紧跟 `- <另一只读数>` ⇒ 同样是停表（`expect(Date.now() - start)`）。
# 锚在读数之后（`^`），避免把「读数之后隔了半条语句的减号」也算成停表。
_DIRECT_STOPWATCH_RE = re.compile(
    r"^\s*\)?\s*-\s*(" + IDENT + r"|Date\s*\.\s*now\s*\(|new\s+Date\s*\(\s*\))"
)


def _direct_stopwatch(tail: str, clock: set[str]) -> bool:
    m = _DIRECT_STOPWATCH_RE.match(tail)
    return bool(m) and (m.group(1) in clock or bool(SOURCE_RE.search(m.group(1))))


def _mentions_tainted(fragment: str, tainted: set[str]) -> bool:
    return any(tok in tainted for tok, _ in _code_tokens(fragment))


def code_mask(fragment: str) -> list[bool]:
    """逐字符标出**代码区**（`True`）；字符串内容为 `False`，但**模板串的 `${...}` 插值是代码**。

    为什么插值必须算代码：`const expectedTime = \\`${hours}:${minutes}\\`` 正是 #4713 的形态，
    把整段模板串当字符串会**漏判**（假绿）。
    """
    mask = [True] * len(fragment)

    def walk(start: int, end: int) -> None:
        i = start
        while i < end:
            c = fragment[i]
            if c in "\"'`":
                quote = c
                j = i + 1
                while j < end:
                    if fragment[j] == "\\":
                        mask[j] = False
                        if j + 1 < end:
                            mask[j + 1] = False
                        j += 2
                        continue
                    if fragment[j] == quote:
                        break
                    if quote == "`" and fragment[j] == "$" and j + 1 < end and fragment[j + 1] == "{":
                        close = _match_brace(fragment, j + 1)
                        walk(j + 2, close)
                        j = close + 1
                        continue
                    mask[j] = False
                    j += 1
                if j < end:
                    mask[j] = False
                i = j + 1
                continue
            i += 1

    walk(0, len(fragment))
    return mask


def _code_tokens(fragment: str):
    """**代码区**的标识符 `(文本, 下标)` —— 字符串内的词、以及 `.` 之后的属性名不算。

    三条排除各治一个实测假红 / 假绿：
    ① `'交期 yyyy-MM-dd'` 里的 `dd` 与污点变量 `dd` 撞名（ProcessingOrderBlock 实测假红）；
    ② `currentPeriod.start` 里真正带污点的是 `currentPeriod`，属性名不是载体；
    ③ 模板串的 `${...}` 插值算代码（见 `code_mask`）。
    """
    mask = code_mask(fragment)
    return [
        (m.group(0), m.start())
        for m in IDENT_RE.finditer(fragment)
        if mask[m.start()] and (fragment[m.start() - 1] if m.start() else "") != "."
    ]


def _stopwatch_operands(text: str, clock: set[str]) -> set[str]:
    """被当作 `-` **右操作数**用掉的墙钟派生名 ⇒ 它是秒表的另一头，不是参照物。

    治的实测假红：`const start = Date.now()` … `expect(Date.now() - start).toBeGreaterThanOrEqual(550)`
    —— `start` 本身不含减号，光靠「结果是停表」的规则拦不住。
    """
    mask = code_mask(text)
    ops: set[str] = set()
    for m in re.finditer(r"-\s*(" + IDENT + r")", text):
        if mask[m.start()] and m.group(1) in clock:
            ops.add(m.group(1))
    return ops


def scan_text(text: str, path: str) -> list[Finding]:
    """单个测试文件里的形态 A 命中（判据本体，供红证直接驱动）。"""
    clean = blank_comments(text)
    file_frozen, frozen_blocks = _frozen_regions(clean)
    if file_frozen:
        return []
    taint = analyze_taint(clean)

    findings: list[Finding] = []
    seen: set[tuple[int, str]] = set()
    for m in EXPECT_RE.finditer(clean):
        if any(b[0] <= m.start() <= b[1] for b in frozen_blocks):
            continue
        # 汇 = **整条 `expect(...)` 语句**（含 matcher 的实参）—— 期望值在 `.toBe(...)` /
        # `.toHaveBeenCalledWith(...)` / `getByText(<参照物>)` 里，**不在** `expect(...)` 自己的
        # 括号内（实证：只取 `expect(` 的配对区间会漏掉全部 `toHaveBeenCalledWith` 形态）。
        span = clean[m.start():_statement_end(clean, m.start())]
        src = next(
            (s for s in SOURCE_RE.finditer(span)
             if not _direct_stopwatch(span[s.end():], taint.clock)),
            None,
        )
        if src is not None:
            symbol, idx = "<direct>", m.start() + src.start()
        else:
            hit = next(((tok, off) for tok, off in _code_tokens(span) if tok in taint.names), None)
            if hit is None:
                continue
            symbol, idx = hit[0], m.start() + hit[1]
        line = _line_of(clean, m.start())
        if (line, symbol) in seen:
            continue
        seen.add((line, symbol))
        findings.append(Finding(path, line, symbol, _snippet(text, line)))
    return findings


def _snippet(text: str, line: int) -> str:
    lines = text.split("\n")
    return lines[line - 1].strip() if 0 < line <= len(lines) else ""


def scan_repo(root: Path = REPO_ROOT) -> tuple[list[Finding], list[Path]]:
    """扫描整个前端测试面。返回 `(命中, 扫描到的文件)` —— 文件列表用于**防空跑**自证。"""
    files = iter_test_files(root)
    findings: list[Finding] = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:  # fail-closed：读不到不许退化成「无命中」
            raise ValueError(f"无法读取测试文件 {p}（{e.__class__.__name__}）") from e
        findings += scan_text(text, p.relative_to(root).as_posix())
    return findings, files


# ═══════════════════════════════════════════════════════════════════════════
# 形态 B 普查（advisory，**不参与**退出码）
# ═══════════════════════════════════════════════════════════════════════════
_AWAIT_RE = re.compile(
    r"await\s+(?:waitFor\s*\(|(?:screen|within\([^)]*\))\.find(?:All)?By)"
)
_TESTID_RE = re.compile(r"[A-Za-z]*[Tt]estId\(\s*['\"`]([^'\"`]+)['\"`]")


def form_b_census(text: str, path: str) -> list[FormBCandidate]:
    """朴素形态 B 规则：「等待的 testid 集合 ∩ 断言的 testid 集合 = ∅」且断言是**同步**的。

    ⚠️ **不得用于门禁** —— 它在现有套件上有大量**合法**命中（同一次交互的同一次 commit
    产出两个 testid）。本函数只为把「为什么不假红」变成可复现读数。
    """
    out: list[FormBCandidate] = []
    for m in _AWAIT_RE.finditer(text):
        open_idx = text.find("(", m.start())
        end = _match_paren(text, open_idx)
        awaited = tuple(sorted(set(_TESTID_RE.findall(text[open_idx:end + 1]))))
        rest = text[end + 1:]
        nxt = re.search(r"\n[ \t]*(?:await\s+)?expect\s*\(", rest)
        if nxt is None:
            continue
        estart = end + 1 + nxt.start()
        eopen = text.find("(", estart)
        if re.search(r"\bawait\b", text[estart:eopen]):
            continue
        asserted = tuple(sorted(set(_TESTID_RE.findall(text[eopen:_match_paren(text, eopen) + 1]))))
        if awaited and asserted and not (set(awaited) & set(asserted)):
            out.append(FormBCandidate(path, _line_of(text, estart), awaited, asserted))
    return out


def census_repo(root: Path = REPO_ROOT) -> list[FormBCandidate]:
    out: list[FormBCandidate] = []
    for p in iter_test_files(root):
        out += form_b_census(p.read_text(encoding="utf-8"), p.relative_to(root).as_posix())
    return out


# ═══════════════════════════════════════════════════════════════════════════
# 账本（存量豁免：每条带理由，只许缩短）
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class Reconcile:
    new: list[Finding]
    grown: list[tuple[str, int, int]]
    stale: list[str]
    problems: list[str]

    @property
    def ok(self) -> bool:
        return not (self.new or self.grown or self.stale or self.problems)


def load_ledger(path: Path = LEDGER_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_ledger(ledger: dict) -> list[str]:
    """账本自身的形态判据：每条豁免都要有理由，且 key 不含行号（否则会腐烂）。"""
    problems: list[str] = []
    entries = ledger.get("entries")
    if not isinstance(entries, dict):
        return ["账本缺 `entries` 字典"]
    for key, meta in entries.items():
        if not isinstance(meta, dict) or not str(meta.get("reason", "")).strip():
            problems.append(f"账本条目 `{key}` 缺非空 `reason`（每个豁免都要有理由）")
        if re.search(r"[:#]\d+\b", key):
            problems.append(f"账本条目 `{key}` 的 key 含行号 —— 改一行就换 key，「只许缩短」会失效")
        if not isinstance(meta.get("count"), int) or meta["count"] < 1:
            problems.append(f"账本条目 `{key}` 缺正整数 `count`")
    return problems


def reconcile(findings: list[Finding], ledger: dict) -> Reconcile:
    """账本对账：新命中 ⇒ 红；计数超出 ⇒ 红；账本记着但已不漂移 ⇒ 红（必须销账）。"""
    counts = Counter(f.key for f in findings)
    entries = ledger.get("entries", {})
    new = [f for f in findings if f.key not in entries]
    grown = [
        (key, cnt, entries[key]["count"])
        for key, cnt in sorted(counts.items())
        if key in entries and cnt > entries[key]["count"]
    ]
    stale = sorted(k for k in entries if k not in counts)
    return Reconcile(new, grown, stale, validate_ledger(ledger))


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="「用墙钟造期望值」的机械守卫（issue #4717 测试层）")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="门禁模式（默认）：0/1/3")
    g.add_argument("--list", action="store_true", help="列出全部命中（含已登记的存量）")
    g.add_argument("--census", action="store_true", help="形态 B 普查（advisory，不参与退出码）")
    args = ap.parse_args(argv)

    if args.census:
        cands = census_repo()
        files = sorted({c.path for c in cands})
        print(f"形态 B 朴素规则命中：{len(cands)} 处 / {len(files)} 个文件（**advisory，不门禁**）")
        for c in cands[:20]:
            print(f"  {c.path}:{c.line} awaited={list(c.awaited_ids)} asserted={list(c.asserted_ids)}")
        if len(cands) > 20:
            print(f"  …（其余 {len(cands) - 20} 处略）")
        return 0

    try:
        findings, files = scan_repo()
        ledger = load_ledger()
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"❓ 无法判定（{e.__class__.__name__}: {e}）", file=sys.stderr)
        return 3

    if not files:
        print("❓ 无法判定：扫描面为空（`frontend/*/{tests,src}` 下一个测试文件都没有）", file=sys.stderr)
        return 3

    result = reconcile(findings, ledger)
    print(f"扫描面：{len(files)} 个前端测试文件；形态 A 命中：{len(findings)} 处"
          f"（其中已登记存量 {len(findings) - len(result.new)} 处）")

    if args.list:
        for f in findings:
            print(f"  {f.path}:{f.line}  [{f.symbol}]  {f.snippet}")
        return 0

    if result.ok:
        print("✅ 无新增「用墙钟造期望值」命中，账本无增长、无残留")
        return 0

    for f in result.new:
        print(f"❌ 新增命中 {f.path}:{f.line}  [{f.symbol}]  {f.snippet}")
    for key, now, base in result.grown:
        print(f"❌ 存量增长 {key}：{base} → {now}")
    for key in result.stale:
        print(f"❌ 账本残留 {key}：该处已不再漂移 ⇒ 必须从 time_flaky_baseline.json 销账")
    for p in result.problems:
        print(f"❌ 账本形态 {p}")
    print("处置：期望值从**夹具自身**派生（如 `baseMsg.created_at`）或冻结时间"
          "（`useFakeTimers()` + `setSystemTime(FROZEN_NOW)`）；**不要**放宽既有断言。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
