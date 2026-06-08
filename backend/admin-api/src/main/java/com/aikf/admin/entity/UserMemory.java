package com.aikf.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 用户记忆实体类
 * 对应表：user_memories
 * 说明：跨会话持久化用户偏好、关键事实、反馈等
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "user_memories", autoResultMap = true)
public class UserMemory {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String userId;

    /** preference | fact | feedback | reference */
    private String type;

    /** 记忆 key，如 "style_preference" */
    private String key;

    /** 记忆值 */
    private String value;

    /** 重要性评分 0-1 */
    private Float importance;

    /** 记录时的对话上下文 */
    private String context;

    /** 关联记忆 ID 列表 */
    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object relatedTo;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;
}
