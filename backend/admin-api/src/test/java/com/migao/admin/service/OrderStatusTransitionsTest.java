// case_ids: OR-045, OR-046
package com.migao.admin.service;

import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 订单状态机（issue #5648）：加 {@code packed} 一态，**既有五条流转逐字不改**。
 *
 * <p>红证方向：把 {@code confirmed → packed} 删掉 ⇒ {@code packedEntersTheStateMachine} 红；
 * 把 {@code packed → producing} 加进表里 ⇒ {@code merchantPathCannotRevertPackedWithoutReason} 红
 * （那意味着商家侧无理由端点也能撤销打包 —— 涉责任的动作留不下痕）。</p>
 */
@DisplayName("订单状态机：packed 入表 + 既有流转不回归 + 撤销打包是具名动作")
class OrderStatusTransitionsTest {

    @Test
    @DisplayName("🔴 packed 入表：confirmed|producing → packed → shipped 可走")
    void packedEntersTheStateMachine() {
        OrderStatusTransitions.assertTransitionAllowed("confirmed", "packed");
        OrderStatusTransitions.assertTransitionAllowed("producing", "packed");
        OrderStatusTransitions.assertTransitionAllowed("packed", "shipped");
        assertThat(OrderStatusTransitions.label("packed")).isEqualTo("已打包");
        assertThat(OrderStatusTransitions.STATUS_TRANSITIONS).containsKey("packed");
    }

    @Test
    @DisplayName("🔴 非法流转仍被拒：pending → packed / shipped → packed / 未知状态")
    void illegalTransitionsAreRejected() {
        assertThatThrownBy(() -> OrderStatusTransitions.assertTransitionAllowed("pending", "packed"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("不允许");
        assertThatThrownBy(() -> OrderStatusTransitions.assertTransitionAllowed("shipped", "packed"))
                .isInstanceOf(BusinessException.class);
        assertThatThrownBy(() -> OrderStatusTransitions.assertTransitionAllowed("confirmed", "no_such"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("无效的订单状态");
    }

    @Test
    @DisplayName("🔴 撤销打包**不在**状态表里（否则商家无理由端点也能退回生产，留不下痕）")
    void merchantPathCannotRevertPackedWithoutReason() {
        assertThatThrownBy(() -> OrderStatusTransitions.assertTransitionAllowed("packed", "producing"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("不允许");
        // 反向护栏：packed → shipped 仍在（撤销打包**不是**为了绕开发货）
        OrderStatusTransitions.assertTransitionAllowed("packed", "shipped");
        assertThat(OrderStatusTransitions.allowedTargets("packed")).isEqualTo(Set.of("shipped"));
    }

    @Test
    @DisplayName("反向护栏：既有五条流转逐字未改")
    void existingTransitionsAreUnchanged() {
        assertThat(OrderStatusTransitions.allowedTargets("pending"))
                .isEqualTo(Set.of("confirmed", "cancelled"));
        assertThat(OrderStatusTransitions.allowedTargets("confirmed"))
                .isEqualTo(Set.of("producing", "packed", "shipped", "cancelled"));
        assertThat(OrderStatusTransitions.allowedTargets("producing"))
                .isEqualTo(Set.of("packed", "shipped", "cancelled"));
        assertThat(OrderStatusTransitions.allowedTargets("shipped")).isEqualTo(Set.of("completed"));
        assertThat(OrderStatusTransitions.allowedTargets("completed")).isEmpty();
        assertThat(OrderStatusTransitions.allowedTargets("cancelled")).isEmpty();
        // 标签：既有六条一字未改（英文枚举误传给企业客户曾是本仓踩过的坑）
        assertThat(OrderStatusTransitions.label("pending")).isEqualTo("待付款");
        assertThat(OrderStatusTransitions.label("producing")).isEqualTo("生产中");
        assertThat(OrderStatusTransitions.label("shipped")).isEqualTo("已发货");
        assertThat(OrderStatusTransitions.label("cancelled")).isEqualTo("已取消");
        assertThat(OrderStatusTransitions.label("no_such")).isEqualTo("no_such");
    }

    @Test
    @DisplayName("🔴 唯一实现点：OrderService 的流转表必须**就是**这一份（同一个对象）")
    void stateMachineHasASingleImplementation() throws Exception {
        java.lang.reflect.Field f = OrderService.class.getDeclaredField("STATUS_TRANSITIONS");
        f.setAccessible(true);
        assertThat(f.get(null)).isSameAs(OrderStatusTransitions.STATUS_TRANSITIONS);
        java.lang.reflect.Field l = OrderService.class.getDeclaredField("ORDER_STATUS_LABELS");
        l.setAccessible(true);
        assertThat(l.get(null)).isSameAs(OrderStatusTransitions.ORDER_STATUS_LABELS);
    }
}
