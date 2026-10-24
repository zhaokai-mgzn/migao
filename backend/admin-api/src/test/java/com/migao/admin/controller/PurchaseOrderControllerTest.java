// case_ids: SP-005
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
 * 采购单端点契约（issue #7369 段 4）。
 *
 * <p>守三件不会自己报错的事：① 路由逐字；② 权限码复用**既有** {@code inbound:view} / {@code inbound:create}
 * （新造 {@code purchase:*} 今天没人持有 ⇒ 页面与菜单对所有人不可见）；③ 三个带 id 的写/读端点标归属认定。</p>
 */
@DisplayName("采购单端点契约：路由 + 权限码 + 归属认定")
class PurchaseOrderControllerTest {

    private static Method method(String name) {
        return Arrays.stream(PurchaseOrderController.class.getDeclaredMethods())
                .filter(m -> m.getName().equals(name))
                .findFirst()
                .orElseThrow(() -> new AssertionError("PurchaseOrderController 里没有方法 " + name));
    }

    private static String permissionOf(Method m) {
        RequirePermission p = m.getAnnotation(RequirePermission.class);
        assertThat(p).as("%s 必须声明 @RequirePermission", m.getName()).isNotNull();
        return p.value();
    }

    @Test
    @DisplayName("路由逐字：GET 列表 / GET 详情 / POST 建单 / POST 收货 / POST 关闭")
    void routesAreExactlyAsDeclared() {
        assertThat(method("list").getAnnotation(GetMapping.class).value())
                .containsExactly("/api/admin/purchase-orders");
        assertThat(method("detail").getAnnotation(GetMapping.class).value())
                .containsExactly("/api/admin/purchase-orders/{id}");
        assertThat(method("create").getAnnotation(PostMapping.class).value())
                .containsExactly("/api/admin/purchase-orders");
        assertThat(method("receive").getAnnotation(PostMapping.class).value())
                .containsExactly("/api/admin/purchase-orders/{id}/receive");
        assertThat(method("close").getAnnotation(PostMapping.class).value())
                .containsExactly("/api/admin/purchase-orders/{id}/close");
    }

    @Test
    @DisplayName("权限码：读用既有 inbound:view，写用既有 inbound:create（零授权 delta）")
    void permissionCodesReuseInboundCodes() {
        assertThat(permissionOf(method("list"))).isEqualTo("inbound:view");
        assertThat(permissionOf(method("detail"))).isEqualTo("inbound:view");
        assertThat(permissionOf(method("create"))).isEqualTo("inbound:create");
        assertThat(permissionOf(method("receive"))).isEqualTo("inbound:create");
        assertThat(permissionOf(method("close"))).isEqualTo("inbound:create");
    }

    @Test
    @DisplayName("归属认定：带 {id} 的三个端点标 @TenantOwnedResource(\"purchaseOrder\")，建单/列表不标")
    void idEndpointsAreTenantOwned() {
        for (String name : List.of("detail", "receive", "close")) {
            TenantOwnedResource owned = method(name).getAnnotation(TenantOwnedResource.class);
            assertThat(owned).as("%s 必须标归属认定", name).isNotNull();
            assertThat(owned.value()).isEqualTo("purchaseOrder");
        }
        assertThat(method("list").getAnnotation(TenantOwnedResource.class)).isNull();
        assertThat(method("create").getAnnotation(TenantOwnedResource.class)).isNull();
    }

    @Test
    @DisplayName("端点面冻结：五个端点（新增必须同批补判据）")
    void controllerSurfaceIsFrozen() {
        List<String> mapping = Arrays.stream(PurchaseOrderController.class.getDeclaredMethods())
                .filter(m -> m.getAnnotation(GetMapping.class) != null
                        || m.getAnnotation(PostMapping.class) != null)
                .map(Method::getName).sorted().toList();
        assertThat(mapping).containsExactly("close", "create", "detail", "list", "receive");
    }
}
