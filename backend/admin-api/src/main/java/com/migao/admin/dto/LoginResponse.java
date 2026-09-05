package com.migao.admin.dto;

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
        /** 智能客服名称（TenantAiConfig.botName，C 端思考中/空态/导航名展示；未配置为 null → 前端兜底「小布」） */
        private String botName;
    }
}
