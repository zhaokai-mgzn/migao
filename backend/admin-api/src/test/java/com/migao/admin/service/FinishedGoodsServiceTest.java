// case_ids: WH-005
package com.migao.admin.service;

import com.migao.admin.entity.FinishedGoodsStock;
import com.migao.admin.entity.InboundOrder;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.OutboundOrder;
import com.migao.admin.entity.Warehouse;
import com.migao.admin.dto.InboundOrderResponse;
import com.migao.admin.dto.FinishedGoodsView;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinishedGoodsStockMapper;
import com.migao.admin.mapper.OrderItemMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 成品库存编排（V196，issue #7750 / 用例 WH-005）：打包入库 / 发货出库 / 撤销打包。
 *
 * <p>守五条：</p>
 * <ol>
 *   <li><b>打包 = 入库</b>：给每个成品订单行分配成品仓仓位号，生成**已过账**的成品入库单；</li>
 *   <li><b>幂等</b>：已有在库行 ⇒ 不重复入库（不建第二张单）；</li>
 *   <li><b>发货 = 出库</b>：没有在库行时**不造空单**（凭空 0 行单据只会让对账多一个无法解释的单）；</li>
 *   <li><b>撤销打包 = 冲销</b>：入库单作废 + 在库行释放（同一张入库单只冲一次）；</li>
 *   <li><b>并发变更显式失败</b>：出库时在库行已被并发改掉 ⇒ 409（整笔回滚），不静默返回成功。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("成品库存编排（V196 / issue #7750）")
class FinishedGoodsServiceTest {

    private static final Long TENANT = 1L;

    @Mock private FinishedGoodsStockMapper stockMapper;
    @Mock private OrderItemMapper orderItemMapper;
    @Mock private WarehouseService warehouseService;
    @Mock private InboundOrderService inboundOrderService;
    @Mock private OutboundOrderService outboundOrderService;
    // V197 / issue #7762：套 × 部位粒度 + 扫水洗唛出库（新依赖；未 mock 会让既有用例 NPE）
    @Mock private com.migao.admin.mapper.ProcessingSetPartTokenMapper tokenMapper;
    @Mock private com.migao.admin.mapper.ProcessingOrderSetMapper setMapper;
    @Mock private com.migao.admin.mapper.ProductionWorkLogMapper workLogMapper;
    @Mock private com.migao.admin.mapper.OrderMapper orderMapper;

    @BeforeEach
    void noWashLabelTokensByDefault() {
        // 既有用例（V196 订单行粒度）⇒ 该订单没有部位码；本类新增的扫唛用例自己 stub
        when(tokenMapper.selectByOrderId(anyLong(), any())).thenReturn(java.util.List.of());
    }

    @InjectMocks private FinishedGoodsService service;

    private static Order order() {
        return Order.builder().id("order-1").orderNo("DD-20261025-0001").tenantId(TENANT).build();
    }

    private static FinishedGoodsStock inStock(String itemId, String bin, String inboundId) {
        return FinishedGoodsStock.builder()
                .id(100L)
                .tenantId(TENANT)
                .orderId("order-1")
                .orderNo("DD-20261025-0001")
                .orderItemId(itemId)
                .productName("遮光布帘")
                .binCode(bin)
                .locationId(7L)
                .quantity(BigDecimal.ONE)
                .unit("set")
                .status(FinishedGoodsStock.STATUS_IN_STOCK)
                .inboundOrderId(inboundId)
                .build();
    }

    private static Warehouse finishedWarehouse() {
        Warehouse warehouse = new Warehouse();
        warehouse.setId(9L);
        warehouse.setName("成品仓");
        warehouse.setWarehouseType(Warehouse.TYPE_FINISHED);
        return warehouse;
    }

    // ============================================================ 打包入库

