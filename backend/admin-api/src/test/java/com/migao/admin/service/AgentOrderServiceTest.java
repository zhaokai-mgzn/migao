package com.migao.admin.service;
// case_ids: OR-008

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
            AgentOrderCreateRequest.AgentOrderItem item = new AgentOrderCreateRequest.AgentOrderItem();
            item.setProductName("窗帘"); item.setQuantity(2);
            item.setUnitPrice(new BigDecimal("150"));
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

            when(orderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testOrder); // resolve UUID
            when(orderLogisticsMapper.selectByOrderId(eq("order-uuid-001"), any())).thenReturn(List.of()); // 无物流 → 新建
            when(orderLogisticsMapper.insert(any(OrderLogistics.class))).thenReturn(1);
            when(orderMapper.selectById("order-uuid-001")).thenReturn(testOrder); // 发货联动 + 详情
            when(orderMapper.update(any(), any())).thenReturn(1); // confirmed → shipped 原子流转
            when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());

            // when
            OrderDetailResponse result = (OrderDetailResponse)
                    orderService.updateOrderForAgent("order-uuid-001", req, 1L);

            // then: 创建物流记录 + 状态流转 shipped
            verify(orderLogisticsMapper).insert(org.mockito.ArgumentMatchers.<OrderLogistics>argThat(l ->
                    "顺丰".equals(l.getLogisticsCompany()) && "SF1234567890".equals(l.getTrackingNo())));
            verify(orderMapper).update(any(), any());
            assertThat(result).isNotNull();
        }

        @Test
        @DisplayName("已有物流记录时更新物流信息")
        void updatesExistingLogistics() {
            AgentOrderUpdateRequest req = buildRequest("中通", "ZT123456");

            OrderLogistics existing = OrderLogistics.builder()
                    .id("log-001").orderId("order-uuid-001").tenantId(1L)
                    .logisticsCompany("顺丰").trackingNo("SFOLD").status("in_transit").build();

            when(orderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testOrder);
            when(orderLogisticsMapper.selectByOrderId(eq("order-uuid-001"), any())).thenReturn(List.of(existing));
            when(orderLogisticsMapper.updateById(any(OrderLogistics.class))).thenReturn(1);
            when(orderMapper.selectById("order-uuid-001")).thenReturn(testOrder);
            when(orderMapper.update(any(), any())).thenReturn(1);
            when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());

            // when
            orderService.updateOrderForAgent("order-uuid-001", req, 1L);

            // then: 更新最新物流记录
            verify(orderLogisticsMapper).updateById(org.mockito.ArgumentMatchers.<OrderLogistics>argThat(l ->
                    "中通".equals(l.getLogisticsCompany()) && "ZT123456".equals(l.getTrackingNo())));
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

            // when
            orderService.updateOrderForAgent("order-uuid-001", req, 1L);

            // then: 发生状态流转（producing → shipped）
            verify(orderMapper).update(any(), any());
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
