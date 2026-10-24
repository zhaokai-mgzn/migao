// case_ids: AR-004
package com.migao.admin.security;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 数据范围纯函数（issue #7372，P0-4 段 1）—— **取宽**与**越权=不存在**两条判据。
 *
 * <p>为什么单独考：范围算错的两种方向都很难被发现 ——
 * ① 算宽了（把 self 解析成 tenant）⇒ 业务员看见全公司订单，**没有任何报错**；
 * ② 算窄了（多给一个只读角色反而缩小可见面）⇒ 用户「多了权限却少了数据」，只会来吐槽。
 * 而越权对象若返回 403，等于告诉对方「这个 id 存在」—— 那是泄露。</p>
 *
 * <p>红证方向：把 {@link DataScope#resolve} 的「取宽」改成「取窄」 ⇒
 * {@link #anyTenantRoleWins} 当场红。</p>
 */
@DisplayName("数据范围：多角色取宽 / 无角色按宽 / owner 过滤值 / 越权=不存在")
class DataScopeTest {

    @Test
    @DisplayName("🔴 多角色取宽：只要有一个 tenant ⇒ 生效 tenant（多给只读角色不该缩小可见面）")
    void anyTenantRoleWins() {
        assertThat(DataScope.resolve(List.of("self", "tenant"))).isEqualTo(DataScope.TENANT);
        assertThat(DataScope.resolve(List.of("tenant", "self"))).isEqualTo(DataScope.TENANT);
        assertThat(DataScope.resolve(List.of("self", "self"))).isEqualTo(DataScope.SELF);
        assertThat(DataScope.resolve(List.of("self"))).isEqualTo(DataScope.SELF);
    }

    @Test
    @DisplayName("无角色 / null 取值 ⇒ 最宽（列有 DEFAULT tenant，null 只可能来自「没写进来」）")
    void missingConfigFallsBackToTenant() {
        assertThat(DataScope.resolve(List.of())).isEqualTo(DataScope.TENANT);
        assertThat(DataScope.resolve(null)).isEqualTo(DataScope.TENANT);
        assertThat(DataScope.resolve(java.util.Arrays.asList(null, "self"))).isEqualTo(DataScope.TENANT);
    }

    @Test
    @DisplayName("🔴 拼错的取值 ⇒ 按**最窄**（fail-closed：宁可少给数据，不可因拼写错误放开全公司）")
    void unknownValueNarrowsToSelf() {
        assertThat(DataScope.resolve(List.of("department"))).isEqualTo(DataScope.SELF);
        assertThat(DataScope.resolve(List.of("Department", "self"))).isEqualTo(DataScope.SELF);
    }

    @Test
    @DisplayName("owner 过滤值：self ⇒ 当前用户 id；tenant ⇒ null（不加限制）")
    void ownerFilterMatchesScope() {
        assertThat(DataScope.ownerFilter(DataScope.SELF, "u-1")).isEqualTo("u-1");
        assertThat(DataScope.ownerFilter(DataScope.TENANT, "u-1")).isNull();
        // self 但没有当前用户（内部服务路径）⇒ null（不构造一个恒不匹配的过滤）
        assertThat(DataScope.ownerFilter(DataScope.SELF, null)).isNull();
    }

    @Test
    @DisplayName("🔴 越权对象 = 不可见（详情面据此返回与「不存在」同一个 404，不泄露存在性）")
    void outOfScopeIsIndistinguishableFromMissing() {
        // tenant：全都可见
        assertThat(DataScope.visible(DataScope.TENANT, "someone-else", "u-1")).isTrue();
        assertThat(DataScope.visible(DataScope.TENANT, null, "u-1")).isTrue();
        // self：只有自己创建的可见
        assertThat(DataScope.visible(DataScope.SELF, "u-1", "u-1")).isTrue();
        assertThat(DataScope.visible(DataScope.SELF, "u-2", "u-1")).isFalse();
        // 无制单人（C 端自助单）在 self 范围下不可见 —— 它不是「我建的」
        assertThat(DataScope.visible(DataScope.SELF, null, "u-1")).isFalse();
        // 没有当前用户 ⇒ self 下一律不可见（fail-closed）
        assertThat(DataScope.visible(DataScope.SELF, "u-1", null)).isFalse();
    }

    @Test
    @DisplayName("两态常量是稳定标识（落库值与判据都按它）")
    void scopeCodesAreStable() {
        assertThat(DataScope.TENANT).isEqualTo("tenant");
        assertThat(DataScope.SELF).isEqualTo("self");
    }
}