    @Test
    @DisplayName("打包 ⇒ 分配仓位 + 生成已过账成品入库单（每个成品行一个仓位）")
    void packReceivesFinishedGoodsWithBins() {
        OrderItem item = OrderItem.builder().id("item-1").productId("prod-1").productName("遮光布帘").build();
        OrderItem item2 = OrderItem.builder().id("item-2").productId("prod-2").productName("纱帘").build();
        when(stockMapper.selectInStockByOrder(TENANT, "order-1"))
                .thenReturn(List.of(), List.of(inStock("item-1", "A-01", "rk-1"), inStock("item-2", "A-02", "rk-1")));
        when(orderItemMapper.selectList(any())).thenReturn(List.of(item, item2));
        when(warehouseService.ensureFinishedWarehouse(TENANT)).thenReturn(finishedWarehouse());
        when(inboundOrderService.receiveFinishedGoods(eq(TENANT), any(Order.class), any(), eq(9L), eq("成品仓"), eq("工人甲")))
                .thenReturn(new InboundOrderResponse());

        List<FinishedGoodsStock> rows = service.receiveOnPack(order(), TENANT, "工人甲");

        assertThat(rows).extracting(FinishedGoodsStock::getBinCode).containsExactly("A-01", "A-02");
        verify(warehouseService).ensureFinishedWarehouse(TENANT);
        verify(inboundOrderService).receiveFinishedGoods(eq(TENANT), any(Order.class), any(), eq(9L), eq("成品仓"), eq("工人甲"));
    }

    @Test
    @DisplayName("🔴 幂等：已有在库成品行 ⇒ 直接返回，不再建第二张成品入库单")
    void packIsIdempotent() {
        when(stockMapper.selectInStockByOrder(TENANT, "order-1"))
                .thenReturn(List.of(inStock("item-1", "A-01", "rk-1")));

        List<FinishedGoodsStock> rows = service.receiveOnPack(order(), TENANT, "工人甲");

        assertThat(rows).hasSize(1);
        verify(inboundOrderService, never()).receiveFinishedGoods(anyLong(), any(), any(), any(), anyString(), anyString());
        verify(warehouseService, never()).ensureFinishedWarehouse(anyLong());
    }

    @Test
    @DisplayName("订单没有成品行 ⇒ 不造假单（返回空，不触达入库服务）")
    void packWithoutItemsCreatesNothing() {
        when(stockMapper.selectInStockByOrder(TENANT, "order-1")).thenReturn(List.of());
        when(orderItemMapper.selectList(any())).thenReturn(List.of());

        assertThat(service.receiveOnPack(order(), TENANT, "工人甲")).isEmpty();
        verify(inboundOrderService, never()).receiveFinishedGoods(anyLong(), any(), any(), any(), anyString(), anyString());
    }

    // ============================================================ 发货出库

    @Test
    @DisplayName("发货 ⇒ 成品出库单 + 在库行置 shipped（仓位释放）")
    void shipIssuesFinishedGoods() {
        List<FinishedGoodsStock> rows = List.of(inStock("item-1", "A-01", "rk-1"));
        when(stockMapper.selectInStockByOrder(TENANT, "order-1")).thenReturn(rows);
        when(warehouseService.ensureFinishedWarehouse(TENANT)).thenReturn(finishedWarehouse());
        OutboundOrder doc = OutboundOrder.builder().id("ck-1").outboundNo("CK-1").build();
        when(outboundOrderService.createFinishedOutbound(any(Order.class), any(), any(), eq(TENANT), eq("工人甲")))
                .thenReturn(doc);
        when(stockMapper.markShippedByOrder(TENANT, "order-1", "ck-1")).thenReturn(1);

        List<FinishedGoodsStock> issued = service.issueOnShip(order(), TENANT, "工人甲");

        assertThat(issued).extracting(FinishedGoodsStock::getBinCode).containsExactly("A-01");
        verify(stockMapper).markShippedByOrder(TENANT, "order-1", "ck-1");
    }

    @Test
    @DisplayName("🔴 没有在库行（一步发货）⇒ 不造空出库单")
    void shipWithoutStockCreatesNoDoc() {
        when(stockMapper.selectInStockByOrder(TENANT, "order-1")).thenReturn(List.of());

        assertThat(service.issueOnShip(order(), TENANT, "工人甲")).isEmpty();
        verify(outboundOrderService, never()).createFinishedOutbound(any(), any(), any(), anyLong(), anyString());
    }

