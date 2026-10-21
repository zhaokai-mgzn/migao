// case_ids: RPT-001
package com.migao.admin.controller;

import com.migao.admin.security.RequirePermission;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.bind.annotation.GetMapping;

import java.lang.reflect.Method;
import java.util.Arrays;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 报表端点契约（issue #7376 段 1）：只读 + 零授权 delta + 不接受客户端传范围。
 *
 * <p>最后一条是安全面：数据范围必须由服务端从角色配置解析（P0-4 同口径）；客户端若能传
 * 「给我看全公司」，那范围就形同虚设。</p>
 */
@DisplayName("报表端点契约：只读 / dashboard:view / 不接受客户端传范围")
class ReportControllerTest {

    private static Method orderMargins() {
        return Arrays.stream(ReportController.class.getDeclaredMethods())
                .filter(m -> m.getName().equals("orderMargins"))
                .findFirst()
                .orElseThrow(() -> new AssertionError("ReportController 里没有 orderMargins"));
    }

    @Test
    @DisplayName("路由逐字：GET /order-margins（类级前缀 /api/admin/reports）")
    void routeIsExact() {
        assertThat(orderMargins().getAnnotation(GetMapping.class).value()).containsExactly("/order-margins");
    }

    @Test
    @DisplayName("只读码：类级 dashboard:view，方法不覆写（报表与看板同域）")
    void usesExistingReadCode() {
        assertThat(orderMargins().getAnnotation(RequirePermission.class)).isNull();
        assertThat(ReportController.class.getAnnotation(RequirePermission.class).value())
                .isEqualTo("dashboard:view");
    }

    @Test
    @DisplayName("🔴 入参只有日期区间：数据范围由服务端解析，不接受客户端递交")
    void takesOnlyDateRange() {
        var names = Arrays.stream(orderMargins().getParameters())
                .map(p -> p.getName()).toList();
        assertThat(names).containsExactly("startDate", "endDate");
    }
}
