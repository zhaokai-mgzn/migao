// case_ids: OR-056
package com.migao.admin.shipment;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.controller.ShipmentController;
import com.migao.admin.dto.ShipmentListRow;
import com.migao.admin.entity.OrderShipmentItem;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.OrderShipmentItemMapper;
import com.migao.admin.mapper.OrderShipmentMapper;
import com.migao.admin.mapper.OrderShipmentQueryMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.ImageRecognitionClient;
import com.migao.admin.service.OrderShipmentService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestMapping;

import java.lang.reflect.Method;
import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 发货单**列表读面**（issue #5939）：{@code GET /api/admin/shipments}。
 *
 * <h2>它补的是哪一个洞</h2>
 * <p>发货单（#3768 纸面 / #5648 数据面）此前**只有按单读面** {@code GET /api/admin/orders/{id}/shipments}
 * —— 想找一张发货单必须先知道是哪张订单。用户 2026-10-02 原话：「我让你开发过发货单的，但是在大菜单上
 * 没见到这个单据」⇒ 本面 = 大菜单「仓储与物料 ▸ 发货单」的第一屏读端点。</p>
 *
 * <h2>判据（每条都有红证方向）</h2>
 * <ol>
 *   <li><b>面存在且只读</b>：{@code /api/admin/shipments} 上只有 GET（本单不新增任何写面 ——
 *       写面归 #5648 的 {@code /api/worker/shipment/**}）。删掉端点 ⇒ 红。</li>
 *   <li><b>权限码 = {@code order:list}</b>：取**既有**码、不新造 —— 与同域读面
 *       {@code GET /api/admin/orders/{id}/shipments} 逐字同码 ⇒ 零授权 delta（新造码会命中
 *       #4203 同族坑：没人持有的码 = 菜单对所有人不可见）。去掉注解 ⇒ 红。</li>
 *   <li><b>实发汇总与既有读面**同源**</b>：{@code shippedTotals} 的三个键
 *       （{@code set_count} / {@code roll_count} / {@code by_unit}）由 {@link OrderShipmentService}
 *       的**同一份**汇总口径给出，且「空值不参与求和」（{@code null} ≠ 0）。改成另算一套 ⇒ 红。</li>
 *   <li><b>无明细 ⇒ 零值与空表，不是缺键</b>：没有实发明细的发货单仍要有可渲染的汇总。</li>
 *   <li><b>租户 / 关键词 / 上限都传到 SQL</b>：三者任一漏传 ⇒ 红（关键词前后空白要 trim）。</li>
 *   <li><b>空列表不做无谓的明细查询</b>（没有发货单时不去查 items）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("发货单列表读面：order:list / 只读 / 汇总同源 / 租户·关键词·上限")
class ShipmentControllerTest {

    private static final long TENANT = 7L;
    private static final int LIMIT = 200;

    @Mock private OrderMapper orderMapper;
    @Mock private OrderItemMapper orderItemMapper;
    @Mock private OrderLogisticsMapper orderLogisticsMapper;
    @Mock private OrderShipmentMapper orderShipmentMapper;
    @Mock private OrderShipmentItemMapper orderShipmentItemMapper;
    @Mock private OrderShipmentQueryMapper orderShipmentQueryMapper;
    @Mock private ProcessingOrderMapper processingOrderMapper;
    @Mock private ClientRequestIdService clientRequestIdService;
    @Mock private ImageRecognitionClient imageRecognitionClient;
    /** issue #6171：商家发货路的单位来源（本类不测它，但构造器按字段序要求它在场）。 */
    @Mock private com.migao.admin.mapper.ProductMapper productMapper;

    private OrderShipmentService service() {
        return new OrderShipmentService(orderMapper, orderItemMapper, orderLogisticsMapper,
                orderShipmentMapper, orderShipmentItemMapper, processingOrderMapper,
                clientRequestIdService, imageRecognitionClient, new ObjectMapper(),
                productMapper, orderShipmentQueryMapper);
    }

    private ShipmentListRow row(String id, String shipmentNo) {
        ShipmentListRow row = new ShipmentListRow();
        row.setId(id);
        row.setShipmentNo(shipmentNo);
        row.setOrderId("order-" + id);
        row.setOrderNo("CSO261002-0001");
        row.setCustomerName("张女士");
        row.setSource("worker_photo");
        return row;
    }

    private OrderShipmentItem item(String shipmentId, BigDecimal qty, String unit,
                                   Integer setCount, Integer rollCount) {
        OrderShipmentItem it = new OrderShipmentItem();
        it.setShipmentId(shipmentId);
        it.setShippedQuantity(qty);
        it.setUnit(unit);
        it.setSetCount(setCount);
        it.setRollCount(rollCount);
        return it;
    }

    // ══════════════════════════════════════════════════════════════════════════
    // 判据 1/2：面与码
    // ══════════════════════════════════════════════════════════════════════════

    private Method listEndpoint() {
        return java.util.Arrays.stream(ShipmentController.class.getDeclaredMethods())
                .filter(m -> m.getAnnotation(GetMapping.class) != null)
                .findFirst()
                .orElseThrow(() -> new AssertionError(
                        "发货单列表页没有读端点（GET /api/admin/shipments）—— 大菜单点进去会是空的"));
    }

    @Test
    @DisplayName("🔴 面存在：类级 @RequestMapping(\"/api/admin/shipments\") + 一个 GET 方法")
    void listFaceExistsOnItsOwnPath() {
        RequestMapping mapping = ShipmentController.class.getAnnotation(RequestMapping.class);
        assertThat(mapping).as("ShipmentController 必须有类级 @RequestMapping").isNotNull();
        assertThat(mapping.value()).containsExactly("/api/admin/shipments");
        assertThat(listEndpoint()).isNotNull();
    }

