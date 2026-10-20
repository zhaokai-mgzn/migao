// case_ids: AR-003
package com.migao.admin.controller;

import com.migao.admin.security.RequirePermission;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.bind.annotation.GetMapping;

import java.lang.reflect.Method;
import java.util.Arrays;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 订单毛利端点契约（issue #7371，P0-3 段 1）：路由逐字 + 读码来自类级 `finance:view`。
 *
 * <p>读端点带 `{orderId}` ⇒ 不覆写方法级码（继承类级 finance:view）；`TenantOwnedResource` 的读面
 * 由 `order` 资源键在写面已登记覆盖，读面的越权面是「按 id 查不到」——服务层 `selectById` 走租户插件。</p>
 */
@DisplayName("毛利端点契约：路由逐字 + 吃类级 finance:view")
class OrderMarginControllerTest {

    private static Method method() {
        return Arrays.stream(FinanceController.class.getDeclaredMethods())
                .filter(m -> m.getName().equals("orderMargin"))
                .findFirst()
                .orElseThrow(() -> new AssertionError("FinanceController 里没有 orderMargin"));
    }

    @Test
    @DisplayName("路由逐字：GET /orders/{orderId}/margin")
    void routeIsExact() {
        assertThat(method().getAnnotation(GetMapping.class).value())
                .containsExactly("/orders/{orderId}/margin");
    }

    @Test
    @DisplayName("不覆写方法级码 ⇒ 继承类级 finance:view（只读面不借写权）")
    void inheritsClassLevelReadCode() {
        assertThat(method().getAnnotation(RequirePermission.class)).isNull();
        assertThat(FinanceController.class.getAnnotation(RequirePermission.class).value())
                .isEqualTo("finance:view");
    }

    @Test
    @DisplayName("只有订单 id 一个入参（毛利是算出来的，不接受客户端传金额）")
    void takesOnlyOrderId() {
        assertThat(method().getParameterCount()).isEqualTo(1);
        assertThat(method().getParameters()[0].getType()).isEqualTo(String.class);
    }
}
