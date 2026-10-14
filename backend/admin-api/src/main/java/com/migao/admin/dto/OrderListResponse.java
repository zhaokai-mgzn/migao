package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 订单列表响应 DTO
 */
@Data
public class OrderListResponse {

    /**
     * 订单ID
     */
    private String id;

    /**
     * 订单号
     */
    private String orderNo;

    /**
     * 客户姓名
     */
    private String customerName;

    /**
     * 客户电话
     */
    private String customerPhone;

    /**
     * 收货地址（issue #2815：C 端下单自动填充用；BeanUtils.copyProperties 自动复制）
     */
    private String customerAddress;

    /**
     * 总金额（商品小计 + 加工费）
     */
    private BigDecimal totalAmount;

    /**
     * 实收款（当前 = totalAmount，后续支持优惠时可调整）
     */
    private BigDecimal actualAmount;

    /**
     * 加工费合计
     */
    private BigDecimal processingFee;

    /**
     * 是否含加工项
     */
    private Boolean hasProcessing;

    /**
     * 订单状态
     */
    private String status;

    /**
     * 备注
     */
    private String remark;

    /**
     * 关闭/取消原因
     */
    private String closeReason;

    /**
     * 创建时间
     */
    private OffsetDateTime createdAt;

    /**
     * 更新时间
     */
    private OffsetDateTime updatedAt;

    /**
     * 订单级**加急标记**（V120，issue #5177）—— 订单列表的**加急角标**读它
     * （由 `BeanUtils.copyProperties(order, response)` 从实体同名字段带出，**不另立第二份口径**）。
     */
    private Boolean isUrgent;

    /** **客户要求到货日**（V120，issue #5177；`YYYY-MM-DD`）；`null` = **未指定**（不猜）。 */
    private LocalDate requiredDeliveryDate;

    /**
     * **制单人姓名**（issue #5835，V142 `orders.created_by_name` 的快照）——
     * 列表「制单人」列读它（由 `BeanUtils.copyProperties(order, response)` 从实体同名字段带出，
     * **不另立第二份口径**）。
     *
     * <p>`null` = **未采集**（存量单 / 内部服务占位 / 匿名 / C 端自助下单）⇒ 前端渲染「—」，
     * **不是**空字符串（「没采集」不许静默留空）。</p>
     */
    private String createdByName;

    /**
     * 订单明细简要列表（用于列表"采购商品"列展示）
     */
    private List<OrderItemBrief> items;

    /**
     * 订单明细简要 DTO（用于列表展示）
     */
    @Data
    @AllArgsConstructor
    @NoArgsConstructor
    public static class OrderItemBrief {
        /**
         * 行主键（`order_items.id`）—— issue #6883 补。
         *
         * 🔴 原实现**刻意不下发**（issue #2916 的实现副产品，前端注释里记着「列表接口不下发 item.id」），
         * 但**「余料台账」的「按商品行搜索」要靠它**指认「是哪一行」：缺它 ⇒ 那边只能靠
         * 「品名 + 颜色 + 规格 + 数量」重新猜一行（而 `color` / `specification` 又不在响应里 ⇒
         * 猜的判据恒真 ⇒ 可能挂到错行）。**加性改动**，不动任何既有键。
         */
        private String id;
        private String productId;
        private String productName;
        private String productCode;
        private BigDecimal quantity;
        private BigDecimal unitPrice;
        /** 金额 = unitPrice * quantity（展示用） */
        private BigDecimal amount;
        /** 小计（数据库 subtotal 字段，可能为 null） */
        private BigDecimal subtotal;
        /** 销售信息（颜色、销售方式、门幅、SKU 等） */
        private Object processingInfo;
    }
}
