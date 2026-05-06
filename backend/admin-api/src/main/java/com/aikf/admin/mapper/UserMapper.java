package com.aikf.admin.mapper;

import com.aikf.admin.entity.User;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * 用户Mapper接口
 */
@Mapper
public interface UserMapper extends BaseMapper<User> {

    /**
     * 跨租户根据手机号查询管理员用户（用于 SMS 登录，绕过多租户拦截器）
     */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT id, tenant_id, phone, password_hash, nickname, avatar, role, session_ttl, status, created_at, updated_at, deleted FROM users WHERE phone = #{phone} AND deleted = 0 AND role IN ('admin', 'super_admin')")
    User selectAdminByPhoneIgnoreTenant(@Param("phone") String phone);
}
