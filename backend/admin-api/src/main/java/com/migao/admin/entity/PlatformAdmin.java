package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 平台管理员实体类（超管）
 * 平台级账号，无租户归属
 * 对应表：platform_admins
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("platform_admins")
public class PlatformAdmin {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private String phone;

    private String passwordHash;

    private String nickname;

    private String avatar;

    private String status;

    private OffsetDateTime lastLoginAt;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;
}
