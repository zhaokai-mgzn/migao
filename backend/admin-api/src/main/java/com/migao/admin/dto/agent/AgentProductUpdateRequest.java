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

    /** 是否允许退货回补库存（issue #2991，null = 不修改） */
    private Boolean allowReturnRestock;

    /**
     * 商品状态（上下架，issue #3560，null = 不修改）。
     * 值：on_sale（上架）/ off_sale（下架）/ draft / under_review，走状态机校验。
     *
     * 回归背景：product_update 一直在请求体里下发 status，但本 DTO 曾无该字段 + service
     * 从不读取它 → Jackson 静默忽略 → 走 hasUpdate=false 分支返回商品详情（HTTP 200 + success）
     * → 米宝回「已下架」而 products.status 未变（假成功）。
     */
    private String status;
}
