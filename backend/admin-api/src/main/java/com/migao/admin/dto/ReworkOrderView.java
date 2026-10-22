package com.migao.admin.dto;

import lombok.Builder;
import lombok.Data;

import java.time.OffsetDateTime;

/** 返工单读面（issue #7377 段 2）。 */
@Data
@Builder
public class ReworkOrderView {

    private String id;

    private String reworkNo;

    private String afterSalesTicketId;

    private String orderId;

    private String processingOrderId;

    /** draft / in_progress / done / cancelled。 */
    private String status;

    private String reason;

    private String createdByName;

    private OffsetDateTime startedAt;

    private OffsetDateTime completedAt;
}
