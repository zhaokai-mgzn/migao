package com.migao.admin.service;

// case_ids: OR-016

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.dto.OrderCreateRequest;
import com.migao.admin.dto.OrderDetailResponse;
import com.migao.admin.dto.agent.AgentOrderCreateRequest;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * 订单写路径幂等接线（issue #4037，F19）—— {@code OrderService.createOrderForAgent}。
 *
 * <p>病根：ai-agent 工具超时 30s / HTTP 客户端超时 25s ⇒「订单已落库但客户端报失败」的窗口
 * 客观存在，LLM 重试 ⇒ **重复下单 = 直接资金损失**。修法：请求头
 * {@code X-Client-Request-Id} 作为幂等键，服务端按 (tenantId, 键) 去重：首次执行 + 快照落库，
 * 同键重复**不再执行**、直接回放首次 {@link OrderDetailResponse}。</p>
 *
 * <p>本类锁 6 条（每条都有红证，见 PR 证据表）：</p>
 * <ol>
 *   <li>同键第二次 ⇒ 底层写操作只被调用一次，且返回**首次那份快照**（同一订单号）；</li>
 *   <li><b>R2 负例</b>：不同键 ⇒ 两次都真的执行（合法输入不得被拦）；</li>
 *   <li>无请求头 ⇒ 完全走原路径（零幂等交互、不报错）——向后兼容未升级的调用方；</li>
 *   <li>同键但无快照（占位在飞/已失败）⇒ <b>fail-closed 抛错且绝不退化成再执行一次</b>；</li>
 *   <li>执行失败 ⇒ 占位被释放（{@code discard}），异常原样抛出（不吞）；</li>
 *   <li>执行成功 ⇒ 快照落库（{@code complete} 收到就是返回给调用方的那份 DTO）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("订单写路径幂等键接线（issue #4037）")
class OrderIdempotencyTest {

    private static final Long TENANT = 1L;
    private static final String KEY = "req-key-1";
    private static final String ENDPOINT = "POST /api/admin/agent/orders";

    @InjectMocks
    private OrderService orderService;
    /** 加工费组合价目表（issue #4406 的取价依赖；本类不涉及加工费口径 ⇒ 空表 ⇒ 未定价 0） */
    @Mock(lenient = true)
    private com.migao.admin.mapper.ProcessingFeeCombinationMapper processingFeeCombinationMapper;

    @Mock
    private OrderMapper orderMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private OrderLogisticsMapper orderLogisticsMapper;
    @Mock
    private CustomerService customerService;
    @Mock
    private ProductMapper productMapper;
    @Mock
    private ProductSkuMapper productSkuMapper;
    @Mock
    private FinanceTransactionMapper financeTransactionMapper;
    @Mock
    private com.fasterxml.jackson.databind.ObjectMapper objectMapper;
    @Mock
    private NotificationService notificationService;
    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private UserService userService;
    @Mock
    private ClientRequestIdService clientRequestIdService;

    private final AtomicInteger inserted = new AtomicInteger();

    @BeforeEach
    void setUp() {
        // issue #4406：取价点用**真实**对象（只桩价目表 Mapper）—— 金额算法仍走生产代码。
        // 为什么不用 @Mock：@InjectMocks 的构造注入发生在本方法之前 ⇒ 直接塞 mock 会把
        // 「谁发射加工费」这条接线本身也 mock 掉（接线判据就失去意义）。
        ReflectionTestUtils.setField(orderService, "processingFeeCalculator",
                new ProcessingFeeCalculator(processingFeeCombinationMapper));
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, OrderItem.class);

