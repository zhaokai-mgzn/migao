package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 用户实体类
 * 对应表：users
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("users")
public class User {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String phone;

    private String passwordHash;

    private String nickname;

    private String avatar;

    private String role;

    /** 岗位（纯展示字段，如"管理员""客服""销售""运营""财务"） */
    private String position;

    /**
     * 工人工号（V98，issue #4733）：非 {@code null} = 该行是**工人档案**（{@code role=worker}）。
     *
     * <p>工人身份与商家账号彻底分离：工号是「工号 + PIN」登录的查找键，
     * 也是「只认工人档案」的机械判据（见 {@code WorkerSessionService.findWorkerByNo}）。</p>
     */
    private String workerNo;

    /** 菜单权限码列表（JSON 数组，如 ["orders.list","products.create"]） */
    private String permissions;

    private Integer sessionTtl;

    private String status;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
