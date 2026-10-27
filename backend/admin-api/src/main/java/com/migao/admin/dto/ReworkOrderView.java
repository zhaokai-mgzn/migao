package com.migao.admin.dto;

import lombok.Builder;
import lombok.Data;

import java.math.BigDecimal;
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

    /** 加工单号（展示用；取不到 ⇒ null，界面渲染 —，**不编值**）。 */
    private String processingOrderNo;

    /** 销售订单号（展示用；取不到 ⇒ null）。 */
    private String orderNo;

    /** 来源（issue #7860）：after_sales / worker。 */
    private String source;

    /** 返工的工序名（车间来源有值）。 */
    private String operationName;

    /** 件定位键（issue #7945）：套号 × 部位；null = 未定位（不猜）。 */
    private String orderItemId;
    private String setId;
    private String setNo;
    /** 部位展示名快照（读面不 join 猜）。 */
    private String positionName;

    /** 返工数量（车间来源有值；不参与计件）。 */
    private BigDecimal qty;

    /** 报返工的工人（车间来源有值）。 */
    private String workerName;

    /** draft / in_progress / done / cancelled。 */
    private String status;

    private String reason;

    private String createdByName;

    private OffsetDateTime startedAt;

    private OffsetDateTime completedAt;
}
