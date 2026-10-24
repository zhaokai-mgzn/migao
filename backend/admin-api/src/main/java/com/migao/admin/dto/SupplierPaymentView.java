package com.migao.admin.dto;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 付款单读面（issue #7369 段 3-B）。
 *
 * @param id            付款单 id
 * @param paymentNo     单号
 * @param supplierId    供应商档案 id
 * @param paidAt        付款日期
 * @param amount        付款金额
 * @param allocatedAmount 已冲抵合计
 * @param unallocatedAmount 未冲抵（= 金额 − 冲抵；预付 / 待勾对）
 * @param method        付款方式
 * @param referenceNo   回单号
 * @param remark        备注
 * @param status        posted / voided
 * @param voidedAt      作废时刻（未作废为 null）
 * @param voidedReason  作废原因
 * @param allocations   冲抵明细
 */
public record SupplierPaymentView(String id,
                                  String paymentNo,
                                  String supplierId,
                                  LocalDate paidAt,
                                  BigDecimal amount,
                                  BigDecimal allocatedAmount,
                                  BigDecimal unallocatedAmount,
                                  String method,
                                  String referenceNo,
                                  String remark,
                                  String status,
                                  OffsetDateTime voidedAt,
                                  String voidedReason,
                                  List<AllocationView> allocations) {

    /**
     * 一行冲抵的读面。
     *
     * @param inboundOrderId 入库单 id
     * @param inboundNo      入库单号（人看得懂的那个）
     * @param amount         冲抵金额
     */
    public record AllocationView(String inboundOrderId, String inboundNo, BigDecimal amount) {
    }
}
