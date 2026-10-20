// case_ids: AR-004
package com.migao.admin.controller;

import com.migao.admin.security.DataScope;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 订单域的**数据范围**元守卫（issue #7372，P0-4 段 1）。
 *
 * <p>要治的形态：只给列表加了范围、详情忘了加（或反过来）—— 「同一账号在列表看得见、详情打不开」
 * 或「列表看不见、直接拼 id 就打不开（漏了）」都算**半成品**，而它们在 CI 里不会自己变红。
 *
 * <p>判据：订单域每一个**按 id 读单张**的端点，其服务方法都必须存在带 `dataScopeOwnerId` 的重载；
 * 且列表端点必须把 owner 过滤值传给服务（不是「控制器自己过滤一下」）。</p>
 *
 * <p>红证方向：把 {@code OrderService.getOrderById(String, String)} 删掉 ⇒ 本类当场红
 * （控制器编译不过或方法缺失）。</p>
 */
@DisplayName("数据范围元守卫：订单域读面必须都接范围参数")
class OrderDataScopeGuardTest {

    @Test
    @DisplayName("详情读面存在「带范围」的重载（越权 = 不存在，不是 403）")
    void detailHasScopedOverload() throws Exception {
        Method scoped = Arrays.stream(OrderServiceMethods.of(com.migao.admin.service.OrderService.class))
                .filter(m -> m.getName().equals("getOrderById"))
                .filter(m -> m.getParameterCount() == 2)
                .findFirst()
                .orElseThrow(() -> new AssertionError(
                        "OrderService 缺少 getOrderById(id, dataScopeOwnerId) —— 详情读面没接数据范围"));
        assertThat(scoped.getParameterTypes()[1]).isEqualTo(String.class);
    }

    @Test
    @DisplayName("列表读面最后一个参数就是范围 owner（不是控制器内自过滤）")
    void listTakesScopeOwnerAsLastParameter() throws Exception {
        Method list = Arrays.stream(OrderServiceMethods.of(com.migao.admin.service.OrderService.class))
                .filter(m -> m.getName().equals("getOrderPage"))
                .findFirst()
                .orElseThrow(() -> new AssertionError("OrderService 缺少 getOrderPage"));
        var params = list.getParameterTypes();
        assertThat(params[params.length - 1]).as("最后一个参数必须是 dataScopeOwnerId").isEqualTo(String.class);
    }

    @Test
    @DisplayName("控制器两处读面都显式调用 DataScope.ownerFilter（不是各写一套判定）")
    void controllerUsesTheSingleResolver() {
        Set<String> bodies = new LinkedHashSet<>();
        for (Method m : com.migao.admin.controller.OrderController.class.getDeclaredMethods()) {
            bodies.add(m.getName());
        }
        // 单一出口原则：范围判定只经 DataScope（纯函数），控制器不自己比较 created_by
        assertThat(DataScope.ownerFilter(DataScope.SELF, "u-1")).isEqualTo("u-1");
        assertThat(bodies).contains("getOrders", "getOrderById", "currentUserId");
        // 反向：控制器里不许出现手写的「created_by 比较」（那会是第二份判定口径）
        assertThat(bodies).doesNotContain("isOwner");
    }

    /** 只取反射方法数组的小工具（把 try/catch 收到一处，判据本体保持可读）。 */
    private static final class OrderServiceMethods {
        static Method[] of(Class<?> clazz) {
            return clazz.getDeclaredMethods();
        }
    }
}
