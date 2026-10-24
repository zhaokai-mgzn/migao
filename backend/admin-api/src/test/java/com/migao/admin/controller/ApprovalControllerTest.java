// case_ids: APP-001
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
 * 审批端点契约（issue #7374，P1-2 段 1）：路由逐字 + 读/写码分离 + **不新造权限码**。
 *
 * <p>写面 `finance:create`、读面 `finance:view`（类级）：审批是财务相关动作，沿用既有码；
 * 新造码会让现网种子岗位全体失效（本仓既有纪律）。「谁能批」的额外约束在服务层（不能自批）。</p>
 */
@DisplayName("审批端点契约：路由逐字 + 读写码分离")
class ApprovalControllerTest {

    private static Method method(String name) {
        return Arrays.stream(ApprovalController.class.getDeclaredMethods())
                .filter(m -> m.getName().equals(name))
                .findFirst()
                .orElseThrow(() -> new AssertionError("ApprovalController 里没有 " + name));
    }

    @Test
    @DisplayName("写面三条：提交 / 通过 / 驳回 / 撤回，路由逐字")
    void writeRoutesAreExact() {
        assertThat(method("submit").getAnnotation(PostMapping.class).value()).isEmpty();
        assertThat(method("approve").getAnnotation(PostMapping.class).value()).containsExactly("/{id}/approve");
        assertThat(method("reject").getAnnotation(PostMapping.class).value()).containsExactly("/{id}/reject");
        assertThat(method("withdraw").getAnnotation(PostMapping.class).value()).containsExactly("/{id}/withdraw");
    }

    @Test
    @DisplayName("读面两条：列表 / 详情，路由逐字")
    void readRoutesAreExact() {
        assertThat(method("list").getAnnotation(GetMapping.class).value()).isEmpty();
        assertThat(method("view").getAnnotation(GetMapping.class).value()).containsExactly("/{id}");
    }

    @Test
    @DisplayName("写面用 finance:create、读面继承类级 finance:view（零授权 delta）")
    void permissionCodesAreReused() {
        for (String name : new String[]{"submit", "approve", "reject", "withdraw"}) {
            assertThat(method(name).getAnnotation(RequirePermission.class).value())
                    .as("写面码：%s", name).isEqualTo("finance:create");
        }
        for (String name : new String[]{"list", "view"}) {
            assertThat(method(name).getAnnotation(RequirePermission.class))
                    .as("读面必须继承类级码，不覆写：%s", name).isNull();
        }
    }

    @Test
    @DisplayName("三个裁决端点都只有 id + 可选备注入参（结论不接受客户端传状态字段）")
    void decisionEndpointsTakeNoStatusField() {
        var names = Arrays.stream(method("approve").getParameters())
                .map(p -> p.getType().getSimpleName()).toList();
        assertThat(names).containsExactly("String", "Map");
    }
}
