// case_ids: WH-001
package com.migao.admin.controller;

import com.migao.admin.security.RequirePermission;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;

import java.lang.reflect.Method;
import java.util.Arrays;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 多仓/调拨端点契约（issue #7373，P1-1 段 1）：路由逐字 + **零授权 delta**。
 *
 * <p>仓与库存同域 ⇒ 读面 `inbound:view`、写面 `inbound:create`（与既有入库/批次读面一致）。
 * 新造权限码会让现网种子岗位全体失效（本仓既有纪律）。</p>
 */
@DisplayName("多仓端点契约：路由逐字 + 沿用 inbound 读写码")
class WarehouseControllerTest {

    private static Method method(String name) {
        return Arrays.stream(WarehouseController.class.getDeclaredMethods())
                .filter(m -> m.getName().equals(name))
                .findFirst()
                .orElseThrow(() -> new AssertionError("WarehouseController 里没有 " + name));
    }

    @Test
    @DisplayName("路由逐字：仓列表/建仓 + 调拨/调拨详情")
    void routesAreExact() {
        assertThat(method("listWarehouses").getAnnotation(GetMapping.class).value()).containsExactly("/warehouses");
        assertThat(method("createWarehouse").getAnnotation(PostMapping.class).value()).containsExactly("/warehouses");
        assertThat(method("transfer").getAnnotation(PostMapping.class).value()).containsExactly("/stock-transfers");
        assertThat(method("viewTransfer").getAnnotation(GetMapping.class).value())
                .containsExactly("/stock-transfers/{id}");
    }

    @Test
    @DisplayName("权限码零 delta：读 inbound:view / 写 inbound:create")
    void permissionCodesReused() {
        assertThat(method("listWarehouses").getAnnotation(RequirePermission.class).value()).isEqualTo("inbound:view");
        assertThat(method("viewTransfer").getAnnotation(RequirePermission.class).value()).isEqualTo("inbound:view");
        assertThat(method("createWarehouse").getAnnotation(RequirePermission.class).value()).isEqualTo("inbound:create");
        assertThat(method("transfer").getAnnotation(RequirePermission.class).value()).isEqualTo("inbound:create");
    }

    @Test
    @DisplayName("调拨入参不接受「目标仓字符串」——只认仓库 id（文本改仓正是本段要治的形态）")
    void transferTakesWarehouseIds() {
        var types = Arrays.stream(method("transfer").getParameters()).map(p -> p.getType().getSimpleName()).toList();
        assertThat(types).containsExactly("StockTransferRequest");
        assertThat(method("transfer").getParameterCount()).isEqualTo(1);
    }
}
