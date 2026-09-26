# case_ids: UI-063
"""`@/components/orders` **桶导出 ↔ 页面测试 mock** 完整性守卫（issue #5651 实测固化）。

## 病根（实测，不是推断）

往 `frontend/admin-web/src/components/orders/index.ts` 加两个导出（`ProcessingDoc` / `SalesDoc`）后，
`frontend/admin-web/tests/unit/pages/order-detail.test.tsx` 的 `vi.mock('@/components/orders', …)`
少了这两个键 ⇒ **26 条用例渲染期崩**：

```
Error: [vitest] No "ProcessingDoc" export is defined on the "@/components/orders" mock.
```

它是**复发类**，不是新问题：同一个文件里**已经**为同族问题留过注释
（`OrderUrgencyPanel`，issue #5177：「不替身会让 `@/components/orders` 的 mock 缺该导出 ⇒ 渲染期直接抛」）
—— 也就是说「加导出 ⇒ 页面测试崩」已经发生过一次，而**没有任何东西会因此变红**
（全量 vitest 会红，但那是事后 26 条一起爆，且只在跑全量时才看得见）。

## 冻结口径

**凡 `vi.mock('@/components/orders', …)` 的测试文件，其 mock 必须覆盖「它加载的页面**真的 import 了**的
那些桶组件」。** 口径**不**写成「桶里全部导出」：页面只 import 自己渲染的那几个（订单详情页不 import
`OrderTable`），按全量要求会把**合规文件判红**（假红，且永远修不完）。

| # | 判据 | 红证（怎么让它**单独**变红） |
|---|---|---|
| C1 | 桶里至少 5 个组件导出、至少 2 个 mock 文件、且至少 1 个解析出**非空**需求集（反空跑） | 解析口径失效 ⇒ 红 |
| C2 | 每个 mock 文件都覆盖了它加载页面所 import 的桶组件 | 删掉一条**页面确实 import 的**替身键 ⇒ 该文件具名报出缺哪个 ⇒ 红 |
| C3 | 注入式红证 + **内容指纹**自证（禁 mtime/size） | 注入未生效 ⇒ 红（红证自己是空断言） |

⚠️ 判据按**去注释后的代码**判定：mock 文件里用注释解释「为什么要替身」并点名组件名，
按原文判定会把解释性注释当成替身 = 假绿。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_WEB = REPO_ROOT / "frontend" / "admin-web"
BARREL = ADMIN_WEB / "src" / "components" / "orders" / "index.ts"
TESTS_DIR = ADMIN_WEB / "tests"
MODULE = "@/components/orders"

#: 只认**组件**导出（`export { default as X } from './X'`）；`export type …` 不是渲染期导出，不判
_BARREL_EXPORT_RE = re.compile(r"export\s*\{\s*default\s+as\s+([A-Za-z_$][\w$]*)\s*\}")
#: `vi.mock('@/components/orders'` 或双引号写法
_MOCK_RE = re.compile(r"vi\.mock\(\s*['\"]" + re.escape(MODULE) + r"['\"]")
#: 测试文件加载的页面模块（`@/app/...`）
_PAGE_IMPORT_RE = re.compile(r"from\s*['\"](@/app/[^'\"]+)['\"]")
#: 页面模块从桶里 import 的名字（含多行写法）
_ORDERS_IMPORT_RE = re.compile(
    r"import\s*(?:type\s+)?\{([^}]*)\}\s*from\s*['\"]" + re.escape(MODULE) + r"['\"]", re.S
)


def _read(path: Path) -> str:
    if not path.is_file():
        raise AssertionError(f"受管文件不存在：{path.relative_to(REPO_ROOT)} ⇒ 路径漂移不得静默跳过（红）")
    return path.read_text(encoding="utf-8")


def _strip_comments(src: str) -> str:
    """剥掉 `//` 与 `/* */` 注释（**字符串字面量内的不剥**）。

    mock 文件用注释解释「为什么要替身」并**点名组件**（如 `OrderUrgencyPanel`）——
    按原文判定会把注释读成替身（假绿），把上一轮的血泪注释逼成违规（假红）。
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


def _barrel_exports() -> list[str]:
    """桶里导出的**组件**名（保持文件里的顺序，便于报错可读）。"""
    return _BARREL_EXPORT_RE.findall(_strip_comments(_read(BARREL)))


def _page_module(alias: str) -> Path | None:
    """把 `@/app/...` 别名解析成真实文件（页面/布局都可能是 `.tsx`）。"""
    base = ADMIN_WEB / "src" / alias[len("@/") :]
    for cand in (base.with_suffix(".tsx"), base.with_suffix(".ts"), base / "index.tsx"):
        if cand.is_file():
            return cand
    return None


def _required_by_pages(code: str) -> list[str]:
    """该测试文件加载的页面**真的 import 了**的桶组件名（判据 C2 的需求集）。"""
    names: list[str] = []
    for alias in sorted(set(_PAGE_IMPORT_RE.findall(code))):
        page = _page_module(alias)
        if page is None:
            continue
        groups = _ORDERS_IMPORT_RE.findall(_strip_comments(page.read_text(encoding="utf-8")))
        for group in groups:
            for raw in group.split(","):
                name = raw.strip()
                if name.startswith("type "):
                    continue
                name = name.split(" as ")[0].strip()
                if name and name not in names:
                    names.append(name)
    return names


