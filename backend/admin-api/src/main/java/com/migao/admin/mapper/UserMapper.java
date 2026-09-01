package com.migao.admin.mapper;

import com.migao.admin.entity.User;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

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
}
