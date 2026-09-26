package com.migao.admin.service;

import com.migao.admin.exception.BusinessException;

import java.util.Map;
import java.util.Set;

/**
 * 订单状态机（**唯一实现点**）：流转表 + 中文标签 + 合法流转断言（issue #5648）。
 *
 * <p><b>为什么必须是唯一实现点</b>：本单在状态机里加了 {@code packed}（打包态），
 * 而「工人打包 / 工人发货」是**第二条**消费者（{@code OrderShipmentService}）——
 * 若两条路各写一份流转表，迟早分叉成「工人能走的流转商家走不了」这类静默不一致。
 * {@link OrderService} 的两个既有静态字段改为**引用本类**（一行），
 * 既有调用点一字未动。</p>
 *
 * <h3>{@code packed} 的位置与口径（issue #5648 裁定，2026-09-26）</h3>
 * <p>用户逐字裁定：「**打包与发货都是工人的动作**」（与 d9「实际就是工人发货的」一致）
 * ⇒ {@code packed} 插在 {@code producing} 与 {@code shipped} 之间，由工人在 H5 推进。</p>
 *
 * <ul>
 *   <li><b>一步到底允许</b>：{@code confirmed → shipped} / {@code producing → shipped} 仍然保留
 *       —— 车间现实里小单不单独点「打包」，把打包做成硬前置会凭空多一步。但
 *       {@code OrderShipmentService} 在发货时**同事务补记** {@code packed_at}
 *       （「发出去的货必然已经被打包过」是物理事实），数据上不出现「跳过打包」的无痕形态。</li>
 *   <li><b>{@code packed} 的唯一出口是 {@code shipped}</b>：撤销打包**不在这张表里**。
 *       它是**具名动作**（{@code OrderShipmentService.unpack}，必带理由 + 留痕），走
 *       {@code transitionStatusAtomic} 但**不扩大本表** —— 否则商家侧
 *       {@code PUT /orders/{id}/status} 也能无理由地把已打包单一键退回生产，
 *       而那条路没有理由字段、留不下痕（涉责任面必须有痕）。</li>
 * </ul>
 */
public final class OrderStatusTransitions {

    /**
     * 合法的状态流转定义：key = 当前状态，value = 允许流转到的目标状态集合。
     *
     * <p>相对 issue #5648 之前**只多两个目标**：{@code confirmed → packed}、
     * {@code producing → packed}；以及新键 {@code packed → shipped}。
     * 其余五条逐字未改（回归判据在 {@code OrderStatusTransitionsTest}）。</p>
     */
    public static final Map<String, Set<String>> STATUS_TRANSITIONS = Map.of(
            "pending", Set.of("confirmed", "cancelled"),
            "confirmed", Set.of("producing", "packed", "shipped", "cancelled"),
            "producing", Set.of("packed", "shipped", "cancelled"),
            "packed", Set.of("shipped"),
            "shipped", Set.of("completed"),
            "completed", Set.of(),
            "cancelled", Set.of()
    );

    /** 订单状态 → 中文业务术语（错误消息用，直接展示给企业客户 ⇒ 必须中文）。 */
    public static final Map<String, String> ORDER_STATUS_LABELS = Map.of(
            "pending", "待付款",
            "confirmed", "已确认",
            "producing", "生产中",
            "packed", "已打包",
            "shipped", "已发货",
            "completed", "已完成",
            "cancelled", "已取消"
    );

    private OrderStatusTransitions() {
    }

    /** 状态值是否是状态机认识的状态（未知值一律拒绝，不做默认回落）。 */
    public static boolean isKnownStatus(String status) {
        return status != null && STATUS_TRANSITIONS.containsKey(status);
    }

    /** 状态的中文标签（未知值原样返回 —— 报错时至少能看见调用方传了什么）。 */
    public static String label(String status) {
        return ORDER_STATUS_LABELS.getOrDefault(status, status);
    }

    /**
     * 断言 {@code from → to} 是合法流转；非法一律抛 400（**不放过、不自动纠正**）。
     */
    public static void assertTransitionAllowed(String from, String to) {
        if (!isKnownStatus(to)) {
            throw BusinessException.validationError("无效的订单状态: " + label(to));
        }
        Set<String> allowed = STATUS_TRANSITIONS.getOrDefault(from, Set.of());
        if (!allowed.contains(to)) {
            throw BusinessException.validationError(
                    String.format("订单状态不允许从 [%s] 变更为 [%s]", label(from), label(to)));
        }
    }

    /** 从 {@code from} 出发的合法目标集合（只读；缺失状态返回空集）。 */
    public static Set<String> allowedTargets(String from) {
        return STATUS_TRANSITIONS.getOrDefault(from, Set.of());
    }
}
