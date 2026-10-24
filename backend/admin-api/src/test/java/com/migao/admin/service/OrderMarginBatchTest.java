// case_ids: RPT-001
package com.migao.admin.service;

import com.migao.admin.dto.OrderMarginView;
import com.migao.admin.entity.FinanceTransaction;
import com.migao.admin.entity.Order;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mockito;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 报表取数批量化的**口径判据**（issue #7582）：批量路径必须与逐单路径逐字段相同。
 *
 * <p>为什么必须有这份判据：报表中心原来逐单调 {@code margin(orderId)}（8 条 SQL/单，
 * 500 单上界 ≈ 4000 条），批量版把取数换成「面料 1 条 GROUP BY + 退款 1 条 IN + 计件 4 条」。
 * 取数一换，最容易出的错**不是慢**，而是**悄悄换口径**：面料缺进价被当 0、退款只算到第一单、
 * 计件只取第一张加工单……每一条都会让报表上的毛利**单看正常、合计错**。</p>
 *
 * <p>两条判据在这里：</p>
 * <ol>
 *   <li>{@code batchEqualsPerOrder}：批量喂「两单全部行」、逐单喂「该单的行」（与真实 DB 的等值过滤等价），
 *       两条路径逐单 {@code isEqualTo}（任一分项/未知计数不等即红）；</li>
 *   <li>{@code batchFetchesOnce}：N 张单只发一次批量查询、且**不再调**逐单取数
 *       （退回逐单实现 ⇒ {@code times(1)} 变 {@code times(N)}，本判据红）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("订单毛利：批量取数 ≡ 逐单取数（issue #7582）")
class OrderMarginBatchTest {

    private static final Long TENANT = 1L;

    private Order order1;
    private Order order2;
    private Map<String, Object> fabric1;
    private Map<String, Object> fabric2;
    private Map<String, Object> piecework1;
    private Map<String, Object> piecework2;

    @BeforeEach
    void setUp() {
        order1 = order("o1", "SO-1");
        order2 = order("o2", "SO-2");
        // ① 面料：o1 有进价（已知），o2 有一行缺进价（未知 —— 绝不当 0）
        fabric1 = fabricRow("400.00", 0, 2);
        fabric2 = fabricRow("0.00", 1, 2);
        // ③ 计件：o1 已定价 100、o2 已定价 200（都没有未定价行）
        piecework1 = piecework("100.00", "0");
        piecework2 = piecework("200.00", "0");
    }

    @Test
    @DisplayName("🔴 批量读数 ≡ 逐单读数（改取数形状不改口径）")
    void batchEqualsPerOrder() {
        // 批量服务：一次 `IN` / `GROUP BY` 取回两单的行（分组是批量路径自己的逻辑）
        OrderMapper batchOrderMapper = Mockito.mock(OrderMapper.class);
        when(batchOrderMapper.selectFabricCosts(eq(TENANT), anyCollection()))
                .thenReturn(List.of(fabricWithNo("SO-1", fabric1), fabricWithNo("SO-2", fabric2)));
        FinanceTransactionMapper batchFinance = Mockito.mock(FinanceTransactionMapper.class);
        when(batchFinance.selectList(any())).thenReturn(List.of(
                refund("o1", "50.00"), refund("o2", "70.00")));
        ProductionService batchPiecework = Mockito.mock(ProductionService.class);
        Map<String, Map<String, Object>> batchMap = new LinkedHashMap<>();
        batchMap.put("o1", piecework1);
        batchMap.put("o2", piecework2);
        when(batchPiecework.pieceworkByOrders(anyList(), eq(TENANT))).thenReturn(batchMap);
        OrderMarginService batchService =
                new OrderMarginService(batchOrderMapper, batchFinance, batchPiecework);

        // 逐单服务：每次查询只返回该单的行（等价于 DB 的等值过滤）
        OrderMarginService single1 = singleService(order1, fabric1, List.of(refund("o1", "50.00")), piecework1);
        OrderMarginService single2 = singleService(order2, fabric2, List.of(refund("o2", "70.00")), piecework2);

        List<OrderMarginView> batch = batchService.margins(List.of(order1, order2));

        assertThat(batch).hasSize(2);
        assertThat(batch.get(0)).isEqualTo(single1.margin("o1"));
        assertThat(batch.get(1)).isEqualTo(single2.margin("o2"));
        // 人读的锚点：o1 = 1000 − 50 − 400 − 100 = 450；o2 缺进价 ⇒ 成本未知（不是毛利 730）
        assertThat(batch.get(0).getGrossMargin()).isEqualByComparingTo("450");
        assertThat(batch.get(1).isCostKnown()).isFalse();
        assertThat(batch.get(1).getFabricCost()).isNull();
    }

