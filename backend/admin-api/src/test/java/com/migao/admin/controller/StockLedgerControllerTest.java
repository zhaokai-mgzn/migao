// case_ids: PR-004, PR-005
// 库存台账只读端点（issue #4055）：GET /api/admin/stock-ledger —— 租户上下文透传、过滤参数、
// 分页响应形状、权限点（product:list，复用商品读权限，不新造权限点）。

package com.migao.admin.controller;

import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.StockLedger;
import com.migao.admin.service.StockLedgerService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * StockLedgerController 单元测试（issue #4055）—— 只读查询端点。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("StockLedgerController 库存台账查询")
class StockLedgerControllerTest extends BaseControllerTest {

    private static final String BASE = "/api/admin/stock-ledger";

    private MockMvc mockMvc;

    @Mock
    private StockLedgerService stockLedgerService;

    @InjectMocks
    private StockLedgerController stockLedgerController;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(stockLedgerController);
    }

    @AfterEach
    void tearDown() {
        super.baseTearDown();
    }

    @Test
    @DisplayName("GET 无过滤 —— 200 返回分页台账（当前租户）")
    void getLedger_ok() throws Exception {
        when(stockLedgerService.getLedgerPage(eq(TEST_TENANT_ID), eq(null), eq(null), eq(null), eq(1L), eq(20L)))
                .thenReturn(PageResponse.of(1L, 1L, 20L, List.of(
                        StockLedger.builder().id(7L).skuId(100L).skuCode("SKU-100")
                                .beforeQty(30).afterQty(20).delta(-10)
                                .reason(StockLedger.REASON_MANUAL).operator("13800138000").build())));

        mockMvc.perform(get(BASE))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.total").value(1))
                .andExpect(jsonPath("$.data.items[0].beforeQty").value(30))
                .andExpect(jsonPath("$.data.items[0].afterQty").value(20))
                .andExpect(jsonPath("$.data.items[0].delta").value(-10))
                .andExpect(jsonPath("$.data.items[0].reason").value("manual"));
    }

    @Test
    @DisplayName("GET 带 skuId/productId/refNo —— 三个过滤条件与分页参数原样透传（含租户）")
    void getLedger_passesFiltersAndTenant() throws Exception {
        when(stockLedgerService.getLedgerPage(any(), any(), any(), any(), any(Long.class), any(Long.class)))
                .thenReturn(PageResponse.of(0L, 2L, 5L, List.of()));

        mockMvc.perform(get(BASE)
                        .param("skuId", "100")
                        .param("productId", "prod-1")
                        .param("refNo", "AS-20260918-0001")
                        .param("page", "2")
                        .param("size", "5"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));

        ArgumentCaptor<Long> skuId = ArgumentCaptor.forClass(Long.class);
        verify(stockLedgerService).getLedgerPage(
                eq(TEST_TENANT_ID), skuId.capture(), eq("prod-1"), eq("AS-20260918-0001"), eq(2L), eq(5L));
        assertThat(skuId.getValue()).as("skuId 必须按数值透传（字符串化会被下游当模糊匹配）").isEqualTo(100L);
    }

    @Test
    @DisplayName("GET 不传 page/size —— 默认第 1 页 20 条")
    void getLedger_defaultPaging() throws Exception {
        when(stockLedgerService.getLedgerPage(any(), any(), any(), any(), any(Long.class), any(Long.class)))
                .thenReturn(PageResponse.of(0L, 1L, 20L, List.of()));

        mockMvc.perform(get(BASE)).andExpect(status().isOk());

        verify(stockLedgerService).getLedgerPage(TEST_TENANT_ID, null, null, null, 1L, 20L);
    }
}