package com.migao.admin.dto;

import java.math.BigDecimal;
import java.time.LocalDate;

/**
 * 一家供应商的应付对账面（issue #7369 段 3-A）。
 *
 * <h3>口径（A 段：只做对账视图，不做付款流水）</h3>
 * <ul>
 *   <li>{@code receivedAmount} = 该供应商**已过账**入库单金额之和（draft / cancelled 不计）；</li>
 *   <li>{@code paidAmount} = **恒 0**：A 段没有付款登记通道（用户 2026-10-20 裁定「A（轻）」）；
 *       等到付款段上线，这一列才开始有值；</li>
 *   <li>{@code outstanding} = {@code receivedAmount − paidAmount}；</li>
 *   <li>{@code paymentsRecorded = false} 是给前端的**诚实标记**：它让页面显示「未登记」，
 *       而不是把「还没做付款登记」伪装成「一分钱都没付」（后者是一句会让商家误判的谎）。</li>
 * </ul>
 *
 * @param supplierId        供应商档案 id
 * @param supplierName      档案名（用它而不是单据文本：对账要按**主数据**聚）
 * @param status            active / inactive
 * @param receivedAmount    累计收货额（已过账）
 * @param orderCount        已过账入库单张数
 * @param firstInboundDate  首次入库日（null = 还没收过货）
 * @param lastInboundDate   最近入库日
 * @param paidAmount        已付（A 段恒 0）
 * @param paymentsRecorded  是否已有付款登记通道（A 段 false）
 * @param outstanding       尚欠 = 收货额 − 已付
 */
public record SupplierPayable(String supplierId,
                              String supplierName,
                              String status,
                              BigDecimal receivedAmount,
                              int orderCount,
                              LocalDate firstInboundDate,
                              LocalDate lastInboundDate,
                              BigDecimal paidAmount,
                              boolean paymentsRecorded,
                              BigDecimal outstanding) {
}
