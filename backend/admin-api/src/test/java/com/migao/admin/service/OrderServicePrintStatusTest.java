// case_ids: OR-071
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.OrderListResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.PrintLogSummary;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.PrintLogMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 订单列表的「是否已打印」回填（issue #7902）—— 一次批量聚合，且**空值必须是确定值**。
 *
 * <h3>为什么单独一个判据类（而不是并进 OrderServiceTest）</h3>
 * 这条链有一个**只有它会红**的失效形态：<b>N+1</b>。实现上「逐单查一次 print_logs」在功能上完全正确、
 * 单张单的断言也全绿，但一页 20 单 = 21 次查询；而列表是商家每天开最多的页面。
 * 故本类把「一页只查**一次**」钉成 verify 次数判据（{@code verify(..., times(1))}）。
 *
 * <h3>第二个失效形态：null 三连</h3>
 * 未打印的单如果回的是 {@code printedAt=null / printCount=null / printedDocTypes=null}，
 * 前端就得分三种情况判空（而后端某一处漏填时**没有任何东西会红**）⇒ 本仓口径是
 * 「未打印 = 确定值」：{@code null / 0 / []}，尤其 {@code printedDocTypes} 必须是**空列表不是 null**。
 *
 * <h3>红证</h3>
 * <ul>
 *   <li>把批量聚合改成逐单 {@code selectPrintSummary} ⇒ 判据 1 红（verify 到 N 次）；</li>
 *   <li>去掉「未打印」的默认值填充 ⇒ 判据 2 红（拿到 null 三连）；</li>
 *   <li>把空页也去查一次 ⇒ 判据 3 红（空 orderIds 生成 {@code IN ()} 是语法错误，且白跑一条 SQL）。</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("订单列表「已打印」回填：一次批量聚合 + 未打印是确定值（#7902）")
class OrderServicePrintStatusTest {

    private static final Long TENANT = 1L;

    @Mock
    private OrderMapper orderMapper;

    @Mock
    private OrderItemMapper orderItemMapper;

    @Mock
    private PrintLogMapper printLogMapper;

    @InjectMocks
    private OrderService orderService;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        // 打印汇总 Mapper 是**字段注入**（`@Autowired(required = false)`，理由见 OrderService 的字段注释：
        // 构造签名被多处测试显式装配）。Mockito 的 @InjectMocks 走完构造注入后**不再注入字段**
        // ⇒ 必须显式装配（与 OrderServiceTest 装配 stockBatchConsumptionService 同法）。
        org.springframework.test.util.ReflectionTestUtils.setField(orderService, "printLogMapper", printLogMapper);
        // 列表路径用 LambdaQueryWrapper ⇒ 需要 MyBatis-Plus 的实体元数据（纯单测里没有容器）
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, OrderItem.class);
        TableInfoHelper.initTableInfo(assistant, Product.class);
        TableInfoHelper.initTableInfo(assistant, ProductSku.class);
        // 本类只判「已打印」回填：明细面给空表（加工费/实收款分支不受影响）
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ============================================================ 判据 1

    @Test
    @DisplayName("🔴 一页 20 单只查**一次** print_logs（禁止 N+1）")
    void theSummaryQueryRunsExactlyOncePerPage() {
        List<Order> orders = List.of(order("order-a"), order("order-b"));
        when(orderMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class))).thenReturn(pageOf(orders));
        when(printLogMapper.selectPrintSummary(eq(TENANT), anyList())).thenReturn(List.of());

        orderService.getOrderPage(1, 20, null, null, null, null, null, null, null, null, null, null,
                TENANT, null, null, null);

        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<String>> ids = ArgumentCaptor.forClass(List.class);
        verify(printLogMapper, times(1)).selectPrintSummary(eq(TENANT), ids.capture());
        assertThat(ids.getValue()).containsExactly("order-a", "order-b");
        verify(printLogMapper, never()).selectByOrder(any(), any(), any(Integer.class));
    }

    // ============================================================ 判据 2

    @Test
    @DisplayName("🔴 已打印的单填 on 三个字段；未打印的单是**确定值**（null / 0 / 空列表，不是 null 三连）")
    void printedOrderIsFilledAndUnprintedOrderGetsDeterministicDefaults() {
        OffsetDateTime printedAt = OffsetDateTime.parse("2026-10-27T09:30:00+08:00");
        List<Order> orders = List.of(order("order-a"), order("order-b"));
        when(orderMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class))).thenReturn(pageOf(orders));
        when(printLogMapper.selectPrintSummary(eq(TENANT), anyList())).thenReturn(List.of(
                PrintLogSummary.builder()
                        .orderId("order-a")
                        .printedAt(printedAt)
                        // string_agg 的原始形态：逗号串 + 无固定顺序（实现必须去重排序）
                        .docTypes("sales,processing,sales")
                        .printCount(3)
                        .build()
        ));

        PageResponse<OrderListResponse> result = orderService.getOrderPage(1, 20, null, null, null, null,
                null, null, null, null, null, null, TENANT, null, null, null);

        OrderListResponse printed = result.getItems().get(0);
        assertThat(printed.getId()).isEqualTo("order-a");
        assertThat(printed.getPrintedAt()).isEqualTo(printedAt);
        assertThat(printed.getPrintCount()).isEqualTo(3);
        assertThat(printed.getPrintedDocTypes()).containsExactly("processing", "sales");

        OrderListResponse never = result.getItems().get(1);
        assertThat(never.getId()).isEqualTo("order-b");
        assertThat(never.getPrintedAt()).isNull();
        assertThat(never.getPrintCount()).isZero();
        // 🔴 必须是空列表：null 会让前端 `?.map` 与 `Array.isArray` 两条路分叉
        assertThat(never.getPrintedDocTypes()).isNotNull().isEmpty();
    }

    @Test
    @DisplayName("聚合返回空 ⇒ 全页都是「未打印」的确定值（不是「本次不填」）")
    void emptyAggregateStillFillsDeterministicDefaults() {
        when(orderMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(pageOf(List.of(order("order-a"))));
        when(printLogMapper.selectPrintSummary(eq(TENANT), anyList())).thenReturn(List.of());

        PageResponse<OrderListResponse> result = orderService.getOrderPage(1, 20, null, null, null, null,
                null, null, null, null, null, null, TENANT, null, null, null);

        OrderListResponse row = result.getItems().get(0);
        assertThat(row.getPrintedAt()).isNull();
        assertThat(row.getPrintCount()).isZero();
        assertThat(row.getPrintedDocTypes()).isNotNull().isEmpty();
    }

    // ============================================================ 判据 3

    @Test
    @DisplayName("空页 ⇒ 一次聚合都不发（`IN ()` 是语法错误，且白跑一条 SQL）")
    void emptyPageSkipsTheSummaryQuery() {
        when(orderMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(pageOf(List.of()));

        PageResponse<OrderListResponse> result = orderService.getOrderPage(1, 20, null, null, null, null,
                null, null, null, null, null, null, TENANT, null, null, null);

        assertThat(result.getItems()).isEmpty();
        verify(printLogMapper, never()).selectPrintSummary(any(), anyList());
    }

    // ============================================================ 工具

    private static Order order(String id) {
        return Order.builder()
                .id(id)
                .tenantId(TENANT)
                .orderNo("ORD-" + id)
                .customerName("客户-" + id)
                .totalAmount(new BigDecimal("100.00"))
                .status("confirmed")
                .build();
    }

    private static Page<Order> pageOf(List<Order> orders) {
        Page<Order> page = new Page<>(1, 20);
        page.setRecords(orders);
        page.setTotal(orders.size());
        return page;
    }
}
