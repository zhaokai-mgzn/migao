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

        /**
         * 首登强制改密（issue #5485 不变式 I4）：{@code true} ⇒ 前端登录后**必须**跳「首登改密」页；
         * 改密前除 {@code POST /api/auth/password/change} / {@code POST /api/auth/logout} /
         * {@code GET /api/auth/me} 外的接口一律 403（{@code PASSWORD_CHANGE_REQUIRED}）。
         *
         * <p>字段名三端逐字一致（camelCase）；与 JWT **内部** claim {@code pwd_change_required}
         * 是两套命名，不要合并成一个字面量。</p>
         */
        private Boolean mustChangePassword;
    }
}
