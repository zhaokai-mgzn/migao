package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;

/**
 * 商品关联的加工项响应 DTO
 * 用于 GET /api/admin/products/{id}/processing-items 接口
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ProductProcessingItemResponse {

    /** 加工项 ID（processing_items.id） */
    private String id;

    /** 加工项名称 */
    private String name;

    /** 计价方式：per_meter / per_piece / fixed / per_area */
    private String pricingMethod;

    /** 原始单价 */
    private BigDecimal unitPrice;

    /** 商品自定义价格（可为 null） */
    private BigDecimal customPrice;

    /** 最终价格：customPrice 不为空则取 customPrice，否则取 unitPrice */
    private BigDecimal finalPrice;

    /** 计价单位 */
    private String unit;
}
