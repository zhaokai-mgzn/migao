package com.aikf.admin.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 订单详情响应 DTO
 */
@Data
public class OrderDetailResponse {

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
     * 客户地址
     */
    private String customerAddress;

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
     * 订单明细列表
     */
    private List<OrderItemResponse> items;

    /**
     * 物流信息
     */
    private LogisticsInfo logistics;

    /**
     * 创建时间
     */
    private OffsetDateTime createdAt;

    /**
     * 更新时间
     */
    private OffsetDateTime updatedAt;

    /**
     * 订单明细响应 DTO
     */
    @Data
    public static class OrderItemResponse {

        /**
         * 明细ID
         */
        private String id;

        /**
         * 商品ID
         */
        private String productId;

        /**
         * 商品名称
         */
        private String productName;

        /**
         * 数量
         */
        private Integer quantity;

        /**
         * 单价
         */
        private BigDecimal unitPrice;

        /**
         * 宽度(米)
         */
        private BigDecimal width;

        /**
         * 高度(米)
         */
        private BigDecimal height;

        /**
         * 加工项详情
         */
        private Object processingInfo;

        /**
         * 小计
         */
        private BigDecimal subtotal;

        /**
         * 金额 = unitPrice * quantity（前端展示用，后端从 unitPrice 与 quantity 计算）
         */
        private BigDecimal amount;

        /**
         * 创建时间
         */
        private OffsetDateTime createdAt;
    }

    /**
     * 物流信息响应 DTO
     */
    @Data
    public static class LogisticsInfo {

        private String id;

        private String logisticsCompany;

        private String trackingNo;

        private String status;

        private Object trackingInfo;

        private OffsetDateTime shippedAt;

        private OffsetDateTime deliveredAt;
    }
}
