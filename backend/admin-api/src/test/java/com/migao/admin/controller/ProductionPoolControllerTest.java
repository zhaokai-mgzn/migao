// case_ids: PR-072
package com.migao.admin.controller;

import com.migao.admin.dto.ProductionPoolViews;
import com.migao.admin.service.ProcessingOrderService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;
import java.util.List;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * ProductionPoolController 端点测试（issue #5169 = 阶段 2b-1）。
 *
 * <p>只判**装配**（请求参数原样下传、缺省不下传 = 服务侧的缺省值生效）——
 * 「池怎么分组、等待多久算超上限、跨订单成组省了几米」的判据分别在
 * {@code ProcessingOrderServiceTest}（PR-069/PR-070，装配与顺序）与
 * {@code PooledDispatchRealDbTest}（PR-071，真库落账读数）。</p>
 *
 * <p>🔴 本类的核心一条是 {@code /dispatch} 不传 {@code pooled} ⇒ 下传 {@code null}
 * （= 服务侧的「缺省关」）—— 这一层是「记录期基线不被污染」的**入口守卫**：
 * 若在这里写死 {@code true}（或在 DTO 上再写一个缺省值），池化就会对所有既有调用方默认生效。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProductionPoolController 端点（issue #5169）")
class ProductionPoolControllerTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock
    private ProcessingOrderService processingOrderService;

    @InjectMocks
    private ProductionPoolController controller;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(controller);
    }

    /**
     * 空池夹具。issue #5177 给 {@code Pool} 加了两个成员：
     * {@code urgentCount}（加急插队区去重订单数）与 {@code urgentLines}（插队区行）；
     * 本夹具是「没有加急单」的形态 ⇒ 两者为 0 / 空，**既有断言（poolingEnabled=false、
     * overdueCount=0）逐值不变**。
     */
    private static ProductionPoolViews.Pool emptyPool(BigDecimal maxWaitHours) {
        return new ProductionPoolViews.Pool(maxWaitHours, false, 0, 0, 0, 0,
                List.of(), List.of(), List.of());
    }

    @Test
    @DisplayName("#5169 判据5 GET /pool — 不传 maxWaitHours ⇒ 下传 null（服务侧用缺省上限，不在这里编造）")
    void poolWithoutMaxWaitHoursPassesNull() throws Exception {
        when(processingOrderService.pool(eq(1L), isNull())).thenReturn(emptyPool(new BigDecimal("24")));

        mockMvc.perform(get("/api/admin/production/pool"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.maxWaitHours").value(24))
                .andExpect(jsonPath("$.data.poolingEnabled").value(false))
                .andExpect(jsonPath("$.data.overdueCount").value(0));

        verify(processingOrderService).pool(eq(1L), isNull());
    }

    @Test
    @DisplayName("#5169 判据5 GET /pool — maxWaitHours 原样下传（滞留上限**可配**）")
    void poolPassesMaxWaitHours() throws Exception {
        when(processingOrderService.pool(eq(1L), any())).thenReturn(emptyPool(new BigDecimal("6")));

        mockMvc.perform(get("/api/admin/production/pool").param("maxWaitHours", "6"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.maxWaitHours").value(6));

        verify(processingOrderService).pool(eq(1L), eq(new BigDecimal("6")));
    }

    @Test
    @DisplayName("🔴 #5169 判据1 POST /dispatch — 不传 pooled ⇒ 下传 null（**缺省关**的 HTTP 入口守卫）")
    void dispatchWithoutPooledFlagStaysPerOrder() throws Exception {
        when(processingOrderService.generate(anyList(), any(), eq(1L), any(), any(), any()))
                .thenReturn(List.of(ProcessingOrderService.GenerateResult.ok("order-1", "JG-1")));

        mockMvc.perform(post("/api/admin/production/pool/dispatch")
                        .contentType("application/json")
                        .content("{\"orderIds\":[\"order-1\"]}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[0].success").value(true));

        // 服务侧的缺省解析（POOLED_DEFAULT_ENABLED）是**唯一**的缺省值来源；
        // 控制器这一层必须原样传 null，不得替它做决定
        verify(processingOrderService).generate(anyList(), any(), eq(1L), any(), isNull(), isNull());
    }

    @Test
    @DisplayName("#5169 判据2 POST /dispatch — pooled=true 原样下传（池化必须**显式**开启）")
    void dispatchWithPooledFlagReachesTheService() throws Exception {
        when(processingOrderService.generate(anyList(), any(), eq(1L), any(), eq("best_fit"), eq(true)))
                .thenReturn(List.of(ProcessingOrderService.GenerateResult.ok("order-1", "JG-1")));

        mockMvc.perform(post("/api/admin/production/pool/dispatch")
                        .contentType("application/json")
                        .content("{\"orderIds\":[\"order-1\"],\"assignmentRule\":\"best_fit\","
                                + "\"pooled\":true}"))
                .andExpect(status().isOk());

        verify(processingOrderService).generate(anyList(), any(), eq(1L), any(), eq("best_fit"), eq(true));
    }

    @Test
    @DisplayName("#5169 判据4 POST /preview — 只读预览（orderIds/batches/assignmentRule 原样下传）")
    void previewPassesItsInputs() throws Exception {
        when(processingOrderService.preview(eq(1L), anyList(), any(), eq("fifo")))
                .thenReturn(new ProductionPoolViews.Preview(2, "fifo", new BigDecimal("6"),
                        new BigDecimal("3"), new BigDecimal("3"), new BigDecimal("6"),
                        new BigDecimal("3")));

        mockMvc.perform(post("/api/admin/production/pool/preview")
                        .contentType("application/json")
                        .content("{\"orderIds\":[\"order-1\",\"order-2\"],\"assignmentRule\":\"fifo\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.savedMeters").value(3))
                .andExpect(jsonPath("$.data.formulaMeters").value(6))
                .andExpect(jsonPath("$.data.assignmentRule").value("fifo"));

        verify(processingOrderService).preview(eq(1L), anyList(), any(), eq("fifo"));
    }
}
