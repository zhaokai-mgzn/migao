// case_ids: PG-018, BM-006, DF-017
package com.migao.admin.controller;

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.service.ProductionScanService;
import com.migao.admin.service.ProductionService;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerSessionService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.hamcrest.Matchers.hasSize;
import static org.hamcrest.Matchers.nullValue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 工人端扫码解析端点（issue #4716 第一切片）—— **HTTP 层**的三条硬约束。
 *
 * <p>为什么需要这个端点（实测缺口）：切片① 的解析面只挂在
 * {@code GET /api/admin/production/scan}，而 {@code /api/admin/**} 把 {@code worker} 放进
 * <b>拒绝集合</b>（#4727 / #4733）⇒ 工人没有任何解析入口，H5 报工页无从落地。</p>
 *
 * <p>锁三条（每条都能红）：</p>
 * <ol>
 *   <li><b>无工人 session ⇒ 401 且不进服务层</b>（与同类读面同款 fail-closed）；</li>
 *   <li>🔴 <b>旧码降级不默认取第 1 套</b>（W9）：服务端返回 {@code granularity="order"} +
 *       {@code needs_selection:["set","position"]} 且 {@code set_no}/{@code position}/
 *       {@code operation} 全为 {@code null} —— 本用例把「不知道就是不知道」钉在 HTTP 层，
 *       前端任何「取 selections[0]」的兜底都会与它冲突；</li>
 *   <li>token / operation_id 原样交给切片①（<b>不复制</b>推断逻辑）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("WorkerProductionController 扫码解析（旧码降级 / 无 session 拒绝）")
class WorkerScanEndpointTest {

    private static final Long TENANT = 1L;

    @Mock
    private ProductionService productionService;
    @Mock
    private WorkerSessionService workerSessionService;
    @Mock
    private ProductionScanService productionScanService;

    private MockMvc mockMvc;

    private static final WorkerIdentity ZHANG =
            new WorkerIdentity("worker-zhang", "张三", WorkerIdentity.SOURCE_SERVER_SESSION, "sess-1");

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        WorkerProductionController controller =
                new WorkerProductionController(productionService, workerSessionService, productionScanService);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    /** 旧码降级形态：逐字照 {@code ProductionScanService.degradedView} 的键。 */
    private static Map<String, Object> degradedView() {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("granularity", ProductionScanService.GRANULARITY_ORDER);
        view.put("order_id", "o-1");
        view.put("processing_order_no", "JG20260920001");
        view.put("set_no", null);
        view.put("set_index", null);
        view.put("position", null);
        view.put("operation", null);
        view.put("alternatives", List.of());
        view.put("set_progress", null);
        view.put("completed", null);
        view.put("completed_at", null);
        view.put("needs_selection", List.of("set", "position"));
        view.put("selections", List.of(
                Map.of("set_id", "set-1", "set_no", 1, "set_index", 0,
                        "positions", List.of(Map.of("order_item_id", "oi-1", "position_name", "布帘"))),
                Map.of("set_id", "set-2", "set_no", 2, "set_index", 1,
                        "positions", List.of(Map.of("order_item_id", "oi-2", "position_name", "纱帘")))));
        return view;
    }

    @Test
    @DisplayName("🔴 无工人 session ⇒ 401 且**不进服务层**（工人路径没有第二条身份来源）")
    void scanWithoutWorkerSessionRejected() throws Exception {
        when(workerSessionService.resolveIdentity(any())).thenReturn(null);

        mockMvc.perform(get("/api/worker/production/scan").param("token", "tok-1"))
                .andExpect(status().isUnauthorized());

        verify(productionScanService, never()).resolve(any(), any(), any());
    }

    @Test
    @DisplayName("🔴 旧码 ⇒ granularity=order + needs_selection=[set,position] 且**不默认第 1 套**（W9）")
    void legacyCodeDegradesWithoutDefaultingToFirstSet() throws Exception {
        when(workerSessionService.resolveIdentity("sess-1")).thenReturn(ZHANG);
        when(productionScanService.resolve(eq("JG20260920001"), any(), eq(TENANT)))
                .thenReturn(degradedView());

        mockMvc.perform(get("/api/worker/production/scan")
                        .param("token", "JG20260920001")
                        .header(WorkerSessionService.SESSION_HEADER, "sess-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.granularity").value("order"))
                // 🔴 这三条就是「绝不默认取第 1 套」的机械判据
                .andExpect(jsonPath("$.data.set_no").value(nullValue()))
                .andExpect(jsonPath("$.data.set_index").value(nullValue()))
                .andExpect(jsonPath("$.data.position").value(nullValue()))
                .andExpect(jsonPath("$.data.operation").value(nullValue()))
                // completed=null = **未知**（不是 false，也不是 true）
                .andExpect(jsonPath("$.data.completed").value(nullValue()))
                .andExpect(jsonPath("$.data.needs_selection", hasSize(2)))
                .andExpect(jsonPath("$.data.needs_selection[0]").value("set"))
                .andExpect(jsonPath("$.data.needs_selection[1]").value("position"))
                // 第 1 套只作为**候选**出现，不是结论
                .andExpect(jsonPath("$.data.selections", hasSize(2)))
                .andExpect(jsonPath("$.data.selections[0].set_no").value(1));
    }

    @Test
    @DisplayName("token / operation_id 原样交给切片①（不复制推断逻辑）")
    void scanDelegatesToSliceOneService() throws Exception {
        when(workerSessionService.resolveIdentity("sess-1")).thenReturn(ZHANG);
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("granularity", ProductionScanService.GRANULARITY_SET_POSITION);
        view.put("set_no", 14);
        view.put("needs_selection", List.of());
        when(productionScanService.resolve("tok-9", "op-7", TENANT)).thenReturn(view);

        mockMvc.perform(get("/api/worker/production/scan")
                        .param("token", "tok-9")
                        .param("operation_id", "op-7")
                        .header(WorkerSessionService.SESSION_HEADER, "sess-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.set_no").value(14));

        verify(productionScanService).resolve("tok-9", "op-7", TENANT);
    }
}
