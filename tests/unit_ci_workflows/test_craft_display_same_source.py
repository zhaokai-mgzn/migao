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
| C2 | 自动识别实现**不在** `craft-display.ts` 里 | 把 `detectAutoFeatures` 挪回去 ⇒ 必红 |
| C3 | 三份文件都存在（路径漂移 ⇒ 红，而不是静默跳过） | 删/移动任一份 ⇒ 必红 |

**为什么 C2 也要有**：C1 只保证「三份一样」——把自动识别**同时**抄进三份也能满足 C1，
而那正是 #4393 要禁止的形态（下单页的**取价**逻辑不属于三端**展示**映射）。
"""
from __future__ import annotations

import hashlib
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
#: 不得出现在同源展示文件里的符号
FORBIDDEN_IN_DISPLAY: tuple[str, ...] = (
    "detectAutoFeatures",
    "resolveDoorWidth",
    "HEM_MARGIN",
    "DEFAULT_DOOR_WIDTH",
    "AutoFeatureName",
)


def _read(rel: str) -> bytes:
    """读一份副本；**不存在 ⇒ 直接失败**（路径漂移不得退化成静默跳过）。"""
    path = REPO_ROOT / rel
    if not path.is_file():
        pytest.fail(f"副本不存在：{rel}（三端同源守卫必须能读到它，路径漂移 = 红）")
    return path.read_bytes()


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
    """C2：自动识别（下单页取价逻辑）**不在**同源展示文件里（挪回去 ⇒ 红）。"""
    display = _read(COPIES[0]).decode("utf-8")
    leaked = [sym for sym in FORBIDDEN_IN_DISPLAY if sym in display]
    assert leaked == [], (
        f"`craft-display.ts` 里出现了自动识别符号 {leaked} —— 它是**下单页取价逻辑**，"
        "不是三端**展示**映射；放进同源文件会让另两端被迫背上下单页语义"
        "（且「三份一起抄」也能骗过 C1）⇒ 应住在 "
        f"`{AUTO_FEATURES_MODULE}`（issue #4531）"
    )


def test_c3_auto_features_module_exists_and_exports_the_api():
    """C3：自动识别模块存在且导出契约（被页面与测试消费的那几个符号）。"""
    src = _read(AUTO_FEATURES_MODULE).decode("utf-8")
    missing = [sym for sym in FORBIDDEN_IN_DISPLAY if f"export const {sym}" not in src
               and f"export function {sym}" not in src
               and f"export type {sym}" not in src]
    assert missing == [], (
        f"`{AUTO_FEATURES_MODULE}` 缺少导出：{missing} —— 页面/测试按这些名字消费，"
        "改名或漏导出 ⇒ 消费方 import 即红（但守卫要在**这里**先说清楚）"
    )
