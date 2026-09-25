package com.migao.admin.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.Builder;
import lombok.Data;

import java.util.List;

/**
 * 用户信息响应 DTO
 * 包含用户信息、角色、权限和菜单
 */
@Data
@Builder
@JsonInclude(JsonInclude.Include.NON_NULL)
public class UserInfoResponse {

    /**
     * 用户信息
     */
    private UserInfo user;

    /**
     * 角色列表
     */
    private List<String> roles;

    /**
     * 权限列表
     */
    private List<String> permissions;

    /**
     * 菜单列表
     */
    private List<MenuItem> menus;

    /**
     * 用户信息内部类
     */
    @Data
    @Builder
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class UserInfo {
        /**
         * 用户ID
         */
        private String id;

        /**
         * 用户名（手机号）
         */
        private String username;

        /**
         * 昵称
         */
        private String nickname;

        /**
         * 岗位（员工档案，User 实体 position 字段；#3099 右上角用户卡片展示）
         */
        private String position;

        /**
         * 头像URL
         */
        private String avatar;

        /**
         * 租户ID
         */
        private Long tenantId;

        /**
         * 企业名称
         */
        private String tenantName;

        /**
         * 智能客服名称（TenantAiConfig.botName，C 端思考中/空态/导航名展示；未配置为 null → 前端兜底「小布」）
         */
        private String botName;

        /**
         * 企业 Logo（「企业基础信息」设置）
         */
        private String tenantLogo;

        /**
         * 状态
         */
        private String status;

        /**
         * 首登强制改密（issue #5485 不变式 I4）：前端靠它决定是否跳「首登改密」页。
         *
         * <p>⚠️ 本字段是 {@code GET /api/auth/me} 在**强制改密白名单**里的原因 ——
         * 会话被拦时前端要靠这次调用（它本身放行）判断该跳哪一页。</p>
         */
        private Boolean mustChangePassword;
    }

    /**
     * 菜单项内部类
     */
    @Data
    @Builder
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class MenuItem {
        /**
         * 菜单唯一标识
         */
        private String key;

        /**
         * 菜单名称
         */
        private String name;

        /**
         * 路由路径
         */
        private String path;

        /**
         * 子菜单
         */
        private List<MenuItem> children;
    }
}
