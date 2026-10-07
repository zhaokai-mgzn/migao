// case_ids: DA-022
// 用料缺口视图只读端点（issue #6280）：GET /api/admin/materials/shortage —— 入参三件原样透传、
// 租户上下文由 TenantContext 单点注入、响应形状（ApiResponse 包裹具名视图）、权限点
// （复用商品读权限 product:list，不新造权限码）。
//
// 判据只读性自证：本文件不起 Spring 上下文、不连库（standalone MockMvc + mock service）。

package com.migao.admin.controller;

import com.migao.admin.dto.MaterialShortageViews;
import com.migao.admin.dto.MaterialShortageViews.FieldInfo;
import com.migao.admin.dto.MaterialShortageViews.HistoryDepth;
import com.migao.admin.dto.MaterialShortageViews.MaterialShortageRow;
import com.migao.admin.dto.MaterialShortageViews.MaterialShortageView;
import com.migao.admin.dto.MaterialShortageViews.NonComparable;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.MaterialShortageService;
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
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * MaterialShortageController 单元测试（issue #6280）—— 只读查询端点。
 *
 * <p>本文件是 {@code .github/growth_gate.py} 对 {@code MaterialShortageController.java}
 * 要求的同名控制器判据（缺了它会直接 block 合并）。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("MaterialShortageController 用料缺口视图")
class MaterialShortageControllerTest extends BaseControllerTest {

    private static final String BASE = "/api/admin/materials/shortage";

    private MockMvc mockMvc;

    @Mock
    private MaterialShortageService materialShortageService;

