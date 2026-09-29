package com.migao.admin.controller;

// case_ids: PG-045

import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.CuttingHeightConfigService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.http.MediaType.APPLICATION_JSON;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 裁高配置端点测试（V140，母单 #5161）。
 *
 * <p>判据（每条都能红）：</p>
 * <ol>
 *   <li>{@code GET} ⇒ 200 + {@code data.source} 原样透传（**不把 default 画成 stored**）；</li>
 *   <li>租户**只**来自 {@code TenantContext}（不来自请求参数 —— 请求参数能被伪造）；</li>
 *   <li>{@code PUT} 合法 ⇒ 200 + 请求体**原样**交给服务（控制器不补默认值、不改键名）；</li>
 *   <li>服务层 422 ⇒ 响应**保留** {@code error.details[].{field,message}} 逐条理由；</li>
 *   <li>{@code POST …/preview} ⇒ 200 且**只读**（不写配置：服务层只调 preview）；</li>
 *   <li><b>权限面</b>：{@code GET} = {@code production:view}；{@code PUT} 与 {@code preview} = 类级
 *       {@code processing:manage}（红证：给 preview 加回 {@code production:view}
 *       ⇒ 本判据红，且 `test_rbac_submenu_granularity` 的「写动词挂读码」台账会被撑大）。</li>
 * </ol>
 */
@DisplayName("CuttingHeightConfigController 裁高配置端点（V140 / 母单 #5161）")
class CuttingHeightConfigControllerTest extends BaseControllerTest {

    private static final String URL = "/api/admin/production/cutting-height-config";

    private CuttingHeightConfigService service;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        service = mock(CuttingHeightConfigService.class);
        mockMvc = buildMockMvc(new CuttingHeightConfigController(service));
    }

    @Test
    @DisplayName("GET：租户取自 TenantContext，source 原样透传")
    void getPassesThroughSourceAndTenant() throws Exception {
        when(service.get(TEST_TENANT_ID)).thenReturn(storedResponse("default"));

        mockMvc.perform(get(URL))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.source").value("default"));

        verify(service).get(eq(TEST_TENANT_ID));
    }

    @Test
    @DisplayName("PUT：请求体原样交给服务（控制器不补默认值、不改键名）")
    void putHandsBodyOverVerbatim() throws Exception {
        when(service.put(eq(TEST_TENANT_ID), any())).thenReturn(storedResponse("stored"));
        String body = objectMapper.writeValueAsString(validBody());

        mockMvc.perform(put(URL).contentType(APPLICATION_JSON).content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.source").value("stored"));

        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(service).put(eq(TEST_TENANT_ID), captor.capture());
        assertThat(captor.getValue()).containsOnlyKeys("items", "rounding");
    }

    @Test
    @DisplayName("PUT：服务层 422 ⇒ 逐条理由原样透传（不吞成 500、不丢 details）")
    void putKeepsValidationDetails() throws Exception {
        when(service.put(eq(TEST_TENANT_ID), any())).thenThrow(
                BusinessException.validationError("裁高配置有 1 处不合法",
                        List.of(BusinessException.detail("items[0].value", "必须在 0 ~ 10 米之间")),
                        "按逐条理由修正后重试"));

        mockMvc.perform(put(URL).contentType(APPLICATION_JSON).content("{}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.details[0].field").value("items[0].value"));
    }

    @Test
    @DisplayName("POST …/preview：200 且只读（不碰写面）")
    void previewIsReadOnly() throws Exception {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("source", "stored");
        data.put("base", new BigDecimal("2.92"));
        data.put("cutting_height", new BigDecimal("2.935"));
        data.put("hits", List.of());
        data.put("misses", List.of());
        when(service.preview(eq(TEST_TENANT_ID), any())).thenReturn(data);

        mockMvc.perform(post(URL + "/preview").contentType(APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(previewRequest())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.cutting_height").value(2.935));

        verify(service).preview(eq(TEST_TENANT_ID), any());
    }

    @Test
    @DisplayName("权限面：GET=production:view；PUT / preview=类级 processing:manage")
    void permissionSurfaceIsExplicit() throws Exception {
        RequirePermission classLevel = CuttingHeightConfigController.class.getAnnotation(RequirePermission.class);
        assertThat(classLevel).isNotNull();
        assertThat(classLevel.value()).isEqualTo("processing:manage");

        RequirePermission get = CuttingHeightConfigController.class
                .getMethod("get").getAnnotation(RequirePermission.class);
        assertThat(get).isNotNull();
        assertThat(get.value()).isEqualTo("production:view");

        // preview 刻意**不**声明方法级码 ⇒ 继承类级写码（写动词挂读码会撑大「只许缩短」的台账）
        assertThat(CuttingHeightConfigController.class.getMethod("preview", Map.class)
                .getAnnotation(RequirePermission.class)).isNull();
        assertThat(CuttingHeightConfigController.class.getMethod("put", Map.class)
                .getAnnotation(RequirePermission.class)).isNull();
    }

    // ── helpers ──

    private static Map<String, Object> storedResponse(String source) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("source", source);
        data.put("config", validBody());
        return data;
    }

    private static Map<String, Object> validBody() {
        Map<String, Object> hit = new LinkedHashMap<>();
        hit.put("trigger_kind", "option");
        hit.put("trigger_value", "布贴");
        hit.put("position", "布帘");
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("key", "butie");
        item.put("name", "布贴");
        item.put("value", new BigDecimal("0.015"));
        item.put("direction", "add");
        item.put("height_join", false);
        item.put("hit", hit);
        item.put("hit_expr", null);
        item.put("enabled", true);
        item.put("order", 10);
        Map<String, Object> rounding = new LinkedHashMap<>();
        rounding.put("mode", "half_up");
        rounding.put("digits", 3);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("items", List.of(item));
        body.put("rounding", rounding);
        return body;
    }

    private static Map<String, Object> previewRequest() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("position", "布帘");
        body.put("finished_height", "2.92");
        body.put("special_options", List.of("布贴"));
        return body;
    }
}
