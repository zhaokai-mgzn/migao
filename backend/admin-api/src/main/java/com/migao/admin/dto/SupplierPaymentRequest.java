package com.migao.admin.dto;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/**
 * 登记付款请求（issue #7369 段 3-B）。
 *
 * <p>{@code allocations} 可为空：**先打款、后勾对**是真实业务（预付 / 未到票），
 * 空数组 = 整笔挂在该供应商往来账上，等有单再冲。
 *
 * @param supplierId  供应商档案 id（必填）
 * @param paidAt      付款日期（可空 ⇒ 服务端取今天）
 * @param amount      付款金额（> 0）
 * @param method      cash / transfer / wechat / alipay / other
 * @param referenceNo 回单号 / 流水号（可空）
 * @param remark      备注（可空）
 * @param allocations 冲抵明细（可空）：每行 { inboundOrderId, amount }
 */
public record SupplierPaymentRequest(String supplierId,
                                     LocalDate paidAt,
                                     BigDecimal amount,
                                     String method,
                                     String referenceNo,
                                     String remark,
                                     List<Allocation> allocations) {

    /**
     * 一行冲抵。
     *
     * @param inboundOrderId 被冲的入库单 id（必须是**本供应商**的 **posted** 单）
     * @param amount         冲到这张单的金额（> 0，且该单累计冲抵 ≤ 该单金额）
     */
    public record Allocation(String inboundOrderId, BigDecimal amount) {
    }
}
