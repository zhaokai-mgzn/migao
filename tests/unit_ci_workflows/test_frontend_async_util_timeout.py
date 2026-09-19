# case_ids: UI-012
"""前端测试必须配置 `asyncUtilTimeout`（部署关键路径 flake 的护栏，issue #4414）。

## 病根（已第二次卡住 `deploy-frontend`）

`deploy-frontend` 的步骤顺序是 `tsc --noEmit` → **`npx vitest run`** → `docker build` → `deploy.sh` → 部署后探测
⇒ **任何单测 flake 都会挡住整条部署腿**，且与「真构建失败」**不可区分**（排查成本高）。

`@testing-library/dom` 的 `waitFor` / `findBy*` 默认 `asyncUtilTimeout = 1000ms`。
CI 机器更慢更挤时，页面「取数 → 渲染」超过 1s ⇒ `waitFor` 超时 ⇒ **间歇性红**。
实证：`deploy-frontend` 在 `40a6324` 的 `Unit tests` 步失败（`ship-order.test.tsx` 两条、
`production-board.test.tsx` 一条），而**同一文件在本地/未改动检出上全绿** ⇒ 是时序而非逻辑。

## 判据

`frontend/admin-web/tests/setup.ts` 必须 `configure({ asyncUtilTimeout: <≥ 3000> })`。
- **下界 3000ms**：默认 1000ms 是已实证不够的值；提高它只是让「真慢」时有更多余量
  （`waitFor` 是**轮询**，正常情况仍在毫秒级返回，**不是**固定 sleep ⇒ 不违反 §15.1「等元素而非定长 sleep」）。
- **上限**：不设（越长越稳，代价只是失败时多等）。

**红证**：删掉该 `configure` 调用（或把值改回 < 3000）⇒ 本判据红。
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
SETUP = REPO / "frontend/admin-web/tests/setup.ts"
MIN_MS = 3000


def test_setup_file_exists():
    assert SETUP.exists(), f"规格锚点变了：找不到 {SETUP}"


def test_setup_configures_async_util_timeout():
    """判据：`setup.ts` 必须把 `asyncUtilTimeout` 配到 ≥ 3000ms。"""
    text = SETUP.read_text(encoding="utf-8")
    # 先断言「配置存在」：直接断言 match 对象（不用 `is not None` —— 那会被弱断言检查判红）
    match = re.search(r"asyncUtilTimeout\s*:\s*(\d+)", text)
    assert match, (
        "frontend/admin-web/tests/setup.ts 没有配置 `asyncUtilTimeout` ⇒ "
        "`waitFor`/`findBy*` 回落默认 1000ms ⇒ CI 负载下超时 ⇒ 单测间歇性红 ⇒ "
        "**挡住整条 deploy-frontend 部署腿**（issue #4414 已实证两次）。\n"
        "修法：`import { configure } from '@testing-library/dom'; configure({ asyncUtilTimeout: 5000 })`"
    )
    value = int(match.group(1))
    assert value >= MIN_MS, (
        f"`asyncUtilTimeout` = {value}ms < {MIN_MS}ms ⇒ 默认 1000ms 已实证不够，"
        f"回到小值等于把 flake 放回来（issue #4414）"
    )


def test_configure_is_actually_imported():
    """自证：光写 `configure(...)` 而不 import 会在运行期 `ReferenceError` ⇒ 必须同时 import。"""
    text = SETUP.read_text(encoding="utf-8")
    assert re.search(r"import\s*\{[^}]*\bconfigure\b[^}]*\}\s*from\s*['\"]@testing-library/dom['\"]", text), (
        "setup.ts 用了 `configure` 但没有从 '@testing-library/dom' 导入它 ⇒ 运行期 ReferenceError"
    )
