package com.migao.admin.controller;

// case_ids: FN-001, FN-002, FN-003

import com.migao.admin.dto.*;
import com.migao.admin.service.FinanceService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;
import java.util.List;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * FinanceController 单元测试 — 覆盖收支汇总/资金流水/应收对账端点。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("FinanceController 财务对账测试")
class FinanceControllerTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock
    private FinanceService financeService;

    @InjectMocks
    private FinanceController financeController;

    private static final String BASE = "/api/admin/finance";

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(financeController);
    }

    @Override
    @org.junit.jupiter.api.AfterEach
    void baseTearDown() {
        super.baseTearDown();
    }

    @Test
    @DisplayName("收支汇总 - GET /summary 返回 200")
    void getSummary_returnsOk() throws Exception {
        FinanceSummaryResponse summary = FinanceSummaryResponse.builder()
                .totalIncome(new BigDecimal("100.00"))
                .totalRefund(new BigDecimal("30.00"))
                .netIncome(new BigDecimal("70.00"))
                .incomeCount(1L)
                .refundCount(1L)
                .pendingReceivable(BigDecimal.ZERO)
                .byPaymentMethod(List.of())
                .dailyTrend(List.of())
                .build();
        when(financeService.getSummary(any(), any(), any())).thenReturn(summary);

        mockMvc.perform(get(BASE + "/summary"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));

        verify(financeService).getSummary(isNull(), isNull(), eq(TEST_TENANT_ID));
    }

    @Test
    @DisplayName("资金流水 - GET /transactions 返回 200")
    void getTransactions_returnsOk() throws Exception {
        FinanceTransactionListResponse txn = FinanceTransactionListResponse.builder()
                .id("t1")
                .transactionNo("FIN-20260815-0001")
                .type("income")
                .amount(new BigDecimal("88.00"))
                .paymentMethod("cash")
                .status("success")
                .build();
        PageResponse<FinanceTransactionListResponse> page =
                PageResponse.of(1L, 1L, 20L, List.of(txn));
        when(financeService.getTransactionPage(anyLong(), anyLong(), any(), any(), any(), any(), any(), any(), any()))
                .thenReturn(page);

        mockMvc.perform(get(BASE + "/transactions").param("page", "1").param("size", "20"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.items[0].transactionNo").value("FIN-20260815-0001"));

        verify(financeService).getTransactionPage(eq(1L), eq(20L), isNull(), isNull(), isNull(), isNull(), isNull(), isNull(), eq(TEST_TENANT_ID));
    }

    @Test
    @DisplayName("登记流水 - POST /transactions 返回 200")
    void createTransaction_returnsOk() throws Exception {
        FinanceTransactionListResponse txn = FinanceTransactionListResponse.builder()
                .id("t1")
                .transactionNo("FIN-20260815-0001")
                .type("income")
                .amount(new BigDecimal("88.00"))
                .paymentMethod("cash")
                .status("success")
                .build();
        when(financeService.createTransaction(any(), eq(TEST_TENANT_ID), any())).thenReturn(txn);

        mockMvc.perform(post(BASE + "/transactions")
                        .contentType("application/json")
                        .content("{\"type\":\"income\",\"amount\":88.00,\"paymentMethod\":\"cash\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.transactionNo").value("FIN-20260815-0001"));

        verify(financeService).createTransaction(any(FinanceTransactionCreateRequest.class), eq(TEST_TENANT_ID), anyString());
    }

    @Test
    @DisplayName("应收对账 - GET /reconciliation 返回 200")
    void getReconciliation_returnsOk() throws Exception {
        ReceivableReconciliationResponse item = ReceivableReconciliationResponse.builder()
                .orderId("o1")
                .orderNo("NO1")
                .customerName("张三")
                .receivableAmount(new BigDecimal("200.00"))
                .receivedAmount(new BigDecimal("180.00"))
                .refundAmount(BigDecimal.ZERO)
                .difference(new BigDecimal("-20.00"))
                .build();
        PageResponse<ReceivableReconciliationResponse> page =
                PageResponse.of(1L, 1L, 20L, List.of(item));
        when(financeService.getReconciliation(anyLong(), anyLong(), any(), any(), any(), any()))
                .thenReturn(page);

        mockMvc.perform(get(BASE + "/reconciliation").param("page", "1").param("size", "20"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.items[0].orderNo").value("NO1"));

        verify(financeService).getReconciliation(eq(1L), eq(20L), isNull(), isNull(), isNull(), eq(TEST_TENANT_ID));
    }
}
