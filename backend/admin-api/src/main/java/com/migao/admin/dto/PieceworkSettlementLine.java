package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;

/**
 * 计件结算单的**明细行快照**（issue #5653）。
 *
 * <p>对消费端可见的 JSON 键即字段名（{@code operation} / {@code qty} / {@code amount}）——
 * 与 {@code GET /api/admin/production/piecework/summary} 的 {@code per_operation[]} 是**同源子集**
 * （逐值取自同一次聚合读数，结算侧不重算）。</p>
 *
 * <p>⚠️ <b>为什么是顶层 DTO 而不是实体的静态内部类</b>：仓内「schema.sql 必须覆盖 Java 实体声明的列」
 * 的判据（{@code TestSchemaCoversEntityColumns}）按 {@code entity/**.java} 里的**所有字段名**推导列集
 * ⇒ 内部类的字段（{@code operation}/{@code qty}/{@code amount}）会被当成 {@code piecework_settlements}
 * 的列而判红（本机实测：三条 missing_cols）。JSONB 列的载荷放在 DTO 层，实体只持
 * {@code List<...>} 引用。</p>
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class PieceworkSettlementLine {

    /** 工序（工序实例快照名，与报表 {@code per_operation[].operation} 逐字同值）。 */
    private String operation;

    private BigDecimal qty;

    private BigDecimal amount;
}
