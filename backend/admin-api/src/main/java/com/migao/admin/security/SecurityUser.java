package com.migao.admin.security;

import lombok.Getter;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.userdetails.User;

import java.util.Collection;
import java.util.List;

/**
 * 安全用户信息
 * 扩展 Spring Security User，携带 userId、tenantId、roles 等业务字段
 * 用于在 SecurityContext 中传递完整的用户认证信息
 */
@Getter
public class SecurityUser extends User {

    /**
     * 用户ID（数据库主键）
     */
    private final String userId;

    /**
     * 租户ID
     */
    private final Long tenantId;

    /**
     * 用户名（手机号）
     */
    private final String displayName;

    /**
     * 角色代码列表
     */
    private final List<String> roles;

    public SecurityUser(String userId,
                        Long tenantId,
                        String username,
                        List<String> roles,
                        Collection<? extends GrantedAuthority> authorities) {
        super(username != null ? username : userId, "", authorities);
        this.userId = userId;
        this.tenantId = tenantId;
        this.displayName = username;
        this.roles = roles != null ? roles : List.of();
    }
}
