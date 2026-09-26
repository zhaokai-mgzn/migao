// case_ids: OR-045, OR-052, PG-018
package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 发货前置守卫（issue #3340 本体，issue #5648 抽成单一实现点）。
 *
 * <p>红证方向：把 {@code isProcessingReadyForShip} 里的 {@code countCompletedByOrderId} 判断删掉
 * ⇒ {@link #processingOrderNotCompletedBlocksShip} 红（含加工项未完成也能发货 = 绕过加工环节，涉钱）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("发货前置守卫：含加工项必须有已完成加工单（唯一实现点）")
class OrderShipGuardTest {

    private static final Long TENANT = 1L;

    @Mock private OrderItemMapper orderItemMapper;
    @Mock private ProcessingOrderMapper processingOrderMapper;

    private final ObjectMapper objectMapper = new ObjectMapper();

    @BeforeAll
    static void initLambdaCache() {
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(
                new org.apache.ibatis.builder.MapperBuilderAssistant(
                        new com.baomidou.mybatisplus.core.MybatisConfiguration(), ""), OrderItem.class);
    }

    private Order order() {
        return Order.builder().id("o1").tenantId(TENANT).status("packed").build();
    }

    private void givenItems(OrderItem... items) {
        when(orderItemMapper.selectList(any())).thenReturn(new ArrayList<>(List.of(items)));
    }

    private OrderItem item(Object processingInfo) {
        return OrderItem.builder().id("i1").orderId("o1").tenantId(TENANT)
                .quantity(new BigDecimal("1")).processingInfo(processingInfo).deleted(0).build();
    }

    @Test
    @DisplayName("无加工项 ⇒ 允许发货（不查加工单）")
    void plainOrderIsReadyForShip() {
        givenItems(item(null));
        assertThat(OrderShipGuard.isProcessingReadyForShip(
                orderItemMapper, processingOrderMapper, objectMapper, order())).isTrue();
        assertThat(OrderShipGuard.hasProcessingItems(orderItemMapper, objectMapper, order())).isFalse();
    }

    @Test
    @DisplayName("🔴 含加工项且加工单未完成 ⇒ 拒绝发货（既有守卫不许被绕过）")
    void processingOrderNotCompletedBlocksShip() {
        givenItems(item(Map.of("processingItems", List.of(Map.of("id", "p1", "name", "韩褶-布")))));
        when(processingOrderMapper.countCompletedByOrderId("o1", TENANT)).thenReturn(0L);
        assertThat(OrderShipGuard.isProcessingReadyForShip(
                orderItemMapper, processingOrderMapper, objectMapper, order())).isFalse();
        assertThatThrownBy(() -> OrderShipGuard.assertProcessingCompletedBeforeShip(
                orderItemMapper, processingOrderMapper, objectMapper, order()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("须先完成加工单");
    }

    @Test
    @DisplayName("含加工项且加工单已完成 ⇒ 放行（守卫不是「含加工项就一律拒」）")
    void completedProcessingOrderAllowsShip() {
        givenItems(item(Map.of("processingItems", List.of(Map.of("id", "p1", "name", "韩褶-布")))));
        when(processingOrderMapper.countCompletedByOrderId("o1", TENANT)).thenReturn(1L);
        assertThat(OrderShipGuard.isProcessingReadyForShip(
                orderItemMapper, processingOrderMapper, objectMapper, order())).isTrue();
    }

    @Test
    @DisplayName("🔴 processing_info 是 JSON **字符串** 时也认得出来（JacksonTypeHandler 缺失的老坑）")
    void jsonStringProcessingInfoIsStillDetected() {
        givenItems(item("{\"processingItems\":[{\"id\":\"p1\",\"name\":\"韩褶-布\",\"quantity\":3}]}"));
        assertThat(OrderShipGuard.hasProcessingItems(orderItemMapper, objectMapper, order())).isTrue();
        assertThat(OrderShipGuard.extractProcessingItems(objectMapper,
                "{\"processingItems\":[{\"id\":\"p1\",\"name\":\"韩褶-布\",\"quantity\":8.4}]}"))
                .hasSize(1)
                .allSatisfy(b -> assertThat(b.getQuantity()).isEqualByComparingTo("8.4"));
    }

    @Test
    @DisplayName("空 JSONB 对象 / 非 Map / 坏 JSON ⇒ 判「无加工项」而不是抛异常（fail-soft 但留日志）")
    void malformedProcessingInfoIsTreatedAsNoProcessingItems() {
        assertThat(OrderShipGuard.extractProcessingItems(objectMapper, Map.of())).isEmpty();
        assertThat(OrderShipGuard.extractProcessingItems(objectMapper, "not json")).isEmpty();
        assertThat(OrderShipGuard.extractProcessingItems(objectMapper, 42)).isEmpty();
    }

    @Test
    @DisplayName("toBigDecimal：十进制解析（不经过 double 截断）")
    void toBigDecimalKeepsDecimalPrecision() {
        assertThat(OrderShipGuard.toBigDecimal("8.4")).isEqualByComparingTo("8.4");
        assertThat(OrderShipGuard.toBigDecimal(new BigDecimal("8.4"))).isEqualByComparingTo("8.4");
        assertThat(OrderShipGuard.toBigDecimal(8.4)).isEqualByComparingTo("8.4");
        assertThat(OrderShipGuard.toBigDecimal(null)).isNull();
        assertThat(OrderShipGuard.toBigDecimal("abc")).isNull();
    }
}
