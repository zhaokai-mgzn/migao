package com.migao.admin.controller;

import com.migao.admin.dto.*;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.AfterSalesTicketService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * AfterSalesController 单元测试 — 覆盖参数校验 / 业务异常 / 租户隔离
 * 与 AfterSalesIntegrationTest 互补（IntegrationTest 覆盖 CRUD + 状态流转主流程）
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("AfterSalesController 售后管理测试")
class AfterSalesControllerTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock
    private AfterSalesTicketService afterSalesTicketService;

    @InjectMocks
    private AfterSalesController afterSalesController;

    private static final String BASE = "/api/admin/after-sales";
    private static final String TICKET_ID = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6";

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(afterSalesController);
    }

    @Override
    @org.junit.jupiter.api.AfterEach
    void baseTearDown() {
        super.baseTearDown();
    }

    private AfterSalesDetailResponse buildTicket(String id, String status, String ticketType) {
        AfterSalesDetailResponse d = new AfterSalesDetailResponse();
        d.setId(id);
        d.setTicketNo("AS20250616001");
        d.setOrderId("order-001");
        d.setOrderNo("ORD20250616001");
        d.setCustomerName("张三");
        d.setCustomerPhone("13800138000");
        d.setTicketType(ticketType);
        d.setStatus(status);
        d.setDescription("商品质量问题");
        d.setPriority("normal");
        d.setRefundAmount(new BigDecimal("299.00"));
        d.setCreatedAt(OffsetDateTime.now());
        d.setUpdatedAt(OffsetDateTime.now());
        return d;
    }

    // ==================== GET /api/admin/after-sales ====================

    @Nested
    @DisplayName("GET /api/admin/after-sales — 工单列表")
    class GetTickets {

        @Test
        @DisplayName("按状态筛选 -> 200")
        void filterByStatus() throws Exception {
            AfterSalesListResponse item = new AfterSalesListResponse();
            item.setId(TICKET_ID);
            item.setTicketNo("AS001");
            item.setCustomerName("张三");
            item.setStatus("processing");
            item.setTicketType("return");

            PageResponse<AfterSalesListResponse> page = PageResponse.of(1L, 1L, 20L, List.of(item));

            when(afterSalesTicketService.getTicketPage(eq(1L), eq(20L), eq("processing"), isNull(), isNull(), eq(TEST_TENANT_ID)))
                    .thenReturn(page);

            mockMvc.perform(get(BASE).param("status", "processing"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.items[0].status").value("processing"));
        }

        @Test
        @DisplayName("按工单类型筛选 -> 200")
        void filterByType() throws Exception {
            PageResponse<AfterSalesListResponse> page = PageResponse.of(0L, 1L, 20L, List.of());

            when(afterSalesTicketService.getTicketPage(eq(1L), eq(20L), isNull(), eq("exchange"), isNull(), eq(TEST_TENANT_ID)))
                    .thenReturn(page);

            mockMvc.perform(get(BASE).param("ticketType", "exchange"))
                    .andExpect(status().isOk());
        }

        @Test
        @DisplayName("多条件组合筛选 -> 200")
        void combinedFilters() throws Exception {
            when(afterSalesTicketService.getTicketPage(eq(1L), eq(20L), eq("pending"), eq("return"), eq("张三"), eq(TEST_TENANT_ID)))
                    .thenReturn(PageResponse.of(1L, 1L, 20L, List.of(new AfterSalesListResponse())));

            mockMvc.perform(get(BASE)
                            .param("status", "pending")
                            .param("ticketType", "return")
                            .param("keyword", "张三"))
                    .andExpect(status().isOk());
        }
    }

    // ==================== GET /api/admin/after-sales/{id} ====================

    @Nested
    @DisplayName("GET /api/admin/after-sales/{id} — 工单详情")
    class GetTicket {

        @Test
        @DisplayName("查询详情 -> 200 + 退款金额")
        void detailWithRefund() throws Exception {
            AfterSalesDetailResponse d = buildTicket(TICKET_ID, "processing", "return");
            d.setRefundAmount(new BigDecimal("299.00"));

            when(afterSalesTicketService.getTicketById(TICKET_ID)).thenReturn(d);

            mockMvc.perform(get(BASE + "/" + TICKET_ID))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.ticketType").value("return"))
                    .andExpect(jsonPath("$.data.refundAmount").value(299.00));
        }

        @Test
        @DisplayName("工单不存在 -> 404")
        void notFound() throws Exception {
            when(afterSalesTicketService.getTicketById("nonexistent"))
                    .thenThrow(new BusinessException("NOT_FOUND", "工单不存在", 404));

            mockMvc.perform(get(BASE + "/nonexistent"))
                    .andExpect(status().isNotFound())
                    .andExpect(jsonPath("$.error.code").value("NOT_FOUND"));
        }
    }

    // ==================== POST /api/admin/after-sales ====================

    @Nested
    @DisplayName("POST /api/admin/after-sales — 创建工单")
    class CreateTicket {

        @Test
        @DisplayName("创建换货工单 -> 200")
        void createExchange() throws Exception {
            AfterSalesDetailResponse d = buildTicket(TICKET_ID, "pending", "exchange");

            when(afterSalesTicketService.createTicket(any(AfterSalesCreateRequest.class), eq(TEST_TENANT_ID), anyString()))
                    .thenReturn(d);

            String body = """
                    {"orderId":"order-001","ticketType":"exchange","description":"尺寸不合适"}
                    """;

            mockMvc.perform(post(BASE).contentType(MediaType.APPLICATION_JSON).content(body))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.ticketType").value("exchange"));
        }

        @Test
        @DisplayName("缺少必填字段 -> 422")
        void missingFields() throws Exception {
            mockMvc.perform(post(BASE).contentType(MediaType.APPLICATION_JSON).content("{}"))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"));
        }
    }

    // ==================== PUT /api/admin/after-sales/{id}/status ====================

    @Nested
    @DisplayName("PUT /api/admin/after-sales/{id}/status — 状态更新")
    class UpdateStatus {

        @Test
        @DisplayName("处理完成 -> 200")
        void resolve() throws Exception {
            doNothing().when(afterSalesTicketService)
                    .updateTicketStatus(eq(TICKET_ID), any(AfterSalesStatusUpdateRequest.class));

            String body = "{\"status\":\"resolved\",\"remark\":\"已退款\"}";

            mockMvc.perform(put(BASE + "/" + TICKET_ID + "/status")
                            .contentType(MediaType.APPLICATION_JSON).content(body))
                    .andExpect(status().isOk());
        }

        @Test
        @DisplayName("关闭工单 -> 200")
        void close() throws Exception {
            doNothing().when(afterSalesTicketService)
                    .updateTicketStatus(eq(TICKET_ID), any(AfterSalesStatusUpdateRequest.class));

            String body = "{\"status\":\"closed\",\"remark\":\"客户主动取消\"}";

            mockMvc.perform(put(BASE + "/" + TICKET_ID + "/status")
                            .contentType(MediaType.APPLICATION_JSON).content(body))
                    .andExpect(status().isOk());
        }
    }

    // ==================== 租户隔离 ====================

    @Nested
    @DisplayName("租户隔离验证")
    class TenantIsolation {

        @Test
        @DisplayName("创建工单携带租户 ID")
        void createPassesTenantId() throws Exception {
            when(afterSalesTicketService.createTicket(any(AfterSalesCreateRequest.class), eq(TEST_TENANT_ID), anyString()))
                    .thenReturn(buildTicket(TICKET_ID, "pending", "return"));

            String body = "{\"orderId\":\"order-001\",\"ticketType\":\"return\",\"description\":\"test\"}";

            mockMvc.perform(post(BASE).contentType(MediaType.APPLICATION_JSON).content(body));

            verify(afterSalesTicketService).createTicket(any(AfterSalesCreateRequest.class), eq(TEST_TENANT_ID), anyString());
        }

        @Test
        @DisplayName("列表查询携带租户 ID")
        void listPassesTenantId() throws Exception {
            when(afterSalesTicketService.getTicketPage(anyLong(), anyLong(), isNull(), isNull(), isNull(), eq(TEST_TENANT_ID)))
                    .thenReturn(PageResponse.of(0L, 1L, 20L, List.of()));

            mockMvc.perform(get(BASE));

            verify(afterSalesTicketService).getTicketPage(anyLong(), anyLong(), isNull(), isNull(), isNull(), eq(TEST_TENANT_ID));
        }
    }
}
