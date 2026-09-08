package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 知识词条实体类（LLM WIKI 板块，issue #3051）
 * 对应表：knowledge_entries
 * 说明：知识单元从 RAG chunk 升级为结构化词条；AI 客服直接读词条回答，
 * 检索用结构化过滤 + 关键词匹配，不引入向量库。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("knowledge_entries")
public class KnowledgeEntry {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 词条标题（如「雪尼尔面料会起球吗」） */
    private String title;

    /** 分类：faq / product / measure / aftersale / config */
    private String category;

    /** 行业（curtain=布艺，模板标识） */
    private String industry;

    /** 来源：template / product / config / conversation / document / manual */
    private String sourceType;

    /** 来源引用：模板ID / 商品ID / 会话ID / 文档ID */
    private String sourceRef;

    /** 常见问法（提炼流产出，人工可改） */
    private String question;

    /** 标准回答/话术（可含变量模板，如 {{price}}） */
    private String answer;

    /** 逗号分隔关键词（轻量检索用） */
    private String keywords;

    /** 适用商品范围（JSONB，如 ["productId1","productId2"]） */
    private String applyProducts;

    /** 变量模板声明（JSONB，L2 运行时用商品/配置数据填充） */
    private String variables;

    /** 状态：draft / pending_review / published / archived */
    private String status;

    /** 版本号（编辑递增） */
    private Integer version;

    private String reviewNote;

    private String createdBy;

    private String reviewedBy;

    private OffsetDateTime reviewedAt;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
