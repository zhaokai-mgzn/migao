// case_ids: RPT-001
package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mockito;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 计件**批量取数**的口径判据（issue #7582）：`pieceworkByOrders` 必须与 `piecework` 逐键相同。
 *
 * <p>批量版把「每单 5 条」压成「4 条与订单数无关」（活跃加工单 / 工序实例 / 报工 / 订单明细行），
 * 聚合仍走 {@code aggregate} 这唯一一份算法。**最容易出的错是分桶错**：把 A 单的报工算到 B 单、
 * 或樘窗组键（套维度）用错单的明细行 —— 两者都会让报表里每单看起来都「有个数」，合计却不对。</p>
 *
 * <p>判据两条：① 两条路径逐键 {@code isEqualTo}（批量喂「两单全部行」、逐单喂「该单的行」，
 * 与真实 DB 的等值过滤等价）；② 批量路径的 SQL 次数与订单数无关（退回逐单 ⇒ 加工单查询从 1 次变 N 次）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("计件批量取数：与逐单路径逐键相同（issue #7582）")
class ProductionPieceworkBatchTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_1 = "order-1";
    private static final String ORDER_2 = "order-2";
    private static final String PO_1 = "po-1";
    private static final String PO_2 = "po-2";

    private ProcessingOrderMapper poMapper;
    private ProcessingPositionOperationMapper opMapper;
    private ProductionWorkLogMapper logMapper;
    private OrderMapper orderMapper;
    private OrderItemMapper itemMapper;

    private ProductionService service;
    private Order order1;
    private Order order2;
    private List<ProcessingOrder> processingOrders;
    private List<ProcessingPositionOperation> operations;
    private List<ProductionWorkLog> logs;
    private List<OrderItem> items;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        order1 = order(ORDER_1, "SO-1");
        order2 = order(ORDER_2, "SO-2");
        processingOrders = List.of(processingOrder(PO_1, ORDER_1), processingOrder(PO_2, ORDER_2));
        // o1：3 米 × ¥0.40 = ¥1.20；o2：2 米 × ¥0.50 = ¥1.00（金额在报工快照上，聚合只读它）
        operations = List.of(
                operation("op-1", PO_1, "精裁", "0.40"),
                operation("op-2", PO_2, "精裁", "0.50"));
        logs = List.of(
                workLog(PO_1, "op-1", "3", "0.40"),
                workLog(PO_2, "op-2", "2", "0.50"));
        items = List.of(orderItem("item-1", ORDER_1), orderItem("item-2", ORDER_2));

        // 批量路径的服务：一次取回两单的全部行（分桶是批量路径自己的逻辑）
        poMapper = Mockito.mock(ProcessingOrderMapper.class);
        for (ProcessingOrder po : processingOrders) {
            when(poMapper.selectActiveByOrderId(po.getOrderId(), TENANT)).thenReturn(po);
        }
        when(poMapper.selectActiveByOrderIds(anyCollection(), eq(TENANT))).thenReturn(processingOrders);
        opMapper = Mockito.mock(ProcessingPositionOperationMapper.class);
        when(opMapper.selectList(any())).thenReturn(operations);
        logMapper = Mockito.mock(ProductionWorkLogMapper.class);
        when(logMapper.selectList(any())).thenReturn(logs);
        itemMapper = Mockito.mock(OrderItemMapper.class);
        when(itemMapper.selectList(any())).thenReturn(items);
        orderMapper = Mockito.mock(OrderMapper.class);
        when(orderMapper.selectById(ORDER_1)).thenReturn(order1);
        when(orderMapper.selectById(ORDER_2)).thenReturn(order2);
        service = new ProductionService(poMapper, opMapper, logMapper, orderMapper, itemMapper,
                Mockito.mock(ClientRequestIdService.class));
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Test
    @DisplayName("🔴 批量 ≡ 逐单：两单各走自己的加工单与报工，逐键相同（分桶错即红）")
    void batchEqualsSingle() {
        Map<String, Map<String, Object>> batch =
                service.pieceworkByOrders(List.of(order1, order2), TENANT);
        // 逐单路径：每次查询只命中该单的行（等价于 DB 的等值过滤）
        ProductionService single1 = serviceWith(
                operations.subList(0, 1), logs.subList(0, 1), items.subList(0, 1));
        ProductionService single2 = serviceWith(
                operations.subList(1, 2), logs.subList(1, 2), items.subList(1, 2));

        assertThat(batch.get(ORDER_1)).isEqualTo(single1.piecework(ORDER_1, TENANT));
        assertThat(batch.get(ORDER_2)).isEqualTo(single2.piecework(ORDER_2, TENANT));
        assertThat((BigDecimal) batch.get(ORDER_1).get("total")).isEqualByComparingTo("1.20");
        assertThat((BigDecimal) batch.get(ORDER_2).get("total")).isEqualByComparingTo("1.00");
    }

    @Test
    @DisplayName("🔴 批量取数条数与订单数无关：加工单/工序/报工/明细各 1 次，不回查订单")
    void batchIssuesConstantNumberOfQueries() {
        service.pieceworkByOrders(List.of(order1, order2), TENANT);

        // 退回逐单实现 ⇒ 加工单查询从 times(1) 变 times(2)，本判据红
        verify(poMapper, times(1)).selectActiveByOrderIds(anyCollection(), eq(TENANT));
        verify(poMapper, never()).selectActiveByOrderId(anyString(), any());
        verify(opMapper, times(1)).selectList(any());
        verify(logMapper, times(1)).selectList(any());
        verify(itemMapper, times(1)).selectList(any());
        verify(orderMapper, never()).selectById(anyString());
    }

    /** 逐单路径的服务（每次查询只命中给定行集）。 */
    private ProductionService serviceWith(List<ProcessingPositionOperation> ops,
                                          List<ProductionWorkLog> workLogs,
                                          List<OrderItem> orderItems) {
        ProcessingOrderMapper singlePoMapper = Mockito.mock(ProcessingOrderMapper.class);
        for (ProcessingOrder po : processingOrders) {
            when(singlePoMapper.selectActiveByOrderId(po.getOrderId(), TENANT)).thenReturn(po);
        }
        ProcessingPositionOperationMapper singleOpMapper = Mockito.mock(ProcessingPositionOperationMapper.class);
        when(singleOpMapper.selectList(any())).thenReturn(ops);
        ProductionWorkLogMapper singleLogMapper = Mockito.mock(ProductionWorkLogMapper.class);
        when(singleLogMapper.selectList(any())).thenReturn(workLogs);
        OrderItemMapper singleItemMapper = Mockito.mock(OrderItemMapper.class);
        when(singleItemMapper.selectList(any())).thenReturn(orderItems);
        OrderMapper singleOrderMapper = Mockito.mock(OrderMapper.class);
        when(singleOrderMapper.selectById(ORDER_1)).thenReturn(order1);
        when(singleOrderMapper.selectById(ORDER_2)).thenReturn(order2);
        return new ProductionService(singlePoMapper, singleOpMapper, singleLogMapper, singleOrderMapper,
                singleItemMapper, Mockito.mock(ClientRequestIdService.class));
    }

    private static Order order(String id, String orderNo) {
        Order order = new Order();
        order.setId(id);
        order.setTenantId(TENANT);
        order.setOrderNo(orderNo);
        order.setStatus("producing");
        order.setDeleted(0);
        return order;
    }

    private static ProcessingOrder processingOrder(String id, String orderId) {
        ProcessingOrder po = new ProcessingOrder();
        po.setId(id);
        po.setTenantId(TENANT);
        po.setOrderId(orderId);
        po.setStatus("generated");
        po.setDeleted(0);
        return po;
    }

    private static ProcessingPositionOperation operation(String id, String poId, String name, String unitPrice) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(poId)
                .positionName("布艺遮光帘A 米白").seq(1).operationName(name).groupName("裁剪").unit("米")
                .qty(new BigDecimal("12.30")).unitPrice(new BigDecimal(unitPrice))
                .isMustFinish(false).isStartMarker(true).status("done")
                .doneQty(new BigDecimal("3")).deleted(0).build();
    }

    /** 带**单价快照**的报工（issue #4351 起金额在报工那一刻固化）。 */
    private static ProductionWorkLog workLog(String poId, String operationId, String qty, String unitPrice) {
        return ProductionWorkLog.builder()
                .tenantId(TENANT).processingOrderId(poId).operationId(operationId).operationName("精裁")
                .workerId("w-1").workerName("走查工人").qty(new BigDecimal(qty))
                .qualifiedQty(new BigDecimal(qty)).workType("normal").workDate(LocalDate.of(2026, 10, 20))
                .unitPrice(new BigDecimal(unitPrice)).deleted(0).build();
    }

    private static OrderItem orderItem(String id, String orderId) {
        return OrderItem.builder()
                .id(id).tenantId(TENANT).orderId(orderId)
                .productName("遮光帘").quantity(BigDecimal.ONE).unitPrice(new BigDecimal("100"))
                .subtotal(new BigDecimal("100")).deleted(0).build();
    }
}
