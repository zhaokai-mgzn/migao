package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 角色实体类
 * 对应表：roles
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("roles")
public class Role {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String name;

    private String code;

    /**
     * 数据范围（V177，issue #7372）：`tenant` = 全租户（默认）/ `self` = 只看本人创建的单据。
     * 多角色取**最宽**（见 {@code DataScope.resolve}）。
     */
    private String dataScope;

    private String description;

    private String status;

    /** 角色已分配的权限列表（role_permissions 关联，@TableField(exist=false) 不落库） */
    @TableField(exist = false)
    private java.util.List<com.migao.admin.entity.Permission> permissions;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
