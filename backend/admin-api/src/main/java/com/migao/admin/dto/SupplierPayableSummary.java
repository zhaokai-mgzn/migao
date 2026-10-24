package com.migao.admin.dto;

import java.math.BigDecimal;
import java.util.List;

/**
 * 应付对账汇总（issue #7369 段 3-A）。
 *
 * @param suppliers        逐家对账面（按累计收货额降序）
 * @param totalReceived    合计累计收货额（= 合计尚欠，因为 A 段没有付款登记）
 * @param totalOutstanding 合计尚欠
 * @param paymentsRecorded 是否已有付款登记通道（A 段 false —— 前端据此把「已付」显示成「未登记」）
 */
public record SupplierPayableSummary(List<SupplierPayable> suppliers,
                                     BigDecimal totalReceived,
                                     BigDecimal totalOutstanding,
                                     boolean paymentsRecorded) {
}
