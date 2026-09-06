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
    @Select("SELECT id, tenant_id, phone, password_hash, nickname, avatar, role, session_ttl, status, created_at, updated_at, deleted FROM users WHERE phone = #{phone} AND deleted = 0 AND status = 'active' ORDER BY updated_at DESC")
    List<User> selectActiveUsersByPhoneIgnoreTenant(@Param("phone") String phone);

    /**
     * 跨租户按手机号查询活跃「员工」账号（B 端小程序登录用，issue #2977）。
     *
     * 门禁语义：仅商户员工（role 非 customer/agent）可绑定 bmini 登录——
     * C 端消费者账号即使手机号撞号也绝不通过 bmini 入口登录（BM-003 员工专属门禁）。
     * 与 C 端 findOrCreate 语义相反：B 端「匹配不到即拒绝」，禁止自动建号。
     */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT id, tenant_id, phone, password_hash, nickname, avatar, role, session_ttl, status, created_at, updated_at, deleted FROM users WHERE phone = #{phone} AND deleted = 0 AND status = 'active' AND role NOT IN ('customer', 'agent') ORDER BY updated_at DESC")
    List<User> selectActiveEmployeesByPhoneIgnoreTenant(@Param("phone") String phone);

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
