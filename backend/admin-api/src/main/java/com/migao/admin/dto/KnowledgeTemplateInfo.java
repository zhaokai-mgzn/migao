package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 行业模板目录信息（LLM WIKI 板块 P3，issue #3051）
 * 模板为平台资产：resources/knowledge-templates/<templateId>/template.json（jar 内可读）
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class KnowledgeTemplateInfo {
    private String templateId;
    private String industry;
    private String name;
    private Integer version;
    private String description;
    private Integer entryCount;
}
