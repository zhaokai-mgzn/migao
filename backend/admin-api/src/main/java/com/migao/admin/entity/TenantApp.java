package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 租户前端应用配置实体类
 * 对应表：tenant_apps
 * 说明：存储微信小程序、公众号H5等应用配置
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("tenant_apps")
public class TenantApp {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String appType;

    private String appId;

    private String appSecret;

    private String token;

    private String encodingAesKey;

    private String msgEncryptMode;

    private String serverUrl;

    private String status;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
