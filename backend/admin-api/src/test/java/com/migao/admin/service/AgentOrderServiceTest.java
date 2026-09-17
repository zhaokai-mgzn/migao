package com.migao.admin.service;
// case_ids: OR-008, OR-011

import com.migao.admin.dto.*;
import com.migao.admin.dto.agent.*;
import com.migao.admin.entity.*;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.*;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * Agent BFF OrderService 方法单元测试
 */
@ExtendWith(MockitoExtension.class)
@org.mockito.junit.jupiter.MockitoSettings(strictness = org.mockito.quality.Strictness.LENIENT)
class AgentOrderServiceTest {

    @InjectMocks private OrderService orderService;
    @Mock private OrderMapper orderMapper;
    @Mock private OrderItemMapper orderItemMapper;
    @Mock private OrderLogisticsMapper orderLogisticsMapper;
    @Mock(lenient = true) private com.migao.admin.service.CustomerService customerService;
    @Mock(lenient = true) private com.migao.admin.mapper.ProductMapper productMapper;
    @Mock(lenient = true) private com.migao.admin.mapper.ProductSkuMapper productSkuMapper;
    @Mock(lenient = true) private com.fasterxml.jackson.databind.ObjectMapper objectMapper;
    @Mock(lenient = true) private FinanceTransactionMapper financeTransactionMapper;
    @Mock(lenient = true) private ProcessingOrderMapper processingOrderMapper;
    /** 发货人兜底（issue #3768）：agent 无独立身份 → 取当前登录用户姓名 */
    @Mock(lenient = true) private UserService userService;

    private Order testOrder;

    @BeforeEach
    void setUp() {
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, OrderItem.class);

