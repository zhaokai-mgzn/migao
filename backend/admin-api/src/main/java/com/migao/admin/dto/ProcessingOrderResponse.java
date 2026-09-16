package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 加工单响应 DTO（issue #3340）
 */
@Data
public class ProcessingOrderResponse {

    private String id;
    private String tenantId;
    private String orderId;
    private String orderNo;
    private String customerName;
    private String customerPhone;
    private String processingOrderNo;
    private String processor;
    private LocalDate expectedDeliveryDate;
    private String status;
    /** 快照明细：不含销售价（决策 2），加工项含 options */
    private List<ProcessingOrderItemBrief> items;
    private String remark;
    private Integer templateVersion;
    private OffsetDateTime generatedAt;
    private OffsetDateTime issuedAt;
    private OffsetDateTime inProcessingAt;
    private OffsetDateTime completedAt;
    private OffsetDateTime cancelledAt;
    private String cancelledReason;
    private Integer printCount;

    /**
     * 快照明细项
     */
    @Data
    public static class ProcessingOrderItemBrief {
        private String productName;
        private String sku;
        private String colorName;
        private String sellingMethod;
        private String doorWidth;
        private BigDecimal width;
        private BigDecimal height;
        private BigDecimal quantity;
        private String unit;
        /** 加工项：含 id/name/unitPrice/quantity/unit/options（options 生成时从加工项目录补齐） */
        private List<ProcessingItemSnapshot> processingItems;
        private String remark;
    }

    @Data
    public static class ProcessingItemSnapshot {
        private String id;
        private String name;
        private BigDecimal unitPrice;
        private BigDecimal quantity;
        private String unit;
        private Object options;
    }
}
