# case_ids: MC-012
"""商家冒烟 spec 的**选择器活性**与**登录步骤归因**守卫（issue #6779，类级固化）。

## 病灶（issue #6779，2026-10-12 实跑读数）

在 `origin/main` 之上真跑 `node scripts/ui-smoke-merchant/spec.mjs`（栈：admin-api:8090 + admin-web:3001）：

    ===== 汇总: 7/34 通过，27 失败 =====
    ❌ 01-login  超时: waiting for getByText('手机号登录').first() to be visible
    ❌ 02-dashboard  看板失败: waiting for getByText('经营看板') … navigated to "http://localhost:3001/login"

通过的是 7 条**未登录面**（官网四页 / 注册 / 登录页渲染）⇒ 真因是**登录步骤**等一个
已不存在的文案：登录页（`frontend/admin-web/src/app/login/page.tsx`）自 issue #5485 起是两个
tab（「员工登录」默认 / 「管理员登录」），**全文件没有「手机号登录」**。
27 条已登录旅程随即被弹回 `/login`，长得像「产品大面积回归」。

## 两道判据

- **判据 A（活性）**：spec 里 `expectText(...)` / `getByText(...)` / `getByRole(..., {name})` 的
  **文案字面量**必须能在**被驱动面**（`frontend/admin-web/src/**` + 同套件的 `criteria.mjs`）里
  **逐字取到**（按空白无关比对；正则选择器按 `|` 分组，**任一分组**能取到才算活 —— 与 Playwright
  的运行语义一致，存活的备选项不会因同列里其它备选项过期而失效）。取不到 ⇒ 判红并**具名**报出
  「哪个字面量 / 哪一行 / 哪个文件」。**确实动态生成**的文案走登记式豁免
  （台账 `ui_smoke_selector_exemptions.json`，只许缩短 + 每条带理由 + 条目不得空转）。
- **判据 B（归因）**：登录步骤失败必须**自报「登录步骤失败[位置]」**，不许让 27 条旅程各自超时
  —— 用**桩 playwright + 桩页面**真跑 `spec.mjs` 钉死：① 登录步骤失败 ⇒ 输出点名登录步骤；
  ② 登录成功、后续旅程失败 ⇒ 输出**不得**归因到登录步骤（负控，判据不是恒真）。

## 边界（照实登记，§19.1）

- **不真起栈、不跑 31 旅程**：判据 A 是静态面，判据 B 用桩 playwright（本机此刻另有栈在跑）。
- 本判据**不改** 31 条旅程的业务断言。
- **未固化面（有意）**：① CSS / xpath 选择器（`.locator('tbody tr')` / `[data-testid=...]`）不在
  射程内 —— 断言「选择器字符串出现在源码里」会把 CSS 选择器判死，形态不同，另单另判；
  ② 选择器的**行为面**（文案在源码里、但页面结构变了导致选择器落空）判不了 —— 本判据只锁
  「文案是否还存在于被驱动面」这一层腐烂；③ 判据 A 只覆盖 `expectText` / `getByText` /
  `getByRole`（issue #6779 的射程），`getByLabel` / `getByPlaceholder` / `getByTestId` 与
  `locator('text=…')` 暂无调用点，出现调用点时须同批扩射程。
"""
from __future__ import annotations

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
            j = i + 1
            while j < len(line) and line[j] != c:
                j += 1
            out.append(("str", line[i + 1:j]))
            i = j + 1
            continue
        if c == "/" and i + 1 < len(line) and line[i + 1] not in " /":
            j = i + 1
            buf = ""
            while j < len(line) and line[j] != "/":
                if line[j] == "\\":
                    buf += line[j:j + 2]
                    j += 2
                    continue
                buf += line[j]
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
    """被驱动面：admin-web 源码（页面本体）+ 同套件的 `criteria.mjs`（判据常量的单一源）。"""
    src: dict[str, str] = {}
    for path in sorted(ADMIN_WEB_SRC.rglob("*")):
        if path.is_file() and path.suffix in (".tsx", ".ts", ".jsx", ".js"):
            src[str(path.relative_to(REPO_ROOT))] = path.read_text(encoding="utf-8", errors="replace")
    src[str(SMOKE_MODULE.relative_to(REPO_ROOT))] = SMOKE_MODULE.read_text(encoding="utf-8")
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
