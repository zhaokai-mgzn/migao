# case_ids: MC-204
"""Agent 侧订单状态**取自生成物、且行为冻结不变**的判据（issue #8198 的 P2-2b）。

## 这层判据守什么

真值只有一处（Java `OrderStatusTransitions`），生成物是它的投影
（`app/constants/order_status_generated.py`，由 `python3 scripts/order_status_codegen.py --write` 产出、入库）。

本文件不重复判「生成物 == 源」（那是 `tests/unit_ci_workflows/test_order_status_codegen.py` 的判据 1/2），
它守的是**消费侧的两件事**：

1. **4 个工具 schema 的订单状态枚举确实从生成物派生**（`list(AGENT_ORDER_STATUSES)`），
   而不是各自手抄一份 —— 手抄的会在下一次改源时静默分叉；
2. **行为逐字不变**：Agent 面今天只暴露 **6 个**状态（不含 `packed`）。生成物里有 7 个，
   直接铺进 schema 就等于**悄悄放开**「Agent 可以把订单改成 packed」——
   那是行为变更，必须单独裁定（重启条件写在 `app/constants/order_status.py` 的 docstring 里）。

## 红证（注入式）

- 把 `AGENT_ORDER_STATUSES` 改成全集（7 个）⇒ 冻结判据与四个面的取值判据一起红；
- 把任一 schema 的 `list(AGENT_ORDER_STATUSES)` 改回手写 6 个字面量 ⇒ 取值判据仍绿（值一样），
  但根判据的**扫面**会红 —— 两条判据合起来才堵住「抄一份一样的」。
"""
from __future__ import annotations

import pytest

from app.constants.order_status import AGENT_ORDER_STATUSES
from app.constants.order_status_generated import (
    CONTENT_EDITABLE_STATUSES,
    ORDER_STATUSES,
    ORDER_STATUS_LABELS,
    PACKED,
    STATUS_TRANSITIONS,
)
from app.tools.customer_order_query import CustomerOrderQueryTool
from app.tools.order_manage import OrderManageTool
from app.tools.order_query import OrderQueryTool
from app.tools.validate_input import _VALIDATION_RULES

#: 单一源的 7 个取值（顺序 = Java 常量声明顺序）—— 独立硬编码的真值，
#: 故意**不**从被测模块反推（反推会让"改了生成物"同时改判据 = 假绿）。
CANONICAL_STATUSES = (
    "pending", "confirmed", "producing", "packed", "shipped", "completed", "cancelled",
)

#: Agent 工具面**冻结**的 6 个（不含 `packed`）：与改前逐字一致（独立硬编码的真值）。
FROZEN_AGENT_STATUSES = ("pending", "confirmed", "producing", "shipped", "completed", "cancelled")


def test_generated_module_carries_the_full_status_set() -> None:
    assert ORDER_STATUSES == CANONICAL_STATUSES
    assert tuple(ORDER_STATUS_LABELS) == CANONICAL_STATUSES
    assert tuple(STATUS_TRANSITIONS) == CANONICAL_STATUSES
    assert PACKED == "packed"
    assert CONTENT_EDITABLE_STATUSES == ("pending",)


@pytest.mark.parametrize("status", CANONICAL_STATUSES)
def test_every_status_carries_a_chinese_label_and_a_transition_row(status: str) -> None:
    """每个状态都必须有标签与流转行（删一行 ⇒ 具名红；空值 / `None` 都不放过）。"""
    assert isinstance(ORDER_STATUS_LABELS[status], str) and ORDER_STATUS_LABELS[status].strip()
    assert isinstance(STATUS_TRANSITIONS[status], tuple)


def test_terminal_statuses_have_no_outgoing_transitions() -> None:
    """终态没有出边（把 `completed` / `cancelled` 的流转行塞上目标 ⇒ 红）。"""
    assert STATUS_TRANSITIONS["completed"] == ()
    assert STATUS_TRANSITIONS["cancelled"] == ()


def test_agent_face_is_frozen_without_packed() -> None:
    """行为零变化：Agent 面仍是那 6 个，`packed` 不在面内（放开它 = 独立的行为变更单）。"""
    assert AGENT_ORDER_STATUSES == FROZEN_AGENT_STATUSES
    assert PACKED not in AGENT_ORDER_STATUSES
    # 窄化是从**全集**派生的（不是另抄一份 6 个）：差集恰好是打包态那一个。
    assert set(ORDER_STATUSES) - set(AGENT_ORDER_STATUSES) == {PACKED}


@pytest.mark.parametrize(
    "label, schema_enum",
    [
        ("order_manage", OrderManageTool.parameters["properties"]["status"]["enum"]),
        ("order_query", OrderQueryTool.parameters["properties"]["status"]["enum"]),
        ("customer_order_query", CustomerOrderQueryTool.parameters["properties"]["status"]["enum"]),
        ("validate_input_gate", _VALIDATION_RULES["order_manage"]["update_status"]["status"]["enum"]),
    ],
)
def test_tool_schemas_derive_their_enum_from_the_generated_module(label: str, schema_enum) -> None:
    """四个面的枚举都必须**等于**派生的 6 个（顺序也一致 —— 顺序即模型看到的契约面）。"""
    assert list(schema_enum) == list(AGENT_ORDER_STATUSES), f"{label} 的订单状态枚举与单一源不一致"
