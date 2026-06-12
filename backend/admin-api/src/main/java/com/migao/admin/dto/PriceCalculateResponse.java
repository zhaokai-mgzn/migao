package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/**
 * 价格计算响应 DTO
 */
@Data
public class PriceCalculateResponse {

    /**
     * 加工项ID
     */
    private String processingItemId;

    /**
     * 加工项名称
     */
    private String processingItemName;

    /**
     * 计价方式
     */
    private String pricingMethod;

    /**
     * 单价
     */
    private BigDecimal unitPrice;

    /**
     * 数量
     */
    private BigDecimal quantity;

    /**
     * 总价
     */
    private BigDecimal totalPrice;

    /**
     * 加工天数
     */
    private Integer processingDays;

    /**
     * 计算明细
     */
    private List<PriceDetail> details;

    /**
     * 额外费用
     */
    private Map<String, BigDecimal> extraFees;

    /**
     * 价格明细项
     */
    @Data
    public static class PriceDetail {
        /**
         * 项目名称
         */
        private String name;

        /**
         * 单价
         */
        private BigDecimal unitPrice;

        /**
         * 数量
         */
        private BigDecimal quantity;

        /**
         * 小计
         */
        private BigDecimal subtotal;

        /**
         * 说明
         */
        private String description;
    }
}
