// case_ids: SP-004
package com.migao.admin.controller;

import com.migao.admin.security.RequirePermission;
import com.migao.admin.security.TenantOwnedResource;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;

import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 付款端点契约（issue #7369，P0-1 段 3-B）。
 *
 * <p>守三件不会自己报错的事：① 路由逐字（前端按这个路径调）；② 权限码用**既有**的
 * {@code finance:create} / {@code finance:view}（新造码今天没人持有 ⇒ 谁都点不动）；
 * ③ 作废端点标归属认定（跨租户 id ⇒ 404，与其余写端点同源）。</p>
 */
@DisplayName("付款端点契约：路由 + 权限码 + 归属认定")
class SupplierPaymentControllerTest {

    private static Method method(String name) {
        return Arrays.stream(SupplierPaymentController.class.getDeclaredMethods())
                .filter(m -> m.getName().equals(name))
                .findFirst()
                .orElseThrow(() -> new AssertionError("SupplierPaymentController 里没有方法 " + name));
    }

    private static String permissionOf(Method m) {
        RequirePermission p = m.getAnnotation(RequirePermission.class);
        assertThat(p).as("%s 必须声明 @RequirePermission", m.getName()).isNotNull();
        return p.value();
    }

    @Test
    @DisplayName("路由逐字：POST /api/admin/supplier-payments · POST /{id}/void · GET /api/admin/supplier-payments")
    void routesAreExactlyAsDeclared() {
        assertThat(method("create").getAnnotation(PostMapping.class).value())
                .containsExactly("/api/admin/supplier-payments");
        assertThat(method("voidPayment").getAnnotation(PostMapping.class).value())
                .containsExactly("/api/admin/supplier-payments/{id}/void");
        assertThat(method("list").getAnnotation(GetMapping.class).value())
                .containsExactly("/api/admin/supplier-payments");
    }

    @Test
    @DisplayName("权限码：写（登记/作废）用既有 finance:create；读用既有 finance:view")
    void permissionCodesReuseFinanceCodes() {
        assertThat(permissionOf(method("create"))).isEqualTo("finance:create");
        assertThat(permissionOf(method("voidPayment"))).isEqualTo("finance:create");
        assertThat(permissionOf(method("list"))).isEqualTo("finance:view");
    }

    @Test
    @DisplayName("归属认定：只给带 id 的作废端点标 @TenantOwnedResource(\"supplierPayment\")")
    void onlyVoidIsTenantOwned() {
        TenantOwnedResource owned = method("voidPayment").getAnnotation(TenantOwnedResource.class);
        assertThat(owned).isNotNull();
        assertThat(owned.value()).isEqualTo("supplierPayment");
        assertThat(method("create").getAnnotation(TenantOwnedResource.class)).isNull();
        assertThat(method("list").getAnnotation(TenantOwnedResource.class)).isNull();
    }

    @Test
    @DisplayName("端点面冻结：三个端点（新增必须同批补判据）")
    void controllerSurfaceIsFrozen() {
        List<String> mapping = Arrays.stream(SupplierPaymentController.class.getDeclaredMethods())
                .filter(m -> m.getAnnotation(GetMapping.class) != null
                        || m.getAnnotation(PostMapping.class) != null)
                .map(Method::getName)
                .sorted()
                .toList();
        assertThat(mapping).containsExactly("create", "list", "voidPayment");
    }
}
