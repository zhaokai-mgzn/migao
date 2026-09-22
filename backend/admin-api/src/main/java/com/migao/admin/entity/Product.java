package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 商品实体类
 * 对应表：products
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "products", autoResultMap = true)
public class Product {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String name;

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

    private String categoryId;

    private BigDecimal basePrice;

    private String description;

    private String mainImage;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object images;

    /**
     * 详情图列表（JSONB 存储）
     */
    @TableField(value = "detail_images", typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private List<String> detailImages;

    private String knowledgeBaseId;

    private String status;

    /**
     * 库存数量
     */
    @TableField("stock")
    private BigDecimal stock = BigDecimal.ZERO;

    /**
     * 库存预警阈值
     */
    @TableField("stock_warning_threshold")
    private Integer stockWarningThreshold = 10;

    /**
     * 库存扣减模式：sku/product
     */
    private String stockDeductionMode = "on_order";

    /**
     * 累计销量
     */
    private BigDecimal salesCount;

    /**
     * 累计销售额
     */
    private BigDecimal salesAmount;

    /**
     * 最后编辑人
     */
    private String editedBy;

    /**
     * 最后编辑时间
     */
    private OffsetDateTime editedAt;

    /**
     * 是否商家推荐（C 端「新品推荐」位展示依据，商家在商品管理页显式打标）
     */
    private Boolean recommended;

    /**
     * 是否允许退货回补库存（issue #2991）
     * 窗帘行业定制退货不可再售，默认 FALSE 不回补；标准件/配件等可再售商品显式开启。
     * 售后工单 refund/return 完结时，仅本开关为 TRUE 才恢复 SKU 库存。
     */
    private Boolean allowReturnRestock;

    /**
     * 售卖方式（**商品级基础属性**，非 SKU 组合维度）—— 用户裁定 2026-09-21：
     * 「商品的售卖方式整卷/散件不能作为 SKU 的组合项，只能作为基础属性，
     * 商品的 SKU 由颜色+门幅组成即可」。取值 {@code bulk_cut}(散剪) / {@code full_roll}(整卷)，
     * JSONB 数组存库（V111 迁移）。
     */
    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private List<String> sellingMethods;

    /**
     * 1 卷 = 多少米（**商品货号级基础参数**，V111 迁移）。
     *
     * <p>{@code null} = 未配置/未知 ⇒ 订单侧**禁止**推算整卷发货分配
     * （行业卷长是区间值「60 米左右」，不得编造 —— 见
     * {@code docs/curtain-selling-method-industry-research.md} §5）。</p>
     */
    private BigDecimal rollLengthM;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
