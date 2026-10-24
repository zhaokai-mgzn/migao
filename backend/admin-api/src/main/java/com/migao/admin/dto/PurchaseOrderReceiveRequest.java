package com.migao.admin.dto;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/**
 * 采购收货请求（issue #7369 段 4）：一次可收多行（同一次到货常有多个 SKU）。
 *
 * @param receivedAt   到货日（可空 ⇒ 业务今天）
 * @param remark       备注（记「这次缺了什么」的地方）
 * @param lines        收货行（每行 = 某明细这次到多少）
 */
public record PurchaseOrderReceiveRequest(LocalDate receivedAt, String remark, List<Line> lines) {

    /**
     * 一行收货。
     *
     * @param itemId         采购单明细 id
     * @param quantity       本次到货数量（> 0，且 ≤ 该行剩余未收数量）
     * @param inboundOrderId 已存在的入库单 id（可空；给了就校验同租户 / 同供应商 / 已过账）
     */
    public record Line(String itemId, BigDecimal quantity, String inboundOrderId) {
    }
}
