package com.migao.admin.dto;

import lombok.Data;

import java.time.OffsetDateTime;

/**
 * 通知模板响应 DTO（issue #2965 补齐模板管理）
 */
@Data
public class NotificationTemplateDTO {

    private String id;

    /** 归属租户；0 = 系统内置模板（只读） */
    private Long tenantId;

    private String name;

    private String type;

    private String channel;

    private String templateContent;

    private String variables;

    private String status;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;
}