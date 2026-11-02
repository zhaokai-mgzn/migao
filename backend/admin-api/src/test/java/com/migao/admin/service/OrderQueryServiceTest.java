// case_ids: OR-061
package com.migao.admin.service;

import com.migao.admin.dto.OrderDetailResponse;
import com.migao.admin.dto.OrderListResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.agent.AgentOrderResolveResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 接线判据（issue #8191，P2-1a）：{@link OrderService} 的查询门面**真的**委托到
 * {@link OrderQueryService}（同名方法 + 同参）。
 *
 * <p><b>为什么需要它</b>：本单拆的是「位置」—— 既有 148 条 {@code OrderServiceTest} 全都通过
 * 门面调用，它们<b>无论实现留在本类还是搬到新类都会绿</b>。所以「拆成功了吗」这件事，
 * 行为面判据看不见，必须单独钉一条<b>交互面</b>的目。</p>
 *
 * <p><b>红证（把委托改回内联实现 ⇒ 这里必红）</b>：门面一旦改回内联实现，
 * ① {@code verify(orderQueryService)} 拿不到交互 ⇒ 红；② 内联实现走的是真 Mapper
 * （本类只给了一个 {@code @Mock OrderQueryService}，其余协作者为 {@code null}）⇒ 更早地 NPE。
 * 实测见 PR body「接线判据红证」一节。</p>
 *
 * <p><b>边界（照实登记）</b>：本判据只管<b>门面 → 服务</b>这一次跳转；它不判
 * {@link OrderQueryService} 内部实现对不对（那由既有 {@code OrderServiceTest} 逐条行为判据承担），
 * 也不覆盖<b>静态委托</b>两点（{@code OrderService.resolveOrderIdToUuid} /
 * {@code OrderService.backfillSkuIdentity} —— 前者是私有入口、后者是静态转发，都不是实例交互）。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("接线判据：OrderService 查询门面必须委托 OrderQueryService（#8191 P2-1a）")
class OrderQueryServiceTest {

    @Mock
    private OrderQueryService orderQueryService;

    @InjectMocks
    private OrderService orderService;

    @BeforeEach
    void wireQueryService() {
        // Mockito 的 @InjectMocks 只做构造注入；{@code orderQueryService} 是**字段注入**
        // （理由见 OrderService 的字段注释：构造签名被多处测试显式装配）⇒ 显式装配。
        ReflectionTestUtils.setField(orderService, "orderQueryService", orderQueryService);
    }

    @Test
    @DisplayName("🔴 列表门面 getOrderPage ⇒ 委托 getOrderPage（16 个入参一个不少，返回值原样透传）")
    void getOrderPageDelegates() {
        PageResponse<OrderListResponse> expected = PageResponse.of(0L, 1L, 20L, List.of());
        when(orderQueryService.getOrderPage(1L, 20L, "confirmed", "kw", "following", Boolean.TRUE,
                "2026-01-01", "2026-01-31", "ORD-1", "张三", "P001", "窗帘", 7L, "u-1", "李四", "u-1"))
                .thenReturn(expected);

        PageResponse<OrderListResponse> actual = orderService.getOrderPage(1L, 20L, "confirmed", "kw",
                "following", Boolean.TRUE, "2026-01-01", "2026-01-31", "ORD-1", "张三", "P001", "窗帘",
                7L, "u-1", "李四", "u-1");

        assertThat(actual).isSameAs(expected);
        verify(orderQueryService).getOrderPage(1L, 20L, "confirmed", "kw", "following", Boolean.TRUE,
                "2026-01-01", "2026-01-31", "ORD-1", "张三", "P001", "窗帘", 7L, "u-1", "李四", "u-1");
    }

    @Test
    @DisplayName("🔴 C 端列表门面 getMyOrderPage ⇒ 委托 getMyOrderPage")
    void getMyOrderPageDelegates() {
        PageResponse<OrderListResponse> expected = PageResponse.of(0L, 1L, 20L, List.of());
        when(orderQueryService.getMyOrderPage(2L, 10L, "pending", 7L, "u-1", "13800138000"))
                .thenReturn(expected);

        PageResponse<OrderListResponse> actual = orderService.getMyOrderPage(2L, 10L, "pending", 7L, "u-1",
                "13800138000");

        assertThat(actual).isSameAs(expected);
        verify(orderQueryService).getMyOrderPage(2L, 10L, "pending", 7L, "u-1", "13800138000");
    }

    @Test
    @DisplayName("🔴 详情门面 getOrderById(id) ⇒ 委托单参重载")
    void getOrderByIdDelegates() {
        OrderDetailResponse expected = new OrderDetailResponse();
        when(orderQueryService.getOrderById("o-1")).thenReturn(expected);

        assertThat(orderService.getOrderById("o-1")).isSameAs(expected);
        verify(orderQueryService).getOrderById("o-1");
    }

    @Test
    @DisplayName("🔴 详情门面 getOrderById(id, dataScopeOwnerId) ⇒ 委托带范围的重载")
    void getOrderByIdWithScopeDelegates() {
        OrderDetailResponse expected = new OrderDetailResponse();
        when(orderQueryService.getOrderById("o-1", "u-owner")).thenReturn(expected);

        assertThat(orderService.getOrderById("o-1", "u-owner")).isSameAs(expected);
        verify(orderQueryService).getOrderById("o-1", "u-owner");
    }

    @Test
    @DisplayName("🔴 归属认定门面 existsForCurrentTenant ⇒ 委托（返回值原样透传，含 false）")
    void existsForCurrentTenantDelegates() {
        when(orderQueryService.existsForCurrentTenant("o-1")).thenReturn(false);

        assertThat(orderService.existsForCurrentTenant("o-1")).isFalse();
        verify(orderQueryService).existsForCurrentTenant("o-1");
    }

    @Test
    @DisplayName("🔴 单号解析门面 resolveOrderId ⇒ 委托（返回值原样透传）")
    void resolveOrderIdDelegates() {
        AgentOrderResolveResponse expected = AgentOrderResolveResponse.builder()
                .id("o-1")
                .orderNo("ORD-1")
                .itemCount(2)
                .build();
        when(orderQueryService.resolveOrderId("ORD-1", 7L)).thenReturn(expected);

        assertThat(orderService.resolveOrderId("ORD-1", 7L)).isSameAs(expected);
        verify(orderQueryService).resolveOrderId("ORD-1", 7L);
    }
}
