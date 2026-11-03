# case_ids: CH-051, HR-009
"""能力边界投影的**进程级状态隔离**判据（issue #8125）。

## 病（origin/main 已复现）

`test_graph_skills.py` 驱动 `execute_skill` 的用例普遍
`@patch("app.graph.skills.base_skill.create_skill_registry")`；它们在
`prepare_turn` → `_build_system_prompt` → `_capability_boundary` 里**反调**了能力边界投影，
而投影内部的可达性探测原先从 `base_skill` 取 `create_skill_registry` —— 于是**替身被当成真实现**：
`MagicMock.get_tool_names()` 迭代为空 ⇒ 探测得到 `frozenset()`，又被公开探测的进程级
`lru_cache` 冻住 ⇒ **同一进程后续任何一次 `resolve_units()` / prompt 渲染都读到「零可达」**，
表现为「B 端能力真值全变了」（改名✅ / 定时提醒✅ 等全部塌成 ❌）。

修复前读数（2026-11-02 现取，本工作区）：
`pytest tests/test_graph_skills.py tests/test_capability_boundary.py` ⇒ **10 failed / 279 passed**；
反序（boundary 先）⇒ 289 passed。修复后两序均 **289 passed**。

## 本文件的判据（每条都带注入自证）

1. `test_seam_injection_is_effective`（对照）：替身确实让 `base_skill.create_skill_registry`
   变成读面为空的 mock —— 证明下面两条的注入**真的生效**，不是空跑。
2. `test_public_probe_result_ignores_execute_seam`：替身生效期间调公开探测 ⇒ 必须等于
   **未被打桩**的未缓存复算值（修复前是空集 ⇒ 红）。
3. `test_boundary_view_does_not_collapse_after_prior_turn`：先让替身跑一次投影（= 前序用例的形态，
   且此时缓存被清空 = 它是第一个探测者），再在**替身已撤销**后取 `resolve_units()` ⇒ 必须与基线
   逐键相等，且「改名 ✅ / 员工创建 ❌」仍成立（修复前缓存已冻结空集 ⇒ 全 False ⇒ 红）。

## 为什么修在生产代码，而不是在测试里 reload / 逐用例 cache_clear

`importlib.reload` 与「每条用例再 `cache_clear()` 一次」都只是**掩盖**：任何一次「替身期间的首个探测」
都会污染全进程，而这条反调链在**生产**里同样存在（`prepare_turn` 真的会渲染投影，只是没有替身）。
修法 = 只读探测从**实现模块** `app.graph.skills.tool_selection` 取工厂（测试从不打桩它），见
`app/agents/capability_boundary.py::_compute_mibao_reachable_tool_names` 的同处注释。

## 边界（照实登记）

本文件只覆盖「执行接缝替身」这一条污染路径；其它进程级状态（工具注册表被替换、skill 单例被重置）
不在射程内。类级结构判据 = `tests/unit_ci_workflows/test_capability_projection_seam_guard.py`。
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.agents.capability_boundary import (
    _compute_mibao_reachable_tool_names,
    mibao_reachable_tool_names,
    resolve_units,
)


@pytest.fixture(autouse=True)
def _clean_reachability_cache():
    """本文件自己也不许把缓存留在任何状态（否则就成了第二份污染源）。"""
    mibao_reachable_tool_names.cache_clear()
    yield
    mibao_reachable_tool_names.cache_clear()


def test_seam_injection_is_effective():
    """对照组：注入确实把接缝换成了**读面为空**的替身。"""
    from app.graph.skills import base_skill

    with patch("app.graph.skills.base_skill.create_skill_registry") as fake:
        assert base_skill.create_skill_registry is fake
        assert list(fake().get_tool_names()) == [], (
            "替身读面不为空 ⇒ 本文件模拟的污染形态不成立，下面两条会变成空跑"
        )


def test_public_probe_result_ignores_execute_seam():
    """替身期间算出的可达面必须与真值逐名相等（不是空集，也不是替身返回值）。"""
    expected = _compute_mibao_reachable_tool_names()
    assert len(expected) > 10, (
        f"真值只有 {len(expected)} 个工具 —— 前提不成立（判据会退化成恒真）"
    )

    with patch("app.graph.skills.base_skill.create_skill_registry"):
        actual = mibao_reachable_tool_names()

    assert actual == expected, (
        "执行接缝的测试替身污染了进程级缓存：替身生效期间公开探测算出了别的值。\n"
        f"替身期间现取：{len(actual)} 个工具（前 5：{sorted(actual)[:5]}）\n"
        f"真值：        {len(expected)} 个工具\n"
        "修法：可达性探测必须从实现模块 app.graph.skills.tool_selection 取 create_skill_registry"
        "（base_skill 的同名符号是测试替身接缝）。"
    )


def test_boundary_view_does_not_collapse_after_prior_turn():
    """前序用例的替身撤销之后，本次用例读到的能力真值不得被冻成空集。"""
    baseline = resolve_units()
    assert baseline["product_rename"] is True, (
        "前提：改名当前是 ✅（CH-051 的正向能力）—— 前提不成立时本判据需同步"
    )
    assert baseline["employee_write"] is True, (
        "前提：员工创建当前是 ✅（issue #7050 接回）—— 前提不成立时本判据需同步"
    )

    # 模拟「前序用例是第一个探测者」：缓存被清掉后，由**替身期间**的那一次投影填缓存。
    mibao_reachable_tool_names.cache_clear()
    with patch("app.graph.skills.base_skill.create_skill_registry"):
        resolve_units()

    after = resolve_units()
    assert after == baseline, (
        "前序用例的替身污染了本次用例读到的能力真值（进程级缓存被冻成空集/退化值）。\n"
        f"污染后仍判可用的单元：{sorted(k for k, v in after.items() if v)}\n"
        f"基线仍判可用的单元：  {sorted(k for k, v in baseline.items() if v)}"
    )
