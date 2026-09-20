# case_ids: UI-012
"""`vi.restoreAllMocks()` 的适用边界 —— 部署关键路径 flake 的真根因（issue #4773 / #4496）。

## 病根（三层，全部实测）

① `vi.restoreAllMocks()` 对**每一个**注册过的 mock 调 `mockRestore()`
   = `mockReset()` + `state.restore()`，而 `mockReset()` 会 `implementation = undefined`
   ⇒ **`vi.fn()` 替身被清空成「返回 undefined」**（不只是 `vi.spyOn`）。
   实测（vitest 3.2.x）：`const m = vi.fn().mockResolvedValue(1); vi.restoreAllMocks(); m()` ⇒ `undefined`。
   对照：`vi.clearAllMocks()` **不会**清实现（它只清调用记录）。
② 它通常写在 `afterEach` 里，而 **RTL 的 `cleanup()`（卸载组件）也在 `afterEach`**，且**本文件先跑**：
   实测那一刻 `document.body.children.length == 1`（组件**尚未卸载**）
   ⇒ 存在「替身已清空、组件仍挂载」的窗口。
③ 窗口里只要组件的 `useEffect` 再跑一次 API 调用，页面就拿到 `undefined` ⇒ `undefined.then` **同步抛**
   ⇒ 组件崩 ⇒ **该文件任意用例随机红**（每次红的用例都不同）。

实证（`ship-order.test.tsx`，CI run 35492364994 —— `deploy-frontend.yml` 的「Unit tests」步 ⇒ **卡住了一次前端部署**）：

```
TypeError: Cannot read properties of undefined (reading 'then')
❯ src/app/(dashboard)/orders/[id]/ship/ShipOrder.tsx:154:57
   154|      .getCustomers({ keyword: phone, page: 1, size: 5 })
```

## 为什么原判据失明（本判据的沿革，不是新增门禁）

本文件原名 `test_no_restore_all_mocks_without_spy.py`，判据只有 R1。而 #4768（issue #4759 的 D 项）
为修 `window.print` 泄漏**正当**地引入了 `vi.spyOn(window, 'print')` —— 这一处正当的 `vi.spyOn`
让 R1 **当场失明**（实测：未修的树上 R1 `2 passed`）；同一次改动又把 #4497 已删掉的
`afterEach(vi.restoreAllMocks)` 加了回来 ⇒ 同一条 flake 原样复发（#4497 的修复被自己加的守卫放过）。
⇒ 判据必须盯住**真正的受力面**：`vi.fn()` 替身会不会被清空。

## 判据

| # | 判据 | 形态 |
|---|---|---|
| R1 | 调了 `vi.restoreAllMocks()` 的文件**必须**至少有一处 `vi.spyOn` | 否则 restore 无对象可恢复，纯误伤（#4497 原判据，保留） |
| R2 | 调了 `vi.restoreAllMocks()` 的文件**不得**有**模块级 `vi.fn()` 替身** | 否则那些替身的实现会在「afterEach 之后、cleanup 之前」的窗口里变 `undefined`（#4773 新增） |

要还原 `vi.spyOn`：在**创建它的那个用例里** `spy.mockRestore()`（`try/finally`），
**不要**文件级 `restoreAllMocks()` 清场。

## 只认「调用」，不认「提及」

判据一律在**去注释后的代码**上判定（`_code()`）：注释里把被禁写法原样贴出来当**反例文档**
**不算**调用 —— 否则「解释这个坑」会**自己触发门禁**，下一个人只能靠改措辞规避
（#4239 的教训：「靠改措辞规避门禁」是失效的 workaround，不能教）。
本文件实测踩到过：修完本坑后，两个测试文件里留下的反例说明注释让 R2 继续判红。
反向也有判据（`test_r2_bites_on_injected_sample`）：**真调用必须判红**，且**注释里的提及必须判绿**。

**红证**：给一个有模块级 `vi.fn()` 替身的文件加回 `vi.restoreAllMocks()` ⇒ R2 红。
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
TESTS_ROOT = REPO / "frontend/admin-web/tests"

# 模块级替身 = **零缩进**（顶层）声明的变量，初始化式里直接出现 `vi.fn(`
# 反例（不算）：用例体内的 `vi.fn()`（缩进 ⇒ 不匹配）、`vi.spyOn(...)`（不是替身）。
MODULE_SCOPE_FN_DOUBLE_RE = re.compile(
    r"^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)[^\n=]*=\s*vi\.fn\s*\(",
    re.MULTILINE,
)

_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")


def _code(text: str) -> str:
    """去掉块注释与行注释后的文本 —— 判据只认**调用**，不认注释里的**提及**。"""
    return _LINE_COMMENT_RE.sub("", _BLOCK_COMMENT_RE.sub("", text))


def module_scope_fn_doubles(text: str) -> list:
    """文本里**模块级** `vi.fn()` 替身的变量名（有序、去重；注释里的提及不算）。"""
    seen, out = set(), []
    for name in MODULE_SCOPE_FN_DOUBLE_RE.findall(_code(text)):
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def violates_r1(text: str) -> bool:
    """R1：调了 restoreAllMocks 却没有一处 vi.spyOn。"""
    code = _code(text)
    return "vi.restoreAllMocks()" in code and "vi.spyOn" not in code


def violates_r2(text: str) -> bool:
    """R2：调了 restoreAllMocks 且存在模块级 `vi.fn()` 替身。"""
    return "vi.restoreAllMocks()" in _code(text) and bool(module_scope_fn_doubles(text))


def _test_files() -> list:
    return sorted(p for p in Path(TESTS_ROOT).rglob("*.test.ts*") if not p.name.endswith(".d.ts"))


def _files_using_restore() -> list:
    out = []
    for p in _test_files():
        text = p.read_text(encoding="utf-8")
        if "vi.restoreAllMocks()" in _code(text):
            out.append((p, text))
    return out


def r1_offenders() -> list:
    return [
        f"{p.relative_to(REPO)}（vi.fn() 出现 {_code(text).count('vi.fn()')} 次，vi.spyOn=0）"
        for p, text in _files_using_restore()
        if violates_r1(text)
    ]


def r2_offenders() -> list:
    return [
        f"{p.relative_to(REPO)}（模块级替身：{', '.join(module_scope_fn_doubles(text))}）"
        for p, text in _files_using_restore()
        if violates_r2(text)
    ]


def test_scan_is_non_trivial():
    """自证：扫描面两侧都非空（否则 R1/R2 是空转的假绿）。"""
    files = _test_files()
    assert len(files) > 50, f"前端测试文件只扫到 {len(files)} 个 —— 扫描疑似失效"
    with_doubles = [p for p in files if module_scope_fn_doubles(p.read_text(encoding="utf-8"))]
    with_restore = [p for p, _ in _files_using_restore()]
    assert with_doubles, "一个带模块级 vi.fn() 替身的文件都没扫到 —— R2 的受力面为空，判据形同虚设"
    assert with_restore, "一个调 vi.restoreAllMocks() 的文件都没扫到 —— R1/R2 的分母为空"


def test_r1_restore_all_mocks_only_where_spy_exists():
    """R1（保留 #4497 原判据）：调用 `vi.restoreAllMocks()` 的文件必须至少有一处 `vi.spyOn`。"""
    offenders = r1_offenders()
    assert not offenders, (
        "这些测试文件调用了 `vi.restoreAllMocks()` 但**没有任何 `vi.spyOn`**：\n  "
        + "\n  ".join(offenders)
        + "\n⇒ restore 无对象可恢复，只会**误伤 `vi.fn()` 替身**（其实现被清空成 undefined）。"
          "\n修法：删掉该文件里的 `vi.restoreAllMocks()`。"
    )


