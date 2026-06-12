package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 客户标签实体类
 * 对应表：customer_tags
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "customer_tags", autoResultMap = true)
public class CustomerTag {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String name;

    private String color;

    /** auto / manual */
    private String tagType;

    private String description;

    // --- 自动标签配置 ---
    private String ruleType;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object ruleCondition;

    /** daily / weekly / realtime / manual */
    private String autoUpdateFrequency;

    private Integer hitCount;

    private String createdBy;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;
}
