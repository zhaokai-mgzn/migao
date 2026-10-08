package com.migao.admin.service;

import java.util.List;

/**
 * 手机端（bmini H5 / 小程序）菜单的**服务端投影** —— issue #6570（用户 2026-10-08 裁定「走 B」）。
 *
 * <h2>治的形态</h2>
 * 「菜单按岗位隔离不干净」的现状（issue #6570 的线上读数，租户 25 四个岗位真账号）：菜单可见性由
 * **每个客户端各自**拿 {@code GET /api/auth/me} 的 {@code permissions} 再各自判码得出 —— bmini 侧那份
 * 判定在 {@code src/utils/adminPermission.ts}（后端注解的镜像，守卫 BM-009 判据 5 逐值比对）。后果两条：
 * ① **未知即照显**（fail-open）：`/me` 拉失败 ⇒ 员工看到自己没有的入口，点进去逐项 403；
 * ② 判定散在客户端 ⇒ 改口径要改每一端。
 *
 * <h2>本类是什么</h2>
 * 一张**服务端**的「手机端可见面」清单 + 按生效权限集合过滤的**唯一实现**。{@code AuthService} 把它投影进
 * {@code GET /api/auth/me} 的 {@code mobileSurfaces}，端侧**只渲染服务端给的面**，不再自己判码。
 *
 * <h2>边界（不许越界）</h2>
 * ① 它**不是授权**：数据面仍由 {@code @RequirePermission} + {@code PermissionInterceptor} 拦（既有契约不砍）；
 * 本类只决定「手机端显示哪些入口/块」。
 * ② 每个面的 {@code readPermission} 与各 Controller 的 {@code @RequirePermission} **逐值相等**
 * （真值仍在注解；判据 = {@code frontend/bmini-app/tests/admin-surfaces-guard.test.ts} 与
 * {@code admin-surfaces-permission.test.tsx} 的逐值比对，改一处不改另一处即红）。
 * ③ {@code route != null} 的面必须在 bmini 的 {@code app.config.ts} 在册、且登记进入口台账
 * （{@code src/utils/pageEntries.ts}）—— 同一条判据守着（未登记即红）。
 * ④ {@code route == null} = **没有独立页面**的能力位（只用来开/关页面内的一块内容），当前只有一个：
 * {@code production-todos}（「数据」页的生产待办块）。
 */
public final class MobileSurfaces {

    /**
     * 手机端一个可见面 / 能力位。
     *
     * @param key            稳定键（端侧的图标表与判据都按它取，**不按中文标题**）
     * @param title          中文名（端侧直接渲染，不再自造文案）
     * @param route          bmini 页面路由；{@code null} = 无独立页面（能力位）
     * @param readPermission 「能读这一面」的权限码（后端注解的逐字镜像）
     */
    public record Surface(String key, String title, String route, String readPermission) {
    }

    /** 清单（顺序 = 端侧渲染顺序）。 */
    public static final List<Surface> ALL = List.of(
            new Surface("pool", "智能派单", "/pages/admin/pool/index", "processing:view"),
            new Surface("inbound", "入库过账", "/pages/admin/inbound/index", "inbound:view"),
            new Surface("after-sales", "售后处理", "/pages/admin/after-sales/index", "after_sales:view"),
            new Surface("piecework", "计件工资报表", "/pages/admin/piecework/index", "production:view"),
            // route == null：没有独立页面 —— 「数据」页的生产待办块按它开/关（缺码的岗位不该看到一块
            // 「无权限查看生产待办」的噪音；现状读数见 issue #6570 的客服/财务两行）。
            new Surface("production-todos", "生产待办", null, "production:view"),);

    private MobileSurfaces() {
    }

    /**
     * 生效权限集合 → 可见面（**唯一过滤实现**）。
     *
     * <p>{@code "*"} 是服务端给管理员的通配标记（{@code RoleService} 口径）⇒ 全给；
     * {@code null}/空集合 ⇒ **空清单**（调用方是「服务端不知道权限」，不是「员工没有权限」；
     * 两条路径在 {@code AuthService} 里不会混：{@code getCurrentUser} 拿不到权限集合会抛异常）。</p>
     */
    public static List<Surface> visibleFor(List<String> permissions) {
        if (permissions == null || permissions.isEmpty()) {
            return List.of();
        }
        boolean wildcard = permissions.contains("*");
        return ALL.stream()
                .filter(surface -> wildcard || permissions.contains(surface.readPermission()))
                .toList();
    }
}
