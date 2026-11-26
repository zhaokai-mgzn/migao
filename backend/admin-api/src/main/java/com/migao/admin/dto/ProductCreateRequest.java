package com.migao.admin.dto;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/**
 * 商品创建请求 DTO
 */
@Data
public class ProductCreateRequest {

    /**
     * 商品名称
     */
    @NotBlank(message = "商品名称不能为空")
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

    /**
     * 分类ID（草稿状态允许为空，Service 层根据 status 校验）
     */
    private String categoryId;

    /**
     * 基础价格（草稿状态允许为空，Service 层根据 status 校验）
     */
    @DecimalMin(value = "0", inclusive = true, message = "商品价格不能为负数")
    private BigDecimal basePrice;

    /**
     * 商品描述
     */
    private String description;

    /**
     * 主图URL
     */
    private String mainImage;

    /**
     * 图片列表（JSON数组）
     */
    private List<String> images;

    /**
     * 知识库ID
     */
    private String knowledgeBaseId;

    /**
     * 状态：合法取值只有 draft（草稿）/ under_review（审核中）/ on_sale（出售中）/ off_sale（已下架）
     * —— **单一真值源 = ProductService.STATUS_TRANSITIONS**（issue #6347：本注释不再重复列一遍，
     * 入口按该集合做**枚举准入**，未知取值 422）。
     * AI 渠道创建默认 draft，避免未确认即上架；前端/Excel 导入由调用方控制
     */
    private String status = "draft";

    /**
     * 🔴 已下线（issue #7597，用户裁定 2026-10-24）：商品档案不再设置库存数值 ——
     * 新建 SKU 一律从 0 起算；库存只由真实单据产生
     * （入库单过账 / 订单扣减 / 售后回补 / 批次盘点）。
     *
     * <p>🔴 issue #9006（P2）：**不再静默忽略**。改前带 {@code stock: 100} ⇒ 200 创建成功却落 0
     * （2026-11-22 生产冒烟实测，调用方以为设上了初始库存）。现在**非 0 ⇒ 422 显式拒绝**
     * （收口 = {@code ProductService.requireNoInitialStockOnCreate} + 可行动文案）；不传 / 传 0 照常
     * （落库值本来就是 0，不存在被丢弃的意图）。</p>
     *
     * <p>字段保留的唯一目的是**看得见它并拒绝它**：Spring 默认忽略未知字段
     * （{@code FAIL_ON_UNKNOWN_PROPERTIES=false}），删掉字段反而会让老客户端传的 100 重新变成
     * **静默丢弃** —— 那正是本 issue 的病灶形态。</p>
     */
    private BigDecimal stock = BigDecimal.ZERO;

    /**
     * 库存预警阈值，默认 10
     */
    private Integer stockWarningThreshold = 10;

    // ========== 销售信息（颜色 / 售卖方式 / 规格尺寸 / SKU） ==========

    /**
     * 颜色分类列表
     */
    private List<ProductColorInput> colors;

    /**
     * 售卖方式列表（如 bulk_cut / full_roll）
     */
    private List<String> sellingMethods;

    /**
     * 1 卷 = 多少米（**商品货号级基础参数**，V108）。
     * 可空 —— 未配置时订单侧**不推算**整卷发货分配（不猜，见 {@code ProductRollAllocation}）。
     */
    private BigDecimal rollLengthM;

    /**
     * 门幅（规格尺寸）清单（如 2.8m / 3.2m / 3.4m）—— 商家声明的**可售门幅**。
     *
     * <p>两个消费面（V214 / issue #9005）：① 与 {@link #colors} 做笛卡尔积自动生成 SKU 矩阵
     * （颜色 × 门幅，用户裁定 2026-09-21）；② **落 {@code products.door_widths}**（本单修复的正是
     * 这一面缺失：改前没有颜色/SKU 时被无声丢弃，{@code GET /{id}} 也读不回来）。
     * 有 SKU 时读面仍以 SKU 派生值为准（门幅是 SKU 维度）；本列承载「还没有 SKU」时的同一份声明。</p>
     */
    private List<String> doorWidths;

    /**
     * SKU 列表
     */
    private List<ProductSkuInput> skus;

    // ========== 商品属性与详情图 ==========

    /**
     * 品牌
     */
    private String brand;

    /**
     * 是否允许退货回补库存（issue #2991，默认 FALSE）
     * 窗帘行业定制退货不可再售，默认关闭不回补；可再售商品创建时即可显式开启。
     */
    private Boolean allowReturnRestock;

    /**
     * 商品属性字典，key 可为 weight/material/function/craft/style/pattern 等
     */
    private Map<String, String> specifications;

    /**
     * 详情图列表
     */
    private List<String> detailImages;
}
