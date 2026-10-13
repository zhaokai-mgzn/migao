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

    /**
     * 工人档案级**工人端页面收窄**（V152，issue #6788；{@code role=worker} 的行才用）。
     *
     * <p>三态：{@code null} = <b>未收窄</b>（= 全部工人端页面 —— 存量与新建的默认值）·
     * 收窄到闭词表 {@code WorkerPages.ALL} 里的某几页。实际下发 = 企业页
     * ⇒ 本列是页面集的**唯一**一层（企业级页面开关已整层移除，issue #6828）。</p>
     *
     * <p>🔴 <b>不是权限码</b>，所以**另开一列**而不是塞进 {@link #permissions}
     * （那是商家 RBAC 权限快照）：工人 session 的 {@code permissions} 恒为 {@code []}，
     * 可达面恒为 {@code /api/worker/**}；本列只影响「页面上看不看得见」，不参与任何授权判定。</p>
     *
     * <p>🔴 <b>为什么是 {@code String} 而不是 {@code List<String>} + {@code JacksonTypeHandler}</b>
     * （与 {@link #permissions} 同形态）：① 手写 {@code select} 返回带类型处理器的实体**必须绑
     * {@code @ResultMap}**，否则 JSONB 列落成字符串、判据静默为假（本仓复发过两次：issue #3340 / #4865，
     * 类级守卫 {@code JacksonTypeHandlerMappingGuardTest} 就此而设）；② 类型处理器对**形态不对**的入库值
     * 会**抛异常**（不是回 {@code null}）⇒ 一行脏数据会让 {@code GET /api/worker/me} 500，
     * 把工人的活挡在外面 —— 与「读侧 fail-open」正好相反。故这里存**原样 JSON 文本**、
     * 由 {@link com.migao.admin.worker.WorkerPages#restrictedOrNull} 自己做**宽容解析**（坏值 ⇒ 当未收窄）。</p>
     *
     * <p>⚠️ 与 {@code NOT_NULL} 更新策略的交互：{@code null} 字段**不会**进 {@code UPDATE} 的 SET
     * ⇒ 「清回收窄」必须走 {@code WorkerAdminService.updateWorkerPages} 的显式 {@code set}（不要用
     * 「更新一个 null 字段」表达清空）。</p>
     */
    private String workerPages;

    private Integer sessionTtl;

    private String status;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
