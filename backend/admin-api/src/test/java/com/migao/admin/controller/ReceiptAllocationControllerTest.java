// case_ids: AR-002
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
 * 核销端点契约（issue #7370，P0-2 段 3）。
 *
 * <p>守三件不会自己报错的事：① 路由逐字（前端与手机端都按它取数）；② 读用 `finance:view`、
 * 写用 `finance:create`（**既有码**，零授权 delta；写面若沿用类级读码 = 「能看账 = 能记账」，
 * 那正是 issue #5246 修掉的形态）；③ 写端点带路径 id ⇒ 必须标归属认定（越权面）。</p>
 */
@DisplayName("核销端点契约：路由逐字 + 读/写码分离 + 写面归属认定")
class ReceiptAllocationControllerTest {

    private static Method method(String name) {
        return Arrays.stream(FinanceController.class.getDeclaredMethods())
                .filter(m -> m.getName().equals(name))
                .findFirst()
                .orElseThrow(() -> new AssertionError("FinanceController 里没有 " + name));
    }

    @Test
    @DisplayName("写：POST /receipts/{transactionId}/allocations + finance:create")
    void allocateRouteAndPermission() {
        Method m = method("allocateReceipt");
        assertThat(m.getAnnotation(PostMapping.class).value())
                .containsExactly("/receipts/{transactionId}/allocations");
        assertThat(m.getAnnotation(RequirePermission.class)).isNotNull();
        assertThat(m.getAnnotation(RequirePermission.class).value()).isEqualTo("finance:create");
    }

    @Test
    @DisplayName("读：GET /receipts/{transactionId}/allocations，不覆写码 ⇒ 吃类级 finance:view")
    void readRouteUsesClassLevelViewCode() {
        Method m = method("receiptAllocations");
        assertThat(m.getAnnotation(GetMapping.class).value())
                .containsExactly("/receipts/{transactionId}/allocations");
        assertThat(m.getAnnotation(RequirePermission.class))
                .as("读面不声明方法级码 ⇒ 继承类级 finance:view（写面才用 finance:create）")
                .isNull();
        assertThat(FinanceController.class.getAnnotation(RequirePermission.class).value())
                .isEqualTo("finance:view");
    }

    @Test
    @DisplayName("写端点带路径 id ⇒ 必须标归属认定（越权面由 TenantOwnedResource 声明）")
    void writeEndpointDeclaresOwnership() {
        assertThat(method("allocateReceipt")
                .getAnnotation(com.migao.admin.security.TenantOwnedResource.class))
                .as("带 {transactionId} 的写端点必须声明归属认定，否则越权面无人认领")
                .isNotNull();
    }
}
