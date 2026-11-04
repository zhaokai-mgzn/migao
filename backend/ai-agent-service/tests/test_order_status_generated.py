# case_ids: MC-204
"""生成物本身的形态判据（issue #8198 的 P2-2b）。

`backend/ai-agent-service/app/constants/order_status_generated.py` 是 Java 单一源
（`OrderStatusTransitions`）的**投影**、入库、由 `python3 scripts/order_status_codegen.py --write` 产出。

「生成物 == 源」的逐值判据在 `tests/unit_ci_workflows/test_order_status_codegen.py`（判据 1/2），
本文件只钉**这一份产物的内容形态**：它是 7 个取值的全集（含 `packed`），三张表键齐、标签齐、
可编辑集合是单元素 —— 手改生成物（改值 / 删键 / 换成手写表）⇒ 红。

消费侧的口径冻结（Agent 面只暴露 6 个）在 `tests/test_order_status.py`。
"""
from __future__ import annotations

import pytest

from app.constants.order_status_generated import (
    CONTENT_EDITABLE_STATUSES,
    ORDER_STATUSES,
    ORDER_STATUS_LABELS,
    PACKED,
    STATUS_TRANSITIONS,
)

#: 单一源的 7 个取值（顺序 = Java 常量声明顺序）—— 独立硬编码的真值，
#: 故意**不**从被测模块反推（反推会让"改了生成物"同时改判据 = 假绿）。
CANONICAL_STATUSES = (
    "pending", "confirmed", "producing", "packed", "shipped", "completed", "cancelled",
)


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
