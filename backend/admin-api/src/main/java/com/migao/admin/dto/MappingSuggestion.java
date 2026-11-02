package com.migao.admin.dto;

/**
 * 一条 AI/确定性列映射建议（issue #8295）。
 *
 * @param sourceIndex  Excel 表头列下标（0-based）
 * @param sourceHeader 原始表头
 * @param targetField  canonical 字段 key
 * @param confidence   0..1
 * @param reason       可读理由（页面展示）
 */
public record MappingSuggestion(
        int sourceIndex,
        String sourceHeader,
        String targetField,
        double confidence,
        String reason
) {
}