def test_r2_no_module_scope_fn_doubles_with_restore_all_mocks():
    """R2（issue #4773 新增）：调用 `vi.restoreAllMocks()` 的文件不得有**模块级 `vi.fn()` 替身**。"""
    offenders = r2_offenders()
    assert not offenders, (
        "这些测试文件同时有**模块级 `vi.fn()` 替身**与 `vi.restoreAllMocks()`：\n  "
        + "\n  ".join(offenders)
        + "\n⇒ `restoreAllMocks()` 会把 `vi.fn()` 替身的实现清成 `undefined`（`mockRestore` → `mockReset`），"
          "\n   而该 afterEach **跑在 RTL `cleanup()` 之前**（实测那一刻组件仍挂载）"
          "\n   ⇒ 组件的 effect 在这个窗口里再跑一次就会 `undefined.then` 同步抛 ⇒ **该文件任意用例随机红**"
          "\n   ⇒ 卡住 `deploy-frontend.yml` 的「Unit tests」步（issue #4773 实证）。"
          "\n修法：删掉文件级 `vi.restoreAllMocks()`；要还原 `vi.spyOn` 就在**创建它的用例里** "
          "`try { … } finally { spy.mockRestore() }`。"
    )


def test_r2_bites_on_injected_sample():
    """判别力自证：合成样本上，判据必须**红在真调用、绿在注释里的提及**。"""
    double = "const mockGetCustomers = vi.fn()\n"
    call = "  afterEach(() => { vi.restoreAllMocks() })\n"
    mention = "  // 反例（被禁的写法）：afterEach(() => { vi.restoreAllMocks() })\n"
    body = "  it('y', () => { const inline = vi.fn(); expect(inline).toBeDefined() })\n"

    # ① 真调用 + 模块级替身 ⇒ 必红（用例体内的 vi.fn 不得干扰识别）
    assert violates_r2(double + "describe('x', () => {\n" + call + body + "})\n") is True
    assert module_scope_fn_doubles(double + call + body) == ["mockGetCustomers"]

    # ② 去掉替身（换成 spyOn）⇒ R2 受力面消失（证明红是由**模块级替身**引起的）
    no_double = "const spy = vi.spyOn(window, 'print')\n" + "describe('x', () => {\n" + call + body + "})\n"
    assert violates_r2(no_double) is False

    # ③ 去掉真调用 ⇒ 变绿（证明红是由 restoreAllMocks 引起的）
    assert violates_r2(double + "describe('x', () => {\n" + body + "})\n") is False

    # ④ **只把被禁写法写进注释**（本单修完后的真实形态）⇒ 必须判绿，否则「解释这个坑」自己触发门禁
    assert violates_r2(double + "describe('x', () => {\n" + mention + body + "})\n") is False
    assert violates_r1(double + "describe('x', () => {\n" + mention + body + "})\n") is False
    # 而注释里的替身声明同样不算替身
    assert module_scope_fn_doubles("// const mockX = vi.fn()\n") == []
