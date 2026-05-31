package com.aikf.admin.dto;

import lombok.Data;

import java.math.BigDecimal;

/**
 * 商品-加工项配置响应 DTO
 * 用于商品详情接口返回已配置的加工项信息
 */
@Data
public class ProcessingItemConfigResponse {

    /**
     * 加工项 ID
     */
    private String processingItemId;

    /**
     * 加工项名称
     */
    private String processingItemName;

    /**
     * 商品自定义价格（可为 null）
     */
    private BigDecimal customPrice;
}
