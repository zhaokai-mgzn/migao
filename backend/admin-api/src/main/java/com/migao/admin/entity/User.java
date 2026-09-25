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

    /**
     * 员工登录用户名（V128，issue #5485）：员工用「{@code <username>@<tenants.code>} + 密码」登录。
     *
     * <p>可空 —— 存量行与「管理员尚未补设」的行都是 {@code null}（**不自动迁移、不自动生成**）。
     * 唯一性是**租户内**的（{@code uk_users_tenant_username} 部分唯一索引）⇒ 不同企业可同名；
     * 跨企业不串号由「登录时先由 tenantCode 解析 tenant_id、查询必须带 tenant_id」保证（不变式 I1/I3）。</p>
     */
    private String username;

    /**
     * 首登强制改密（V128，issue #5485）：管理员设的初始密码必须首登改掉。
     *
     * <p>签发侧按**数据库当前值**计算 JWT claim（登录与刷新都算），拦截侧带该 claim 的会话
     * 除白名单外一律 403（不变式 I4）—— 「只在登录时算」会被「刷新一次 token」绕过。</p>
     */
    private Boolean mustChangePassword;

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
