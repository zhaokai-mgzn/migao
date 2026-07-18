package com.migao.admin.dto.agent;

import lombok.Data;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/**
 * Agent 专用商品创建请求。
 * 全部字段 Optional —— 无 @NotBlank，字段为 null 时取默认值或报友好错误。
 * categoryId 可为名称/UUID/前缀，服务端解析。
 * processingItemIds 可为 UUID 字符串/名称/序号，服务端解析。
 */
@Data
public class AgentProductCreateRequest {

    /** 商品名称（必填，手动校验） */
    private String name;

    /** 分类ID，可为 UUID / 名称 / 前缀 */
    private String categoryId;

    /** 基础价格 */
    private BigDecimal basePrice;

    /** 货号（可选，空则自动生成） */
    private String skuCode;

    /** 商品描述 */
    private String description;

    /** 品牌 */
    private String brand;

    /** 计价单位，空则按品类默认（窗帘→"米"） */
    private String unit;

    /** 计价方式，空则按品类默认（窗帘→"per_meter"） */
    private String pricingType;

    /** 库存数量，默认 0 */
    private Integer stock;

    /** 商品状态，默认 "draft" */
    private String status;

    /** 主图 URL 列表 */
    private List<String> images;

    /** 详情图 URL 列表 */
    private List<String> detailImages;

    /** 颜色列表（纯字符串），服务端转为 ProductColorInput */
    private List<String> colors;

    /** 售卖方式（如 "散剪"/"整卷"），服务端翻译为 bulk_cut/full_roll */
    private List<String> sellingMethods;

    /** 门幅列表（如 "2.8米"） */
    private List<String> doorWidths;

    /**
     * 加工项 ID 列表。
     * 可混合传入 UUID 字符串 / 加工项名称 / 序号（1-based）。
     * 服务端统一解析为真实 UUID。
     */
    private List<String> processingItemIds;

    /** 加工项配置（含自定义价格） */
    private List<AgentProcessingItemConfig> processingItemConfigs;

    /** 规格属性 */
    private Map<String, String> specifications;

    /** 库存扣减模式 */
    private String stockDeductionMode;

    // ---- 加工项配置子对象 ----

    @Data
    public static class AgentProcessingItemConfig {
        /** 加工项 ID（可为 UUID / 名称 / 序号） */
        private String processingItemId;
        /** 自定义价格（可选） */
        private BigDecimal customPrice;
    }
}
