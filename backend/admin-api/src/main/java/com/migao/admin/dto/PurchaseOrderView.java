package com.migao.admin.dto;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 采购单读面（issue #7369 段 4）—— 收货进度是**派生值**（Σ receipts），不是存储列。
 *
 * @param id           采购单 id
 * @param poNo         单号
 * @param supplierId   供应商 id
 * @param supplierName 供应商名（人看得懂的那个；档案改名后这里跟着变，是主数据引用）
 * @param orderDate    下单日
 * @param expectedDate 预计到货日
 * @param status       ordered / partially_received / received / closed
 * @param totalAmount  明细金额之和
 * @param remark       备注
 * @param closedAt     关闭时刻
 * @param closedReason 关闭原因
 * @param items        明细（含已收 / 未收数量）
 * @param receipts     收货记录（按时间倒序）
 */
public record PurchaseOrderView(String id,
                                String poNo,
                                String supplierId,
                                String supplierName,
                                LocalDate orderDate,
                                LocalDate expectedDate,
                                String status,
                                BigDecimal totalAmount,
                                String remark,
                                OffsetDateTime closedAt,
                                String closedReason,
                                List<ItemView> items,
                                List<ReceiptView> receipts) {

    /**
     * 明细读面。
     *
     * @param id              明细 id
     * @param skuId           SKU
     * @param productId       商品 id
     * @param quantity        采购数量
     * @param unitPrice       单价
     * @param amount          金额（数量 × 单价，2 位小数）
     * @param receivedQuantity 已收（Σ receipts）
     * @param remainingQuantity 未收（采购数量 − 已收；收齐 = 0）
     */
    public record ItemView(String id,
                           String skuId,
                           String productId,
                           BigDecimal quantity,
                           BigDecimal unitPrice,
                           BigDecimal amount,
                           BigDecimal receivedQuantity,
                           BigDecimal remainingQuantity) {
    }

    /**
     * 收货记录读面。
     *
     * @param id             收货记录 id
     * @param itemId         对应明细 id
     * @param quantity       数量
     * @param receivedAt     到货日
     * @param inboundOrderId 关联的入库单（可空）
     */
    public record ReceiptView(String id,
                              String itemId,
                              BigDecimal quantity,
                              LocalDate receivedAt,
                              String inboundOrderId) {
    }
}
