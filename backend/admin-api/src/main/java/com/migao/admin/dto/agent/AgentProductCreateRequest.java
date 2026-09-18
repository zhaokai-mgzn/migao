package com.migao.admin.dto.agent;

import lombok.Data;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/**
 * Agent 专用商品创建请求。
 * 全部字段 Optional —— 无 @NotBlank，字段为 null 时取默认值或报友好错误。
 * categoryId 可为名称/UUID/前缀，服务端解析。
 *
 * <p>加工项解耦（issue #4371）：商品**不再**持有加工项 —— 加工项是店铺全目录，
 * 由用户在加工项目录里独立选择，生产路线由「安装方式 + 商品」经
 * {@code app/production/routing.py} 的 {@code ROUTINGS[(部位,工艺)]} 决定。
 * 故本请求**没有** processingItemIds / processingItemConfigs 字段
 * （回归防线见 {@code ProductProcessingDecouplingTest}）。
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

    /** 规格属性 */
    private Map<String, String> specifications;

    /** 库存扣减模式 */
    private String stockDeductionMode;

    /**
     * 是否允许退货回补库存（issue #2991，null = 默认 false）
     * 窗帘行业定制退货不可再售，默认不回补；可再售商品（标准件/配件）传 true 开启。
     */
    private Boolean allowReturnRestock;
}
