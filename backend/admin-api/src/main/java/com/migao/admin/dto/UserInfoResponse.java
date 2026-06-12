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
         * 状态
         */
        private String status;
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
         * 图标名称（Lucide 图标）
         */
        private String icon;

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
