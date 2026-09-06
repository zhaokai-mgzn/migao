package com.migao.admin.dto;

import lombok.Data;

import java.time.OffsetDateTime;

/**
 * 通知规则响应 DTO（issue #2965 补齐规则管理）
 */
@Data
public class NotificationRuleDTO {

    private String id;

    /** 归属租户；0 = 系统内置规则（只读） */
    private Long tenantId;

    private String eventType;

    private String recipientType;

    private String channels;

    private Boolean enabled;

    private String templateId;

    /** 关联模板名称（联查冗余） */
    private String templateName;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;
}