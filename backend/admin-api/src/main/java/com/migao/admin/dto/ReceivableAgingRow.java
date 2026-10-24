package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * 应收账龄的**单笔应收行**（issue #7370，P0-2 段 2）。
 *
 * <p><b>应收口径 = 未收款订单</b>：{@code paid_at IS NULL}（**与授信闸门 {@code selectOutstandingTotal} 同一真值源**）
 * ⇒ 应收 = {@code total_amount − Σ退款}。为什么不复用「对账页」的 {@code actual_amount} 兜底：
 * 该列 {code NULL} 在既有对账页被读成「已收满」，而真实存量里它只表示**未采集** —— 拿它算账龄
 * 会让「没登记的收款」被当成「已付清」，欠款静默消失。</p>
 *
 * <p>📌 部分收款（一笔钱冲多张单）随 P0-2 段 3「逐笔核销」上线，届时应收改为
 * {@code Σ订单 − Σ核销 + Σ退款}，本行字段不变、SQL 换算即可。</p>
 *
 * <p>到期日不在 SQL 里算：账期是**客户档案**属性，分档规则（到期日当天归未到期等）钉在纯函数
 * {@code ReceivableAging} 里，逐格有判据。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ReceivableAgingRow {

    private String orderId;

    private String orderNo;

    private String customerName;

    private String customerPhone;

    /** 应收（orders.total_amount） */
    private BigDecimal receivable;

    /** 该单退款合计（finance_transactions type=refund ∧ status=success）—— 退款冲减应收 */
    private BigDecimal refunded;

    /** 余额 = 应收 − 已退（SQL 已过滤 &gt; 0；已收款单不在本行集合里） */
    private BigDecimal remaining;

    /** 下单时刻（SQL 原样带回；**日界换算不许在这里做**，见 #3802） */
    private OffsetDateTime createdAt;

    /**
     * 下单的**业务日期**（+08 口径；由 {@code CustomerService} 用 {@code BusinessClock.zone()} 从
     * {@link #createdAt} 换算后回填，到期日 = 它 + 客户账期天数）。
     *
     * <p>为什么分成两个字段：SQL 只能给时刻；「业务是哪一天」是**业务口径**，日界只许有一个来源
     * （{@code BusinessClock}）—— 把换算藏进 SQL 或这里都会造成两处口径（#3802 / #6200）。</p>
     */
    private LocalDate businessDate;
}
