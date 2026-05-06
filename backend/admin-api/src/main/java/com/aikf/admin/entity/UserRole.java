package com.aikf.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 用户角色关联实体类
 * 对应表：user_roles
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("user_roles")
public class UserRole {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String userId;

    private String roleId;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableLogic
    private Integer deleted;
}
