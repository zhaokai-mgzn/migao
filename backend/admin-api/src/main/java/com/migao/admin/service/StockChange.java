package com.migao.admin.service;

import java.math.BigDecimal;
import java.util.Map;

/**
 * 一次库存变更的**变更前/变更后**读数（issue #6299 / #6300）。
 *
 * <p><b>为什么要有这个类型</b>：库存台账（{@code stock_ledger_entries}）的每一行都要求
 * {@code before_qty} 与 {@code after_qty} <b>首尾相接</b>（相邻两行的 prev.after == cur.before）。
 * 而在并发下，「先 {@code SELECT stock} 取快照、再 {@code UPDATE} 加/减」这个写法会让两个请求
 * 读到<b>同一个 before</b>（同基、链断裂）—— 净增量还是对的，所以<b>只看库存查不出来</b>，
 * 只有查台账链才暴露。</p>
 *
 * <p>⇒ 本类型的唯一生产者是「一条 SQL 同时改动库存并 {@code RETURNING} 出前后值」的柱面
 * （{@code ProductSkuMapper#deductStock} / {@code receiveStock}）——
 * <b>不提供任何「从读快照构造」的入口</b>，从类型上就堵住那条路。</p>
 *
 * @param beforeQuantity 变更前库存（来自同一条原子语句的 {@code RETURNING}）
 * @param afterQuantity  变更后库存（同上）
 * @param skuCode        库内的 SKU 货号（台账追溯用；SKU 行会被硬删重建，故台账冗余存它）
 */
record StockChange(BigDecimal beforeQuantity, BigDecimal afterQuantity, String skuCode) {

    /** 从 mapper 的 {@code RETURNING} 行映射构造；{@code null}（0 行 = 没改成）⇒ {@code null}。 */
    static StockChange from(Map<String, Object> row) {
        if (row == null) {
            return null;
        }
        return new StockChange(decimal(row.get("beforeQuantity")),
                decimal(row.get("afterQuantity")), (String) row.get("skuCode"));
    }

    private static BigDecimal decimal(Object value) {
        if (value == null) {
            return null;
        }
        return value instanceof BigDecimal bd ? bd : new BigDecimal(value.toString());
    }
}
