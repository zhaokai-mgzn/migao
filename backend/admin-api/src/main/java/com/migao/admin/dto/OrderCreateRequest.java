package com.migao.admin.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/**
 * 订单创建请求 DTO
 */
@Data
public class OrderCreateRequest {

    /**
     * 客户姓名
     */
    @NotBlank(message = "客户姓名不能为空")
    private String customerName;

    /**
     * 客户电话
     */
    @NotBlank(message = "客户电话不能为空")
    private String customerPhone;

    /**
     * 客户地址
     */
    private String customerAddress;

    /**
     * 备注
     */
    private String remark;

    /**
     * 订单明细列表
     */
    @NotEmpty(message = "订单明细不能为空")
    @Valid
    private List<OrderItemRequest> items;

    /**
     * 订单明细请求 DTO
     */
    @Data
    public static class OrderItemRequest {

        /**
         * 商品ID
         */
        private String productId;

        /**
         * 商品名称
         */
        @NotBlank(message = "商品名称不能为空")
        private String productName;

        /**
         * 数量
         */
        @NotNull(message = "数量不能为空")
        @Positive(message = "数量必须大于 0")
        private Integer quantity;

        /**
         * 单价
         */
        @NotNull(message = "单价不能为空")
        @Positive(message = "单价必须大于 0")
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
         * 加工项详情 JSON
         */
        private Object processingInfo;

        /**
         * 小计
         */
        @NotNull(message = "小计不能为空")
        @Positive(message = "小计必须大于 0")
        private BigDecimal subtotal;
    }
}
