package com.aikf.admin.controller;

import com.aikf.admin.config.GlobalExceptionHandler;
import com.aikf.admin.config.TenantContext;
import com.aikf.admin.dto.*;
import com.aikf.admin.exception.BusinessException;
import com.aikf.admin.service.AfterSalesTicketService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * 售后工单控制器集成测试
 * 覆盖：工单 CRUD、状态流转、非法状态流转拒绝
 */
@ExtendWith(MockitoExtension.class)
class AfterSalesIntegrationTest {

    private MockMvc mockMvc;

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private AfterSalesTicketService afterSalesTicketService;

    @InjectMocks
    private AfterSalesController afterSalesController;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(1L);
        mockMvc = MockMvcBuilders.standaloneSetup(afterSalesController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ======================== 辅助方法 ========================

    private AfterSalesDetailResponse buildTicketDetail(String id, String ticketNo, String status) {
        AfterSalesDetailResponse detail = new AfterSalesDetailResponse();
        detail.setId(id);
        detail.setTicketNo(ticketNo);
        detail.setOrderId("order-001");
        detail.setOrderNo("ORD20250425001");
        detail.setCustomerId("cust-001");
        detail.setCustomerName("张三");
        detail.setCustomerPhone("13800138000");
        detail.setTicketType("return");
        detail.setStatus(status);
        detail.setDescription("窗帘颜色与描述不符，申请退货");
        detail.setImages(List.of("https://example.com/img1.jpg"));
        detail.setSource("admin");
        detail.setPriority("normal");
        detail.setCreatedAt(OffsetDateTime.now());
        detail.setUpdatedAt(OffsetDateTime.now());

        AfterSalesDetailResponse.StatusHistoryItem historyItem = new AfterSalesDetailResponse.StatusHistoryItem();
        historyItem.setStatus("pending");
        historyItem.setTime(OffsetDateTime.now().toString());
        historyItem.setOperator("system");
        historyItem.setRemark("工单创建");
        detail.setStatusHistory(List.of(historyItem));

        return detail;
    }

    // ======================== 创建售后工单 ========================

    @Test
    @DisplayName("创建售后工单 - 退货类型")
    void testCreateAfterSalesTicket() throws Exception {
        // Given
        AfterSalesCreateRequest request = new AfterSalesCreateRequest();
        request.setOrderId("order-001");
        request.setTicketType("return");
        request.setDescription("窗帘颜色与描述不符，申请退货");
        request.setImages(List.of("https://example.com/img1.jpg"));
        request.setPriority("normal");
        request.setRefundAmount(new BigDecimal("1500.00"));

        AfterSalesDetailResponse response = buildTicketDetail("ticket-001", "AS20250425001", "pending");
        response.setRefundAmount(new BigDecimal("1500.00"));

        when(afterSalesTicketService.createTicket(any(AfterSalesCreateRequest.class), eq(1L)))
                .thenReturn(response);

        // When & Then
        mockMvc.perform(post("/api/admin/after-sales")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.id").value("ticket-001"))
                .andExpect(jsonPath("$.data.ticketNo").value("AS20250425001"))
                .andExpect(jsonPath("$.data.status").value("pending"))
                .andExpect(jsonPath("$.data.ticketType").value("return"))
                .andExpect(jsonPath("$.data.customerName").value("张三"));

        verify(afterSalesTicketService).createTicket(any(AfterSalesCreateRequest.class), eq(1L));
    }

    // ======================== 查询工单列表 ========================

    @Test
    @DisplayName("获取售后工单列表 - 分页查询")
    void testGetAfterSalesTicketList() throws Exception {
        // Given
        AfterSalesListResponse ticket1 = new AfterSalesListResponse();
        ticket1.setId("ticket-001");
        ticket1.setTicketNo("AS20250425001");
        ticket1.setOrderNo("ORD20250425001");
        ticket1.setCustomerName("张三");
        ticket1.setTicketType("return");
        ticket1.setStatus("pending");

        AfterSalesListResponse ticket2 = new AfterSalesListResponse();
        ticket2.setId("ticket-002");
        ticket2.setTicketNo("AS20250425002");
        ticket2.setOrderNo("ORD20250425002");
        ticket2.setCustomerName("李四");
        ticket2.setTicketType("exchange");
        ticket2.setStatus("processing");

        PageResponse<AfterSalesListResponse> pageResponse = PageResponse.of(2L, 1L, 20L, List.of(ticket1, ticket2));

        when(afterSalesTicketService.getTicketPage(eq(1L), eq(20L), isNull(), isNull(), isNull(), eq(1L)))
                .thenReturn(pageResponse);

        // When & Then
        mockMvc.perform(get("/api/admin/after-sales")
                        .param("page", "1")
                        .param("size", "20")
                        .contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.total").value(2))
                .andExpect(jsonPath("$.data.items").isArray())
                .andExpect(jsonPath("$.data.items[0].ticketNo").value("AS20250425001"))
                .andExpect(jsonPath("$.data.items[1].status").value("processing"));
    }

    // ======================== 查询工单详情 ========================

    @Test
    @DisplayName("获取售后工单详情 - 包含状态历史")
    void testGetAfterSalesTicketDetail() throws Exception {
        // Given
        AfterSalesDetailResponse detail = buildTicketDetail("ticket-001", "AS20250425001", "processing");

        when(afterSalesTicketService.getTicketById("ticket-001")).thenReturn(detail);

        // When & Then
        mockMvc.perform(get("/api/admin/after-sales/ticket-001")
                        .contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.id").value("ticket-001"))
                .andExpect(jsonPath("$.data.status").value("processing"))
                .andExpect(jsonPath("$.data.statusHistory").isArray())
                .andExpect(jsonPath("$.data.statusHistory[0].status").value("pending"));
    }

    // ======================== 更新工单状态 ========================

    @Test
    @DisplayName("更新工单状态 - pending -> processing")
    void testUpdateAfterSalesStatus() throws Exception {
        // Given
        doNothing().when(afterSalesTicketService).updateTicketStatus(eq("ticket-001"), any(AfterSalesStatusUpdateRequest.class));

        // When & Then
        mockMvc.perform(put("/api/admin/after-sales/ticket-001/status")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"status\":\"processing\",\"remark\":\"开始处理\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));

        verify(afterSalesTicketService).updateTicketStatus(eq("ticket-001"), any(AfterSalesStatusUpdateRequest.class));
    }

    // ======================== 非法状态流转 ========================

    @Test
    @DisplayName("非法状态流转被拒绝 - resolved 不能回退到 pending")
    void testAfterSalesStatusFlowValidation() throws Exception {
        // Given: Service 层抛出业务异常
        doThrow(new BusinessException("INVALID_STATUS", "非法的状态流转: resolved -> pending", 400))
                .when(afterSalesTicketService).updateTicketStatus(eq("ticket-001"), any(AfterSalesStatusUpdateRequest.class));

        // When & Then
        mockMvc.perform(put("/api/admin/after-sales/ticket-001/status")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"status\":\"pending\",\"remark\":\"尝试回退\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("INVALID_STATUS"));
    }
}