def _mock_files() -> dict[str, str]:
    """`{相对路径: 去注释后的源码}` —— 所有 `vi.mock('@/components/orders', …)` 的测试文件。"""
    found: dict[str, str] = {}
    for path in sorted(TESTS_DIR.rglob("*")):
        if not path.is_file() or path.suffix not in (".ts", ".tsx"):
            continue
        code = _strip_comments(path.read_text(encoding="utf-8"))
        if _MOCK_RE.search(code):
            found[str(path.relative_to(REPO_ROOT))] = code
    return found


def _missing_stubs(required: list[str], code: str) -> list[str]:
    """该 mock 文件**没提供替身**的需求项（判据：名字必须作为对象键出现在代码里）。"""
    missing: list[str] = []
    for name in required:
        if not re.search(r"(?m)^\s+" + re.escape(name) + r"\s*:", code):
            missing.append(name)
    return missing


def _fingerprint(text: str) -> str:
    """内容指纹（issue #4260 红证卫生：**禁 mtime / size**）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── C1：反空跑 ───────────────────────────────────────────────────────────────

def test_c1_scan_is_not_vacuous():
    """C1：桶导出解析得到、且至少一个 mock 文件解析出**非空**需求集（解析失效 ⇒ 空跑 ⇒ 必须红）。"""
    exports = _barrel_exports()
    assert len(exports) >= 5, (
        f"只解析到 {len(exports)} 个桶组件导出（{exports}）—— 解析口径已失效，本守卫正在空跑"
    )
    for name in ("ProcessingDoc", "SalesDoc", "ShipmentDoc", "QuotationDoc"):
        assert name in exports, f"桶里没有 `{name}` 导出 —— 本单新增的两份单据或既有单据不见了"

    mocks = _mock_files()
    assert len(mocks) >= 2, f"只找到 {len(mocks)} 个 `vi.mock('{MODULE}')` 的测试文件 —— 判据会空跑通过"
    resolved = {rel: _required_by_pages(code) for rel, code in mocks.items()}
    assert any(resolved.values()), (
        "没有任何 mock 文件解析出需求集（页面 import 解析失效）—— C2 会**空跑通过**"
        f"（解析结果：{resolved}）"
    )


# ── C2：mock 覆盖页面 import 的桶组件 ────────────────────────────────────────

def test_c2_every_barrel_export_has_a_stub_in_every_mock_file():
    """C2：mock 替身必须覆盖它加载页面所 import 的桶组件（issue #5651 实测的那 26 条崩因）。"""
    offenders: list[str] = []
    checked = 0
    for rel, code in sorted(_mock_files().items()):
        required = _required_by_pages(code)
        if not required:
            continue
        checked += 1
        missing = _missing_stubs(required, code)
        if missing:
            offenders.append(f"{rel}: 缺 {missing}（页面 import 了：{required}）")
    assert checked >= 1, "没有任何 mock 文件被真正判定 ⇒ 判据空跑（解析口径失效）"
    assert offenders == [], (
        "页面测试的 `@/components/orders` 替身**少了导出**（issue #5651 实测：加两个导出后 "
        '26 条用例渲染期崩 —— `No "ProcessingDoc" export is defined on the "@/components/orders" mock`）：\n  '
        + "\n  ".join(offenders)
        + "\n修法：在该测试文件的 `vi.mock('@/components/orders', () => ({ … }))` 里补上位"
        "（可替身成空壳 div，纸面内容由对应组件自己的测试覆盖）"
    )


# ── C3：注入式红证 + 内容指纹自证 ─────────────────────────────────────────────

def test_c3_injected_missing_stub_is_red():
    """C3：从副本里删掉一条替身键 ⇒ C2 的判定函数必须判红；并用内容指纹自证注入生效。"""
    exports = _barrel_exports()
    target_rel, target_code, required = "", "", []
    for rel, code in sorted(_mock_files().items()):
        names = [n for n in _required_by_pages(code) if n in exports]
        if len(names) >= 2:
            target_rel, target_code, required = rel, code, names
            break
    assert target_rel != "", "找不到「需求集 ≥2」的 mock 文件 ⇒ 本红证会**空跑**"
    assert _missing_stubs(required, target_code) == [], f"`{target_rel}` 原文件本应干净（C2 已单独判）"

    victim = required[0]
    injected = re.sub(r"(?m)^\s+" + re.escape(victim) + r"\s*:.*\n", "", target_code, count=1)
    assert injected != target_code, f"`{target_rel}` 里找不到 `{victim}:` 替身注入点 ⇒ 本红证会**空跑**"
    assert _fingerprint(injected) != _fingerprint(target_code), "注入后内容指纹未变（**禁 mtime/size**）"
    assert _missing_stubs(required, injected) == [victim], (
        "删掉一条替身键后判据**没判红**（或红得不对）⇒ 守卫是空判据"
    )
