// case_ids: PG-001, OR-001
// #3887：订单还没有加工单是正常状态 —— GET /api/admin/processing-orders/{orderId}
// 应返回 200 + data null（前端 ProcessingOrderBlock 走 setNotFound(!data) 展示「生成加工单」态），
// 只有订单本身也不存在（真无效 ID）才 404 + NOT_FOUND。

package com.migao.admin.controller;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.service.OrderService;
import com.migao.admin.service.ProcessingOrderService;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * ProcessingOrder detail 端点契约（issue #3887）：
 * 走真实 ProcessingOrderService + mock mapper 的全链路 MockMvc 测试，
 * 覆盖「订单无加工单是正常状态」三态：无加工单→200+data null / 乱 ID→404+NOT_FOUND /
 * 已有加工单→200+加工单数据（防回归）。
 */
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProcessingOrder detail 无加工单契约（#3887）")
class ProcessingOrderDetailNoProcOrderTest extends BaseControllerTest {

    private static final Long TENANT = 1L;

    private MockMvc mockMvc;

    @Mock
    private ProcessingOrderMapper processingOrderMapper;

    @Mock
    private OrderMapper orderMapper;

    @Mock
    private OrderItemMapper orderItemMapper;

    @Mock
    private ProcessingItemMapper processingItemMapper;

    @Mock
    private OrderService orderService;

    // issue #4116：ProcessingOrderService 增依赖 ProductionService（生成加工单即实例化工序）；
    // 本测试只覆盖 detail 查询，故 mock 掉（不参与本文件断言的链路）
    @Mock
    private com.migao.admin.service.ProductionService productionService;

    // issue #4116 切库：工序来源改读工序库（ProductionOperationQueryService）；本测试不生成加工单，mock 掉
    @Mock
    private com.migao.admin.service.ProductionOperationQueryService productionOperationQueryService;

    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    private ProcessingOrderService processingOrderService;
    private ProcessingOrderController controller;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        // LambdaQueryWrapper 构建需 TableInfo（同 ProcessingOrderServiceTest 的做法）
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, ProcessingOrder.class);

        processingOrderService = new ProcessingOrderService(
                processingOrderMapper, orderMapper, orderItemMapper, processingItemMapper, orderService, objectMapper,
                productionService, productionOperationQueryService);
        controller = new ProcessingOrderController(processingOrderService);
        mockMvc = buildMockMvc(controller);
    }

    private Order order(String id, String orderNo) {
        return Order.builder()
                .id(id)
                .tenantId(TENANT)
                .orderNo(orderNo)
                .status("confirmed")
                .customerName("张三")
                .customerPhone("13800138000")
                .build();
    }

    @Test
    @DisplayName("有效订单但无加工单 → 200 + success=true + data null（#3887 主场景）")
    void detailValidOrderWithoutProcessingOrder() throws Exception {
        Order order = order("order-001", "ORD-20260912-0001");
        when(orderMapper.selectById("order-001")).thenReturn(order);
        // processingOrderMapper.selectOne 默认返回 null = 该订单还没有加工单

        mockMvc.perform(get("/api/admin/processing-orders/order-001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.error").doesNotExist())
                // ApiResponse @JsonInclude(NON_NULL)：data=null 时该字段被省略，
                // 前端 res.data?.data ?? null 得到 null → setNotFound(true) →「生成加工单」态
                .andExpect(jsonPath("$.data").doesNotExist());
    }

    @Test
    @DisplayName("乱 ID（订单与加工单都不存在）→ 404 + NOT_FOUND（真无效 ID 语义保持）")
    void detailInvalidIdStill404() throws Exception {
        when(orderMapper.selectById("no-such-id")).thenReturn(null);
        when(orderMapper.selectOne(any())).thenReturn(null);

        mockMvc.perform(get("/api/admin/processing-orders/no-such-id"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("NOT_FOUND"))
                .andExpect(jsonPath("$.error.message").value("加工单不存在"));
    }

    @Test
    @DisplayName("已有加工单的订单 → 200 + 加工单数据（防回归）")
    void detailExistingProcessingOrder() throws Exception {
        Order order = order("order-001", "ORD-20260912-0001");
        ProcessingOrder po = ProcessingOrder.builder()
                .id("po-001")
                .tenantId(TENANT)
                .orderId("order-001")
                .processingOrderNo("JG-20260912-0001")
                .status("generated")
                .build();
        when(processingOrderMapper.selectOne(any())).thenReturn(po);
        when(orderMapper.selectById("order-001")).thenReturn(order);

        mockMvc.perform(get("/api/admin/processing-orders/po-001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.id").value("po-001"))
                .andExpect(jsonPath("$.data.processingOrderNo").value("JG-20260912-0001"))
                .andExpect(jsonPath("$.data.status").value("generated"))
                .andExpect(jsonPath("$.data.orderNo").value("ORD-20260912-0001"));
    }
}