    @InjectMocks
    private MaterialShortageController materialShortageController;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(materialShortageController);
    }

    @AfterEach
    void tearDown() {
        super.baseTearDown();
    }

    // ── 夹具 ────────────────────────────────────────────────────────────────────

    private static MaterialShortageView sampleView() {
        Map<String, FieldInfo> fields = new LinkedHashMap<>();
        fields.put("gap_meters", new FieldInfo(MaterialShortageViews.WIRED, null,
                "SUM(order_items.quantity) − SUM(product_skus.stock)", MaterialShortageViews.HAS_TRUTH,
                "需求减供给（负 = 有余量）", "缺口（米）"));
        fields.put("rate_per_week", new FieldInfo(MaterialShortageViews.NOT_WIRED,
                "声明无真值（v1 未接线）：真实周桶深度不足", "history_depth",
                MaterialShortageViews.NO_TRUTH, "每周用料速率", "周速率"));
        Map<String, Integer> bandCounts = new LinkedHashMap<>();
        for (String bandName : MaterialShortageViews.RISK_BANDS) {
            bandCounts.put(bandName, 0);
        }
        bandCounts.put("blocked", 1);
        return new MaterialShortageView(
                MaterialShortageViews.VIEW_ID,
                1L,
                "2026-10-04",
                Map.of("unit", "米（可比性判据 = products.unit = '米'）"),
                fields,
                List.of(new MaterialShortageRow("p-1", "遮光布", new BigDecimal("10.0"), 1, 1,
                        new BigDecimal("4.0"), new BigDecimal("6.0"), "blocked", -2,
                        java.time.LocalDate.of(2026, 10, 2), null, null, List.of())),
                1,
                1,
                false,
                List.of("rate_per_week", "exhaust_date"),
                List.of("gap_meters"),
                bandCounts,
                new NonComparable(0, 0),
                0,
                0,
                HistoryDepth.insufficient(2, 2, MaterialShortageService.REQUIRED_WEEKS));
    }

    // ── 判据 ────────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("GET 无参 —— 200 + ApiResponse 包裹具名视图（视图 id / 分层 / 三态逐字段透出）")
    void shortage_ok() throws Exception {
        when(materialShortageService.shortage(null, null, null)).thenReturn(sampleView());

        mockMvc.perform(get(BASE))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.view").value("material_shortage"))
                .andExpect(jsonPath("$.data.tenantId").value(1))
                .andExpect(jsonPath("$.data.asOf").value("2026-10-04"))
                .andExpect(jsonPath("$.data.rows[0].productId").value("p-1"))
                .andExpect(jsonPath("$.data.rows[0].riskBand").value("blocked"))
                .andExpect(jsonPath("$.data.rows[0].gapMeters").value(6.0))
                .andExpect(jsonPath("$.data.rows[0].daysToDeadline").value(-2))
                .andExpect(jsonPath("$.data.bandCounts.blocked").value(1))
                .andExpect(jsonPath("$.data.historyDepth.sufficient").value(false))
                .andExpect(jsonPath("$.data.fields.rate_per_week.status").value("not_wired"))
                .andExpect(jsonPath("$.data.fields.gap_meters.status").value("wired"));
    }

    @Test
    @DisplayName("GET 三件入参 —— statuses / limit / as_of **原样**透传（控制器不持任何算法）")
    void shortage_passesThreeParamsVerbatim() throws Exception {
        when(materialShortageService.shortage("confirmed", "7", "2026-10-01")).thenReturn(sampleView());

        mockMvc.perform(get(BASE)
                        .param("statuses", "confirmed")
                        .param("limit", "7")
                        .param("as_of", "2026-10-01"))
                .andExpect(status().isOk());

        ArgumentCaptor<String> statuses = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> limit = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> asOf = ArgumentCaptor.forClass(String.class);
        verify(materialShortageService).shortage(statuses.capture(), limit.capture(), asOf.capture());
        // 控制器**不做**解析 / 归一化：非法值的 400 由 service 的 parseLimit / parseStatuses 单点给出
        assertThat(statuses.getValue()).isEqualTo("confirmed");
        assertThat(limit.getValue()).as("limit 必须原样透传（在控制器里 try-parse 会让 400 口径分叉）")
                .isEqualTo("7");
        assertThat(asOf.getValue()).isEqualTo("2026-10-01");
    }

    @Test
    @DisplayName("GET 不传参 —— service 收到三个 null（缺省口径在 service 单点，不在控制器）")
    void shortage_defaultsAreServiceOwned() throws Exception {
        when(materialShortageService.shortage(null, null, null)).thenReturn(sampleView());

        mockMvc.perform(get(BASE)).andExpect(status().isOk());

        verify(materialShortageService).shortage(null, null, null);
    }

    @Test
    @DisplayName("权限面：读端点挂**既有** product:list（不新造权限码，也不放宽）")
    void permissionSurfaceIsExplicit() throws Exception {
        assertThat(MaterialShortageController.class.getAnnotation(RequirePermission.class))
                .as("本控制器是只读端点 ⇒ 类级不得声明写码").isNull();
        RequirePermission onMethod = MaterialShortageController.class
                .getMethod("shortage", String.class, String.class, String.class)
                .getAnnotation(RequirePermission.class);
        assertThat(onMethod).as("方法级必须显式声明权限码（缺了 = 端点裸奔）").isNotNull();
        assertThat(onMethod.value()).isEqualTo("product:list");
    }

    @Test
    @DisplayName("只读自证：唯一的映射方法是 GET（写动词映射 + 类级写码一律判红）")
    void controllerIsReadOnly() throws Exception {
        // 只读面 = 「读端点挂读权限」这条架构契约：本体是 GET，且**不存在**任何写动词映射
        assertThat(MaterialShortageController.class.getMethod("shortage", String.class, String.class, String.class)
                .getAnnotation(org.springframework.web.bind.annotation.GetMapping.class))
                .as("shortage 必须是 GET 映射").isNotNull();
        for (java.lang.reflect.Method m : MaterialShortageController.class.getDeclaredMethods()) {
            for (Class<? extends java.lang.annotation.Annotation> writeMapping : List.of(
                    org.springframework.web.bind.annotation.PostMapping.class,
                    org.springframework.web.bind.annotation.PutMapping.class,
                    org.springframework.web.bind.annotation.DeleteMapping.class,
                    org.springframework.web.bind.annotation.PatchMapping.class)) {
                assertThat(m.getAnnotation(writeMapping))
                        .as("只读端点不得有写动词映射：%s 上的 %s", m.getName(), writeMapping.getSimpleName())
                        .isNull();
            }
        }
        verifyNoInteractions(materialShortageService);
    }
}
