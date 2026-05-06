package com.aikf.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 知识库同步历史实体类
 * 对应表：knowledge_sync_history
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "knowledge_sync_history", autoResultMap = true)
public class KnowledgeSyncHistory {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** single / batch / full */
    private String syncType;

    /** product / manual */
    private String sourceType;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object sourceIds;

    /** pending / processing / completed / failed */
    private String status;

    private Integer totalCount;

    private Integer successCount;

    private Integer failedCount;

    private String errorMessage;

    private OffsetDateTime startedAt;

    private OffsetDateTime completedAt;

    private String createdBy;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;
}
