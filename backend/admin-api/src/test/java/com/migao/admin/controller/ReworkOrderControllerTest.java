// case_ids: QC-002
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
 * 返工单端点契约（issue #7377 段 2）：路由逐字 + **写面不得新造权限码**。
 *
 * <p>踩过的坑（#4203 同族，采购单段 4-B）：新造 `after_sales:create` 这种「今天没有任何岗位持有」的码
 * 会让端点对所有人不可达 —— 全仓权限目录里只有 `after_sales:view`，所以写面必须复用既有写码
 * （`order:refund`，与售后处理同一码）。</p>
 */
@DisplayName("返工单端点契约：动作路由逐字 + 复用既有读写码")
class ReworkOrderControllerTest {

    private static Method method(String name) {
        return Arrays.stream(ReworkOrderController.class.getDeclaredMethods())
                .filter(m -> m.getName().equals(name))
                .findFirst()
                .orElseThrow(() -> new AssertionError("ReworkOrderController 里没有 " + name));
    }

    @Test
    @DisplayName("读面：列表 / 详情")
    void readRoutes() {
        assertThat(method("list").getAnnotation(GetMapping.class).value()).isEmpty();
        assertThat(method("detail").getAnnotation(GetMapping.class).value()).containsExactly("/{id}");
    }

    @Test
    @DisplayName("动作面：开单 / 开工 / 完成 / 取消，路由逐字")
    void actionRoutes() {
        assertThat(method("create").getAnnotation(PostMapping.class).value()).isEmpty();
        assertThat(method("start").getAnnotation(PostMapping.class).value()).containsExactly("/{id}/start");
        assertThat(method("complete").getAnnotation(PostMapping.class).value()).containsExactly("/{id}/complete");
        assertThat(method("cancel").getAnnotation(PostMapping.class).value()).containsExactly("/{id}/cancel");
    }

    @Test
    @DisplayName("🔴 权限码零 delta：读 `after_sales:view`、写 `order:refund`（不新造 after_sales:create）")
    void permissionCodesReuseExisting() {
        assertThat(method("list").getAnnotation(RequirePermission.class).value()).isEqualTo("after_sales:view");
        assertThat(method("detail").getAnnotation(RequirePermission.class).value()).isEqualTo("after_sales:view");
        for (String action : new String[]{"create", "start", "complete", "cancel"}) {
            assertThat(method(action).getAnnotation(RequirePermission.class).value())
                    .as("写面码：%s（新造码会让端点对所有人不可达）", action).isEqualTo("order:refund");
        }
    }

    @Test
    @DisplayName("完成面不接受客户端传售后状态（回写规则由服务端决定）")
    void completeDoesNotTakeStatus() {
        assertThat(method("complete").getParameterTypes())
                .containsExactly(String.class, java.util.Map.class);
    }
}
