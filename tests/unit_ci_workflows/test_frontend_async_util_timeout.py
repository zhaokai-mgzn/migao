# case_ids: UI-012
"""前端测试必须配置 `asyncUtilTimeout`（部署/门禁关键路径 flake 的护栏）。

## 病根（同类已第三次卡住关键路径）

`@testing-library/dom` 的 `waitFor` / `findBy*` 默认 `asyncUtilTimeout = 1000ms`。
机器更慢更挤时（CI 并行腿 / 本地全量档 81 个 suite 并行 / 门禁里其它腿同时在跑），
页面「取数 → 渲染」超过 1s ⇒ `waitFor` 超时 ⇒ **间歇性红**，且与「真构建失败」**不可区分**。

- **第一次**（issue #4414）：`deploy-frontend` 的 `npx vitest run` 步失败（`ship-order.test.tsx`
  两条、`production-board.test.tsx` 一条），同一文件在未改动检出上全绿 ⇒ 在
  `frontend/admin-web/tests/setup.ts` 落了 `configure({ asyncUtilTimeout: 5000 })`。
- **第二次**（issue #6645，2026-10-10）：`./verify-all.sh gate` 的
  `bmini-app 类型检查 + 单测 + 构建（h5 + weapp）` 腿偶红 —— `tests/worker-reprint-page.test.tsx`
  的 `reprint-step-detail` 等不到；**同文件不带负载连跑 5 次全绿、同一提交的 CI 腿也绿**；
  用 CPU 压满复算 ⇒ 单文件连跑 10 次**红 2 次**。那条链上 decode / lookup 全是**立即 resolve
  的 jest mock**（无计时器 / 无网络）⇒ 卡的是 **jest worker 被调度出去**的那段时间。
  ⇒ 本判据的覆盖面由 `admin-web` **扩到三个前端**（`admin-web` / `bmini-app` / `mini-app`）：
  后两者此前**零配置**，是同一个洞（Taro H5 + jest + RTL，同一份形态）。

## 判据（三个前端各自的 `tests/setup.ts` 都要满足）

1. 文件存在；
2. `configure({ asyncUtilTimeout: <≥ 3000> })` 且**真的 import 了** `configure`
   （光写不 import = 运行期 `ReferenceError`）。
   🔴 来源**必须**是 `@testing-library/dom`：本文件是 `setupFiles`（jest 框架安装**之前**跑），
   在那里 import `@testing-library/react` 会让它注册 auto-cleanup 时 `afterEach` 尚不存在
   ⇒ **静默失去自动清理** ⇒ DOM 跨用例累积 ⇒ 成片「Found multiple elements」红（#6645 实测踩过）。
3. `jest.config.js` 必须真的把该 setup 挂进 `setupFiles`（否则上面两条是只看文本的空断言）。
- **下界 3000ms**：默认 1000ms 是已实证不够的值；提高它只是让「真慢」时有更多余量
  （`waitFor` 是**轮询**，正常情况仍在毫秒级返回，**不是**固定 sleep ⇒ 不违反 §15.1「等元素而非定长 sleep」）。
- **上限**：不设（越长越稳，代价只是失败时多等）。
- **断言一条都没放宽**：真有永不落地的状态（产品竞态），到点照样红。

**红证**：删掉任一个 `configure` 调用（或把值改回 < 3000、或删掉 import）⇒ 本判据红（三个文件逐条独立）。
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
SETUPS = [
    "frontend/admin-web/tests/setup.ts",
    "frontend/bmini-app/tests/setup.ts",
    "frontend/mini-app/tests/setup.ts",
]
MIN_MS = 3000


@pytest.mark.parametrize("rel", SETUPS)
def test_setup_file_exists(rel):
    assert (REPO / rel).exists(), f"规格锚点变了：找不到 {rel}"


@pytest.mark.parametrize("rel", SETUPS)
def test_setup_configures_async_util_timeout(rel):
    """判据：每个前端的 `tests/setup.ts` 都要把 `asyncUtilTimeout` 配到 ≥ 3000ms。"""
    text = (REPO / rel).read_text(encoding="utf-8")
    # 先断言「配置存在」：直接断言 match 对象（不用 `is not None` —— 那会被弱断言检查判红）
    match = re.search(r"asyncUtilTimeout\s*:\s*(\d+)", text)
    assert match, (
        f"{rel} 没有配置 `asyncUtilTimeout` ⇒ `waitFor`/`findBy*` 回落默认 1000ms ⇒ "
        "负载下超时 ⇒ 单测间歇性红 ⇒ **挡住部署腿 / 本地全量档**（issue #4414 与 #6645 各实证一次）。\n"
        "修法：`import { configure } from '@testing-library/dom'; configure({ asyncUtilTimeout: 5000 })`"
    )
    value = int(match.group(1))
    assert value >= MIN_MS, (
        f"{rel} 的 `asyncUtilTimeout` = {value}ms < {MIN_MS}ms ⇒ 默认 1000ms 已实证不够，"
        "回到小值等于把 flake 放回来（issue #4414 / #6645）"
    )


@pytest.mark.parametrize("rel", SETUPS)
def test_configure_is_actually_imported(rel):
    """自证：光写 `configure(...)` 而不 import 会在运行期 `ReferenceError` ⇒ 必须同时 import。"""
    text = (REPO / rel).read_text(encoding="utf-8")
    assert re.search(
        r"import\s*\{[^}]*\bconfigure\b[^}]*\}\s*from\s*['\"]@testing-library/dom['\"]", text
    ), (
        f"{rel} 用了 `configure` 但没有从 '@testing-library/dom' 导入它 ⇒ 运行期 ReferenceError。"
        "若改从 '@testing-library/react' 导入：`setupFiles` 阶段它注册 auto-cleanup 会因缺 `afterEach` "
        "而静默失效 ⇒ DOM 跨用例累积（#6645 实测踩过）。"
    )


@pytest.mark.parametrize("rel", SETUPS)
def test_test_runner_config_actually_loads_the_setup(rel):
    """接线判据：测试运行器配置必须把该 setup 挂进 `setupFiles` —— 否则 `configure` 永不执行。

    运行器按 app 分：admin-web = vitest（`vitest.config.ts`）；两个 Taro app = jest（`jest.config.js`）。
    红证：把 `setupFiles` 里那一项删掉 ⇒ 本判据红（而上面两条仍绿 ⇒ 单看那两条是空断言）。
    """
    app = (REPO / rel).parent.parent
    candidates = sorted(app.glob("vitest.config.*")) + sorted(app.glob("jest.config.*"))
    assert candidates, f"{app.name} 找不到测试运行器配置（vitest.config.* / jest.config.*）"
    wired = [p for p in candidates if re.search(r"setupFiles\s*:\s*\[[^\]]*tests/setup\.ts", p.read_text(encoding="utf-8"))]
    assert wired, (
        f"{app.name} 的测试运行器配置（{[p.name for p in candidates]}）没有把 `tests/setup.ts` "
        "挂进 `setupFiles` ⇒ `configure({ asyncUtilTimeout })` 永不生效"
        "（判据 2 会退化成只看文本的空断言）"
    )
