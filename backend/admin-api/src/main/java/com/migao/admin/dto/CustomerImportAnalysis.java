package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * 客户 Excel 分析结果（issue #8295）：只读，不写库。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class CustomerImportAnalysis {

    private List<String> headers;

    /** 前 5 行样本（页面展示/人工确认映射用；不用于日志）。 */
    private List<List<String>> samples;

    private int totalRows;

    private List<CustomerImportField> fields;

    private List<MappingSuggestion> suggestions;

    /** AI 服务不可用/解析失败时为 true；suggestions 仍有确定性别名兜底。 */
    private boolean aiDegraded;

    private String aiMessage;
}
