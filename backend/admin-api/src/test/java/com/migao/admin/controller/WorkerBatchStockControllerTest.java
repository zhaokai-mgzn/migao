package com.migao.admin.controller;

// case_ids: BM-056, PG-018

import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.dto.WorkerBatchCorrectionRequest;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.WorkerBatchStockService;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerSessionService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.lang.reflect.Field;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 工人端**批次库存修正**接口测试（issue #8104；用户 2026-10-29 逐字
 * 「手机端还要增加一个库存修正的功能，apk程序也要同步增加这个功能，允许工人对某个批次的布匹进行修正」）。
 *
 * <p>判据（每条都能单独变红）：</p>
 * <ol>
 *   <li><b>无有效工人 session ⇒ 401 且服务层零调用</b>（读面 / 写面都一样：匿名不能读批次余量、
 *       更不能改库存）；</li>
 *   <li><b>零商家权限码</b>：本路径在 {@code /api/worker/**} 内，挂 {@code @RequirePermission}
 *       只会让工人恒 403 ⇒ 反射判红；</li>
 *   <li><b>租户只由会话解</b>：服务层收到的 tenant 是 {@code TenantContext}（由工人 session 过滤器
 *       从会话行定下来），请求体里没有这个字段可传；</li>
 *   <li><b>请求体结构上不含身份字段</b>：{@code WorkerBatchCorrectionRequest} 的字段集
 *       == 能力集（没有 worker_id / worker_name / tenant_id），想冒名改前端也没用；</li>
 *   <li><b>入参校验原样透传</b>：缺批次 / 负米数 / 幂等键缺失等由服务层抛 4xx，
 *       经 {@code GlobalExceptionHandler} 原样回到工人屏（不在控制器里改成 200 或吞掉）；</li>
 *   <li><b>回执原样下发</b>：盘前 / 实盘 / 差异 / 盘后四个数不在控制器里重算。</li>
 * </ol>
 */
@DisplayName("WorkerBatchStockController 工人批次库存修正（issue #8104）")
class WorkerBatchStockControllerTest extends BaseControllerTest {

    private static final String BATCHES_URL = "/api/worker/batch-stock/batches";
    private static final String CORRECTION_URL = "/api/worker/batch-stock/correction";
    private static final String SESSION = "sess-worker-zhang";
    private static final WorkerIdentity ZHANG =
            new WorkerIdentity("worker-zhang", "张三", WorkerIdentity.SOURCE_SERVER_SESSION, SESSION);

    private WorkerBatchStockService workerBatchStockService;
    private WorkerSessionService workerSessionService;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        workerBatchStockService = mock(WorkerBatchStockService.class);
        workerSessionService = mock(WorkerSessionService.class);
        when(workerSessionService.resolveIdentity(SESSION)).thenReturn(ZHANG);
        mockMvc = buildMockMvc(new WorkerBatchStockController(workerBatchStockService, workerSessionService));
    }

    private static Map<String, Object> row() {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("batch_id", 7L);
        row.put("batch_no", "PC-20261020-0007");
        row.put("product_id", "prod-1");
        row.put("product_name", "雪尼尔窗帘布");
        row.put("sku_code", "2659-04-28");
        row.put("dye_lot", "A12");
        row.put("inbound_no", "RK-20261020-0001");
        row.put("received_date", LocalDate.of(2026, 10, 20));
        row.put("remaining_meters", new BigDecimal("45.5"));
        return row;
    }

    private static Map<String, Object> page() {
        Map<String, Object> reason = new LinkedHashMap<>();
        reason.put("code", "miscount");
        reason.put("label", "数量记错了");
        Map<String, Object> page = new LinkedHashMap<>();
        page.put("items", List.of(row()));
        page.put("total", 1L);
        page.put("page", 1L);
        page.put("size", 20L);
        page.put("reasons", List.of(reason));
        return page;
    }

    private static Map<String, Object> correction(String status) {
        Map<String, Object> receipt = new LinkedHashMap<>();
        receipt.put("run_id", "wc-8f2b");
        receipt.put("batch_id", 7L);
        receipt.put("batch_no", "PC-20261020-0007");
        receipt.put("product_name", "雪尼尔窗帘布");
        receipt.put("sku_code", "2659-04-28");
        receipt.put("status", status);
        receipt.put("before_meters", new BigDecimal("45.5"));
        receipt.put("actual_meters", new BigDecimal("42"));
        receipt.put("delta_meters", new BigDecimal("-3.5"));
        receipt.put("after_meters", new BigDecimal("42"));
        receipt.put("worker_name", "张三");
        receipt.put("worker_no", "CY-1001");
        return receipt;
    }

    // ────────────────────────────────────────────────────────── ① 无 session ⇒ 401 + 零调用

    @Test
    @DisplayName("① 无工人 session / session 失效 ⇒ 两个端点都 401，服务层零调用（fail-closed）")
    void anonymousRequestsAreRejectedBeforeAnyWork() throws Exception {
        when(workerSessionService.resolveIdentity(any())).thenReturn(null);

        mockMvc.perform(get(BATCHES_URL))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error.message").value(org.hamcrest.Matchers.containsString("工号")));
        mockMvc.perform(post(CORRECTION_URL).contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isUnauthorized());

        verify(workerBatchStockService, never()).search(anyLong(), any(), anyLong(), anyLong());
        verify(workerBatchStockService, never()).correct(any(), any(), any());
    }

    // ────────────────────────────────────────────────────────── ② 读面

    @Test
    @DisplayName("② 搜批次 ⇒ 200 + 服务端行原样下发（含原因闭词表；tenant 来自会话上下文）")
    void searchPassesTheSessionTenantAndReturnsRowsVerbatim() throws Exception {
        when(workerBatchStockService.search(eq(TEST_TENANT_ID), eq("PC-20261020"), eq(1L), eq(20L)))
                .thenReturn(page());

        mockMvc.perform(get(BATCHES_URL)
                        .param("keyword", "PC-20261020")
                        .header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.items[0].batch_no").value("PC-20261020-0007"))
                .andExpect(jsonPath("$.data.items[0].product_name").value("雪尼尔窗帘布"))
                .andExpect(jsonPath("$.data.items[0].remaining_meters").value(45.5))
                // 原因清单跟着读面下发（端侧不写第二份选项）
                .andExpect(jsonPath("$.data.reasons[0].code").value("miscount"))
                .andExpect(jsonPath("$.data.reasons[0].label").value("数量记错了"));
    }

    // ────────────────────────────────────────────────────────── ③ 写面

    @Test
    @DisplayName("③ 提交修正 ⇒ 200 + 四个数原样下发 + 服务层收到会话解出的身份")
    void correctionPassesIdentityFromSessionAndReturnsReceipt() throws Exception {
        when(workerBatchStockService.correct(eq(TEST_TENANT_ID), eq(ZHANG), any()))
                .thenReturn(correction(BatchStockViews.STOCKTAKE_APPLIED));

        mockMvc.perform(post(CORRECTION_URL)
                        .contentType(MediaType.APPLICATION_JSON)
                        .header(WorkerSessionService.SESSION_HEADER, SESSION)
                        .content("{\"batchId\":7,\"actualMeters\":42,\"reason\":\"miscount\","
                                + "\"clientRequestId\":\"8f2b-1\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.status").value("applied"))
                .andExpect(jsonPath("$.data.before_meters").value(45.5))
                .andExpect(jsonPath("$.data.actual_meters").value(42))
                .andExpect(jsonPath("$.data.delta_meters").value(-3.5))
                .andExpect(jsonPath("$.data.after_meters").value(42))
                .andExpect(jsonPath("$.data.worker_name").value("张三"))
                // 身份字段**不在**请求体里：服务层拿到的是 resolveIdentity 的返回值
                .andExpect(jsonPath("$.data.batch_id").value(7));

        ArgumentCaptor<WorkerBatchCorrectionRequest> body =
                ArgumentCaptor.forClass(WorkerBatchCorrectionRequest.class);
        verify(workerBatchStockService).correct(eq(TEST_TENANT_ID), eq(ZHANG), body.capture());
        // 请求体契约 = camelCase（与工人端其它**写面**同口径；读面才是 snake_case）
        assertThat(body.getValue().getBatchId()).isEqualTo(7L);
        assertThat(body.getValue().getActualMeters()).isEqualByComparingTo("42");
        assertThat(body.getValue().getReason()).isEqualTo("miscount");
        assertThat(body.getValue().getClientRequestId()).isEqualTo("8f2b-1");
    }

    @Test
    @DisplayName("④ 服务层 4xx 原样回到工人屏（负米数 400 / 校验 422 —— 控制器不改写状态码）")
    void serviceErrorsKeepTheirStatusCodes() throws Exception {
        org.mockito.Mockito.doThrow(new BusinessException("WORKER_STOCK_CORRECTION_ACTUAL_NEGATIVE",
                        "实盘米数不能为负：-1", 400, "最小是 0"))
                .when(workerBatchStockService).correct(any(), any(), any());
        mockMvc.perform(post(CORRECTION_URL).contentType(MediaType.APPLICATION_JSON)
                        .header(WorkerSessionService.SESSION_HEADER, SESSION)
                        .content("{\"batchId\":7,\"actualMeters\":-1,\"reason\":\"miscount\","
                                + "\"clientRequestId\":\"x\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("WORKER_STOCK_CORRECTION_ACTUAL_NEGATIVE"));

        org.mockito.Mockito.doThrow(BusinessException.validationError("请选择修正原因"))
                .when(workerBatchStockService).correct(any(), any(), any());
        mockMvc.perform(post(CORRECTION_URL).contentType(MediaType.APPLICATION_JSON)
                        .header(WorkerSessionService.SESSION_HEADER, SESSION)
                        .content("{\"batchId\":7,\"actualMeters\":42,\"clientRequestId\":\"x\"}"))
                .andExpect(status().isUnprocessableEntity());
    }

    // ────────────────────────────────────────────────────────── ⑤ 结构判据

    @Test
    @DisplayName("⑤ 零商家权限码 + 路径只在 /api/worker/**（挂 @RequirePermission ⇒ 工人恒 403 ⇒ 红）")
    void carriesNoMerchantPermissionCode() {
        assertThat(WorkerBatchStockController.class.getAnnotation(RequirePermission.class)).isNull();
        for (java.lang.reflect.Method method : WorkerBatchStockController.class.getDeclaredMethods()) {
            assertThat(method.getAnnotation(RequirePermission.class))
                    .as("工人路径不得挂商家权限码：%s", method.getName())
                    .isNull();
        }
        assertThat(WorkerBatchStockController.class.getAnnotation(
                org.springframework.web.bind.annotation.RequestMapping.class).value())
                .containsExactly("/api/worker/batch-stock");
    }

    @Test
    @DisplayName("⑥ 请求体结构上不含身份 / 租户字段（能力集 = 字段集）")
    void requestBodyCannotCarryIdentity() {
        Set<String> fields = java.util.Arrays.stream(WorkerBatchCorrectionRequest.class.getDeclaredFields())
                .map(Field::getName)
                .collect(Collectors.toSet());
        assertThat(fields).containsExactlyInAnyOrder("batchId", "actualMeters", "reason", "note",
                "clientRequestId");
        assertThat(fields).doesNotContain("workerId", "workerName", "tenantId", "operator");
    }
}
