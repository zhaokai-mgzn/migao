// case_ids: PR-055, PR-066
// 批次账只读端点（V116，issue #5145 阶段 1）：GET /api/admin/batch-stock/{batches,distribution,
// reconcile,candidates,consumptions} —— 租户上下文透传、过滤参数原样下传、响应形状、
// 权限点（product:list，复用商品读权限，不新造权限点）。

package com.migao.admin.controller;

import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.service.StockBatchConsumptionService;
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

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * StockBatchController 单元测试（V116 / issue #5145 阶段 1）—— 批次账只读查询端点。
 *
 * <p>四条判据：① **租户上下文**必须逐调用下传（跨租户读 = 数据泄漏，不是分页问题）；
 * ② 过滤参数原样下传（`productId` / `skuId` / `onlyAvailable` / `meters`）；
 * ③ 响应形状与 DTO 字段名一致（前端 `batchStockApi` 直接消费，改名即破契约）；
 * ④ 只读端点**不得**出现在写路径上（本控制器没有写端点 —— 批次账的写入方是加工单生成/作废）。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("StockBatchController 批次账查询")
class StockBatchControllerTest extends BaseControllerTest {

    private static final String BASE = "/api/admin/batch-stock";

    private MockMvc mockMvc;

    @Mock
    private StockBatchConsumptionService stockBatchConsumptionService;

