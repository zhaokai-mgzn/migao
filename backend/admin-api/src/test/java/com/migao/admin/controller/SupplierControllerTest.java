// case_ids: SP-001
package com.migao.admin.controller;

import com.migao.admin.entity.Supplier;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.security.TenantOwnedResource;
import com.migao.admin.service.SupplierService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;

import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 供应商端点契约（issue #7369，P0-1 段 1）。
 *
 * <p>守三件**不会自己报错**的事：
 * <ol>
 *   <li><b>路由</b>：三条端点的动词 + 路径逐字（前端 `supplierApi` 与菜单锚点都按这个路径）；
 *   <li><b>权限码</b>：读 = `inbound:view`、写 = `inbound:create` —— 与菜单节点码 / RBAC 清单
 *       / `AUTHORIZATION_CENSUS` 逐字同码（不新造 `supplier:*`，否则菜单对所有人不可见）；</li>
 *   <li><b>归属认定</b>：`PUT /{id}` 必须标 `@TenantOwnedResource("supplier")`（#6158/#6167），
 *       读端点**不该**标（没有 id 归属可言）。</li>
 * </ol>
 * 红证方向：把 PUT 的注解摘掉 ⇒ `ServiceLayerValidatedWriteEndpointGuardTest` 与本类同时红。
 */
@DisplayName("供应商端点契约：路由 + 权限码 + 归属认定")
class SupplierControllerTest {

    private static Method method(String name) {
        return Arrays.stream(SupplierController.class.getDeclaredMethods())
                .filter(m -> m.getName().equals(name))
                .findFirst()
                .orElseThrow(() -> new AssertionError("SupplierController 里没有方法 " + name));
    }

    private static String permissionOf(Method m) {
        RequirePermission p = m.getAnnotation(RequirePermission.class);
        assertThat(p).as("%s 必须声明 @RequirePermission（无注解 = 对全部商户员工开放）", m.getName()).isNotNull();
        return p.value();
    }

    @Test
    @DisplayName("路由逐字：GET /api/admin/suppliers · POST /api/admin/suppliers · PUT /api/admin/suppliers/{id}")
    void routesAreExactlyAsDeclared() {
        assertThat(method("list").getAnnotation(GetMapping.class).value())
                .containsExactly("/api/admin/suppliers");
        assertThat(method("create").getAnnotation(PostMapping.class).value())
                .containsExactly("/api/admin/suppliers");
        assertThat(method("update").getAnnotation(PutMapping.class).value())
                .containsExactly("/api/admin/suppliers/{id}");
    }

    @Test
    @DisplayName("权限码：读面 inbound:view / 写面 inbound:create（与菜单节点码、RBAC 清单逐字同码）")
    void permissionCodesAreTheInboundOnes() {
        assertThat(permissionOf(method("list"))).isEqualTo("inbound:view");
        assertThat(permissionOf(method("create"))).isEqualTo("inbound:create");
        assertThat(permissionOf(method("update"))).isEqualTo("inbound:create");
    }

    @Test
    @DisplayName("归属认定：写端点标 @TenantOwnedResource(\"supplier\")，读端点不标")
    void writeEndpointIsTenantOwned() {
        TenantOwnedResource owned = method("update").getAnnotation(TenantOwnedResource.class);
        assertThat(owned).as("PUT 必须标 @TenantOwnedResource（#6158/#6167）").isNotNull();
        assertThat(owned.value()).isEqualTo("supplier");

        assertThat(method("list").getAnnotation(TenantOwnedResource.class)).isNull();
        assertThat(method("create").getAnnotation(TenantOwnedResource.class)).isNull();
    }

    @Test
    @DisplayName("控制器端点面冻结：列表 / 建档 / 更新 / 待指派（新增端点必须同批补判据，不许悄悄长出口）")
    void controllerSurfaceIsFrozen() {
        List<String> mappingMethods = Arrays.stream(SupplierController.class.getDeclaredMethods())
                .filter(m -> m.getAnnotation(GetMapping.class) != null
                        || m.getAnnotation(PostMapping.class) != null
                        || m.getAnnotation(PutMapping.class) != null)
                .map(Method::getName)
                .sorted()
                .toList();
        // 待指派清单（issue #7369 段 2）：A 口径「不猜」的人工出口，读码与列表同码
        assertThat(mappingMethods)
                .containsExactly("create", "list", "payables", "unassignedInbound", "update");
    }

    @Test
    @DisplayName("待指派端点：GET /api/admin/suppliers/unassigned-inbound + 读码 inbound:view（无 id ⇒ 不标归属）")
    void unassignedEndpointContract() {
        java.lang.reflect.Method m = method("unassignedInbound");
        assertThat(m.getAnnotation(GetMapping.class).value())
                .containsExactly("/api/admin/suppliers/unassigned-inbound");
        assertThat(permissionOf(m)).isEqualTo("inbound:view");
        assertThat(m.getAnnotation(TenantOwnedResource.class)).isNull();
    }

    @Test
    @DisplayName("应付对账端点：GET /api/admin/suppliers/payables + 读码 inbound:view（金额不新增暴露面）")
    void payablesEndpointContract() {
        java.lang.reflect.Method m = method("payables");
        assertThat(m.getAnnotation(GetMapping.class).value())
                .containsExactly("/api/admin/suppliers/payables");
        assertThat(permissionOf(m)).isEqualTo("inbound:view");
        assertThat(m.getAnnotation(TenantOwnedResource.class)).isNull();
    }

    @Test
    @DisplayName("请求体/响应体就是实体本身（没有中间 DTO ⇒ 不存在第二套字段口径）")
    void requestsUseTheEntityDirectly() {
        assertThat(method("create").getParameterTypes()).contains(Supplier.class);
        assertThat(method("update").getParameterTypes())
                .contains(String.class, Supplier.class);
        assertThat(SupplierService.class).isNotNull();
    }
}
