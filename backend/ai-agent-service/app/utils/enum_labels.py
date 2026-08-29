"""
售后/订单枚举 → 中文业务术语映射（用户可见回复专用）

背景：系统内部枚举（如工单优先级 normal/urgent/critical、状态 pending/...、
类型 refund/...）以英文存储。若原样回显给用户，用户无法理解其含义
（会话反馈：'系统里所有待处理工单的优先级标记都是 normal'）。

规则：面向用户的回复必须使用中文业务术语；英文枚举值仅在内部推理
与 admin-api 调用参数中使用。Tool 结果数据附加 *_label 字段携带中文
术语，LLM 回复时直接采用。
"""

# 工单状态
TICKET_STATUS_LABELS = {
    "pending": "待处理",
    "processing": "处理中",
    "resolved": "已解决",
    "rejected": "已拒绝",
    "closed": "已关闭",
}

# 工单优先级（用户反馈的核心：normal/urgent/critical 用户看不懂）
TICKET_PRIORITY_LABELS = {
    "normal": "普通",
    "urgent": "紧急",
    "critical": "严重",
}

# 工单类型
TICKET_TYPE_LABELS = {
    "refund": "退款",
    "exchange": "换货",
    "repair": "维修",
    "complaint": "投诉",
    "other": "其他",
}


def label_for(mapping: dict, value) -> str:
    """取枚举的中文业务术语；未知值原样返回（不丢信息）。"""
    if value is None:
        return ""
    return mapping.get(value, value)


def attach_ticket_labels(item: dict) -> dict:
    """为售后工单对象附加中文业务术语标签（保留原始枚举值）。

    附加字段：
      - status_label       状态：待处理/处理中/已解决/已拒绝/已关闭
      - priority_label     优先级：普通/紧急/严重
      - ticket_type_label  类型：退款/换货/维修/投诉/其他
    """
    enriched = dict(item)
    if "status" in enriched:
        enriched["status_label"] = label_for(TICKET_STATUS_LABELS, enriched["status"])
    if "priority" in enriched:
        enriched["priority_label"] = label_for(TICKET_PRIORITY_LABELS, enriched["priority"])
    if "ticketType" in enriched:
        enriched["ticket_type_label"] = label_for(TICKET_TYPE_LABELS, enriched["ticketType"])
    return enriched
