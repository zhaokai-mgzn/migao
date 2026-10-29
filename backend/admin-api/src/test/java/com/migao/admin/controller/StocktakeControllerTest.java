// case_ids: STK-001
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
 * 盘点端点契约（issue #7373 段 2）：路由逐字 + 零授权 delta + 完成面不接受客户端传差异。
 *
 * <p>最后一条是安全面：差异由服务端按「实盘 − 账面」算，客户端若能把差异或调整量传进来，
 * 就等于绕过了审批闸门（审批金额按服务端算出的差异总额）。</p>
 */
@DisplayName("盘点端点契约：动作路由逐字 + 沿用 inbound 读写码")
class StocktakeControllerTest {

    private static Method method(String name) {
        return Arrays.stream(StocktakeController.class.getDeclaredMethods())
                .filter(m -> m.getName().equals(name))
                .findFirst()
                .orElseThrow(() -> new AssertionError("StocktakeController 里没有 " + name));
    }

    @Test
    @DisplayName("读面：列表 / 详情")
    void readRoutes() {
        assertThat(method("list").getAnnotation(GetMapping.class).value()).isEmpty();
        assertThat(method("detail").getAnnotation(GetMapping.class).value()).containsExactly("/{id}");
    }

    @Test
    @DisplayName("动作面：出任务 / 录实盘 / 完成 / 作废，路由逐字")
    void actionRoutes() {
        assertThat(method("open").getAnnotation(PostMapping.class).value()).isEmpty();
        assertThat(method("count").getAnnotation(PostMapping.class).value()).containsExactly("/{id}/count");
        assertThat(method("complete").getAnnotation(PostMapping.class).value()).containsExactly("/{id}/complete");
        assertThat(method("cancel").getAnnotation(PostMapping.class).value()).containsExactly("/{id}/cancel");
    }

    @Test
    @DisplayName("权限码：读 stock:view（issue #8087 拆码） / 写 inbound:create")
    void permissionCodes() {
        assertThat(method("list").getAnnotation(RequirePermission.class).value()).isEqualTo("stock:view");
        assertThat(method("detail").getAnnotation(RequirePermission.class).value()).isEqualTo("stock:view");
        for (String action : new String[]{"open", "count", "complete", "cancel"}) {
            assertThat(method(action).getAnnotation(RequirePermission.class).value())
                    .as("写面码：%s", action).isEqualTo("inbound:create");
        }
    }

    @Test
    @DisplayName("🔴 完成面只收盘点单 id（差异/调整量由服务端算，不许客户端递）")
    void completeTakesOnlyId() {
        assertThat(method("complete").getParameterCount()).isEqualTo(1);
        assertThat(method("complete").getParameterTypes()[0]).isEqualTo(String.class);
    }
}
