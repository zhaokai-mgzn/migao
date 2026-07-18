package com.migao.admin.service;

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
}
