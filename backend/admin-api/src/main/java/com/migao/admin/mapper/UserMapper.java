package com.migao.admin.mapper;

import com.migao.admin.entity.User;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

/**
 * 用户Mapper接口
 */
@Mapper
public interface UserMapper extends BaseMapper<User> {

    /**
     * 跨租户根据手机号查询全部活跃用户（用于 SMS 登录，绕过多租户拦截器）。
     * 同手机号可能存在于多个租户——登录时须按 tenantId 精确匹配或拒绝歧义
     * （审计 07 P1-2：禁止静默 LIMIT 1 导致登录落错租户）。
     */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT id, tenant_id, phone, username, password_hash, nickname, avatar, role, worker_no, session_ttl, status, must_change_password, created_at, updated_at, deleted FROM users WHERE phone = #{phone} AND deleted = 0 AND status = 'active' ORDER BY updated_at DESC")
    List<User> selectActiveUsersByPhoneIgnoreTenant(@Param("phone") String phone);

    /**
     * 按「租户 + 用户名」查询活跃员工账号（员工登录，issue #5485 不变式 I1/I3）。
     *
     * <p>🔴 {@code tenant_id} 谓词是**契约的一部分**，不是可选项：它由
     * {@code tenants.code} 解析出的 tenant_id 传入，用户名唯一性只到租户内 ⇒ **不同企业可同名**。
     * 任何「不带租户限定的用户名查询 / 跨租户兜底」都是跨企业串号（I1）。
     * 类级元守卫：{@code tests/unit_ci_workflows/test_tenant_scoped_user_queries.py}
     * （凡是 {@code @InterceptorIgnore(tenantLine="true")} 又查 {@code users} 的方法，
     * SQL 里没有 tenant_id 就必须登记豁免台账 —— 未登记即红）。</p>
     *
     * <p>🔴 <b>{@code @InterceptorIgnore} 是必须的（不是优化）</b> —— 真栈验收实测（issue #5485）：
     * 登录端点**未认证**，此时 {@code TenantContext} 为空，租户拦截器走 fail-closed
     * 分支直接抛 {@code RuntimeException: Tenant context not initialized - possible unauthenticated access}
     * ⇒ 凡走到"查用户"这一步的登录请求全部 **500**（最常见的「用户名打错」场景也会 500），
     * 同时破坏反枚举（三种病因必须同码同文案）。单测抓不到它：单测 mock 掉了 mapper，
     * 拦截器根本没被执行（本仓点名的「mock 掉的依赖，其真实行为在生产才第一次执行」）。</p>
     *
     * <p>之所以能安全绕过自动注入：租户谓词 {@code tenant_id = #{tenantId}} **显式写在 SQL 里**
     * （由 {@code tenants.code} 解析所得）⇒ 与同族的 {@code selectActiveUsersByPhoneIgnoreTenant}
     * 同口径。类级元守卫 {@code tests/unit_ci_workflows/test_tenant_scoped_user_queries.py} 仍会
     * 钉住这条 SQL 必须带 tenant_id 谓词（去掉谓词即红，无需登记豁免）。</p>
     */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT id, tenant_id, phone, username, password_hash, nickname, avatar, role, worker_no, session_ttl, status, must_change_password, created_at, updated_at, deleted FROM users WHERE tenant_id = #{tenantId} AND username = #{username} AND deleted = 0 AND status = 'active'")
    User selectActiveByTenantAndUsername(@Param("tenantId") Long tenantId, @Param("username") String username);

    /**
     * 看板客户维度聚合（#2886 性能优化：客户总数 + 今日新增一次查询，替代 2 次串行 selectCount）。
     * 租户条件由 TenantLineInnerInterceptor 自动注入。
     */
    @Select("SELECT " +
            "COUNT(*) FILTER (WHERE role = 'customer') AS total_customers, " +
            "COUNT(*) FILTER (WHERE role = 'customer' AND created_at >= #{todayStart}) AS new_customers_today " +
            "FROM users WHERE deleted = 0")
    Map<String, Object> selectDashboardUserStats(@Param("todayStart") OffsetDateTime todayStart);
}
