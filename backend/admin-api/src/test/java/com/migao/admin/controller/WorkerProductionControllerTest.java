// case_ids: PG-018, BM-006, DF-017
package com.migao.admin.controller;

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.ProductionService;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerSessionService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 工人报工端点契约测试（issue #4733）—— **HTTP 层**的「服务端解身份」。
 *
 * <p>锁三条（每条都能红）：</p>
 * <ol>
 *   <li><b>无工人 session ⇒ 401</b>，且**不进服务层**（工人路径上「谁报的」没有第二条来源，
 *       不降级到 body 口径）；</li>
 *   <li>有工人 session ⇒ 传给 {@code ProductionService} 的身份是
 *       {@code server_session}（**body 里的 worker_id 一个字节都没读**）——
 *       用 {@link ArgumentCaptor} 钉住实参；</li>
 *   <li>读面（operations / current-worker）同样要求有效工人 session。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("WorkerProductionController 契约（服务端解身份 / 无 session 拒绝）")
class WorkerProductionControllerTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "order-1";

    @Mock
    private ProductionService productionService;
    @Mock
    private WorkerSessionService workerSessionService;

    private MockMvc mockMvc;

    private static final WorkerIdentity ZHANG =
            new WorkerIdentity("worker-zhang", "张三", WorkerIdentity.SOURCE_SERVER_SESSION, "sess-1");

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        WorkerProductionController controller =
                new WorkerProductionController(productionService, workerSessionService);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Test
    @DisplayName("🔴 无工人 session ⇒ 401 且**不进服务层**（不降级到 body 口径）")
    void reportWithoutWorkerSessionRejected() throws Exception {
        when(workerSessionService.resolveIdentity(any())).thenReturn(null);

        mockMvc.perform(post("/api/worker/production/orders/" + ORDER_ID + "/operations/op-1/report")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"worker_id\":\"worker-li\",\"worker_name\":\"李四\",\"qty\":1,"
                                + "\"qualified_qty\":1,\"work_type\":\"normal\"}"))
                .andExpect(status().isUnauthorized());

        verify(productionService, never()).report(any(), any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("🔴 有工人 session ⇒ 传下去的身份是 **server_session**（body 传别人的 id 不参与）")
    void reportPassesServerResolvedIdentity() throws Exception {
        when(workerSessionService.resolveIdentity("sess-1")).thenReturn(ZHANG);
        when(productionService.report(any(), any(), any(), any(), any(), any()))
                .thenReturn(Map.of("operation_id", "op-1", "done_qty", 1, "status", "done",
                        "order_completed", false, "worker_name", "张三",
                        "identity_source", WorkerIdentity.SOURCE_SERVER_SESSION));

        mockMvc.perform(post("/api/worker/production/orders/" + ORDER_ID + "/operations/op-1/report")
                        .header(WorkerSessionService.SESSION_HEADER, "sess-1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"worker_id\":\"worker-li\",\"worker_name\":\"李四\",\"qty\":1,"
                                + "\"qualified_qty\":1,\"work_type\":\"normal\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.identity_source").value(WorkerIdentity.SOURCE_SERVER_SESSION))
                .andExpect(jsonPath("$.data.worker_name").value("张三"));

        ArgumentCaptor<WorkerIdentity> identityCaptor = ArgumentCaptor.forClass(WorkerIdentity.class);
        verify(productionService).report(eq(ORDER_ID), eq("op-1"), any(), eq(TENANT), isNull(),
                identityCaptor.capture());
        assertThat(identityCaptor.getValue().workerId())
                .as("HTTP 层传下去的必须是登录者（body 里的 worker-li 不参与）")
                .isEqualTo("worker-zhang");
        assertThat(identityCaptor.getValue().source()).isEqualTo(WorkerIdentity.SOURCE_SERVER_SESSION);
    }

    @Test
    @DisplayName("读面（operations）无工人 session ⇒ 401，不进服务层")
    void operationsWithoutWorkerSessionRejected() throws Exception {
        // 无 session ⇒ 控制器拿不到身份（null）⇒ 必须显式拒绝（不静默当匿名放行）
        when(workerSessionService.resolveIdentity(any())).thenReturn(null);

        mockMvc.perform(get("/api/worker/production/orders/" + ORDER_ID + "/operations"))
                .andExpect(status().isUnauthorized());

        verify(productionService, never()).getOperations(any(), any());
    }

    @Test
    @DisplayName("读面（operations）有工人 session ⇒ 200，且读的是**同一份**服务端读面")
    void operationsWithWorkerSessionReturnsSameReadModel() throws Exception {
        when(workerSessionService.resolveIdentity("sess-1")).thenReturn(ZHANG);
        Map<String, Object> detail = new LinkedHashMap<>();
        detail.put("order_id", ORDER_ID);
        when(productionService.getOperations(ORDER_ID, TENANT)).thenReturn(detail);

        mockMvc.perform(get("/api/worker/production/orders/" + ORDER_ID + "/operations")
                        .header(WorkerSessionService.SESSION_HEADER, "sess-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.order_id").value(ORDER_ID));

        verify(productionService).getOperations(ORDER_ID, TENANT);
    }

    @Test
    @DisplayName("current-worker 无 session ⇒ 401；有 session ⇒ 200（页头「当前工人」数据源）")
    void currentWorkerEndpoints() throws Exception {
        when(workerSessionService.resolveIdentity(any())).thenReturn(null);
        mockMvc.perform(get("/api/worker/production/current-worker"))
                .andExpect(status().isUnauthorized());

        when(workerSessionService.resolveIdentity("sess-1")).thenReturn(ZHANG);
        when(workerSessionService.currentWorker("sess-1")).thenReturn(Map.of("worker_name", "张三"));
        mockMvc.perform(get("/api/worker/production/current-worker")
                        .header(WorkerSessionService.SESSION_HEADER, "sess-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.worker_name").value("张三"));
    }

    @Test
    @DisplayName("会话失效（resolveIdentity 抛 401）⇒ 401（不静默当匿名放行）")
    void expiredSessionRejected() throws Exception {
        when(workerSessionService.resolveIdentity("sess-old"))
                .thenThrow(BusinessException.authFailed("登录已闲置超时（默认 15 分钟），请重新登录"));

        mockMvc.perform(post("/api/worker/production/orders/" + ORDER_ID + "/operations/op-1/report")
                        .header(WorkerSessionService.SESSION_HEADER, "sess-old")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"qty\":1,\"qualified_qty\":1,\"work_type\":\"normal\"}"))
                .andExpect(status().isUnauthorized());
    }
}
