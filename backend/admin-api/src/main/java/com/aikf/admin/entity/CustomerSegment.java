package com.aikf.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 客户分群规则实体类
 * 对应表：customer_segments
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "customer_segments", autoResultMap = true)
public class CustomerSegment {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String name;

    /** value_tier / behavior / custom */
    private String segmentType;

    private String description;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object conditions;

    /** daily / weekly / manual */
    private String updateFrequency;

    private Integer customerCount;

    private OffsetDateTime lastCalculatedAt;

    private String createdBy;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;
}
