package com.migao.admin.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.annotation.JsonDeserialize;
import lombok.Data;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

/**
 * 商品响应 DTO
 *
 * <p>{@code @JsonIgnoreProperties(ignoreUnknown = true)}（issue #6209）：幂等回放时快照 JSON 由
 * 同一个 DTO 序列化而来，而本 DTO 有**只写不出的派生 getter**（{@code getPrice()}）⇒ 严格模式下
 * {@code replay} 会反序列化失败并 fail-closed 拒绝同键重试。与 {@code OrderDetailResponse} /
 * {@code AfterSalesDetailResponse} 同款处置（它们各自也有派生 getter）。</p>
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@Data
public class ProductResponse {

    /**
     * 本次响应是否为**同键回放**（true = 没有新建，返回的是首次那条商品）。
     *
     * <p>issue #6209：不加这个字段时，调用方**分不出**「新建成功」与「同键回放」——
     * 与订单 / 售后两条路径同款（见 {@code ClientRequestIdService.replay} 的 replayedMarker：
     * 标记字段必须真实存在于响应 DTO 上，否则 Jackson 反序列化会把它**静默丢掉**）。
     * 正常首建为 {@code null}（{@code @JsonInclude(NON_NULL)} 口径下不出现在响应里）。</p>
     */
    private Boolean replayed;

    /**
     * 商品ID
     */
    private String id;

    /**
     * 商品名称
     */
    private String name;

    /**
     * 分类ID
     */
    private String categoryId;

    /**
     * 分类名称
     */
    private String categoryName;

    /**
     * 基础价格
     */
    private BigDecimal basePrice;

    /**
     * 价格（前端兼容字段，同 basePrice）
     */
    public BigDecimal getPrice() {
        return basePrice;
    }

    /**
     * 商品描述
     */
    private String description;

    /**
     * 主图URL
     */
    private String mainImage;

    /**
     * 图片列表
     */
    private List<String> images;

    /**
     * 知识库ID
     */
    private String knowledgeBaseId;

    /**
     * 状态：on_sale（上架）、off_sale（下架）
     */
    private String status;

    /**
     * 库存数量
     */
    private BigDecimal stock;

    /**
     * 库存预警阈值
     */
    private Integer stockWarningThreshold;

    /**
     * 商品货号
     */
    private String skuCode;

    /**
     * 计价单位（米/件/套等）
     */
    private String unit;

    /**
     * 计价方式：per_meter / per_piece / fixed / per_area
     */
    private String pricingType;

    /**
     * 库存扣减模式
     */
    private String stockDeductionMode;

    /**
     * 颜色数量
     */
    private Integer colorCount;

    /**
     * SKU总库存
     */
    private BigDecimal totalStock;

    /**
     * 累计销量
     */
    private BigDecimal salesCount;

    /**
     * 累计销售额
     */
    private BigDecimal salesAmount;

    /**
     * 是否商家推荐（C 端「新品推荐」位展示依据）
     */
    private Boolean recommended;

    /**
     * 是否允许退货回补库存（issue #2991）
     * 窗帘行业定制退货不可再售，默认 FALSE；标准件/配件等可再售商品开启后，
     * 售后工单退款/退货完结时恢复 SKU 库存。
     */
    private Boolean allowReturnRestock;

    /**
     * 颜色分类列表（详情接口返回）
     */
    private List<ProductColorResponse> colors;

    /**
     * 售卖方式列表（**商品级基础属性**，非 SKU 组合维度）—— 取自 {@code products.selling_methods}。
     *
     * <p>V108 / 用户裁定 2026-09-21：SKU 组合只有 颜色 × 门幅，售卖方式上移为商品属性。
     * 原实现「从 SKU 派生」已删除（SKU 不再带该列 ⇒ 那样会恒返回空数组）。</p>
     */
    private List<String> sellingMethods;

    /**
     * 1 卷 = 多少米（**商品货号级基础参数**）。
     * {@code null} = 未配置 ⇒ 订单侧**禁止**推算整卷发货分配（见 {@code ProductRollAllocation}）。
     */
    private BigDecimal rollLengthM;

    /**
     * 规格尺寸列表（详情接口返回，去重后从 SKU 派生）
     */
    private List<String> doorWidths;

    /**
     * SKU列表（详情接口返回）
     */
    private List<ProductSkuResponse> skus;

    /**
     * 品牌
     */
    private String brand;

    /**
     * 商品属性字典（weight/material/function/craft/style/pattern 等）
     */
    private Map<String, String> specifications;

    /**
     * 详情图列表
     */
    private List<String> detailImages;

    /**
     * 最后编辑人
     */
    private String editedBy;

    /**
     * 最后编辑时间
     */
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    @JsonDeserialize(using = LenientOffsetDateTimeDeserializer.class)
    private OffsetDateTime editedAt;

    /**
     * 创建时间
     */
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    @JsonDeserialize(using = LenientOffsetDateTimeDeserializer.class)
    private OffsetDateTime createdAt;

    /**
     * 更新时间
     */
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    @JsonDeserialize(using = LenientOffsetDateTimeDeserializer.class)
    private OffsetDateTime updatedAt;
}
