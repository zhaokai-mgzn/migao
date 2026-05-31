package com.aikf.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 订单列表响应 DTO
 */
@Data
public class OrderListResponse {

    /**
     * 订单ID
     */
    private String id;

    /**
     * 订单号
     */
    private String orderNo;

    /**
     * 客户姓名
     */
    private String customerName;

    /**
     * 客户电话
     */
    private String customerPhone;

    /**
     * 总金额
     */
    private BigDecimal totalAmount;

    /**
     * 订单状态
     */
    private String status;

    /**
     * 备注
     */
    private String remark;

    /**
     * 创建时间
     */
    private OffsetDateTime createdAt;

    /**
     * 更新时间
     */
    private OffsetDateTime updatedAt;

    /**
     * 订单明细简要列表（用于列表"采购商品"列展示）
     */
    private List<OrderItemBrief> items;

    /**
     * 订单明细简要 DTO（用于列表展示）
     */
    @Data
    @AllArgsConstructor
    @NoArgsConstructor
    public static class OrderItemBrief {
        private String productId;
        private String productName;
        private String productCode;
        private Integer quantity;
        private BigDecimal unitPrice;
    }
}
