# case_ids: UI-012
"""无 `vi.spyOn` 的测试文件**不得**调用 `vi.restoreAllMocks()`（部署关键路径 flake 的真根因，issue #4496）。

## 病根（已实测，不是猜测）

`vi.restoreAllMocks()` 对 **`vi.fn()`**（不是 `vi.spyOn`）会**清掉其实现** ⇒ 该 mock 变回「返回 `undefined`」。

而它通常写在 `afterEach` 里，**RTL 的 `cleanup`（卸载组件）也在 `afterEach`** ⇒ **两者顺序不定**：
若 `restoreAllMocks()` 先跑而组件**尚未卸载**，其 `useEffect` 仍可能再触发一次 API 调用 ⇒
命中「无实现」的 mock ⇒ 页面拿到 `undefined` ⇒ `undefined.then` **同步抛** ⇒ 组件崩 ⇒
**该文件任意用例随机红**。

实证（`ship-order.test.tsx`，CI run 35415017266）：

```
TypeError: Cannot read properties of undefined (reading 'then')
❯ src/app/(dashboard)/orders/[id]/ship/ShipOrder.tsx:154
   154|      .getCustomers({ keyword: phone, page: 1, size: 5 })
```

⇒ 这正是「间歇性、且每次红的用例都不一样」的机制 —— 不是超时（#4463 已把 `asyncUtilTimeout` 提到 5s，
本坑仍在），而是**测试替身被提前清空**。

## 判据

若一个测试文件**调用了 `vi.restoreAllMocks()`**，则它**必须**至少有一处 `vi.spyOn`
（否则 restore 无对象可恢复，只会**误伤** `vi.fn()`）。

**红证**：在一个没有 `vi.spyOn` 的文件里加上 `vi.restoreAllMocks()` ⇒ 本判据红。
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
TESTS_ROOT = REPO / "frontend/admin-web/tests"


def _files_using_restore() -> list:
    out = []
    for p in Path(TESTS_ROOT).rglob("*.ts*"):
        if p.name.endswith(".d.ts"):
            continue
        text = p.read_text(encoding="utf-8")
        if "vi.restoreAllMocks()" in text:
            out.append((p, text))
    return out


def test_scan_is_non_trivial():
    """自证：确实扫到了测试文件（否则本文件空转 = 假绿）。"""
    assert len(list(Path(TESTS_ROOT).rglob("*.test.ts*"))) > 50, "前端测试文件解析结果过少 —— 扫描疑似失效"


def test_restore_all_mocks_only_where_spy_exists():
    """判据：调用 `vi.restoreAllMocks()` 的文件必须至少有一处 `vi.spyOn`。"""
    offenders = []
    for path, text in _files_using_restore():
        if "vi.spyOn" not in text:
            offenders.append(f"{path.relative_to(REPO)}（vi.fn={text.count('vi.fn()')}，vi.spyOn=0）")
    assert not offenders, (
        "这些测试文件调用了 `vi.restoreAllMocks()` 但**没有任何 `vi.spyOn`**：\n  "
        + "\n  ".join(offenders)
        + "\n⇒ `restoreAllMocks()` 对 `vi.fn()` 会**清掉其实现**；而 RTL 的 `cleanup` 也在 `afterEach`，"
          "两者顺序不定 ⇒ 未卸载的组件 effect 可能命中「无实现」的 mock ⇒ 页面拿到 undefined ⇒ "
          "同步抛 ⇒ **该文件任意用例随机红**（issue #4496 实证）。\n"
          "修法：删掉该文件里的 `vi.restoreAllMocks()`（无 `spyOn` ⇒ 它没有任何正面作用）。"
    )
