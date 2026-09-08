package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 知识提炼候选实体类（LLM WIKI 板块，issue #3051）
 * 对应表：knowledge_candidates
 * 说明：AI 提炼（会话/文档/商品）产生的候选词条，进入商家「待采纳」队列。
 * 核心不变式：AI 只产生候选，发布权在商家。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("knowledge_candidates")
public class KnowledgeCandidate {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 来源：conversation / document / product / config */
    private String sourceType;

    /** 来源引用：会话ID / 文档ID / 商品ID */
    private String sourceRef;

    /** 建议词条标题 */
    private String suggestedTitle;

    /** 建议标准回答 */
    private String suggestedAnswer;

    /** 建议分类 */
    private String suggestedCategory;

    /** 建议关键词（逗号分隔） */
    private String suggestedKeywords;

    /** 提炼置信度 0~1 */
    private BigDecimal confidence;

    /** 提炼依据（会话摘录 / 文档原文片段） */
    private String evidence;

    /** 状态：pending / adopted / edited / rejected */
    private String status;

    private String statusNote;

    private OffsetDateTime createdAt;

    private OffsetDateTime reviewedAt;

    private String reviewedBy;
}
