package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.stream.Collectors;

/**
 * 一张订单的打印**汇总投影**（issue #7902）—— 订单列表「是否已打印」的唯一数据面。
 *
 * <p>由 {@code PrintLogMapper.selectPrintSummary} **一次批量**聚合出来（禁止 N+1），
 * 字段与聚合 SQL 的四个投影列逐一对应（{@code order_id} / {@code printed_at} / {@code print_count} / {@code doc_types}）。</p>
 *
 * <p>🔴 只聚合 {@code status = 'fired'} 的行：失败的那次纸没有出来，算进「已打印」会让商家以为打过了。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class PrintLogSummary {

    private String orderId;

    /** 最近一次打印时间（= 该单 fired 行的 {@code MAX(created_at)}）。 */
    private OffsetDateTime printedAt;

    /** 打印条数（不是出纸张数的和：`sheets` 是「这次几张纸」，条数是「打了几次」）。 */
    private Integer printCount;

    /**
     * {@code string_agg(DISTINCT doc_type, ',')} 的**原始**逗号串（无序、实现细节）——
     * 上屏请用 {@link #printedDocTypes()}（去重 + 排序）。
     */
    private String docTypes;

    /**
     * 去重排序后的单据类型列表（如 {@code ["processing", "sales"]}）。
     *
     * <p>空 / null ⇒ **空列表**（不是 null）：消费方（前端）据此判断「从未打印」，
     * 让「没有数据」与「读不到」长得不一样是本仓的既有口径。</p>
     */
    public List<String> printedDocTypes() {
        if (docTypes == null || docTypes.isBlank()) {
            return Collections.emptyList();
        }
        return Arrays.stream(docTypes.split(","))
                .map(String::trim)
                .filter(type -> !type.isEmpty())
                .distinct()
                .sorted()
                .collect(Collectors.toList());
    }
}
