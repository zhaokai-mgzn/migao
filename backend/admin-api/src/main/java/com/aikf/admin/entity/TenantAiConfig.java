package com.aikf.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 租户AI配置实体类
 * 对应表：tenant_ai_configs
 * 说明：存储AI客服的自我介绍、营业时间、转人工关键词等配置
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "tenant_ai_configs", autoResultMap = true)
public class TenantAiConfig {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String greetingTemplate;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object businessHours;

    private String timezone;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object autoHandoffKeywords;

    private Boolean emotionHandoff;

    private Boolean aiFallbackHandoff;

    private Integer aiFallbackThreshold;

    private String afterHoursMode;

    private String afterHoursMessage;

    private String recommendStrategy;

    private Integer recommendCount;

    private String recommendTrigger;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object quickReplies;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
