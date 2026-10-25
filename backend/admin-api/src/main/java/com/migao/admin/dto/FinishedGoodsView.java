package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 成品库存视图（V196，issue #7750）—— 「这件成品现在在哪个仓位」。
 *
 * <p>读面口径 = {@code finished_goods_stock} 的在库行（{@code status='in_stock'}）：
 * 已发货 / 已撤销打包的行不出现在库存页（它们只在单据与历史里可追溯）。</p>
 */
@Data
public class FinishedGoodsView {

    private Long id;

    /** 仓位号（如 A-01）—— 本页最要紧的一列 */
    private String binCode;

    private Long warehouseId;

    private Long locationId;

    private String orderId;

    private String orderNo;

    /** 成品订单行（一个订单行 = 一个在库行） */
    private String orderItemId;

    private String productId;

    private String productName;

    private BigDecimal quantity;

    /** set = 套 */
    private String unit;

    /** in_stock / shipped / unpacked */
    private String status;

    /** 进货的成品入库单（打包时自动建） */
    private String inboundOrderId;

    /** 出货的成品出库单（发货时自动建） */
    private String outboundOrderId;

    private OffsetDateTime createdAt;
}