        // 每次 insert 分配一个不同的订单 id，并按 id 回读（createOrder 用 selectById 组装响应）
        when(orderMapper.insert(any(Order.class))).thenAnswer(inv -> {
            Order o = inv.getArgument(0);
            o.setId("order-" + inserted.incrementAndGet());
            return 1;
        });
        when(orderMapper.selectById("order-1")).thenReturn(
                Order.builder().id("order-1").orderNo("ORD-1").customerName("张三")
                        .status("pending").totalAmount(new BigDecimal("300.00")).build());
        when(orderMapper.selectById("order-2")).thenReturn(
                Order.builder().id("order-2").orderNo("ORD-2").customerName("张三")
                        .status("pending").totalAmount(new BigDecimal("300.00")).build());
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
    }

    @Test
    @DisplayName("同键第二次：不再执行底层写操作，回放首次 OrderDetailResponse（同一订单号）")
    void sameKeyReplaysFirstSnapshot() {
        when(clientRequestIdService.claim(TENANT, KEY, ENDPOINT)).thenReturn(true, false);

        OrderDetailResponse first = orderService.createOrderForAgent(request(KEY), TENANT);
        // 第二次到达：回放的就是首次那份快照（同一对象 ⇒ 同一订单号，这才叫幂等）
        when(clientRequestIdService.replay(TENANT, KEY, OrderDetailResponse.class))
                .thenReturn(Optional.of(first));
        OrderDetailResponse replayed = orderService.createOrderForAgent(request(KEY), TENANT);

        assertThat(first.getOrderNo()).isEqualTo("ORD-1");
        assertThat(replayed).isSameAs(first);
        verify(orderMapper, times(1)).insert(any(Order.class));
        verify(clientRequestIdService).complete(TENANT, KEY, first);
        verify(clientRequestIdService, times(1)).complete(anyLong(), anyString(), any());
    }

    @Test
    @DisplayName("R2 负例：不同幂等键 ⇒ 两次都真的执行（合法输入不得被拦）")
    void differentKeysBothExecute() {
        // 打桩精确到「键」这一维：只有请求**自带**的键才算首次。接线若把键写死/写错/传空，
        // claim 拿到的是未打桩的键（Mockito 布尔默认 false）⇒ 走回放分支 ⇒ 本断言立刻红
        when(clientRequestIdService.claim(TENANT, "req-key-1", ENDPOINT)).thenReturn(true);
        when(clientRequestIdService.claim(TENANT, "req-key-2", ENDPOINT)).thenReturn(true);

        OrderDetailResponse r1 = orderService.createOrderForAgent(request("req-key-1"), TENANT);
        OrderDetailResponse r2 = orderService.createOrderForAgent(request("req-key-2"), TENANT);

        assertThat(r1.getOrderNo()).isEqualTo("ORD-1");
        assertThat(r2.getOrderNo()).isEqualTo("ORD-2");
        verify(orderMapper, times(2)).insert(any(Order.class));
        verify(clientRequestIdService, never()).replay(anyLong(), anyString(), any());
        verify(clientRequestIdService).claim(TENANT, "req-key-2", ENDPOINT);
    }

    @Test
    @DisplayName("无幂等键：完全走原路径（零幂等交互、不报错）—— 向后兼容未升级的调用方")
    void noKeyKeepsLegacyPath() {
        OrderDetailResponse result = orderService.createOrderForAgent(request(null), TENANT);

        assertThat(result.getOrderNo()).isEqualTo("ORD-1");
        verify(orderMapper).insert(any(Order.class));
        verifyNoInteractions(clientRequestIdService);
    }

    @Test
    @DisplayName("同键但无可回放快照 ⇒ fail-closed 抛错，且绝不退化成「再执行一次」")
    void duplicateWithoutSnapshotFailsClosed() {
        when(clientRequestIdService.claim(TENANT, KEY, ENDPOINT)).thenReturn(false);
        when(clientRequestIdService.replay(TENANT, KEY, OrderDetailResponse.class))
                .thenReturn(Optional.empty());

        assertThatThrownBy(() -> orderService.createOrderForAgent(request(KEY), TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("请勿重复提交");

        verify(orderMapper, never()).insert(any(Order.class));
        verify(clientRequestIdService, never()).complete(anyLong(), anyString(), any());
    }

    @Test
    @DisplayName("执行失败 ⇒ 释放占位（discard）+ 异常原样抛出，不吞")
    void failureReleasesPlaceholder() {
        when(clientRequestIdService.claim(TENANT, KEY, ENDPOINT)).thenReturn(true);
        when(orderMapper.insert(any(Order.class))).thenThrow(new RuntimeException("DB 写失败"));

        assertThatThrownBy(() -> orderService.createOrderForAgent(request(KEY), TENANT))
                .isInstanceOf(RuntimeException.class)
                .hasMessageContaining("DB 写失败");

        verify(clientRequestIdService).discard(TENANT, KEY);
        verify(clientRequestIdService, never()).complete(anyLong(), anyString(), any());
    }

    @Test
    @DisplayName("校验类错误（未占位前抛出）：不得污染幂等表，也不得误标记为「已执行」")
    void validationErrorBeforeClaimDoesNotTouchKeys() {
        AgentOrderCreateRequest invalid = request(KEY);
        invalid.setCustomerPhone("12345");

        assertThatThrownBy(() -> orderService.createOrderForAgent(invalid, TENANT))
                .isInstanceOf(BusinessException.class);

        verifyNoInteractions(clientRequestIdService);
        verify(orderMapper, never()).insert(any(Order.class));
    }

    private AgentOrderCreateRequest request(String clientRequestId) {
        AgentOrderCreateRequest req = new AgentOrderCreateRequest();
        req.setCustomerName("张三");
        req.setCustomerPhone("13800001111");
        req.setClientRequestId(clientRequestId);
        OrderCreateRequest.OrderItemRequest item = new OrderCreateRequest.OrderItemRequest();
        item.setProductName("遮光窗帘");
        item.setQuantity(BigDecimal.valueOf(2));
        item.setUnitPrice(new BigDecimal("150"));
        // subtotal 必填（issue #4089 收敛：共享类型 @NotNull；本用例锁幂等语义，给它一个自洽值）
        item.setSubtotal(new BigDecimal("300.00"));
        req.setItems(List.of(item));
        return req;
    }
}