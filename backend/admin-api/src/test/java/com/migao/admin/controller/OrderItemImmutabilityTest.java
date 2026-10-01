// case_ids: PG-014, OR-055

package com.migao.admin.controller;

import com.migao.admin.controller.agent.AgentOrderController;
import com.migao.admin.dto.agent.AgentOrderUpdateRequest;
import com.migao.admin.service.OrderShipGuard;
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
import java.util.Objects;
import java.util.Set;
import java.util.TreeSet;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 订单内容可编辑性 tripwire（原 issue #3352 决策 2026-09-12「选项 C」⇒ issue #5842 改判）。
 *
 * <h3>这条判据的来历（逐字保留改判前的原文，别把它当历史噪音）</h3>
 * <p>决策 C 当年写的是：加工项仅在创建订单时可写、创建后**无任何修改通道**；
 * <b>「若将来要引入编辑入口，必须同时启用『发货守卫覆盖校验』（选项 B），届时本测试会失败，
 * 提醒作者同步评估守卫。」</b></p>
 *
 * <h3>它今天为什么长这样（issue #5842，用户 2026-10-01 裁定）</h3>
 * <p>用户裁定「买家未付款的订单要允许修改」，范围 = 收货信息 + 商品明细（商品/数量/单价）+
 * 加工项 + 金额重算 ⇒ <b>那个"将来"到了</b>。按决策 C 自己写下的交接方式，本测试**改判**为
 * 「编辑通道存在 ⇒ 守卫必须存在」的形态，并且：</p>
 * <ul>
 *   <li><b>不是删掉</b>：判据仍然会红，只是红的条件从「出现编辑通道」换成
 *       「出现编辑通道**却**没有漂移守卫」/「编辑通道被撤掉」；</li>
 *   <li><b>不是放松</b>：原判据的两条（Agent 端无明细写端点、Agent 改单 DTO 字段集冻结）
 *       <b>一字未改</b>地留着 —— Agent 侧今天仍然没有内容编辑通道，那两条依旧是真绊线；</li>
 *   <li><b>守卫的"接线"不靠本文件判</b>：反射只能证明符号存在，证明不了它被调用。
 *       接线判据 = {@code com.migao.admin.service.OrderContentEditTest#shipPathEnforcesDriftGuard}
 *       （真走 {@code OrderService.updateOrderStatus(id, "shipped")}，漂移单必须被拦下）。</li>
 * </ul>
 *
 * <p>判据 1 的正向锚（"通道存在"）是**故意**的：谁撤掉编辑通道，也会红一次 —— 提醒他
 * 回来重估这一对（通道 / 守卫）是否还成立，而不是让 tripwire 悄悄退化成空断言。</p>
 */
@DisplayName("订单内容可编辑 tripwire（决策 C 改判：编辑通道 ⇒ 必须漂移守卫）")
class OrderItemImmutabilityTest {

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

    /**
     * 商户端订单控制器上**内容编辑**类的写端点（路径含 {@code content}：issue #5842 的
     * {@code PUT /orders/{id}/content}）。
     */
    private static List<String> contentEditEndpoints() {
        return Arrays.stream(OrderController.class.getDeclaredMethods())
                .filter(OrderItemImmutabilityTest::isMutating)
                .map(OrderItemImmutabilityTest::pathOf)
                .filter(Objects::nonNull)
                .filter(path -> path.toLowerCase().contains("content"))
                .collect(Collectors.toList());
    }

    @Test
    @DisplayName("① 编辑通道存在（正向锚）：撤掉通道即红 —— 提醒同步重估「通道 / 守卫」这一对")
    void contentEditChannelExists() {
        assertThat(contentEditEndpoints())
                .as("订单详情页的「编辑」入口需要一条内容编辑通道（issue #5842：PUT /orders/{id}/content）。"
                        + "通道被撤掉时本判据变红：请连同下面那条守卫判据一起重估，"
                        + "而不是让 tripwire 静默退化成空断言")
                .isNotEmpty();
    }

    @Test
    @DisplayName("② 编辑通道 ⇒ 必须存在漂移守卫（守卫被删而通道仍在 ⇒ 红）")
    void editChannelRequiresDriftGuard() {
        List<String> channels = contentEditEndpoints();
        assertThat(channels)
                .as("前置：编辑通道存在（见判据 ①）")
                .isNotEmpty();

        Set<String> guardMethods = Arrays.stream(OrderShipGuard.class.getDeclaredMethods())
                .map(Method::getName)
                .collect(Collectors.toSet());
        assertThat(guardMethods)
                .as("存在订单内容编辑通道 %s ⇒ 必须同时存在「加工单快照 vs 订单加工项漂移」的**发货守卫覆盖校验**"
                        + "（#3352 决策 C 逐字交接的选项 B）。守卫缺失/改名而通道仍在时，本判据变红；"
                        + "接线判据 = com.migao.admin.service.OrderContentEditTest#shipPathEnforcesDriftGuard",
                        channels)
                .contains("hasProcessingDrift", "assertProcessingCompletedBeforeShip");
    }

    @Test
    @DisplayName("Agent 端订单控制器：仍无内容编辑端点（Agent 侧今天没有编辑通道）")
    void agentOrderControllerHasNoContentEditEndpoint() {
        List<String> offenders = Arrays.stream(AgentOrderController.class.getDeclaredMethods())
                .filter(OrderItemImmutabilityTest::isMutating)
                .map(OrderItemImmutabilityTest::pathOf)
                .filter(Objects::nonNull)
                .filter(path -> {
                    String lower = path.toLowerCase();
                    return lower.contains("content") || lower.contains("item");
                })
                .collect(Collectors.toList());
        assertThat(offenders)
                .as("AgentOrderController 不得暴露订单明细/内容修改端点（决策 C；商家改单入口在 admin-web，"
                        + "Agent 若要开必须同步评估发货守卫覆盖校验并更新 PG-014）")
                .isEmpty();
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
