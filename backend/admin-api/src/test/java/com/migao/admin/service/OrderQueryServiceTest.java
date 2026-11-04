// case_ids: OR-061
package com.migao.admin.service;

import com.migao.admin.dto.OrderDetailResponse;
import com.migao.admin.dto.OrderListResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.agent.AgentOrderResolveResponse;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.times;
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
 * <p><b>第二批（issue #8681，P2-1e 第二批）</b>：{@code getMyOrderPage} 的调用方（Agent 控制器
 * C 端「我的订单」端点）已改直连实现点、门面同名转发**删除** ⇒ 对应的委托判据失去对象。
 * 按本文件既有口径（不删、不恒绿）改成<b>直测实现点</b>：用真实 {@link OrderQueryService}
 * 判「用户级隔离条件是否真的进了查询」，并钉住缺用户标识时**拒绝且不查库**。</p>
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
    /** 直测实现点时它自己读的两个协作者（issue #8681，P2-1e）。 */
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private OrderItemMapper orderItemMapper;

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

    /**
     * C 端「我的订单」的**用户级隔离**（门面转发已退休 ⇒ 改直测实现点，issue #8681 第二批）。
     *
     * <p>判据形状：从查询 wrapper 的 SQL 段读「隔离条件是否真的进了查询」—— 这是这条查询的
     * 安全语义本体（{@code user_id} 直配；**只有**带绑定手机号时才追加「该单未被归属 且
     * 手机号等于本人」的兜底）。另一半是 fail-closed 出口：缺用户标识 ⇒ 拒绝**且一次都不查库**。</p>
     */
    @Test
    @DisplayName("🔴 C 端我的订单（直测实现点）：user_id 直配、仅绑定手机号才追加「未归属 + 同手机号」兜底；缺标识 ⇒ 拒绝且不查库")
    void getMyOrderPageIsolatesByUser() {
        Page<Order> empty = new Page<>(1L, 10L);
        empty.setRecords(List.of());
        empty.setTotal(0);
        when(orderMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class))).thenReturn(empty);

        OrderQueryService service = directQueryService();
        service.getMyOrderPage(1L, 10L, null, 7L, "u-1", null);

        ArgumentCaptor<LambdaQueryWrapper<Order>> noPhone = ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(orderMapper).selectPage(any(Page.class), noPhone.capture());
        assertThat(noPhone.getValue().getSqlSegment())
                .as("没有绑定手机号 ⇒ 只按 user_id 直配，不许出现手机号兜底条件")
                .contains("user_id")
                .doesNotContain("customer_phone");

        service.getMyOrderPage(1L, 10L, null, 7L, "u-1", " 13800138000 ");

        ArgumentCaptor<LambdaQueryWrapper<Order>> withPhone = ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(orderMapper, times(2)).selectPage(any(Page.class), withPhone.capture());
        assertThat(withPhone.getValue().getSqlSegment())
                .as("有绑定手机号 ⇒ 追加「未归属 + 手机号相等」兜底（手机号去空白后参与比较）")
                .contains("user_id")
                .contains("customer_phone");

        assertThatThrownBy(() -> service.getMyOrderPage(1L, 10L, null, 7L, "internal-service", null))
                .as("缺用户标识 ⇒ fail-closed")
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("缺少用户标识");
        // 拒绝的这条路径一次都不许查库（查库次数仍是 2）
        verify(orderMapper, times(2)).selectPage(any(Page.class), any(LambdaQueryWrapper.class));
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

    // ── 以下两条（issue #8681，P2-1e）：门面的同名转发已随调用方迁移**删除** ────────────────
    // 判据**不删、不恒绿**：改成**直接测实现点**（真实 OrderQueryService，只 mock 它自己读的 Mapper）。
    // 「调用方不再走门面」这一半由 OrderFacadeForwarderRetirementTest 的载体判据承担。

    /** 直测用实现点：真实 OrderQueryService，只交给它 resolveOrderId / existsForCurrentTenant 会碰的协作者。 */
    private OrderQueryService directQueryService() {
        return new OrderQueryService(orderMapper, orderItemMapper, null, null, null,
                new ObjectMapper(), null, new com.migao.admin.time.BusinessClock());
    }

    /**
     * 归属认定 = {@code orderMapper.selectById} 的「查得到吗」（租户条件由拦截器追加）。
     */
    @Test
    @DisplayName("🔴 归属认定 existsForCurrentTenant（直测实现点）：本租户查得到 ⇒ true；查不到 ⇒ false")
    void existsForCurrentTenantIsTheMapperTruth() {
        OrderQueryService service = directQueryService();
        when(orderMapper.selectById("o-1")).thenReturn(new Order());

        assertThat(service.existsForCurrentTenant("o-1")).isTrue();
        assertThat(service.existsForCurrentTenant("o-404")).isFalse();
    }

    /**
     * 单号解析的两条 fail-closed 出口（空关键词 / 解析不到），话术与拆分前逐字一致。
     */
    @Test
    @DisplayName("🔴 单号解析 resolveOrderId（直测实现点）：关键词为空 ⇒ 校验失败；解析不到 ⇒ ORDER_NOT_FOUND")
    void resolveOrderIdFailsClosed() {
        OrderQueryService service = directQueryService();

        assertThatThrownBy(() -> service.resolveOrderId("   ", 7L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("keyword 不能为空");
        assertThatThrownBy(() -> service.resolveOrderId("NOPE", 7L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("未找到匹配的订单：NOPE");
    }

    /** MyBatis-Plus 的 Lambda 列名是惰性解析的（不预热 ⇒ can not find lambda cache）。 */
    @org.junit.jupiter.api.BeforeAll
    static void primeMybatisPlusLambdaCache() {
        com.baomidou.mybatisplus.core.MybatisConfiguration configuration =
                new com.baomidou.mybatisplus.core.MybatisConfiguration();
        org.apache.ibatis.builder.MapperBuilderAssistant assistant =
                new org.apache.ibatis.builder.MapperBuilderAssistant(configuration, "");
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(assistant, Order.class);
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(assistant, OrderItem.class);
    }
}
