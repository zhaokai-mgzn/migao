# case_ids: OR-040
"""`craft-display.ts` **三端逐字同源**守卫（issue #4531 收口 #4393）。

## 病根（实测，2026-09-19）

`craft-display.ts` 在 admin-web / mini-app / bmini-app **三端逐字同源**（设计文档 §4.9
「一份 spec，三处渲染」——三端是独立 npm 工程、无共享包，故用**副本**），但**没有守卫**：

- 实测合并前三分 sha 全等 `76956fd1be94a321aca9cc4b20453eb7565e4fd8`、各 183 行；
- PR #4530 只改了 admin-web 那一份（+116 行自动识别）⇒ 合并后 admin 侧 **299 行**、
  另两端仍 183 行 ⇒ **不变量被静默破坏**（既有 issue **#4393** 记的正是这个缺口）。

## 判据形态：**逐字节相等** + **反向断言**（自动识别不在同源文件里）

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| C1 | 三份 `craft-display.ts` 逐字节相等 | 只改其中一份 ⇒ 必红 |
| C2 | 取价口径模块**不在** `craft-display.ts` 里 | 把 `AUTO_FEATURE_NAMES` / `parseDoorWidth` 挪回去 ⇒ 必红（⚠️ issue #5035：`detectAutoFeatures` 已退场，**不能再当锚点** —— 拿一个不存在的符号当红证 = 空断言） |
| C3 | 三份文件都存在（路径漂移 ⇒ 红，而不是静默跳过） | 删/移动任一份 ⇒ 必红 |

**为什么 C2 也要有**：C1 只保证「三份一样」——把自动识别**同时**抄进三份也能满足 C1，
而那正是 #4393 要禁止的形态（下单页的**取价**逻辑不属于三端**展示**映射）。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 三端副本路径（唯一真相源；`craft-display.ts` 的同步纪律见其文件头注释）
COPIES: tuple[str, ...] = (
    "frontend/admin-web/src/lib/craft-display.ts",
    "frontend/mini-app/src/utils/craft-display.ts",
    "frontend/bmini-app/src/utils/craft-display.ts",
)

#: 自动识别（下单页取价逻辑）必须住在 admin-web 专属文件里
AUTO_FEATURES_MODULE = "frontend/admin-web/src/lib/craft-auto-features.ts"

#: 专属模块**必须**导出的核心符号（**非空锚点**：防止模块被清空后 C2 空跑通过）
#: ⚠️ 2026-09-21（issue #4877 门幅落地）**同步改名**：门幅**缺省口径已删除** ——
#: `resolveDoorWidth` / `DEFAULT_DOOR_WIDTH` 退场，唯一解析入口改为 `parseDoorWidth`
#: （解析不到 ⇒ `None` ⇒ 判定面**不判**、规则面 `undecidable`；反向守卫在
#: `tests/unit_ci_workflows/test_fabric_width_truth_source.py` 判据 3 与
#: `frontend/admin-web/tests/unit/lib/craft-auto-features.test.ts`）。
#: 🔴 2026-09-21（issue #5043 包 2b，**第二次有意缩水**）：`SIDE_MARGIN` / `HEM_MARGIN` 的**前端副本**
#: 已全部退场（`SIDE_MARGIN` 随 issue #5030、`HEM_MARGIN` 随 issue #5043 包 2b 规则面迁服务端）
#: ⇒ 锚点**必须**去掉它们，否则本守卫会要求一个**不存在**的符号（假红）。
#: **缩水不是放宽**：C2 的动态名单仍由剩余符号堵住，且「副本不得回来」另有独立的反向守卫
#: （`tests/unit_ci_workflows/test_hem_margin_cross_language_drift.py`）。
#: 🔴 2026-09-21（issue #5035）**有意缩水**（正面回答上面那条「锚点只换名、**不缩水**」纪律）：
#: `detectAutoFeatures` / `detectAutoFeatureNotices` **真的退场了** —— 判定（#5019 切源）/
#: 提示（#5036）/ 算例（#5043 包 2a）全部搬到**服务端**，前端本地实现已删除
#: ⇒ 锚点**必须**去掉它们，否则本守卫会要求一个**不存在**的符号（那是假红）。
#: ⚠️ **缩水不是放宽**：堵「模块被清空 ⇒ C2 恒真」的锚点**数量不减**（用 `AUTO_FEATURE_NAMES`
#: 补上退场符号的位置），且新增**死亡条件**守卫
#: （`tests/unit_ci_workflows/test_fabric_width_truth_source.py` 判据 4：那两个函数不得回来）。
#: ⚠️ 2026-09-21（issue #5030 宽高口径改判）**再删一个锚点**：`SIDE_MARGIN` 整体退场
#: （订单宽 = 净窗宽 ⇒ 宽方向没有余量）⇒ 锚点从它身上撤下；**锚点只换名、不缩水**：
#: 仍覆盖「识别推导 + 门幅解析 + 高方向余量常量 + 加工类型常量」。
#: 反向守卫（源码里再出现该标识符 ⇒ 红）= `test_panels_formula_split_audit.py` 判据 C5 与
#: `test_hem_margin_cross_language_drift.py` 判据 C2'。
CORE_EXPORTS: tuple[str, ...] = (
    "AUTO_FEATURE_NAMES",
    "parseDoorWidth",
    "CUTTING_MODE_FIXED_HEIGHT",
    "CUTTING_MODE_FIXED_WIDTH",
)

#: 从专属模块源码里**动态**取导出符号名 —— **刻意不硬编码名单**（issue #4531 加固）：
#: 硬编码的名单会**腐烂**（符号改名/新增 ⇒ 守卫静默失效，而没有任何东西会变红）。
#: 动态取名的代价是「模块被清空 ⇒ 名单为空 ⇒ C2 恒真」，由上面的 `CORE_EXPORTS` 锚点堵住。
_EXPORT_RE = re.compile(r"^export\s+(?:const|function|type|interface|class)\s+(\w+)", re.M)


def _read(rel: str) -> bytes:
    """读一份副本；**不存在 ⇒ 直接失败**（路径漂移不得退化成静默跳过）。"""
    path = REPO_ROOT / rel
    if not path.is_file():
        pytest.fail(f"副本不存在：{rel}（三端同源守卫必须能读到它，路径漂移 = 红）")
    return path.read_bytes()


def _exported_symbols(src: str) -> list[str]:
    """专属模块导出的符号名（动态；保序去重）。"""
    return list(dict.fromkeys(_EXPORT_RE.findall(src)))


def _sha(rel: str) -> str:
    return hashlib.sha256(_read(rel)).hexdigest()


def test_c1_three_copies_are_byte_identical():
    """C1：三份 `craft-display.ts` **逐字节相等**（只改一份 ⇒ 红）。"""
    shas = {rel: _sha(rel) for rel in COPIES}
    assert len(set(shas.values())) == 1, (
        "三端 `craft-display.ts` 不再逐字节相等（设计 §4.9「一份定义，三处渲染」）——"
        "三端是独立 npm 工程、无共享包，改一处必须同步另两处（issue #4393）：\n"
        + "\n".join(f"  {sha[:12]}  {rel}" for rel, sha in shas.items())
    )


def test_c2_auto_features_not_in_the_shared_display_file():
    """C2：专属模块的**全部**导出符号都不得出现在同源展示文件里（挪回去 ⇒ 红）。

    ⚠️ 名单**动态取自专属模块**（不是硬编码）：硬编码名单会腐烂（符号改名/新增 ⇒
    守卫静默失效）；空名单的退化风险由 `CORE_EXPORTS` 锚点在 C3 里堵住。
    """
    display = _read(COPIES[0]).decode("utf-8")
    symbols = _exported_symbols(_read(AUTO_FEATURES_MODULE).decode("utf-8"))
    assert symbols, (
        f"`{AUTO_FEATURES_MODULE}` 里解析不出任何导出符号 ⇒ C2 会**空跑通过**"
        "（判据必须能判红）—— 模块被清空/改写形态时请同步修本守卫"
    )
    leaked = [sym for sym in symbols if sym in display]
    assert leaked == [], (
        f"`craft-display.ts` 里出现了自动识别符号 {leaked} —— 它是**下单页取价逻辑**，"
        "不是三端**展示**映射；放进同源文件会让另两端被迫背上下单页语义"
        "（且「三份一起抄」也能骗过 C1）⇒ 应住在 "
        f"`{AUTO_FEATURES_MODULE}`（issue #4531）"
    )


def test_c3_auto_features_module_exists_and_exports_the_core_api():
    """C3：专属模块存在、且导出**核心 API**（被页面与测试消费的那几个符号）。

    `CORE_EXPORTS` 是 C2 动态名单的**非空锚点**：模块被清空 / 核心符号改名 ⇒ 这里先红，
    而不是让 C2 静默变成恒真判据。
    """
    src = _read(AUTO_FEATURES_MODULE).decode("utf-8")
    exported = set(_exported_symbols(src))
    missing = [sym for sym in CORE_EXPORTS if sym not in exported]
    assert missing == [], (
        f"`{AUTO_FEATURES_MODULE}` 缺少核心导出：{missing} —— 页面/测试按这些名字消费，"
        "改名或漏导出 ⇒ 消费方 import 即红（守卫要在这里先说清楚）；"
        "同时该锚点保证 C2 的动态名单不会退化成空名单"
    )