    @InjectMocks
    private StockBatchController stockBatchController;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(stockBatchController);
    }

    @AfterEach
    void tearDown() {
        super.baseTearDown();
    }

    @Test
    @DisplayName("GET /batches —— 200 返回余量列表（租户 + 过滤参数下传）")
    void batchesOk() throws Exception {
        when(stockBatchConsumptionService.remaining(TEST_TENANT_ID, "prod-1", 12L, true))
                .thenReturn(List.of(new BatchStockViews.BatchRemaining(77L, "PC-20260923-0001", "prod-1",
                        12L, "SKU-A", "RK-1", "L1", LocalDate.of(2026, 9, 1), new BigDecimal("12.5"),
                        new BigDecimal("60"), new BigDecimal("2.7"), new BigDecimal("57.3"))));

        mockMvc.perform(get(BASE + "/batches")
                        .param("productId", "prod-1").param("skuId", "12").param("onlyAvailable", "true"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data[0].batchNo").value("PC-20260923-0001"))
                .andExpect(jsonPath("$.data[0].inboundMeters").value(60))
                .andExpect(jsonPath("$.data[0].consumedMeters").value(2.7))
                .andExpect(jsonPath("$.data[0].remainingMeters").value(57.3));
        verify(stockBatchConsumptionService).remaining(TEST_TENANT_ID, "prod-1", 12L, true);
    }

    @Test
    @DisplayName("GET /distribution —— 200 返回恒四档（批次数 + 占比）")
    void distributionOk() throws Exception {
        when(stockBatchConsumptionService.distribution(TEST_TENANT_ID, null))
                .thenReturn(new BatchStockViews.Distribution(6, List.of(
                        new BatchStockViews.Bucket("le_0_2", "≤0.2 米", 3, new BigDecimal("0.5")),
                        new BatchStockViews.Bucket("b0_2_0_5", "0.2~0.5 米", 1, new BigDecimal("0.1667")),
                        new BatchStockViews.Bucket("b0_5_1", "0.5~1 米", 1, new BigDecimal("0.1667")),
                        new BatchStockViews.Bucket("gt_1", ">1 米", 1, new BigDecimal("0.1667")))));

        mockMvc.perform(get(BASE + "/distribution"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.totalBatches").value(6))
                .andExpect(jsonPath("$.data.buckets.length()").value(4))
                .andExpect(jsonPath("$.data.buckets[0].key").value("le_0_2"))
                .andExpect(jsonPath("$.data.buckets[0].batchCount").value(3))
                .andExpect(jsonPath("$.data.buckets[0].share").value(0.5));
    }

    @Test
    @DisplayName("GET /reconcile —— 200 返回差额与分解腿（含 reconciled 判据）")
    void reconcileOk() throws Exception {
        when(stockBatchConsumptionService.reconcile(TEST_TENANT_ID, "prod-1", null))
                .thenReturn(new BatchStockViews.Reconcile(List.of(new BatchStockViews.ReconcileRow(
                        12L, "SKU-A", "prod-1", new BigDecimal("57.3"), new BigDecimal("60"),
                        new BigDecimal("60"), new BigDecimal("0"), new BigDecimal("2.7"),
                        new BigDecimal("0"), new BigDecimal("0"), new BigDecimal("2.7"),
                        new BigDecimal("2.7"),
                        // V119 / issue #5158：差额拆成「已售未派」+「排料节省」两项（此处无排料 ⇒ 省 0）
                        new BigDecimal("2.7"), new BigDecimal("0"), new BigDecimal("2.7"),
                        true)), new BigDecimal("2.7"), 0,
                BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO));

        mockMvc.perform(get(BASE + "/reconcile").param("productId", "prod-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.rows[0].skuStock").value(57.3))
                .andExpect(jsonPath("$.data.rows[0].batchRemaining").value(60))
                .andExpect(jsonPath("$.data.rows[0].diff").value(2.7))
                .andExpect(jsonPath("$.data.rows[0].reconciled").value(true))
                .andExpect(jsonPath("$.data.unreconciledCount").value(0));
    }

    @Test
    @DisplayName("GET /candidates —— 200 返回候选 + 建议值口径（meters 参数下传）")
    void candidatesOk() throws Exception {
        when(stockBatchConsumptionService.candidates(eq(TEST_TENANT_ID), eq("prod-1"), eq(12L), any(), any()))
                .thenReturn(new BatchStockViews.Candidates(
                        StockBatchConsumptionService.SUGGESTION_RULE_FIFO, "PC-20260923-0001",
                        new BigDecimal("2.7"), List.of(new BatchStockViews.Candidate("PC-20260923-0001",
                        new BigDecimal("57.3"), LocalDate.of(2026, 9, 1), "L1", "RK-1",
                        new BigDecimal("12.5"), true, true))));

        mockMvc.perform(get(BASE + "/candidates")
                        .param("productId", "prod-1").param("skuId", "12").param("meters", "2.7"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.suggestionRule").value("FIFO_RECEIVED_DATE"))
                .andExpect(jsonPath("$.data.suggestedBatchNo").value("PC-20260923-0001"))
                .andExpect(jsonPath("$.data.candidates[0].suggested").value(true))
                .andExpect(jsonPath("$.data.candidates[0].enough").value(true));
    }

    @Test
    @DisplayName("#5167 GET /candidates?assignmentRule=best_fit —— 规则原样下传，读面回 best-fit 口径")
    void candidatesPassesAssignmentRule() throws Exception {
        when(stockBatchConsumptionService.candidates(eq(TEST_TENANT_ID), eq("prod-1"), eq(12L),
                any(), eq("best_fit"))).thenReturn(new BatchStockViews.Candidates(
                        StockBatchConsumptionService.SUGGESTION_RULE_BEST_FIT, "PC-LATE",
                        new BigDecimal("3"), List.of(new BatchStockViews.Candidate("PC-LATE",
                        new BigDecimal("3"), LocalDate.of(2026, 9, 1), "L1", "RK-2",
                        new BigDecimal("12.5"), true, true))));

        mockMvc.perform(get(BASE + "/candidates").param("productId", "prod-1").param("skuId", "12")
                        .param("meters", "3").param("assignmentRule", "best_fit"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.suggestionRule").value("BEST_FIT_REMAINING"))
                .andExpect(jsonPath("$.data.suggestedBatchNo").value("PC-LATE"));

        ArgumentCaptor<String> rule = ArgumentCaptor.forClass(String.class);
        verify(stockBatchConsumptionService).candidates(eq(TEST_TENANT_ID), eq("prod-1"), eq(12L),
                any(), rule.capture());
        assertThat(rule.getValue()).as("请求参数原样下传（控制器不做规则取值判断）").isEqualTo("best_fit");
    }

    @Test
    @DisplayName("🔴 #5167 未知 assignmentRule ⇒ 400（服务侧显式拒绝，不静默回落 fifo）")
    void unknownAssignmentRuleIsRejectedWith400() throws Exception {
        when(stockBatchConsumptionService.candidates(eq(TEST_TENANT_ID), any(), any(), any(), eq("bestfit")))
                .thenThrow(new com.migao.admin.exception.BusinessException(
                        StockBatchConsumptionService.ERR_ASSIGNMENT_RULE_UNKNOWN,
                        "未知的批次指派规则：bestfit", 400, "可选值：fifo / best_fit"));

        mockMvc.perform(get(BASE + "/candidates").param("productId", "prod-1").param("skuId", "12")
                        .param("meters", "3").param("assignmentRule", "bestfit"))
                .andExpect(status().isBadRequest());
    }

    @Test
    @DisplayName("GET /consumptions —— 200 返回分页台账（按批次/加工单/订单过滤下传）")
    void consumptionsOk() throws Exception {
        when(stockBatchConsumptionService.consumptionPage(TEST_TENANT_ID, "PC-1", "JG-1", "ORD-1", 1L, 20L))
                .thenReturn(com.migao.admin.dto.PageResponse.of(1L, 1L, 20L, List.of()));

        mockMvc.perform(get(BASE + "/consumptions")
                        .param("batchNo", "PC-1").param("processingOrderNo", "JG-1").param("orderNo", "ORD-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(1));

        ArgumentCaptor<String> batchNo = ArgumentCaptor.forClass(String.class);
        verify(stockBatchConsumptionService).consumptionPage(
                eq(TEST_TENANT_ID), batchNo.capture(), eq("JG-1"), eq("ORD-1"), eq(1L), eq(20L));
        assertThat(batchNo.getValue()).isEqualTo("PC-1");
    }

    @Test
    @DisplayName("租户隔离：四个读面都拿到当前租户（不得用请求参数充当租户）")
    void tenantIsAlwaysFromContext() throws Exception {
        when(stockBatchConsumptionService.remaining(any(), any(), any(), anyBoolean())).thenReturn(List.of());
        when(stockBatchConsumptionService.distribution(any(), any()))
                .thenReturn(new BatchStockViews.Distribution(0, List.of()));
        when(stockBatchConsumptionService.reconcile(any(), any(), any()))
                .thenReturn(new BatchStockViews.Reconcile(List.of(), BigDecimal.ZERO, 0,
                        BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO));
        when(stockBatchConsumptionService.candidates(any(), any(), any(), any(), any()))
                .thenReturn(new BatchStockViews.Candidates(
                        StockBatchConsumptionService.SUGGESTION_RULE_FIFO, null, BigDecimal.ZERO, List.of()));

        mockMvc.perform(get(BASE + "/batches")).andExpect(status().isOk());
        mockMvc.perform(get(BASE + "/distribution")).andExpect(status().isOk());
        mockMvc.perform(get(BASE + "/reconcile")).andExpect(status().isOk());
        mockMvc.perform(get(BASE + "/candidates")).andExpect(status().isOk());

        verify(stockBatchConsumptionService).remaining(eq(TEST_TENANT_ID), any(), any(), anyBoolean());
        verify(stockBatchConsumptionService).distribution(eq(TEST_TENANT_ID), any());
        verify(stockBatchConsumptionService).reconcile(eq(TEST_TENANT_ID), any(), any());
        verify(stockBatchConsumptionService).candidates(eq(TEST_TENANT_ID), any(), any(), any(), any());
    }
}
