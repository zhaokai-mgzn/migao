// case_ids: OR-061
package com.migao.admin.service;

import com.migao.admin.dto.OrderCreateRequest;
import com.migao.admin.dto.OrderDetailResponse;
import com.migao.admin.dto.agent.AgentOrderCreateRequest;
import com.migao.admin.entity.Order;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 建单**实现点**的直测判据（issue #8681，P2-1e 第五批；取代原来那条「门面 ⇒ 委托」的接线判据）。
 *
 * <p><b>为什么改直测</b>：{@code OrderService.createOrder} 的转发已随调用方迁移<b>删除</b>（订单控制器直连
 * {@link OrderCreationService}）⇒ 原来那条「门面必须把 createOrder 转出去」的判据<b>失去对象</b>。按本单前几批
 * 的既定范式：**不删、不恒绿**，改成<b>直测实现点</b> + 把「调用方有没有直连实现点」交给
 * {@code OrderFacadeForwarderRetirementTest} 的退休／接线面（载体集合）。</p>
 *
 * <p><b>它判什么（两条互为正反）</b>：① 建单实现点跑的是**传入的那份门面实例**上的共享部件
 * （明细金额闸门 / 安装信息归一 / 服务端取价）—— 闸门抛 ⇒ 建单中止、一行不落（fail-closed）；
 * ② 闸门放行 ⇒ 流程**真的继续**向下（否则「闸门抛了就停」可以靠「永远抛」蒙混过关）。</p>
 *
 * <p><b>{@code createOrderForAgent} 为什么仍判「门面 ⇒ 委托」</b>：它是 Agent BFF 的一档，
 * 转发本批<b>没有</b>退休（按 #8681 的下一批清单第 5 项在 Agent BFF 收口时处理）⇒ 那一半的接线判据保留原样。</p>
 *
 * <p><b>红证方向</b>：把实现点里的共享部件调用改成「自己另造一份」或删掉 ⇒ ① 的 verify 与「零落库」当场红；
 * 把实现点改成入口即抛 ⇒ ② 红。两者都在同一份真实现上跑，不是内存谓词。</p>
 *
 * <p><b>复算</b>：{@code cd backend/admin-api && ./mvnw -Dtest=OrderCreationServiceTest test}。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("建单实现点直测 + Agent 建单门面仍须委托（#8191 P2-1b / #8681 P2-1e 第五批）")
class OrderCreationServiceTest {

    /** Agent 建单门面的委托目标（该转发本批未退休）。 */
    @Mock
    private OrderCreationService orderCreationServiceForFacade;

    /**
     * 建单实现点的**共享部件来源**：真实现点要求把一个 {@code OrderService} 实例传进去，建单与改单共用同一份
     * 明细装配 / 取价 / 库存前置（见 {@code OrderService} 类注释）。本类只判「它用的是不是**传进来的那一份**」，
     * 所以这里用 mock —— 真实现本身由 {@code OrderServiceTest} / {@code AgentOrderServiceTest} 等逐条承担。
     */
    @Mock
    private OrderService facadeSharedParts;

    @Mock
    private OrderMapper orderMapper;
    @Mock
    private ProductMapper productMapper;
    @Mock
    private ProductSkuMapper productSkuMapper;
    @Mock
    private CustomerService customerService;
    @Mock
    private UserService userService;
    @Mock
    private NotificationService notificationService;
    @Mock
    private ClientRequestIdService clientRequestIdService;
    @Mock
    private OrderPricingService orderPricingService;
    @Mock
    private ApprovalService approvalService;
    @Mock
    private OrderQueryService orderQueryService;

    @InjectMocks
    private OrderService orderService;

    /** 建单实现点（**真实例**，只桩它自己的协作者）。 */
    private OrderCreationService creationService;

    @BeforeEach
    void setUp() {
        // @InjectMocks 只做构造注入；orderCreationService 是字段注入（理由见 OrderService 的
        // creationService() 注释：构造签名被多处测试显式装配）⇒ 显式装配。
        ReflectionTestUtils.setField(orderService, "orderCreationService", orderCreationServiceForFacade);
        creationService = new OrderCreationService(orderMapper, productMapper, productSkuMapper,
                customerService, userService, notificationService, clientRequestIdService,
                orderPricingService, approvalService, orderQueryService);
    }

    // ──────────────────────── 判据 1：实现点真的走传入门面的共享部件（fail-closed）

    @Test
    @DisplayName("🔴 建单实现点：共享部件取自传入的门面实例 —— 明细闸门抛 ⇒ 建单中止、一行不落")
    void createOrderRunsTheSharedGateOnThePassedInFacade() {
        OrderCreateRequest request = requestWithOneItem();
        doThrow(BusinessException.validationError("数量不能小于 1"))
                .when(facadeSharedParts).assertItemAmountsValid(request.getItems());

        assertThatThrownBy(() -> creationService.createOrder(request, 7L, facadeSharedParts))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("数量不能小于 1");

        verify(facadeSharedParts).assertItemAmountsValid(request.getItems());
        verify(orderMapper, never()).insert(any(Order.class));
    }

    // ──────────────────────── 判据 2：反向对照（防「入口即抛」的恒绿）

    @Test
    @DisplayName("🔴 建单实现点：闸门放行 ⇒ 流程继续到安装信息归一与服务端取价（不是「永远抛」）")
    void createOrderProceedsPastTheGate() {
        OrderCreateRequest request = requestWithOneItem();
        // 取价点在真实现里是**第一处**带返回值的共享部件之后的下一个协作者 ⇒ 用它当「已越过闸门」的标记。
        when(orderPricingService.applyServerPrices(anyList(), any(), eq(7L)))
                .thenThrow(new IllegalStateException("reached-server-pricing"));

        assertThatThrownBy(() -> creationService.createOrder(request, 7L, facadeSharedParts))
                .isInstanceOf(IllegalStateException.class)
                .hasMessage("reached-server-pricing");

        verify(facadeSharedParts).assertItemAmountsValid(request.getItems());
        verify(facadeSharedParts).normalizeInstallRooms(request.getItems());
        verify(orderPricingService).applyServerPrices(request.getItems(), null, 7L);
        verify(orderMapper, never()).insert(any(Order.class));
    }

    // ──────────────────────── Agent 建单门面（本批未退休，判据保留原样）

    @Test
    @DisplayName("🔴 Agent 建单门面 createOrderForAgent ⇒ 委托（同样带 this）")
    void createOrderForAgentDelegates() {
        AgentOrderCreateRequest request = new AgentOrderCreateRequest();
        OrderDetailResponse expected = new OrderDetailResponse();
        when(orderCreationServiceForFacade.createOrderForAgent(request, 9L, orderService)).thenReturn(expected);

        OrderDetailResponse actual = orderService.createOrderForAgent(request, 9L);

        assertThat(actual).isSameAs(expected);
        verify(orderCreationServiceForFacade).createOrderForAgent(request, 9L, orderService);
    }

    // ──────────────────────── 夹具

    /** 一张最简请求：明细只有一行（金额口径由本类 mock 的共享部件决定，这里不承载语义）。 */
    private static OrderCreateRequest requestWithOneItem() {
        OrderCreateRequest request = new OrderCreateRequest();
        OrderCreateRequest.OrderItemRequest item = new OrderCreateRequest.OrderItemRequest();
        item.setProductId("prod-creation-service");
        item.setProductName("遮光窗帘");
        request.setItems(List.of(item));
        return request;
    }
}
