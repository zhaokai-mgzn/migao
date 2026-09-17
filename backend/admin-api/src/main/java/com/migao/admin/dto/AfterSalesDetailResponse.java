package com.migao.admin.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.Data;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 售后工单详情响应 DTO
 * 对齐前端 AfterSalesTicket 类型（含 statusHistory）
 *
 * <p>{@code @JsonIgnoreProperties(ignoreUnknown = true)}（issue #4037）：幂等回放时快照 JSON
 * 会带 {@code replayed: true}（见 {@code ClientRequestIdService.replay}），显式声明"多出的键
 * 不影响反序列化"，免得默认值被收紧后**回放路径静默变 500**。</p>
 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class AfterSalesDetailResponse {

    /**
     * 幂等回放标记（issue #4037）：{@code true} = 本次响应来自「同键回放」，
     * 服务端**没有**新建记录；首次执行时不出现该键（{@code NON_NULL}）。
     *
     * <p>为什么必须是**真字段**而不是"在快照 JSON 里塞一个键"：Jackson 反序列化时
     * 未声明的键会被丢弃（本类还显式声明了 {@code ignoreUnknown=true}）⇒ 标记会被**静默丢掉**，
     * 响应里永远不会出现它，而调用方（ai-agent）就分不出「首次执行」与「同键回放」，
     * 会把一次重试播报成两笔订单（观察性缺陷）。</p>
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    private Boolean replayed;

    private String id;
    private String ticketNo;
    private String orderId;
    private String orderNo;
    private String customerId;
    private String customerName;
    private String customerPhone;
    private String ticketType;
    private String status;
    private String description;
    private List<String> images;
    private String source;
    private String priority;
    private String handlerId;
    private String handlerName;
    private OffsetDateTime assignedAt;
    private BigDecimal refundAmount;
    private String refundMethod;
    private List<String> evidenceImages;
    private String internalNotes;
    private OffsetDateTime deadline;
    private OffsetDateTime closedAt;
    private String closeReason;
    private List<StatusHistoryItem> statusHistory;
    private OffsetDateTime createdAt;
    private OffsetDateTime updatedAt;


    /**
     * 状态变更历史项
     * 对齐前端 AfterSalesStatusHistory
     */
    @Data
    public static class StatusHistoryItem {
        private String status;
        private String time;
        private String operator;
        private String remark;
    }
}
