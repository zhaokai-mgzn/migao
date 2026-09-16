// case_ids: PG-014

package com.migao.admin.controller;

import com.migao.admin.controller.agent.AgentOrderController;
import com.migao.admin.dto.agent.AgentOrderUpdateRequest;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestMapping;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 订单加工项不可变性 tripwire（issue #3352 决策 2026-09-12，选项 C「源头约束」）
 *
 * 背景：加工单快照在生成时固化；若订单加工项在生成后可被修改，快照会与订单漂移
 * → 新增的加工项没人做却仍可发货。业务决策：**源头约束**——加工项仅在创建订单时可写，
 * 创建后无任何修改通道；若将来要引入编辑入口，必须同时启用「发货守卫覆盖校验」（选项 B），
 * 届时本测试会失败，提醒作者同步评估守卫。
 */
@DisplayName("订单加工项不可变性 tripwire（决策 C）")
class OrderItemImmutabilityTest {

    private static final Set<String> MUTATING_VERBS = Set.of("PUT", "POST", "PATCH", "DELETE");

    private static String pathOf(Method m) {
        RequestMapping rm = m.getAnnotation(RequestMapping.class);
        if (m.isAnnotationPresent(PutMapping.class)) return join(m.getAnnotation(PutMapping.class).value());
        if (m.isAnnotationPresent(PostMapping.class)) return join(m.getAnnotation(PostMapping.class).value());
        if (m.isAnnotationPresent(PatchMapping.class)) return join(m.getAnnotation(PatchMapping.class).value());
        if (m.isAnnotationPresent(DeleteMapping.class)) return join(m.getAnnotation(DeleteMapping.class).value());
        if (rm != null) return join(rm.value());
        return null;
    }

    private static String join(String[] v) {
        return v.length == 0 ? "" : String.join(",", v);
    }

    private static boolean isMutating(Method m) {
        return m.isAnnotationPresent(PutMapping.class) || m.isAnnotationPresent(PostMapping.class)
                || m.isAnnotationPresent(PatchMapping.class) || m.isAnnotationPresent(DeleteMapping.class);
    }

    private void assertNoItemMutationEndpoint(Class<?> controller, String label) {
        List<String> offenders = Arrays.stream(controller.getDeclaredMethods())
                .filter(OrderItemImmutabilityTest::isMutating)
                .filter(m -> pathOf(m) != null && pathOf(m).toLowerCase().contains("item"))
                .map(m -> m.getName() + " -> " + pathOf(m))
                .collect(Collectors.toList());
        assertThat(offenders)
                .as("%s 不得暴露订单明细修改端点（决策 C：加工项仅创建时可写）；"
                        + "如确需新增编辑入口，必须同步启用发货守卫覆盖校验（选项 B）并更新 PG-014", label)
                .isEmpty();
    }

    @Test
    @DisplayName("商户端订单控制器：无明细修改端点（PUT/POST/PATCH/DELETE 路径不含 item）")
    void orderControllerHasNoItemMutationEndpoint() {
        assertNoItemMutationEndpoint(OrderController.class, "OrderController");
    }

    @Test
    @DisplayName("Agent 端订单控制器：无明细修改端点")
    void agentOrderControllerHasNoItemMutationEndpoint() {
        assertNoItemMutationEndpoint(AgentOrderController.class, "AgentOrderController");
    }

    @Test
    @DisplayName("Agent 改单 DTO 字段集固定：新增 items 类字段即失败（提醒评估守卫）")
    void agentUpdateRequestHasNoItemFields() {
        Set<String> fields = new TreeSet<>();
        for (Field f : AgentOrderUpdateRequest.class.getDeclaredFields()) {
            fields.add(f.getName());
        }
        assertThat(fields).containsExactly(
                "action", "cancelReason", "logisticsCompany", "refundAmount", "refundReason",
                "status", "trackingNumber");
        assertThat(fields).noneMatch(f -> f.toLowerCase().contains("item"));
    }
}
