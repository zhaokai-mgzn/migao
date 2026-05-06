package com.aikf.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 知识库文档实体类
 * 对应表：knowledge_documents
 * 说明：存储RAG知识库文档元数据
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("knowledge_documents")
public class KnowledgeDocument {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String title;

    private String docType;

    private String category;

    private String fileType;

    private String fileUrl;

    private String content;

    private String productId;

    private String embeddingStatus;

    private Integer chunkCount;

    private String dashvectorCollection;

    private Boolean isActive;

    private String createdBy;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
