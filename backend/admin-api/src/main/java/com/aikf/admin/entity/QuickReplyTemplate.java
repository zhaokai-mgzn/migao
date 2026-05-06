package com.aikf.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 快捷回复模板实体类 - 人工客服工作台使用
 * 对应表：quick_reply_templates
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("quick_reply_templates")
public class QuickReplyTemplate {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String category;

    private String title;

    private String content;

    private String shortcut;

    private Integer usageCount;

    private Boolean isPublic;

    private String createdBy;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
