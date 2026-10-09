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
     * 手机端（bmini）可见面 —— **服务端按岗位投影**（issue #6570，用户 2026-10-08 裁定「走 B」）。
     *
     * <p>🔴 与 {@link #capabilities} 同一口径：**这是端侧唯一的判定来源**，端侧不得自己拿
     * {@link #permissions} 判菜单（旧口径 = 每个客户端各判一次码、且「集合未知 ⇒ 照显」，
     * 线上读数与形态见 issue #6570）。</p>
     * <p>空数组 = 服务端**明确答复**「本岗位一个面都没有」（这是正常答复）；
     * 端侧**拿不到**本字段时应显式说「菜单没加载出来 + 重试」，不许静默隐藏、也不许照显。</p>
     * <p>⚠️ 它只是 UI 显隐，不是授权：数据面仍由 {@code @RequirePermission}
     * 与 {@code PermissionInterceptor} 拦（既有架构契约，不砍）。</p>
     */
    private List<MobileSurface> mobileSurfaces;

    /**
     * 手机端（bmini）**底栏 tab** —— 同一个服务端投影（issue #6574，用户 2026-10-08 逐字「1，按权限隐藏」）。
     *
     * <p>为什么不能靠客户端过滤：{@code app.config.ts} 的 {@code tabBar} 是**构建期静态**的 4 项
     * （{@code setTabBarItem} 只能改文字/图标，不能删格；{@code hideTabBar} 只能整条收起）
     * ⇒ 没有 {@code agent:session} 的岗位照样看到「坐席」。端侧据本字段**自绘底栏**并把原生条收起。</p>
     * <p>空数组 = 服务端明确答复（正常答复，但当前清单里 `chat`/`profile` 是「无需任何码」⇒ 实际不会空）；
     * 端侧**拿不到**本字段时按「不隐藏功能」处置 —— **照显全部 tab**（与「数据」页待办块 error ⇒ 照渲染同规则）。</p>
     * <p>⚠️ 同样只是 UI 显隐：进页后的数据面仍由 {@code @RequirePermission} 拦。</p>
     */
    private List<MobileSurface> mobileTabs;

    /**
     * 手机端一个可见面 / 能力位（{@code MobileSurfaces.Surface} 的响应投影）。
     */
    @Data
    @Builder
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class MobileSurface {
        /** 稳定键（端侧按它取图标、写判据；**不按中文标题**） */
        private String key;

        /** 中文名（端侧直接渲染，不自造文案） */
        private String title;

        /** bmini 页面路由；**缺键** = 该面没有独立页面（只用来开/关页面内的一块内容） */
        private String route;
    }

    /**
     * 能力位（issue #5642 功能⑤「黄金策唤出授权门」）。
     *
     * <p>🔴 **这是端侧唯一的判定来源**：前端**不得**自己判权限码（哪些码算管理员是服务端
     * {@code AdminGate.ADMIN_PERMISSION_CODES} 的单一真值）⇒ 改一处即 h5 与 admin-web 两端同步。
     * <p>⚠️ 它只是**能力位（UI 显隐与文案）**，不是授权本身；数据面仍由 {@code @RequirePermission}
     * 与 {@code PermissionInterceptor} 拦（既有架构契约，不砍）。
     */
    private Capabilities capabilities;

    /**
     * 能力位内部类
     */
    @Data
    @Builder
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class Capabilities {
        /**
         * 能否唤出黄金策（{@code AdminGate.canSummonMibao}）。
         * {@code true} ⇒ 端侧进对话；{@code false} ⇒ 端侧必须给「需要管理员授权」+ 可行动引导
         * （**不是**静默隐藏入口、**不是** 403 白屏）。
         */
        private Boolean mibaoChat;

        /**
         * 本租户是否**启用智能客服**（{@code AdminGate.tenantUsesAiService}）——
         * 经营看板「AI 接待占比」等指标的**可插拔开关**。
         *
         * <p>{@code false} / 缺省 ⇒ 端侧**不渲染**这些指标卡（**不是**渲染成 0、**不是**空白占位）；
         * {@code true} ⇒ 正常渲染且数字取服务端字段。判定口径与未来改法见
         * {@link com.migao.admin.security.AdminGate#tenantUsesAiService}。</p>
         */
        private Boolean aiService;
    }

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
         * 智能客服名称（TenantAiConfig.botName，C 端思考中/空态/导航名展示；未配置为 null → 前端兜底「元元」）
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
