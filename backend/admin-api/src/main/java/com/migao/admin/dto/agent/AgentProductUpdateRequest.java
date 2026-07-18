package com.migao.admin.dto.agent;

import lombok.Data;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/**
 * Agent 专用商品更新请求。
 * 全部字段 Optional —— null = "不修改此字段"。
 * 加工项走独立的 PATCH /{id}/processing-items 端点。
 */
@Data
public class AgentProductUpdateRequest {

    /** 商品名称，null = 不修改 */
    private String name;

    /** 分类ID（可为名称/UUID/前缀），null = 不修改 */
    private String categoryId;

    /** 基础价格，null = 不修改 */
    private BigDecimal basePrice;

    /** 货号，null = 不修改 */
    private String skuCode;

    /** 商品描述，null = 不修改 */
    private String description;

    /** 品牌，null = 不修改 */
    private String brand;

    /** 计价单位，null = 不修改 */
    private String unit;

    /** 计价方式，null = 不修改 */
    private String pricingType;

    /** 库存数量，null = 不修改 */
    private Integer stock;

    /** 主图 URL 列表，null = 不修改，[] = 清空 */
    private List<String> images;

    /** 详情图 URL 列表，null = 不修改，[] = 清空 */
    private List<String> detailImages;

    /**
     * 颜色列表，null = 不修改。
     * 传了则全量替换（会触发 SKU 重建）。
     */
    private List<String> colors;

    /**
     * 售卖方式列表，null = 不修改。
     * 传了则全量替换（会触发 SKU 重建）。
     */
    private List<String> sellingMethods;

    /**
     * 门幅列表，null = 不修改。
     * 传了则全量替换（会触发 SKU 重建）。
     */
    private List<String> doorWidths;

    /** 规格属性，null = 不修改 */
    private Map<String, String> specifications;

    /** 库存扣减模式，null = 不修改 */
    private String stockDeductionMode;
}