    @Test
    @DisplayName("在库行被并发改掉 ⇒ 409（不静默成功）")
    void shipConcurrentChangeConflicts() {
        when(stockMapper.selectInStockByOrder(TENANT, "order-1"))
                .thenReturn(List.of(inStock("item-1", "A-01", "rk-1")));
        when(warehouseService.ensureFinishedWarehouse(TENANT)).thenReturn(finishedWarehouse());
        when(outboundOrderService.createFinishedOutbound(any(), any(), any(), anyLong(), anyString()))
                .thenReturn(OutboundOrder.builder().id("ck-1").build());
        when(stockMapper.markShippedByOrder(TENANT, "order-1", "ck-1")).thenReturn(0);

        assertThatThrownBy(() -> service.issueOnShip(order(), TENANT, "工人甲"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("并发变更");
    }

    // ============================================================ 撤销打包

    @Test
    @DisplayName("撤销打包 ⇒ 入库单作废 + 在库行释放；同一张入库单只冲一次")
    void unpackReversesInboundOnce() {
        when(stockMapper.selectInStockByOrder(TENANT, "order-1")).thenReturn(List.of(
                inStock("item-1", "A-01", "rk-1"),
                inStock("item-2", "A-02", "rk-1")));
        when(stockMapper.markUnpackedByOrder(TENANT, "order-1")).thenReturn(2);

        int released = service.reverseOnUnpack(order(), TENANT, "工人甲", "装错单了");

        assertThat(released).isEqualTo(2);
        verify(stockMapper).markUnpackedByOrder(TENANT, "order-1");
        verify(inboundOrderService, times(1))
                .cancelFinishedPosting(eq("rk-1"), eq(TENANT), eq("工人甲"), eq("撤销打包：装错单了"));
    }

    @Test
    @DisplayName("没有在库行 ⇒ 释放 0 行（幂等，不报错）")
    void unpackWithoutStockIsNoop() {
        when(stockMapper.selectInStockByOrder(TENANT, "order-1")).thenReturn(List.of());

        assertThat(service.reverseOnUnpack(order(), TENANT, "工人甲", "重复撤销")).isZero();
        verify(stockMapper, never()).markUnpackedByOrder(anyLong(), anyString());
    }

    // ============================================================ 读面

    @Test
    @DisplayName("仓位回执：order_item_id / product_name / bin_code / quantity / unit 五键")
    void binAssignmentsShape() {
        when(stockMapper.selectInStockByOrder(TENANT, "order-1"))
                .thenReturn(List.of(inStock("item-1", "A-01", "rk-1")));

        List<Map<String, Object>> assignments = service.binAssignments(TENANT, "order-1");

        assertThat(assignments).hasSize(1);
        assertThat(assignments.get(0)).containsEntry("order_item_id", "item-1")
                .containsEntry("bin_code", "A-01")
                .containsEntry("product_name", "遮光布帘")
                .containsEntry("unit", "set");
    }

    @Test
    @DisplayName("在库总览透出仓位号（成品库存页唯一的数据来源）")
    void listInStockExposesBins() {
        when(stockMapper.selectInStock(TENANT)).thenReturn(List.of(inStock("item-1", "A-01", "rk-1")));

        List<FinishedGoodsView> views = service.listInStock(TENANT);

        assertThat(views).extracting(FinishedGoodsView::getBinCode).containsExactly("A-01");
        assertThat(views.get(0).getStatus()).isEqualTo(FinishedGoodsStock.STATUS_IN_STOCK);
    }

    /**
     * issue #7792：「入库单」列印的是内部 UUID 而不是 RK- 单号。
     *
     * <p>读面必须把 {@code inbound_orders.inbound_no} 一起投影出来（{@code inboundNo}），
     * 而 {@code inboundOrderId} 仍原样透传（契约冻结：其它调用方按 id 定位单据）。</p>
     */
    @Test
    @DisplayName("🔴 在库总览透出入库单号 inboundNo，且 inboundOrderId 仍是内部 id（契约不变）")
    void listInStockExposesInboundNo() {
        FinishedGoodsStock row = inStock("item-1", "A-01", "3f2a9c1e-5b44-4a77-9a0e-2b1f7c9d8e10");
        row.setInboundNo("RK-20261025-0001");
        when(stockMapper.selectInStock(TENANT)).thenReturn(List.of(row));

        List<FinishedGoodsView> views = service.listInStock(TENANT);

        assertThat(views).hasSize(1);
        assertThat(views.get(0).getInboundNo()).isEqualTo("RK-20261025-0001");
        // 契约冻结：id 字段仍在、值不变（前端与其它读面按 id 定位单据）
        assertThat(views.get(0).getInboundOrderId()).isEqualTo("3f2a9c1e-5b44-4a77-9a0e-2b1f7c9d8e10");
    }
}
