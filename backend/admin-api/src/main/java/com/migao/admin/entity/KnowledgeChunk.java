package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 知识库文档分块实体类
 * 对应表：rag_chunks
 * 说明：存储RAG文档分块，用于BM25检索
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "rag_chunks", autoResultMap = true)
public class KnowledgeChunk {

    @TableId(type = IdType.ASSIGN_UUID)
    private String chunkId;

    private Long tenantId;

    private String documentId;

    private String content;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object metadata;

    private Integer chunkIndex;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