        testOrder = Order.builder()
                .id("order-uuid-001").orderNo("ORD-20250718001")
                .tenantId(1L).customerName("张三").customerPhone("13800001111")
                .status("confirmed").totalAmount(new BigDecimal("299.00")).build();
    }

    @Nested
    @DisplayName("Agent 创建订单")
    class CreateOrderForAgent {

        @Test
        @DisplayName("基本创建成功")
        void basicCreate() {
            AgentOrderCreateRequest req = new AgentOrderCreateRequest();
            req.setCustomerName("张三");
            req.setCustomerPhone("13800001111");
            OrderCreateRequest.OrderItemRequest item = new OrderCreateRequest.OrderItemRequest();
            item.setProductName("窗帘"); item.setQuantity(BigDecimal.valueOf(2));
            item.setUnitPrice(new BigDecimal("150"));
            item.setSubtotal(new BigDecimal("300.00"));
            req.setItems(List.of(item));

            when(orderMapper.insert(any(Order.class))).thenAnswer(inv -> {
                Order o = inv.getArgument(0); o.setId("order-new"); return 1;
            });
            when(orderMapper.selectById("order-new")).thenReturn(
                    Order.builder().id("order-new").orderNo("ORD-new")
                            .customerName("张三").status("pending")
                            .totalAmount(new BigDecimal("300.00")).build());
            when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());

            OrderDetailResponse result = orderService.createOrderForAgent(req, 1L);
            assertThat(result).isNotNull();
            assertThat(result.getCustomerName()).isEqualTo("张三");
        }

        @Test
        @DisplayName("手机号格式错误 → 抛异常")
        void invalidPhone() {
            AgentOrderCreateRequest req = new AgentOrderCreateRequest();
            req.setCustomerName("张三"); req.setCustomerPhone("12345");
            assertThatThrownBy(() -> orderService.createOrderForAgent(req, 1L))
                    .isInstanceOf(BusinessException.class);
        }

        @Test
        @DisplayName("缺少客户姓名 → 抛异常")
        void missingName() {
            AgentOrderCreateRequest req = new AgentOrderCreateRequest();
            req.setCustomerPhone("13800001111");
            assertThatThrownBy(() -> orderService.createOrderForAgent(req, 1L))
                    .isInstanceOf(BusinessException.class);
        }

        @Test
        @DisplayName("缺少商品明细 → 抛异常")
        void missingItems() {
            AgentOrderCreateRequest req = new AgentOrderCreateRequest();
            req.setCustomerName("张三"); req.setCustomerPhone("13800001111");
            assertThatThrownBy(() -> orderService.createOrderForAgent(req, 1L))
                    .isInstanceOf(BusinessException.class);
        }

        // ============ GB/T 47746-2026 M3 服务端取价校验（issue #2806） ============

        /**
         * 取价校验请求构造（issue #4089 收敛后）：规格键（skuCode/colorName）**只在
         * processingInfo 内**——DTO 不再有顶层同类字段（旧 AgentOrderItem 已删）。
         */
        private AgentOrderCreateRequest buildPriceReq(String skuCode, String colorName,
                                                      BigDecimal unitPrice, Object processingInfo) {
            AgentOrderCreateRequest req = new AgentOrderCreateRequest();
            req.setCustomerName("张三"); req.setCustomerPhone("13800001111");
            OrderCreateRequest.OrderItemRequest item = new OrderCreateRequest.OrderItemRequest();
            item.setProductName("遮光窗帘"); item.setProductId("p-001");
            Map<String, Object> info = new java.util.HashMap<>();
            if (processingInfo instanceof Map<?, ?> given) {
                given.forEach((k, v) -> info.put(String.valueOf(k), v));
            }
            if (skuCode != null) { info.put("skuCode", skuCode); }
            if (colorName != null) { info.put("colorName", colorName); }
            item.setProcessingInfo(info.isEmpty() ? null : info);
            item.setQuantity(BigDecimal.valueOf(2)); item.setUnitPrice(unitPrice);
            // subtotal 必填（共享类型 @NotNull；收敛前 agent 侧可选）
            item.setSubtotal(unitPrice == null ? null : unitPrice.multiply(BigDecimal.valueOf(2)));
            req.setItems(List.of(item));
            return req;
        }

        private void mockOrderInsert() {
            when(orderMapper.insert(any(Order.class))).thenAnswer(inv -> {
                Order o = inv.getArgument(0); o.setId("order-new"); return 1;
            });
            when(orderMapper.selectById("order-new")).thenReturn(
                    Order.builder().id("order-new").orderNo("ORD-new")
                            .customerName("张三").status("pending")
                            .totalAmount(new BigDecimal("300.00")).build());
            when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        }

        @Test
        @DisplayName("取价校验：skuCode 可解析且单价一致 → 成功（M3）")
        void priceMatchBySkuCode() {
            AgentOrderCreateRequest req = buildPriceReq("SKU-001", null, new BigDecimal("150"), null);
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(ProductSku.builder().id(1L).price(new BigDecimal("150")).build()));
            mockOrderInsert();

            OrderDetailResponse result = orderService.createOrderForAgent(req, 1L);
            assertThat(result).isNotNull();
            verify(productSkuMapper).selectList(any(LambdaQueryWrapper.class));
        }

        @Test
        @DisplayName("取价校验：processingInfo 内 colorName 可解析且单价一致 → 成功（M3，兼容 ai-agent 现状）")
        void priceMatchFromProcessingInfo() {
            AgentOrderCreateRequest req = buildPriceReq(null, null, new BigDecimal("150"),
                    Map.of("colorName", "白色"));
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(ProductSku.builder().id(1L).price(new BigDecimal("150")).build()));
            mockOrderInsert();

            OrderDetailResponse result = orderService.createOrderForAgent(req, 1L);
            assertThat(result).isNotNull();
            verify(productSkuMapper).selectList(any(LambdaQueryWrapper.class));
        }

        @Test
        @DisplayName("取价校验：SKU 可解析但单价不一致 → 拒绝并附权威价（M3）")
        void priceMismatchRejected() {
            AgentOrderCreateRequest req = buildPriceReq("SKU-001", null, new BigDecimal("160"), null);
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(ProductSku.builder().id(1L).price(new BigDecimal("150")).build()));

            assertThatThrownBy(() -> orderService.createOrderForAgent(req, 1L))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("单价与系统价格不一致")
                    .hasMessageContaining("系统价 150.00");
        }

        @Test
        @DisplayName("取价校验：SKU 无法解析 → 不拦截（防误伤）")
        void priceUnresolvableSkips() {
            AgentOrderCreateRequest req = buildPriceReq("SKU-NOPE", null, new BigDecimal("999"), null);
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
            mockOrderInsert();

            OrderDetailResponse result = orderService.createOrderForAgent(req, 1L);
            assertThat(result).isNotNull();
        }

        @Test
        @DisplayName("取价校验：SKU 歧义（命中多条）→ 不拦截")
        void priceAmbiguousSkips() {
            AgentOrderCreateRequest req = buildPriceReq(null, "白色", new BigDecimal("150"), null);
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(
                            ProductSku.builder().id(1L).price(new BigDecimal("150")).build(),
                            ProductSku.builder().id(2L).price(new BigDecimal("180")).build()));
            mockOrderInsert();

            OrderDetailResponse result = orderService.createOrderForAgent(req, 1L);
            assertThat(result).isNotNull();
        }

        // ============ 参数范围闸门（issue #3622：负数量/负单价不得落库） ============
        //
        // issue #4089 收敛后：agent 路径入参就是 OrderCreateRequest 的子类型（同一组注解），
        // Bean Validation 在控制器层执行；本组锁的是 createOrder() 共享入口的显式判定 ——
        // 它兜的是**绕过 HTTP 的程序化调用方**（不是"手工 new 让注解失效"导致的第二套口径）。

        private AgentOrderCreateRequest buildQtyReq(BigDecimal quantity, BigDecimal unitPrice) {
            AgentOrderCreateRequest req = new AgentOrderCreateRequest();
            req.setCustomerName("张三");
            req.setCustomerPhone("13800001111");
            OrderCreateRequest.OrderItemRequest item = new OrderCreateRequest.OrderItemRequest();
            item.setProductName("遮光窗帘");
            item.setQuantity(quantity);
            item.setUnitPrice(unitPrice);
            item.setSubtotal(unitPrice == null ? null
                    : unitPrice.multiply(quantity == null ? BigDecimal.ZERO : quantity));
            req.setItems(List.of(item));
            return req;
        }

        @Test
        @DisplayName("负数量 → 拒绝（不 insert 订单：负金额会污染总额，负需求还绕过库存校验）")
        void negativeQuantityRejected() {
            AgentOrderCreateRequest req = buildQtyReq(BigDecimal.valueOf(-3), new BigDecimal("168"));

            assertThatThrownBy(() -> orderService.createOrderForAgent(req, 1L))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("数量");

            verify(orderMapper, never()).insert(any(Order.class));
        }

        @Test
        @DisplayName("0 数量 → 拒绝（0 元明细）")
        void zeroQuantityRejected() {
            AgentOrderCreateRequest req = buildQtyReq(BigDecimal.valueOf(0), new BigDecimal("168"));

            assertThatThrownBy(() -> orderService.createOrderForAgent(req, 1L))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("数量");

            verify(orderMapper, never()).insert(any(Order.class));
        }

        @Test
        @DisplayName("负单价 → 拒绝（负单价 × 数量 = 负金额）")
        void negativeUnitPriceRejected() {
            AgentOrderCreateRequest req = buildQtyReq(BigDecimal.valueOf(3), new BigDecimal("-168"));

            assertThatThrownBy(() -> orderService.createOrderForAgent(req, 1L))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("单价");

            verify(orderMapper, never()).insert(any(Order.class));
        }

        @Test
        @DisplayName("0 单价 → 拒绝")
        void zeroUnitPriceRejected() {
            AgentOrderCreateRequest req = buildQtyReq(BigDecimal.valueOf(3), BigDecimal.ZERO);

            assertThatThrownBy(() -> orderService.createOrderForAgent(req, 1L))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("单价");

            verify(orderMapper, never()).insert(any(Order.class));
        }

        @Test
        @DisplayName("合法数量/单价 → 仍可下单（防过严：闸门不是「永远下不了单」）")
        void legalQuantityAndPriceStillPass() {
            AgentOrderCreateRequest req = buildQtyReq(BigDecimal.valueOf(3), new BigDecimal("168"));
            mockOrderInsert();

            OrderDetailResponse result = orderService.createOrderForAgent(req, 1L);

            assertThat(result).isNotNull();
            verify(orderMapper).insert(any(Order.class));
        }
    }

    @Nested
    @DisplayName("createOrder 共享入口的参数闸门（#3622：程序化调用同样拦住）")
    class CreateOrderSharedGuard {

        private OrderCreateRequest buildReq(BigDecimal quantity, BigDecimal unitPrice) {
            OrderCreateRequest req = new OrderCreateRequest();
            req.setCustomerName("张三");
            req.setCustomerPhone("13800001111");
            OrderCreateRequest.OrderItemRequest item = new OrderCreateRequest.OrderItemRequest();
            item.setProductName("遮光窗帘");
            item.setQuantity(quantity);
            item.setUnitPrice(unitPrice);
            item.setSubtotal(unitPrice == null ? null
                    : unitPrice.multiply(quantity == null ? BigDecimal.ZERO : quantity));
            req.setItems(List.of(item));
            return req;
        }

        @Test
        @DisplayName("createOrder（绕过 @Valid 的程序化调用）负数量 → 拒绝且不落库")
        void negativeQuantityRejectedInSharedEntry() {
            OrderCreateRequest req = buildReq(BigDecimal.valueOf(-2), new BigDecimal("100"));

            assertThatThrownBy(() -> orderService.createOrder(req, 1L))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("数量");

            verify(orderMapper, never()).insert(any(Order.class));
        }

        @Test
        @DisplayName("createOrder 负单价 → 拒绝且不落库")
        void negativeUnitPriceRejectedInSharedEntry() {
            OrderCreateRequest req = buildReq(BigDecimal.valueOf(2), new BigDecimal("-100"));

            assertThatThrownBy(() -> orderService.createOrder(req, 1L))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("单价");

            verify(orderMapper, never()).insert(any(Order.class));
        }

        @Test
        @DisplayName("createOrder 合法值 → 照旧成功（防过严）")
        void legalValuesStillPassInSharedEntry() {
            OrderCreateRequest req = buildReq(BigDecimal.valueOf(2), new BigDecimal("100"));
            mockOrderInsert2();

            OrderDetailResponse result = orderService.createOrder(req, 1L);

            assertThat(result).isNotNull();
            verify(orderMapper).insert(any(Order.class));
        }

        // ── 数量下限 1（issue #3682）：<1 会被库存/销量按 0 件计 → 静默漏扣 ──
        //
        // 为什么 Service 层必须有：本类是「程序化调用」的唯一防线 ——
        // `createOrderForAgent` 手工 new `OrderCreateRequest` 转交 `createOrder()`，
        // 不过 Bean Validation（@DecimalMin 对它无效），故实体判据在 Service 里。

        @Test
        @DisplayName("createOrder 数量 0.5 → 拒绝且不落库（#3682：intValue()->0 → 不扣库存、销量 +0）")
        void subOneQuantityRejectedInSharedEntry() {
            OrderCreateRequest req = buildReq(new BigDecimal("0.5"), new BigDecimal("100"));

            assertThatThrownBy(() -> orderService.createOrder(req, 1L))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("数量")
                    .hasMessageContaining("1");

            verify(orderMapper, never()).insert(any(Order.class));
        }

        @Test
        @DisplayName("createOrder Agent 路径数量 0.5 → 拒绝（createOrderForAgent 同样受影响）")
        void subOneQuantityRejectedOnAgentPath() {
            AgentOrderCreateRequest req = new AgentOrderCreateRequest();
            req.setCustomerName("张三");
            req.setCustomerPhone("13800001111");
            OrderCreateRequest.OrderItemRequest item = new OrderCreateRequest.OrderItemRequest();
            item.setProductName("遮光窗帘");
            item.setQuantity(new BigDecimal("0.5"));
            item.setUnitPrice(new BigDecimal("168"));
            item.setSubtotal(new BigDecimal("84.00"));
            req.setItems(List.of(item));

            assertThatThrownBy(() -> orderService.createOrderForAgent(req, 1L))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("数量");

            verify(orderMapper, never()).insert(any(Order.class));
        }

        @Test
        @DisplayName("createOrder 数量 1 与 8.4 → 照旧成功（下限不误伤整数与小数，OR-028 口径）")
        void minimumAndDecimalQuantityStillPassInSharedEntry() {
            OrderCreateRequest req = buildReq(new BigDecimal("1"), new BigDecimal("100"));
            mockOrderInsert2();
            assertThat(orderService.createOrder(req, 1L)).as("数量 1 = 下限值，必须放行").isNotNull();
            verify(orderMapper).insert(any(Order.class));

            OrderCreateRequest decimalReq = buildReq(new BigDecimal("8.4"), new BigDecimal("100"));
            mockOrderInsert2();
            assertThat(orderService.createOrder(decimalReq, 1L))
                    .as("数量 8.4（per_area 面积）≥1，必须放行").isNotNull();
            verify(orderMapper, times(2)).insert(any(Order.class));
        }

        private void mockOrderInsert2() {
            when(orderMapper.insert(any(Order.class))).thenAnswer(inv -> {
                Order o = inv.getArgument(0);
                o.setId("order-new");
                return 1;
            });
            when(orderMapper.selectById("order-new")).thenReturn(
                    Order.builder().id("order-new").orderNo("ORD-new")
                            .customerName("张三").status("pending")
                            .totalAmount(new BigDecimal("200.00")).build());
            when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        }
    }

    @Nested
    @DisplayName("订单 ID 解析")
    class ResolveOrderId {

        @Test
        @DisplayName("未找到 → 抛 BusinessException")
        void notFound() {
            when(orderMapper.selectById("notexist")).thenReturn(null);
            when(orderMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());

            assertThatThrownBy(() -> orderService.resolveOrderId("notexist", 1L))
                    .isInstanceOf(BusinessException.class);
        }
    }

    @Nested
    @DisplayName("Agent 统一更新 - update_logistics（发货）")
    class UpdateLogistics {

        private AgentOrderUpdateRequest buildRequest(String company, String trackingNumber) {
            AgentOrderUpdateRequest req = new AgentOrderUpdateRequest();
            req.setAction("update_logistics");
            req.setLogisticsCompany(company);
            req.setTrackingNumber(trackingNumber);
            return req;
        }

        @Test
        @DisplayName("无物流记录时新建物流并将 confirmed 订单流转为 shipped")
        void createsLogisticsAndShips() {
            AgentOrderUpdateRequest req = buildRequest("顺丰", "SF1234567890");
            // 发货人兜底：agent 透传的 X-User-Id → users.nickname
            when(userService.resolveCurrentUserDisplayName()).thenReturn("李四");

            when(orderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testOrder); // resolve UUID
            when(orderLogisticsMapper.selectByOrderId(eq("order-uuid-001"), any())).thenReturn(List.of()); // 无物流 → 新建
            when(orderLogisticsMapper.insert(any(OrderLogistics.class))).thenReturn(1);
            when(orderMapper.selectById("order-uuid-001")).thenReturn(testOrder); // 发货联动 + 详情
            when(orderMapper.update(any(), any())).thenReturn(1); // confirmed → shipped 原子流转
            when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
            when(orderItemMapper.selectByOrderId(any(), any())).thenReturn(List.of()); // 加工单守卫：无加工项

            // when
            OrderDetailResponse result = (OrderDetailResponse)
                    orderService.updateOrderForAgent("order-uuid-001", req, 1L);

            // then: 创建物流记录（含发货人兜底）+ 状态流转 shipped
            verify(orderLogisticsMapper).insert(org.mockito.ArgumentMatchers.<OrderLogistics>argThat(l ->
                    "顺丰".equals(l.getLogisticsCompany()) && "SF1234567890".equals(l.getTrackingNo())
                            && "李四".equals(l.getShipperName())));
            verify(orderMapper).update(any(), any());
            assertThat(result).isNotNull();
        }

        @Test
        @DisplayName("已有物流记录时更新物流信息")
        void updatesExistingLogistics() {
            AgentOrderUpdateRequest req = buildRequest("中通", "ZT123456");
            // 关键判别力：当前操作人**有名字**。若实现用「兜底值」去覆盖已记录的发货人，
            // 这里就会把「李四」改成「王五」→ 断言红。（不 stub 的话兜底恒为 null，
            // 缺陷实现也能"看起来对"——那是无判别力的假绿）
            when(userService.resolveCurrentUserDisplayName()).thenReturn("王五");

            OrderLogistics existing = OrderLogistics.builder()
                    .id("log-001").orderId("order-uuid-001").tenantId(1L)
                    .logisticsCompany("顺丰").trackingNo("SFOLD").shipperName("李四").status("in_transit").build();

            when(orderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testOrder);
            when(orderLogisticsMapper.selectByOrderId(eq("order-uuid-001"), any())).thenReturn(List.of(existing));
            when(orderLogisticsMapper.updateById(any(OrderLogistics.class))).thenReturn(1);
            when(orderMapper.selectById("order-uuid-001")).thenReturn(testOrder);
            when(orderMapper.update(any(), any())).thenReturn(1);
            when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
            when(orderItemMapper.selectByOrderId(any(), any())).thenReturn(List.of()); // 加工单守卫：无加工项

            // when
            orderService.updateOrderForAgent("order-uuid-001", req, 1L);

            // then: 更新最新物流记录，且**不覆盖**已记录的发货人
            // （改运单号/纠错 ≠ 换发货人；agent 本次操作人不该顶替首发的经手人）
            verify(orderLogisticsMapper).updateById(org.mockito.ArgumentMatchers.<OrderLogistics>argThat(l ->
                    "中通".equals(l.getLogisticsCompany()) && "ZT123456".equals(l.getTrackingNo())
                            && "李四".equals(l.getShipperName())));
        }

        @Test
        @DisplayName("存量订单（发货人为空）改运单号：不为历史数据猜经手人")
        void doesNotGuessShipperForLegacyRecord() {
            AgentOrderUpdateRequest req = buildRequest("中通", "ZT123456");
            // 关键判别力：当前操作人**有名字** —— 缺陷实现会把「王五」写进历史订单，
            // 于是纸面上出现一个从未发过这批货的经手人
            when(userService.resolveCurrentUserDisplayName()).thenReturn("王五");

            OrderLogistics legacy = OrderLogistics.builder()
                    .id("log-002").orderId("order-uuid-001").tenantId(1L)
                    .logisticsCompany("顺丰").trackingNo("SFOLD").status("in_transit").build(); // shipperName = null

            when(orderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testOrder);
            when(orderLogisticsMapper.selectByOrderId(eq("order-uuid-001"), any())).thenReturn(List.of(legacy));
            when(orderLogisticsMapper.updateById(any(OrderLogistics.class))).thenReturn(1);
            when(orderMapper.selectById("order-uuid-001")).thenReturn(testOrder);
            when(orderMapper.update(any(), any())).thenReturn(1);
            when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
            when(orderItemMapper.selectByOrderId(any(), any())).thenReturn(List.of());

            // when
            orderService.updateOrderForAgent("order-uuid-001", req, 1L);

            // then: 发货人保持 null（宁可空白显示「-」，也不把当次操作人写成历史经手人）
            verify(orderLogisticsMapper).updateById(org.mockito.ArgumentMatchers.<OrderLogistics>argThat(l ->
                    l.getShipperName() == null));
        }

        @Test
        @DisplayName("producing 订单记录物流后流转为 shipped")
        void shipsProducingOrder() {
            AgentOrderUpdateRequest req = buildRequest("顺丰", "SF999");

            testOrder.setStatus("producing");
            when(orderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testOrder);
            when(orderLogisticsMapper.selectByOrderId(eq("order-uuid-001"), any())).thenReturn(List.of());
            when(orderLogisticsMapper.insert(any(OrderLogistics.class))).thenReturn(1);
            when(orderMapper.selectById("order-uuid-001")).thenReturn(testOrder);
            when(orderMapper.update(any(), any())).thenReturn(1);
            when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
            when(orderItemMapper.selectByOrderId(any(), any())).thenReturn(List.of()); // 加工单守卫：无加工项

            // when
            orderService.updateOrderForAgent("order-uuid-001", req, 1L);

            // then: 发生状态流转（producing → shipped）
            verify(orderMapper).update(any(), any());
        }

        @Test
        @DisplayName("P1 复核修复（PG-009）：含加工项订单经 agent 发货路径无 completed 加工单 → 拒绝")
        void shipsRejectedViaAgentPathWithoutCompletedProcessingOrder() {
            AgentOrderUpdateRequest req = buildRequest("顺丰", "SF001");
            testOrder.setStatus("producing");
            when(orderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testOrder);
            when(orderMapper.selectById("order-uuid-001")).thenReturn(testOrder);
            when(orderLogisticsMapper.selectByOrderId(eq("order-uuid-001"), any())).thenReturn(List.of());
            when(orderLogisticsMapper.insert(any(OrderLogistics.class))).thenReturn(1);
            // 含加工项 + 无 completed 加工单
            com.migao.admin.entity.OrderItem item = com.migao.admin.entity.OrderItem.builder()
                    .id("item-1").orderId("order-uuid-001").productName("布艺遮光帘A")
                    .processingInfo(Map.of("processingItems", List.of(Map.of("id", "p1", "name", "打孔"))))
                    .build();
            when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(item));
            when(processingOrderMapper.countCompletedByOrderId("order-uuid-001", 1L)).thenReturn(0L);

            // when
            assertThatThrownBy(() -> orderService.updateOrderForAgent("order-uuid-001", req, 1L))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("须先完成加工单");

            // then: 未发生 shipped 流转
            verify(orderMapper, never()).update(any(), any());
        }

        @Test
        @DisplayName("缺少快递公司/运单号被拒绝")
        void rejectsMissingFields() {
            when(orderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testOrder);

            AgentOrderUpdateRequest noCompany = buildRequest(null, "SF123");
            assertThatThrownBy(() -> orderService.updateOrderForAgent("order-uuid-001", noCompany, 1L))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("logisticsCompany");

            AgentOrderUpdateRequest noTracking = buildRequest("顺丰", null);
            assertThatThrownBy(() -> orderService.updateOrderForAgent("order-uuid-001", noTracking, 1L))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("trackingNumber");
        }

        @Test
        @DisplayName("Agent refund - 传递退款金额到 refundOrder")
        void refundPassesRefundAmount() {
            AgentOrderUpdateRequest req = new AgentOrderUpdateRequest();
            req.setAction("refund");
            req.setRefundAmount(new BigDecimal("100.00"));
            req.setRefundReason("部分退款");

            when(orderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testOrder);
            when(orderMapper.selectById("order-uuid-001")).thenReturn(testOrder);
            when(orderMapper.update(any(), any(com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper.class))).thenReturn(1);
            when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());

            // when
            orderService.updateOrderForAgent("order-uuid-001", req, 1L);

            // then: refundOrder 以 3 参调用，原子累加退款金额（审计 07 P1-10）
            assertThat(testOrder.getRefundAmount()).isEqualByComparingTo("100.00");
            verify(orderMapper).update(isNull(), any(com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper.class));
        }
    }
}
