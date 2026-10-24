// case_ids: OR-045, PG-018, PG-020, PG-088
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
 *
 * <p>issue #7079 追加：卖布单（{@code saleForm=布料}、**无加工项**）也算「有需要报工的作业」
 * ⇒ 必须先完成出库作业单的裁剪/打包报工。红证方向：
 * 把 {@code isProcessingReadyForShip} 里的判据退回 {@code hasProcessingItems}（或让
 * {@code hasFabricSaleLine} 恒返回 {@code false}）⇒ {@link #fabricSaleOrderWithoutCompletedWorkOrderBlocksShip}
 * 与 {@link #jsonStringFabricSaleInfoIsStillDetected} 红（卖布单一道工序没报工也能发货 = 工人计件丢钱）；</p>
 *
 * <p>反向护栏（本单**不许误伤**）：{@link #plainOrderWithoutProcessingItemsIsStillReadyForShip}
 * —— 非卖布的普通无加工项订单（配件 / 赠品行）必须**仍可直发**，
 * 把 {@code needsWork} 改成「一律 true」或让「无加工项 ⇒ 拦」都会让它红。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("发货前置守卫：含加工项或有卖布行 ⇒ 必须有已完成的出库作业单（唯一实现点）")
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

    /** 卖布行：按米卖布 ⇒ 行上**天然没有** {@code processingItems}，只有 {@code saleForm=布料}。 */
    private OrderItem fabricItem(Object processingInfo) {
        return OrderItem.builder().id("i-fabric").orderId("o1").tenantId(TENANT)
                .quantity(new BigDecimal("12")).processingInfo(processingInfo).deleted(0).build();
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

    // ──────────────────────────── issue #7079：卖布单（无加工项，但仍有裁剪/打包报工） ────────────────────────────

    @Test
    @DisplayName("🔴 卖布单无已完成作业单 ⇒ 拒绝发货（按米卖布没有加工项，但工人报了裁剪+打包的工）")
    void fabricSaleOrderWithoutCompletedWorkOrderBlocksShip() {
        givenItems(fabricItem(Map.of("saleForm", "布料")));
        when(processingOrderMapper.countCompletedByOrderId("o1", TENANT)).thenReturn(0L);

        // 前置自断言：这单**没有**加工项（否则下面证明不了「卖布行也让它需要报工」这件事）
        assertThat(OrderShipGuard.hasProcessingItems(orderItemMapper, objectMapper, order())).isFalse();
        assertThat(OrderShipGuard.hasFabricSaleLine(orderItemMapper, objectMapper, order())).isTrue();
        assertThat(OrderShipGuard.isProcessingReadyForShip(
                orderItemMapper, processingOrderMapper, objectMapper, order())).isFalse();
        assertThatThrownBy(() -> OrderShipGuard.assertProcessingCompletedBeforeShip(
                orderItemMapper, processingOrderMapper, objectMapper, order()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("出库作业单")
                .hasMessageContaining("裁剪")
                .hasMessageContaining("打包");
    }

    @Test
    @DisplayName("卖布单作业单已完成 ⇒ 放行（判据不是「卖布单一律拒」）")
    void completedWorkOrderAllowsFabricSaleShip() {
        givenItems(fabricItem(Map.of("saleForm", "布料")));
        when(processingOrderMapper.countCompletedByOrderId("o1", TENANT)).thenReturn(1L);
        assertThat(OrderShipGuard.isProcessingReadyForShip(
                orderItemMapper, processingOrderMapper, objectMapper, order())).isTrue();
    }

    @Test
    @DisplayName("🔴 反向护栏：非卖布的普通无加工项订单（配件 / 赠品行）**仍可直发**")
    void plainOrderWithoutProcessingItemsIsStillReadyForShip() {
        givenItems(item(Map.of()));

        assertThat(OrderShipGuard.hasFabricSaleLine(orderItemMapper, objectMapper, order())).isFalse();
        assertThat(OrderShipGuard.isProcessingReadyForShip(
                orderItemMapper, processingOrderMapper, objectMapper, order())).isTrue();
        org.assertj.core.api.Assertions.assertThatCode(() -> OrderShipGuard.assertProcessingCompletedBeforeShip(
                orderItemMapper, processingOrderMapper, objectMapper, order())).doesNotThrowAnyException();
    }

    @Test
    @DisplayName("🔴 卖布行也可以以 JSON **字符串** 形态出现（JacksonTypeHandler 缺失的老坑）")
    void jsonStringFabricSaleInfoIsStillDetected() {
        givenItems(fabricItem("{\"saleForm\":\"布料\",\"fabricMeters\":12.5}"));
        when(processingOrderMapper.countCompletedByOrderId("o1", TENANT)).thenReturn(0L);

        assertThat(OrderShipGuard.hasFabricSaleLine(orderItemMapper, objectMapper, order())).isTrue();
        assertThat(OrderShipGuard.isProcessingReadyForShip(
                orderItemMapper, processingOrderMapper, objectMapper, order())).isFalse();
    }

    // ──────────────── issue #7079 第 5 包：读面「该生成哪一型」（requiredOrderKind） ────────────────

    @Test
    @DisplayName("🔴 全是卖布行 ⇒ 出库作业单（卖布单在订单详情要拿到「生成出库作业单」的出口）")
    void fabricOnlyOrderRequiresOutboundKind() {
        givenItems(fabricItem(Map.of("saleForm", "布料")));
        assertThat(OrderShipGuard.requiredOrderKind(orderItemMapper, objectMapper, order()))
                .isEqualTo(ProcessingOrderService.ORDER_KIND_OUTBOUND);
    }

    @Test
    @DisplayName("🔴 含加工项 ⇒ 加工单（成品帘单的出口文案仍是「生成加工单」）")
    void processingOrderRequiresProcessingKind() {
        givenItems(item(Map.of("processingItems", List.of(Map.of("id", "p1", "name", "韩褶-布")))));
        assertThat(OrderShipGuard.requiredOrderKind(orderItemMapper, objectMapper, order()))
                .isEqualTo(ProcessingOrderService.ORDER_KIND_PROCESSING);
    }

    @Test
    @DisplayName("🔴 混合单（卖布行 + 加工行）⇒ 加工单（与生成侧 deriveOrderKind「有加工 ⇒ 加工」同源）")
    void mixedOrderRequiresProcessingKind() {
        givenItems(fabricItem(Map.of("saleForm", "布料")),
                item(Map.of("processingItems", List.of(Map.of("id", "p1", "name", "韩褶-布")))));
        assertThat(OrderShipGuard.requiredOrderKind(orderItemMapper, objectMapper, order()))
                .isEqualTo(ProcessingOrderService.ORDER_KIND_PROCESSING);
    }

    @Test
    @DisplayName("🔴 反向护栏：无需要报工的作业 ⇒ null（配件/赠品行不许凭空造出一个生成入口）")
    void plainOrderRequiresNoWorkOrderKind() {
        givenItems(item(Map.of()));
        assertThat(OrderShipGuard.requiredOrderKind(orderItemMapper, objectMapper, order())).isNull();
    }

    @Test
    @DisplayName("🔴 卖布行以 JSON **字符串** 形态出现 ⇒ 仍判出库（不因解析形态退回「无作业」）")
    void jsonStringFabricSaleInfoStillYieldsOutboundKind() {
        givenItems(fabricItem("{\"saleForm\":\"布料\",\"fabricMeters\":12.5}"));
        assertThat(OrderShipGuard.requiredOrderKind(orderItemMapper, objectMapper, order()))
                .isEqualTo(ProcessingOrderService.ORDER_KIND_OUTBOUND);
    }

    // ──────────── issue #7222：客户端漏写 saleForm（API / 米宝 / 回归脚本建单） ────────────

    @Test
    @DisplayName("🔴 缺 saleForm 但有 sellingMethod=full_roll ⇒ 仍判卖布行（整卷是布料专属事实）")
    void fabricSaleLineWithoutSaleFormIsRecognizedBySellingMethod() {
        givenItems(OrderItem.builder().id("i-roll").orderId("o1").tenantId(TENANT)
                .quantity(new BigDecimal("12")).sellingMethod("full_roll")
                .processingInfo(Map.of("sellingMethod", "full_roll")).deleted(0).build());
        when(processingOrderMapper.countCompletedByOrderId("o1", TENANT)).thenReturn(0L);

        assertThat(OrderShipGuard.hasFabricSaleLine(orderItemMapper, objectMapper, order())).isTrue();
        assertThat(OrderShipGuard.requiredOrderKind(orderItemMapper, objectMapper, order()))
                .as("API 建的卖布单也必须拿到「生成出库作业单」出口（否则作业链静默消失）")
                .isEqualTo(ProcessingOrderService.ORDER_KIND_OUTBOUND);
        assertThat(OrderShipGuard.isProcessingReadyForShip(
                orderItemMapper, processingOrderMapper, objectMapper, order()))
                .as("卖布单一道工序没报工 ⇒ 不许直接发货")
                .isFalse();
    }

    @Test
    @DisplayName("🔴 兜底不许误伤：缺 saleForm 且无任何布料事实 ⇒ 仍判「无需作业」（配件 / 赠品行直发）")
    void orderWithoutFabricEvidenceStillNeedsNoWork() {
        givenItems(item(Map.of("colorName", "米白")));
        assertThat(OrderShipGuard.needsWork(orderItemMapper, objectMapper, order())).isFalse();
        assertThat(OrderShipGuard.requiredOrderKind(orderItemMapper, objectMapper, order())).isNull();
    }

    @Test
    @DisplayName("🔴 显式 saleForm=成品帘 不被布料事实覆盖（明确声明优先于派生信号）")
    void explicitNonFabricSaleFormWinsOverRollEvidence() {
        givenItems(OrderItem.builder().id("i-x").orderId("o1").tenantId(TENANT)
                .quantity(new BigDecimal("1")).sellingMethod("full_roll")
                .processingInfo(Map.of("saleForm", "成品帘", "sellingMethod", "full_roll")).deleted(0).build());
        assertThat(OrderShipGuard.hasFabricSaleLine(orderItemMapper, objectMapper, order())).isFalse();
        assertThat(OrderShipGuard.requiredOrderKind(orderItemMapper, objectMapper, order())).isNull();
    }

    @Test
    @DisplayName("🔴 兜底不许抢路线：缺 saleForm、有 sellingMethod，但**有加工项** ⇒ 仍判加工单（成品帘）")
    void fabricFallbackDoesNotHijackLinesWithProcessingItems() {
        givenItems(OrderItem.builder().id("i-p").orderId("o1").tenantId(TENANT)
                .quantity(new BigDecimal("1")).sellingMethod("full_roll")
                .processingInfo(Map.of(
                        "sellingMethod", "full_roll",
                        "processingItems", List.of(Map.of("id", "p1", "name", "韩褶-布"))))
                .deleted(0).build());
        assertThat(OrderShipGuard.hasFabricSaleLine(orderItemMapper, objectMapper, order())).isFalse();
        assertThat(OrderShipGuard.requiredOrderKind(orderItemMapper, objectMapper, order()))
                .as("有加工项 ⇒ 成品帘 ⇒ 加工单（卖布行按米卖，行上从无加工项）")
                .isEqualTo(ProcessingOrderService.ORDER_KIND_PROCESSING);
    }

    @Test
    @DisplayName("🔴 与 needsWork 同源：有型 ⇔ needsWork（两处口径分叉即红）")
    void requiredKindIsInSyncWithNeedsWork() {
        List<OrderItem[]> fixtures = List.of(
                new OrderItem[]{fabricItem(Map.of("saleForm", "布料"))},
                new OrderItem[]{item(Map.of("processingItems", List.of(Map.of("id", "p1", "name", "韩褶-布"))))},
                new OrderItem[]{item(Map.of())});
        for (OrderItem[] fixture : fixtures) {
            givenItems(fixture);
            boolean needsWork = OrderShipGuard.needsWork(orderItemMapper, objectMapper, order());
            String kind = OrderShipGuard.requiredOrderKind(orderItemMapper, objectMapper, order());
            assertThat(kind != null).as("有型 ⇔ 需要作业（分叉方向：前端拿到型却没有该拦/该放行的依据）")
                    .isEqualTo(needsWork);
        }
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
