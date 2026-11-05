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
 * <p><b>第四批（issue #8681，P2-1e 第四批）</b>：{@code getOrderPage} / {@code getOrderById}（两个重载）
 * 的调用方（订单控制器列表与两处详情、建单服务回读）已改直连实现点，门面同名转发**删除** ⇒
 * 这三条委托判据同样失去对象，按同一口径改成<b>直测实现点</b>：列表判「服务端数据范围 / C 端用户隔离 /
 * 制单人模糊」三条条件是否真的进了查询（且缺省时**不**收窄）；详情判 404 与「范围外 = 不存在」
 * 两条 fail-closed 出口，并有一条「范围内真的读得到」的反向对照。</p>
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
    /** 详情转换要读物流（直测实现点时它自己读的第三个协作者）。 */
    @Mock
    private com.migao.admin.mapper.OrderLogisticsMapper orderLogisticsMapper;

    @InjectMocks
    private OrderService orderService;

    @BeforeEach
    void wireQueryService() {
        // Mockito 的 @InjectMocks 只做构造注入；{@code orderQueryService} 是**字段注入**
        // （理由见 OrderService 的字段注释：构造签名被多处测试显式装配）⇒ 显式装配。
        ReflectionTestUtils.setField(orderService, "orderQueryService", orderQueryService);
    }

    /**
     * 列表读面的三条**安全 / 语义条件**是否真的进了查询（门面转发已退休 ⇒ 直测实现点，issue #8681 第四批）。
     *
     * <p>判据形状：从 wrapper 的 SQL 段读条件。三条各自是独立口径，缺一条就有一类单据被看见或看不见：
     * ① 服务端角色范围（{@code dataScopeOwnerId}）⇒ {@code created_by} **精确**匹配；
     * ② C 端隔离（{@code userId}）⇒ {@code user_id} 精确匹配；
     * ③ 制单人（{@code creator}）⇒ {@code created_by_name} **模糊**匹配（快照列，不 join users）。
     * 反向对照：范围缺省时**不许**出现该条件（否则「不限范围」会被静默收窄成「只看自己」）。</p>
     */
    @Test
    @DisplayName("🔴 列表读面 getOrderPage（直测实现点）：服务端范围落 created_by、C 端 userId 落 user_id、制单人走模糊；范围缺省时不收窄")
    void getOrderPageAppliesScopeUserIsolationAndCreator() {
        Page<Order> empty = new Page<>(1L, 20L);
        empty.setRecords(List.of());
        empty.setTotal(0);
        when(orderMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class))).thenReturn(empty);

        OrderQueryService service = directQueryService();
        PageResponse<OrderListResponse> scoped = service.getOrderPage(1L, 20L, null, null, null, null,
                null, null, null, null, null, null, 7L, "u-2", "李四", "u-1");

        ArgumentCaptor<LambdaQueryWrapper<Order>> withScope = ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(orderMapper).selectPage(any(Page.class), withScope.capture());
        assertThat(withScope.getValue().getSqlSegment())
                .as("服务端角色范围（self）⇒ created_by 精确匹配")
                .contains("created_by =")
                .as("制单人 ⇒ created_by_name 模糊匹配（不是精确匹配）")
                .contains("created_by_name LIKE")
                .as("C 端隔离 ⇒ user_id 精确匹配")
                .contains("user_id =");
        assertThat(scoped.getItems()).as("空页如实返回空列表").isEmpty();

        // 反向对照：范围 / 用户 / 制单人全部缺省 ⇒ 三条条件一个都不许出现（不静默收窄）
        PageResponse<OrderListResponse> unscoped = service.getOrderPage(1L, 20L, null, null, null, null,
                null, null, null, null, null, null, 7L, null, null, null);

        ArgumentCaptor<LambdaQueryWrapper<Order>> noScope = ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(orderMapper, times(2)).selectPage(any(Page.class), noScope.capture());
        assertThat(noScope.getValue().getSqlSegment())
                .as("范围缺省 ⇒ 不加 created_by / user_id / created_by_name 条件")
                .doesNotContain("created_by")
                .doesNotContain("user_id");
        assertThat(unscoped.getItems()).isEmpty();
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

    /**
     * 单参详情的两条出口（门面转发已退休 ⇒ 直测实现点，issue #8681 第四批）：
     * 查不到 ⇒ 404「订单不存在」；查得到 ⇒ 按 id 读到的详情原样返回（反向对照，防「永远 404」的恒绿）。
     */
    @Test
    @DisplayName("🔴 详情读面 getOrderById(id)（直测实现点）：查不到 ⇒ 404 订单不存在；查得到 ⇒ 该 id 的详情")
    void getOrderByIdReadsThroughTheMapper() {
        OrderQueryService service = directQueryService();
        when(orderMapper.selectById("o-404")).thenReturn(null);

        assertThatThrownBy(() -> service.getOrderById("o-404"))
                .as("查不到 ⇒ 与其它读面同一个 404 话术")
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("订单不存在");

        when(orderMapper.selectById("o-1")).thenReturn(Order.builder()
                .id("o-1").tenantId(7L).orderNo("ORD-1").build());
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        when(orderLogisticsMapper.selectByOrderId(any(), any())).thenReturn(List.of());

        OrderDetailResponse detail = service.getOrderById("o-1");
        assertThat(detail.getId()).isEqualTo("o-1");
        assertThat(detail.getOrderNo()).isEqualTo("ORD-1");
    }

    /**
     * 数据范围收窄（门面转发已退休 ⇒ 直测实现点，issue #8681 第四批）。
     *
     * <p>核心语义：**范围外与「不存在」是同一个 404** —— 403 会告诉调用方「这个 id 存在，只是你看不到」，
     * 那本身就是泄露。反向对照两条：① 范围内的单真的读得到（防「永远 404」的恒绿）；
     * ② 范围缺省（{@code null}）⇒ 不收窄（既有单参语义逐字不变）。</p>
     */
    @Test
    @DisplayName("🔴 详情读面 + 数据范围（直测实现点）：范围外与不存在同一个 404；范围内读得到；null ⇒ 不收窄")
    void getOrderByIdOutOfScopeIsIndistinguishableFromMissing() {
        OrderQueryService service = directQueryService();
        when(orderMapper.selectById("o-1")).thenReturn(Order.builder()
                .id("o-1").tenantId(7L).createdBy("someone-else").orderNo("ORD-1").build());

        assertThatThrownBy(() -> service.getOrderById("o-1", "u-owner"))
                .as("范围外 ⇒ 与「不存在」同一句提示（不泄露存在性）")
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("订单不存在");

        when(orderMapper.selectById("o-2")).thenReturn(Order.builder()
                .id("o-2").tenantId(7L).createdBy("u-owner").orderNo("ORD-2").build());
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        when(orderLogisticsMapper.selectByOrderId(any(), any())).thenReturn(List.of());

        assertThat(service.getOrderById("o-2", "u-owner").getOrderNo())
                .as("范围内的单读得到 ⇒ 上面那条不是「永远 404」").isEqualTo("ORD-2");
        assertThat(service.getOrderById("o-1", null).getId())
                .as("范围缺省 ⇒ 不收窄（单参重载的语义）").isEqualTo("o-1");
    }

    // ── 以下两条（issue #8681，P2-1e）：门面的同名转发已随调用方迁移**删除** ────────────────
    // 判据**不删、不恒绿**：改成**直接测实现点**（真实 OrderQueryService，只 mock 它自己读的 Mapper）。
    // 「调用方不再走门面」这一半由 OrderFacadeForwarderRetirementTest 的载体判据承担。

    /** 直测用实现点：真实 OrderQueryService，只交给它 resolveOrderId / existsForCurrentTenant 会碰的协作者。 */
    private OrderQueryService directQueryService() {
        return new OrderQueryService(orderMapper, orderItemMapper, orderLogisticsMapper, null, null,
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
