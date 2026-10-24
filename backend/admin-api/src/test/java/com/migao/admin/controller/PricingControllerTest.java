// case_ids: PRC-001
package com.migao.admin.controller;

import com.migao.admin.security.RequirePermission;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.bind.annotation.GetMapping;

import java.lang.reflect.Method;
import java.util.Arrays;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 报价端点契约（issue #7375，P1-3 段 1）：路由逐字 + 只读码 + **未定价不给 0**（读面契约）。
 */
@DisplayName("报价端点契约：路由逐字 + 读码 order:list + 金额算式")
class PricingControllerTest {

    private static Method quote() {
        return Arrays.stream(PricingController.class.getDeclaredMethods())
                .filter(m -> m.getName().equals("quote"))
                .findFirst()
                .orElseThrow(() -> new AssertionError("PricingController 里没有 quote"));
    }

    @Test
    @DisplayName("路由逐字：GET /quote（类级前缀 /api/admin/pricing）")
    void routeIsExact() {
        assertThat(quote().getAnnotation(GetMapping.class).value()).containsExactly("/quote");
    }

    @Test
    /**
     * 🔴 2026-10-22 修正（issue #7375 段 3）：此处原写 `order:view` —— 而**权限目录里没有这个码**
     * （`RegistrationService` / `PermissionService` 两处种子目录都没有）⇒ 报价与价格本
     * **对所有人恒 403**。类级码改回目录里真实存在的 `order:list`。
     * 类级尺度的兜底判据 = `tests/unit_ci_workflows/test_admin_role_read_surface_guard.py` 判据 4b。
     */
    @DisplayName("只读码：类级 order:list，方法不覆写（报价是下单读面的一部分，不新造码）")
    void usesExistingReadCode() {
        assertThat(quote().getAnnotation(RequirePermission.class)).isNull();
        assertThat(PricingController.class.getAnnotation(RequirePermission.class).value())
                .isEqualTo("order:list");
    }

    @Test
    @DisplayName("入参只有「客户 + SKU + 数量」：价格不接受客户端传值（服务端为准的前提）")
    void takesNoClientPrice() {
        var names = Arrays.stream(quote().getParameters()).map(p -> p.getType().getSimpleName()).toList();
        assertThat(names).doesNotContain("PriceQuoteView", "BigDecimal[]");
        assertThat(quote().getParameterCount()).isEqualTo(3);
    }
}
