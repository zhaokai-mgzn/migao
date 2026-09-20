// case_ids: PG-018, BM-006, DF-017
package com.migao.admin.controller;

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.service.ProductionScanCompleteService;
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
 * 工人端扫码解析端点的 **旧码降级契约**（issue #4716 第一切片 / 设计 W9）—— **HTTP 层**判据。
 *
 * <p><b>与 {@link WorkerProductionControllerTest} 的分工（两处都保留，不是重复）</b>：
 * 那边的 {@code scanRequiresWorkerSessionAndReusesResolve} 钉的是「无 session ⇒ 401 不进服务层」
 * 与「复用同一份 resolve」；<b>本类</b>钉的是**降级形态本身**——
 * {@code granularity="order"} + {@code needs_selection:["set","position"]} 且
 * {@code set_no}/{@code set_index}/{@code position}/{@code operation}/{@code completed}
 * 全为 {@code null}（「不知道就是不知道」）。这条是 H5 页面「绝不默认取第 1 套」的**上游判据**：
 * 服务端若哪天偷偷回落到第 1 套，页面侧的一切兜底讨论都没意义 —— 故必须在 HTTP 层可红。</p>
 *
 * <p>端点本体由切片② 落在 main（与切片① 的解析面同源）；本类只补**契约断言**，不改实现。</p>
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
    /** 切片② 的写入口依赖：本类只测读面契约，故只满足构造签名（**不**被调用）。 */
    @Mock
    private ProductionScanCompleteService productionScanCompleteService;

    private MockMvc mockMvc;

    private static final WorkerIdentity ZHANG =
            new WorkerIdentity("worker-zhang", "张三", WorkerIdentity.SOURCE_SERVER_SESSION, "sess-1");

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        WorkerProductionController controller =
                new WorkerProductionController(productionService, workerSessionService, productionScanService,
                        productionScanCompleteService);
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

    @Test
    @DisplayName("🔴 旧码收口（#4794）：set_id + order_item_id 原样转给扩展重载；无选择 ⇒ 仍走 3 参签名")
    void legacySelectionParamsAreForwarded() throws Exception {
        when(workerSessionService.resolveIdentity("sess-1")).thenReturn(ZHANG);
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("granularity", ProductionScanService.GRANULARITY_SET_POSITION);
        view.put("set_no", 14);
        view.put("needs_selection", List.of());
        when(productionScanService.resolve("JG20260920001", null, "set-14", "oi-1", TENANT))
                .thenReturn(view);

        mockMvc.perform(get("/api/worker/production/scan")
                        .param("token", "JG20260920001")
                        .param("set_id", "set-14")
                        .param("order_item_id", "oi-1")
                        .header(WorkerSessionService.SESSION_HEADER, "sess-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.granularity").value("set_position"))
                .andExpect(jsonPath("$.data.needs_selection", hasSize(0)));

        verify(productionScanService).resolve("JG20260920001", null, "set-14", "oi-1", TENANT);
        // 反向护栏：带了选择就**不再**走 3 参签名（无选择那条路径一字不动，见上一个用例）
        verify(productionScanService, never()).resolve(any(), any(), any());
    }
}
