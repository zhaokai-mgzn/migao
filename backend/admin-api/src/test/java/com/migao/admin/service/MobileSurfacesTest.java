// case_ids: BM-046, BM-047
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 手机端菜单的**服务端投影**（issue #6570，用户 2026-10-08 裁定「走 B」）。
 *
 * <p>判据口径：权限集合 → 可见面 = {@link MobileSurfaces#visibleFor}。期望值**逐字取自线上真账号读数**
 * （2026-10-08 20:09 +08，租户 25 四个岗位在 `/b/` 的「我的」页实拍）：客服 3 / 运营 4 / 商品管理员 2 / 财务 2。
 * ⇒ 本测试同时是「服务端投影 == 端侧旧口径的实际可见性」的等价性判据（零行为回归）。</p>
 *
 * <p>红证（怎么让它单独变红）：把某个面的 {@code readPermission} 改错一个字母 ⇒ 对应用例的键序列对不上。</p>
 */
class MobileSurfacesTest {

    /** 线上读数：tenant 25 / a06_customer_service（客服，12 码） */
    private static final List<String> CUSTOMER_SERVICE_CODES = List.of(
            "dashboard:view", "processing:view", "production:execute", "inbound:view", "knowledge:view",
            "order:list", "order:detail", "order:refund", "after_sales:view", "customer:view",
            "agent:session", "agent:session:manage");

    /** 线上读数：a06_product_manager（商品管理员，8 码） */
    private static final List<String> PRODUCT_MANAGER_CODES = List.of(
            "dashboard:view", "product:list", "product:create", "product:category", "product:category:view",
            "processing:manage", "processing:view", "production:view");

    /** 线上读数：a06_finance（财务，9 码） */
    private static final List<String> FINANCE_CODES = List.of(
            "dashboard:view", "processing:view", "production:execute", "inbound:view", "order:list",
            "order:detail", "customer:view", "finance:view", "finance:create");

    private static List<String> keys(List<String> permissions) {
        return MobileSurfaces.visibleFor(permissions).stream().map(MobileSurfaces.Surface::key).toList();
    }

    @Test
    @DisplayName("通配 `*`（管理员）⇒ 全部 5 项，顺序 = 清单声明顺序")
    void wildcardSeesEverything() {
        assertThat(keys(List.of("*"))).containsExactly(
                "pool", "inbound", "after-sales", "piecework", "production-todos");
    }

    @Test
    @DisplayName("🔴 客服（12 码，无 production:view）⇒ 智能派单/入库过账/售后处理 + 生产待办块**关**")
    void customerServiceMatchesLiveReading() {
        // 线上实拍：3 个入口；「数据」页那块「无权限查看生产待办」的噪音正是因为没有 production:view
        assertThat(keys(CUSTOMER_SERVICE_CODES)).containsExactly("pool", "inbound", "after-sales");
    }

    @Test
    @DisplayName("🔴 商品管理员（8 码）⇒ 智能派单 + 计件工资报表（+ 生产待办块开）")
    void productManagerMatchesLiveReading() {
        assertThat(keys(PRODUCT_MANAGER_CODES)).containsExactly("pool", "piecework", "production-todos");
    }

    @Test
    @DisplayName("🔴 财务（9 码）⇒ 智能派单 + 入库过账（无 production:view ⇒ 生产待办块关）")
    void financeMatchesLiveReading() {
        assertThat(keys(FINANCE_CODES)).containsExactly("pool", "inbound");
    }

    @Test
    @DisplayName("空集合 / null ⇒ 空清单（不是「全给」）")
    void emptyPermissionsYieldNothing() {
        assertThat(MobileSurfaces.visibleFor(List.of())).isEmpty();
        assertThat(MobileSurfaces.visibleFor(null)).isEmpty();
    }

    @Test
    @DisplayName("每个面的读码 = 后端注解的镜像（真值在 `@RequirePermission`）")
    void readPermissionsMirrorBackendAnnotations() {
        assertThat(MobileSurfaces.ALL).extracting(MobileSurfaces.Surface::key, MobileSurfaces.Surface::readPermission)
                .containsExactly(
                        org.assertj.core.groups.Tuple.tuple("pool", "processing:view"),
                        org.assertj.core.groups.Tuple.tuple("inbound", "inbound:view"),
                        org.assertj.core.groups.Tuple.tuple("after-sales", "after_sales:view"),
                        org.assertj.core.groups.Tuple.tuple("piecework", "production:view"),
                        org.assertj.core.groups.Tuple.tuple("production-todos", "production:view"));
    }

    @Test
    @DisplayName("只有 production-todos 没有独立页面（其余 4 个都有 bmini 路由）")
    void onlyProductionTodosHasNoRoute() {
        assertThat(MobileSurfaces.ALL).filteredOn(s -> s.route() == null)
                .extracting(MobileSurfaces.Surface::key).containsExactly("production-todos");
        assertThat(MobileSurfaces.ALL).filteredOn(s -> s.route() != null)
                .extracting(MobileSurfaces.Surface::route)
                .containsExactly(
                        "/pages/admin/pool/index",
                        "/pages/admin/inbound/index",
                        "/pages/admin/after-sales/index",
                        "/pages/admin/piecework/index");
    }

    // ══════════════════════════════════════════════════════════════════════
    // 底栏 tab（issue #6574，用户 2026-10-08 逐字「**1，按权限隐藏**」）
    // ══════════════════════════════════════════════════════════════════════

    private static List<String> tabKeys(List<String> permissions) {
        return MobileSurfaces.visibleTabsFor(permissions).stream().map(MobileSurfaces.Surface::key).toList();
    }

    @Test
    @DisplayName("🔴 商品管理员（8 码，无 agent:session）⇒ 底栏**没有**「坐席」")
    void productManagerHasNoSessionsTab() {
        // 线上实测（2026-10-08）：这一类岗位此前照样看到「坐席」（静态 4 项）
        assertThat(tabKeys(PRODUCT_MANAGER_CODES)).containsExactly("chat", "dashboard", "profile");
    }

    @Test
    @DisplayName("🔴 财务（9 码，无 agent:session）⇒ 底栏**没有**「坐席」")
    void financeHasNoSessionsTab() {
        assertThat(tabKeys(FINANCE_CODES)).containsExactly("chat", "dashboard", "profile");
    }

    @Test
    @DisplayName("客服（12 码，持 agent:session）⇒ 底栏 4 项齐全")
    void customerServiceHasAllTabs() {
        assertThat(tabKeys(CUSTOMER_SERVICE_CODES))
                .containsExactly("chat", "dashboard", "sessions", "profile");
    }

    @Test
    @DisplayName("一个码都没有的员工 ⇒ 仍看得见「问黄金策 / 我的」（无码项），看不到数据/坐席")
    void zeroCodesKeepsCodelessTabs() {
        assertThat(tabKeys(List.of())).containsExactly("chat", "profile");
    }

    @Test
    @DisplayName("通配 `*` ⇒ 4 项全给，顺序 = 清单声明顺序")
    void wildcardSeesAllTabs() {
        assertThat(tabKeys(List.of("*"))).containsExactly("chat", "dashboard", "sessions", "profile");
    }

    @Test
    @DisplayName("底栏两项的码 = 后端注解镜像（dashboard:view / agent:session），另两项**无码**（不是 `*`）")
    void tabCodesMirrorBackendAnnotations() {
        assertThat(MobileSurfaces.TABS)
                .extracting(MobileSurfaces.Surface::key, MobileSurfaces.Surface::readPermission)
                .containsExactly(
                        org.assertj.core.groups.Tuple.tuple("chat", null),
                        org.assertj.core.groups.Tuple.tuple("dashboard", "dashboard:view"),
                        org.assertj.core.groups.Tuple.tuple("sessions", "agent:session"),
                        org.assertj.core.groups.Tuple.tuple("profile", null));
    }

    @Test
    @DisplayName("底栏 4 项都有 bmini 路由（与 `app.config.ts` 的 tabBar 逐值比对在 jest 守卫里）")
    void tabsAllHaveRoutes() {
        assertThat(MobileSurfaces.TABS).extracting(MobileSurfaces.Surface::route)
                .containsExactly(
                        "/pages/chat/index/index",
                        "/pages/dashboard/index/index",
                        "/pages/sessions/index/index",
                        "/pages/profile/index/index");
    }
}
