package com.migao.admin.dto;

import lombok.Data;

import java.time.LocalDate;

/**
 * 加工单状态更新请求（issue #3340）
 * action: issue（发加工）/ start（开始加工）/ complete（加工完成）/ cancel（取消）
 */
@Data
public class ProcessingOrderUpdateRequest {

    private String action;

    /** issue 时可选：加工方 */
    private String processor;

    /** issue 时可选：交期（手工填写，决策 3） */
    private LocalDate expectedDeliveryDate;

    /** cancel 时必填：取消原因（issued 及以上必填，人工确认语义） */
    private String reason;
}
