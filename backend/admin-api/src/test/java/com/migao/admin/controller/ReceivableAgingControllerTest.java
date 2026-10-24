// case_ids: AR-001
package com.migao.admin.controller;

import com.migao.admin.security.RequirePermission;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.bind.annotation.GetMapping;

import java.lang.reflect.Method;
import java.util.Arrays;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 应收账龄端点契约（issue #7370，P0-2 段 2）。
 *
 * <p>守三件不会自己报错的事：① 路由逐字（前端与黄金策都按它取数）；② 权限码复用**既有** {@code customer:view}
 * （不新造 {@code credit:view} —— 新码今天没人持有 ⇒ 页面对所有人不可见，#4203 同族坑）；
 * ③ 读端点**不加** {@code @TenantOwnedResource}（它没有路径 id，租户隔离由 TenantContext + RLS 承担）。</p>
 */
@DisplayName("应收账龄端点契约：路由 + 权限码 + 无 id 不标归属认定")
class ReceivableAgingControllerTest {

    private static Method method() {
        return Arrays.stream(CustomerController.class.getDeclaredMethods())
                .filter(m -> m.getName().equals("receivableAging"))
                .findFirst()
                .orElseThrow(() -> new AssertionError("CustomerController 里没有 receivableAging"));
    }

    @Test
    @DisplayName("路由逐字：GET /api/admin/customers/receivable-aging")
    void routeIsExact() {
        assertThat(method().getAnnotation(GetMapping.class).value())
                .containsExactly("/api/admin/customers/receivable-aging");
    }

    @Test
    @DisplayName("权限码 = 既有 customer:view（零授权 delta）")
    void permissionReusesCustomerView() {
        RequirePermission permission = method().getAnnotation(RequirePermission.class);
        assertThat(permission).as("必须声明 @RequirePermission").isNotNull();
        assertThat(permission.value()).isEqualTo("customer:view");
    }

    @Test
    @DisplayName("不带 id ⇒ 不标归属认定（越权面由 TenantContext + RLS 承担）")
    void noIdEndpointIsNotTenantOwned() {
        assertThat(method().getAnnotation(com.migao.admin.security.TenantOwnedResource.class)).isNull();
        assertThat(method().getParameterCount()).isZero();
    }
}