    @Test
    @DisplayName("🔴 批量取数：面料/退款/计件各一次，且不再逐单回查（退回逐单 ⇒ 本判据红）")
    void batchFetchesOnce() {
        OrderMapper orderMapper = Mockito.mock(OrderMapper.class);
        when(orderMapper.selectFabricCosts(eq(TENANT), anyCollection()))
                .thenReturn(List.of(fabricWithNo("SO-1", fabric1), fabricWithNo("SO-2", fabric2)));
        FinanceTransactionMapper financeMapper = Mockito.mock(FinanceTransactionMapper.class);
        when(financeMapper.selectList(any())).thenReturn(List.of());
        ProductionService pieceworkService = Mockito.mock(ProductionService.class);
        when(pieceworkService.pieceworkByOrders(anyList(), eq(TENANT))).thenReturn(Map.of());
        OrderMarginService service = new OrderMarginService(orderMapper, financeMapper, pieceworkService);

        service.margins(List.of(order1, order2));

        verify(orderMapper, times(1)).selectFabricCosts(eq(TENANT), anyCollection());
        verify(orderMapper, never()).selectFabricCost(any(), anyString());
        verify(orderMapper, never()).selectById(anyString());
        verify(financeMapper, times(1)).selectList(any());
        verify(pieceworkService, times(1)).pieceworkByOrders(anyList(), eq(TENANT));
        verify(pieceworkService, never()).piecework(anyString(), any());
    }

    /** 逐单路径的服务：每次查询只命中该单（面料按 order_no、退款按 order_id、计件按订单 id）。 */
    private OrderMarginService singleService(Order order, Map<String, Object> fabricRow,
                                             List<FinanceTransaction> refunds,
                                             Map<String, Object> piecework) {
        OrderMapper orderMapper = Mockito.mock(OrderMapper.class);
        when(orderMapper.selectById(order.getId())).thenReturn(order);
        when(orderMapper.selectFabricCost(TENANT, order.getOrderNo())).thenReturn(withoutOrderNo(fabricRow));
        FinanceTransactionMapper financeMapper = Mockito.mock(FinanceTransactionMapper.class);
        when(financeMapper.selectList(any())).thenReturn(refunds);
        ProductionService pieceworkService = Mockito.mock(ProductionService.class);
        when(pieceworkService.piecework(order.getId(), TENANT)).thenReturn(piecework);
        return new OrderMarginService(orderMapper, financeMapper, pieceworkService);
    }

    private static Order order(String id, String orderNo) {
        Order order = new Order();
        order.setId(id);
        order.setTenantId(TENANT);
        order.setOrderNo(orderNo);
        order.setTotalAmount(new BigDecimal("1000.00"));
        order.setStatus("completed");
        order.setDeleted(0);
        return order;
    }

    private static FinanceTransaction refund(String orderId, String amount) {
        FinanceTransaction transaction = new FinanceTransaction();
        transaction.setTenantId(TENANT);
        transaction.setOrderId(orderId);
        transaction.setType("refund");
        transaction.setStatus("success");
        transaction.setAmount(new BigDecimal(amount));
        return transaction;
    }

    /** 面料聚合的三元组（与 `OrderMapper::selectFabricCost(s)` 返回的键名逐字一致）。 */
    private static Map<String, Object> fabricRow(String fabricCost, int unknownLines, int lines) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("fabric_cost", new BigDecimal(fabricCost));
        row.put("unknown_lines", unknownLines);
        row.put("lines", lines);
        return row;
    }

    private static Map<String, Object> fabricWithNo(String orderNo, Map<String, Object> row) {
        Map<String, Object> withNo = new LinkedHashMap<>();
        withNo.put("order_no", orderNo);
        withNo.putAll(row);
        return withNo;
    }

    private static Map<String, Object> withoutOrderNo(Map<String, Object> row) {
        Map<String, Object> copy = new LinkedHashMap<>(row);
        copy.remove("order_no");
        return copy;
    }

    /** 计件聚合的最小形状（真身由 ProductionService 的同一份聚合产出）。 */
    private static Map<String, Object> piecework(String total, String unpricedQty) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("total", new BigDecimal(total));
        result.put("per_worker", new LinkedHashMap<>());
        result.put("per_operation", List.of());
        result.put("per_position", List.of());
        result.put("per_set", List.of());
        Map<String, Object> unpriced = new LinkedHashMap<>();
        unpriced.put("qty", new BigDecimal(unpricedQty));
        result.put("unpriced", unpriced);
        return result;
    }
}