    @Test
    @DisplayName("🔴 权限码 = order:list（与按单读面逐字同码；不新造权限码）")
    void listFaceCarriesTheExistingOrderListCode() {
        RequirePermission required = listEndpoint().getAnnotation(RequirePermission.class);
        assertThat(required).as("发货单列表读面必须标 @RequirePermission").isNotNull();
        assertThat(required.value()).isEqualTo("order:list");
    }

    @Test
    @DisplayName("🔴 只读：该类上没有任何写动词（写面归 #5648 的工人面）")
    void listFaceIsReadOnly() {
        List<Class<? extends java.lang.annotation.Annotation>> writeVerbs = List.of(
                PostMapping.class, PutMapping.class, PatchMapping.class, DeleteMapping.class);
        for (Method m : ShipmentController.class.getDeclaredMethods()) {
            for (Class<? extends java.lang.annotation.Annotation> verb : writeVerbs) {
                assertThat(m.getAnnotation(verb))
                        .as("%s 上不该出现写动词 %s（本单只补读面）", m.getName(), verb.getSimpleName())
                        .isNull();
            }
        }
    }

    // ══════════════════════════════════════════════════════════════════════════
    // 判据 3/4：实发汇总与既有读面同源
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 实发汇总三个键由同一份口径给出：set_count / roll_count / by_unit（空值不参与求和）")
    void shippedTotalsComeFromTheSameProjection() {
        ShipmentListRow s1 = row("s1", "FH-20261002-0001");
        when(orderShipmentQueryMapper.selectListRows(eq(TENANT), any(), anyInt()))
                .thenReturn(List.of(s1));
        when(orderShipmentItemMapper.selectByShipmentIds(any(), eq(TENANT))).thenReturn(List.of(
                // set_count 显式填过 ⇒ 参与求和
                item("s1", new BigDecimal("10.50"), "米", 2, null),
                item("s1", new BigDecimal("2.00"), "米", null, null),
                // roll_count 只对「显式填过」的行求和：这一行留 null ⇒ 不参与（roll_count 仍是 0，
                // 但语义是「这一维不适用」，与「发了 0 卷」是两件事）
                item("s1", new BigDecimal("3.00"), "卷", null, 1)));

        List<ShipmentListRow> rows = service().listShipments("  ", TENANT);

        assertThat(rows).hasSize(1);
        Map<String, Object> totals = rows.get(0).getShippedTotals();
        assertThat(totals).containsOnlyKeys("set_count", "roll_count", "by_unit");
        assertThat(totals.get("set_count")).isEqualTo(new BigDecimal("2"));
        assertThat(totals.get("roll_count")).isEqualTo(new BigDecimal("1"));
        @SuppressWarnings("unchecked")
        Map<String, BigDecimal> byUnit = (Map<String, BigDecimal>) totals.get("by_unit");
        assertThat(byUnit).containsEntry("米", new BigDecimal("12.50"));
        assertThat(byUnit).containsEntry("卷", new BigDecimal("3.00"));
    }

    @Test
    @DisplayName("没有实发明细的发货单仍要有可渲染的汇总（零值 + 空 by_unit，不是缺键）")
    void shipmentWithoutItemsStillHasTotalsShape() {
        ShipmentListRow s2 = row("s2", "FH-20261002-0002");
        when(orderShipmentQueryMapper.selectListRows(anyLong(), any(), anyInt()))
                .thenReturn(List.of(s2));
        when(orderShipmentItemMapper.selectByShipmentIds(any(), anyLong())).thenReturn(List.of());

        List<ShipmentListRow> rows = service().listShipments(null, TENANT);

        Map<String, Object> totals = rows.get(0).getShippedTotals();
        assertThat(totals).containsOnlyKeys("set_count", "roll_count", "by_unit");
        assertThat(totals.get("set_count")).isEqualTo(BigDecimal.ZERO);
        assertThat((Map<?, ?>) totals.get("by_unit")).isEmpty();
    }

    // ══════════════════════════════════════════════════════════════════════════
    // 判据 5/6：租户 / 关键词 / 上限
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("租户 / 关键词（trim）/ 上限都传到 SQL（漏传 = 跨租户或全表）")
    void tenantKeywordAndLimitReachTheQuery() {
        when(orderShipmentQueryMapper.selectListRows(anyLong(), any(), anyInt()))
                .thenReturn(List.of());
        service().listShipments("  CSO261002  ", TENANT);
        verify(orderShipmentQueryMapper).selectListRows(TENANT, "CSO261002", LIMIT);
    }

    @Test
    @DisplayName("空白关键词 ⇒ 不按关键词过滤（传 null，不当成「搜空串」）")
    void blankKeywordBecomesNull() {
        when(orderShipmentQueryMapper.selectListRows(anyLong(), any(), anyInt()))
                .thenReturn(List.of());
        service().listShipments("   ", TENANT);
        verify(orderShipmentQueryMapper).selectListRows(TENANT, null, LIMIT);
    }

    @Test
    @DisplayName("空列表不去查明细（没有发货单时不做无谓查询）")
    void emptyListDoesNotQueryItems() {
        when(orderShipmentQueryMapper.selectListRows(anyLong(), any(), anyInt()))
                .thenReturn(List.of());
        assertThat(service().listShipments(null, TENANT)).isEmpty();
        verify(orderShipmentItemMapper, never()).selectByShipmentIds(any(), anyLong());
    }
}
