# case_ids: UI-114
# drift-audit: refs-are-fixtures
"""**demo path spec（`tests/e2e/**`）的占位符选择器活性**守卫（issue #7079 的类级固化）。

> 本文件里的 `路径:行号` 字面量**是红证夹具**：它们必须**逐字**等于 CI 真实失败报文里的那一段
> （`assert` 的那段报文里**含该文件的真实行号**），改成文本锚就**验不了**「守卫真的点到了那一处」。
> 按 `scripts/drift_audit.py` 的口径，`tests/**` 下声明 `# drift-audit: refs-are-fixtures`
> 即视为「按定义是失效引用」⇒ 不作引用新鲜度判定（同族先例：`test_agent_jwt_key_alignment.py`
> 等 3 个文件）。**注意**：本豁免只覆盖本文件；`.github/cases/ui.yml` 里的引用**不**适用
> （那里已改成文本锚 —— 用例库是**判定面**不是夹具面）。

## 病灶（2026-10-17 实测，不是推断）

issue #7079 把生产看板的搜索占位从「请输入**加工单**号或订单号」改成「请输入**作业单**号或订单号」，
源码与 **vitest** 断言都跟着改了，**但 `tests/e2e/specs/orders/processing-orders.spec.ts` 这个消费方漏了**。
CI 的 `Demo path specs (admin-web, fixture mode)` 腿当场红、并具名到文件:行：

    [web] › e2e/specs/orders/processing-orders.spec.ts:366:7 › 生产看板 /production（加工单唯一入口） › 关键词搜索…
    TimeoutError: locator.fill: Timeout 10000ms exceeded.
      - waiting for getByPlaceholder('请输入加工单号或订单号')
    2 failed / 59 passed

**结构原因**：仓里已有同族守卫 `test_ui_smoke_selector_liveness.py`（判据 A「文案活性」），
但它的射程**只有冒烟 spec**（`scripts/ui-smoke-merchant/spec.mjs`）—— `tests/e2e/**` 这条**载体的
选择器活性此前零守卫** ⇒ 改一处屏上文案时，「谁在断言它」这件事只能靠 CI 的浏览器腿在**推之后**发现。

## 本守卫的射程与判据（**窄而准**，故意不贪）

射程 = `tests/e2e/**/*.ts` 里 **`getByPlaceholder(...)` / `getByPlaceholderText(...)` 的字面量**
（现取 12 处 / 6 个不同字面量）。

**为什么只判占位符，不判 `getByText` / `getByRole(name)`**（现取读数：`getByText` 397 处、
`getByRole` 330 处、`getByLabel` 14 处、`getByPlaceholder` 12 处）：那三类的字面量大量是
**动态拼装 / 断言的是运行期数据**（单号、客户名、金额），静态活性判据会对它们大面积假红。
占位符是**纯静态 UI 文案**，且**恰好**是本次真实漏网的形态 ⇒ 先钉住这一档；
更宽的那一档由 `test_ui_smoke_selector_liveness.py` 的同名机制在**它自己的载体**上承担。
**不得**把本文件的绿读成「e2e 里所有文案选择器都活着」。

| # | 判据 | 会怎么红 |
|---|---|---|
| L1 | 射程内每个占位符字面量，必须在 `frontend/admin-web/src/**`（`.ts`/`.tsx`）里**逐字**出现 | 改了源码占位文案、e2e 没跟 ⇒ 具名报出「哪个字面量 / 哪个 spec 文件:行」（**这正是本次漏网的形态**） |
| L2 | **反空跑（fail-closed）**：射程为空（正则失配 / 目录空了 / 文件搬走）⇒ 红 | 把调用改成变量、或把 spec 目录改名 ⇒ 红，不许静默通过 |
| L3 | **判别力自证（反恒真）**：对注入的坏形态判红、对好形态不报 | 守卫退化成恒真 ⇒ 红 |

## 边界（照实登记，§19.1）

- 射程只到 **`tests/e2e/**`** 与 `frontend/admin-web/src/**` 两侧；**不含** `scripts/ui-smoke-merchant/spec.mjs`
  （那是 `test_ui_smoke_selector_liveness.py` 的射程，两处**不互为副本、也不互相重判**）。
- 判据是**字面量在不在源码里**，**不是**「Playwright 真能定位到它」：同一段文案可能落在
  多个页面上、或源码里的那个占位符实际渲染在别的路由。运行期真实定位由 CI 的
  `Demo path specs (admin-web, fixture mode)` 腿承担（本文件的绿**不能**替代它）。
- 只覆盖**占位符**这一档（见上「为什么只判占位符」）。`getByText` / `getByRole(name)` / `getByLabel`
  的同族字面量**不在本判据面**。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))

from unit_ci_workflows._source_parsing import java_code  # noqa: E402

E2E_DIR = REPO_ROOT / "tests" / "e2e"
ADMIN_WEB_SRC = REPO_ROOT / "frontend" / "admin-web" / "src"

#: 占位符选择器调用（`getByPlaceholder('X')` / `getByPlaceholderText("X")`）
PLACEHOLDER_CALL = re.compile(r"""getByPlaceholder(?:Text)?\(\s*(['"])(.*?)\1""")


def admin_web_sources() -> str:
    """`frontend/admin-web/src/**` 的 `.ts`/`.tsx` 正文拼接（**现取**，不写死文件清单）。"""
    files = sorted(
        [*ADMIN_WEB_SRC.rglob("*.ts"), *ADMIN_WEB_SRC.rglob("*.tsx")]
    )
    assert files, (
        f"{ADMIN_WEB_SRC.relative_to(REPO_ROOT).as_posix()} 下取不到任何 .ts/.tsx ⇒ "
        "被驱动面不存在 ⇒ 本判据失去对象（不许静默通过）"
    )
    return "\n".join(p.read_text(encoding="utf-8") for p in files)


def placeholder_sites() -> list[tuple[str, str, int]]:
    """射程内每处占位符字面量 ⇒ `[(仓库相对路径, 字面量, 行号)]`。

    🔴 **先剥注释再取值**（`java_code`，引号感知且**保持行数**）：注释里举例
    `// 用 getByPlaceholder('X') 取输入框` 不是真选择器 —— 按原文扫会被注释喂中
    （判据 = tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py）。
    """
    sites: list[tuple[str, str, int]] = []
    for path in sorted(E2E_DIR.rglob("*.ts")):
        text = java_code(path.read_text(encoding="utf-8"))
        for line_no, line in enumerate(text.splitlines(), start=1):
            for _quote, literal in PLACEHOLDER_CALL.findall(line):
                if literal:
                    sites.append((path.relative_to(REPO_ROOT).as_posix(), literal, line_no))
    return sites


def liveness_failures(sites: list[tuple[str, str, int]], sources: str) -> list[str]:
    """L1 ⇒ 逐处判「该字面量在前端源码里取不到」，返回具名失败清单（空 = 通过）。"""
    live = {literal for _p, literal, _n in sites if literal in sources}
    return [
        f"{path}:{line} 的 getByPlaceholder('{literal}') 在 frontend/admin-web/src/** 里取不到逐字文案"
        for path, literal, line in sites
        if literal not in live
    ]


# ══════════════════════════════════════════════════════════════════════════════
# L1 / L2 —— 对**真文件**的判定
# ══════════════════════════════════════════════════════════════════════════════


def test_every_e2e_placeholder_literal_is_alive_in_admin_web():
    """L1：e2e 里每个占位符字面量都必须在被驱动面里活着。"""
    sites = placeholder_sites()
    # L2 反空跑：射程为空 ⇒ 红（不许「没有可比对的东西」当通过）
    assert sites, (
        f"{E2E_DIR.relative_to(REPO_ROOT).as_posix()} 下取不到任何 "
        "`getByPlaceholder(...)` 字面量 ⇒ 射程为空（spec 被改名/搬走？调用换成了变量？）"
        "⇒ 本判据失去对象，不许静默通过"
    )
    failures = liveness_failures(sites, admin_web_sources())
    assert not failures, (
        "demo path spec 里的占位符选择器已在前端源码里取不到（改了屏上文案、e2e 没跟）：\n  "
        + "\n  ".join(failures)
    )


# ══════════════════════════════════════════════════════════════════════════════
# L3 —— 判别力自证（**反恒真**）
# ══════════════════════════════════════════════════════════════════════════════


def test_discriminating_power():
    """L3：好形态不报；坏形态**具名报出**（含本次真实漏网的形态）。"""
    good = [
        ("tests/e2e/specs/a.spec.ts", "请输入作业单号或订单号", 12),
        ("tests/e2e/specs/a.spec.ts", "请输入快递单号", 30),
    ]
    sources = "placeholder=\"请输入作业单号或订单号\" … placeholder=\"请输入快递单号\""
    assert liveness_failures(good, sources) == []

    bad = [("tests/e2e/specs/orders/processing-orders.spec.ts", "请输入加工单号或订单号", 368)]
    failures = liveness_failures(bad, sources)
    assert failures, "坏形态没有判红 ⇒ 守卫是恒真的"
    assert "processing-orders.spec.ts:368" in failures[0]
    assert "请输入加工单号或订单号" in failures[0]


def test_call_parser_reads_both_spellings():
    """L3-b：两种拼写（`getByPlaceholder` / `getByPlaceholderText`、单双引号）都认。"""
    text = (
        "await page.getByPlaceholder('甲').fill('x')\n"
        'await page.getByPlaceholderText("乙").fill("y")\n'
        "const p = getByPlaceholder(name)\n"
    )
    found = {lit for _q, lit in PLACEHOLDER_CALL.findall(text)}
    assert found == {"甲", "乙"}, f"解析到的字面量 = {found}"
