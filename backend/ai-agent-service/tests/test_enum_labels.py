"""
app.utils.enum_labels 单元测试 — 售后工单枚举 → 中文业务术语映射

背景：系统内部枚举（normal/urgent/critical 等）以英文存储，若原样回显给
用户无法理解（会话反馈：'系统里所有待处理工单的优先级标记都是 normal'）。
本模块提供中文业务术语映射，Tool 结果数据通过 attach_ticket_labels 附加
*_label 字段，LLM 回复用户时直接采用中文术语。
"""
# case_ids: AS-001, AS-002, AS-003, AS-004
import pytest

from app.utils.enum_labels import (
    TICKET_PRIORITY_LABELS,
    TICKET_STATUS_LABELS,
    TICKET_TYPE_LABELS,
    attach_ticket_labels,
    label_for,
)


class TestLabelMappings:
    """枚举 → 中文业务术语全量映射（与前端 AfterSalesPriorityLabels 对齐）"""

    def test_priority_labels(self):
        assert TICKET_PRIORITY_LABELS == {
            "normal": "普通",
            "urgent": "紧急",
            "critical": "严重",
        }

    def test_status_labels(self):
        assert TICKET_STATUS_LABELS == {
            "pending": "待处理",
            "processing": "处理中",
            "resolved": "已解决",
            "rejected": "已拒绝",
            "closed": "已关闭",
        }

    def test_ticket_type_labels(self):
        assert TICKET_TYPE_LABELS == {
            "refund": "退款",
            "exchange": "换货",
            "repair": "维修",
            "complaint": "投诉",
            "other": "其他",
        }


class TestLabelFor:
    def test_known_value(self):
        assert label_for(TICKET_PRIORITY_LABELS, "normal") == "普通"
        assert label_for(TICKET_STATUS_LABELS, "pending") == "待处理"
        assert label_for(TICKET_TYPE_LABELS, "refund") == "退款"

    def test_unknown_value_passthrough(self):
        # 未知枚举原样返回，不丢信息
        assert label_for(TICKET_PRIORITY_LABELS, "p0") == "p0"

    def test_none_value(self):
        assert label_for(TICKET_PRIORITY_LABELS, None) == ""


class TestAttachTicketLabels:
    def test_attaches_all_labels(self):
        item = {"id": "t1", "status": "pending", "priority": "urgent", "ticketType": "complaint"}
        enriched = attach_ticket_labels(item)
        assert enriched["status_label"] == "待处理"
        assert enriched["priority_label"] == "紧急"
        assert enriched["ticket_type_label"] == "投诉"
        # 原始枚举值必须保留（内部推理/API 契约需要）
        assert enriched["status"] == "pending"
        assert enriched["priority"] == "urgent"
        assert enriched["ticketType"] == "complaint"

    def test_does_not_mutate_original(self):
        item = {"id": "t1", "status": "resolved"}
        attach_ticket_labels(item)
        assert "status_label" not in item

    def test_missing_fields_no_labels(self):
        enriched = attach_ticket_labels({"id": "t1"})
        assert enriched == {"id": "t1"}

    def test_unknown_enum_label_passthrough(self):
        enriched = attach_ticket_labels({"id": "t1", "status": "archived"})
        assert enriched["status_label"] == "archived"

    def test_critical_priority_label(self):
        enriched = attach_ticket_labels({"id": "t1", "priority": "critical"})
        assert enriched["priority_label"] == "严重"
