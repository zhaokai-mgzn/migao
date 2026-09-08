package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;

/**
 * 商品-加工项配置响应 DTO
 * 用于商品详情接口返回已配置的加工项信息
 *
 * 价格回退规则（2026-09-08 sess_c1fce183dae24f22 复盘固化）：
 * customPrice 不为空则 finalPrice = customPrice，否则 finalPrice = unitPrice（加工项默认单价）。
 * 此前仅透传 customPrice（创建时未携带则为 null）→ 前端展示 ¥0.00；
 * 与 getProductProcessingItems(finalPrice=customPrice?:unitPrice) 对齐后，
 * 加工项价格在 AI 建品未携带自定义价时也能正确回填默认单价。
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
     * 加工项默认单价（processing_items.unit_price，可为 null）
     */
    private BigDecimal unitPrice;

    /**
     * 商品自定义价格（可为 null）
     */
    private BigDecimal customPrice;

    /**
     * 最终价格：customPrice 不为空则取 customPrice，否则取 unitPrice
     */
    private BigDecimal finalPrice;

    /**
     * 计价单位（米/平方米/件等）
     */
    private String unit;
}