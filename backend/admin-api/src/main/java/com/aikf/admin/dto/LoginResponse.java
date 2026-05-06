package com.aikf.admin.dto;

import lombok.Builder;
import lombok.Data;

import java.util.List;

/**
 * 登录响应 DTO
 */
@Data
@Builder
public class LoginResponse {

    /**
     * 用户信息
     */
    private UserInfo user;

    /**
     * JWT Access Token（用于前端存储，实际认证通过 Cookie）
     */
    private String accessToken;

    /**
     * 刷新 Token
     */
    private String refreshToken;

    /**
     * Token 过期时间（秒）
     */
    private Long expiresIn;

    /**
     * 用户信息内部类
     */
    @Data
    @Builder
    public static class UserInfo {
        private String id;
        private String nickname;
        private String avatar;
        private String role;
        private String identityType;
        private List<String> roles;
        private Long tenantId;
        private String tenantName;
    }
}
