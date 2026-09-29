package com.migao.admin.controller;

// case_ids: PG-045

import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.WorkerPageConfigService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.web.servlet.MockMvc;

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
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 工人端页面开关端点测试（V141，母单 #5161）。
 *
 * <p>判据（每条都能红）：</p>
 * <ol>
 *   <li>{@code GET} ⇒ 200 + {@code data.source} 原样透传（**不把 default 画成 stored**）；</li>
 *   <li>租户**只**来自 {@code TenantContext}（不来自请求参数 —— 请求参数能被伪造）；</li>
 *   <li>{@code PUT} 合法 ⇒ 200 + 请求体**原样**交给服务（控制器不补默认值、不改键名）；</li>
 *   <li>服务层 422 ⇒ 响应**保留** {@code error.details[].{field,message}} 逐条理由；</li>
 *   <li><b>权限面</b>：{@code GET} = {@code production:view}；{@code PUT} = 类级
 *       {@code processing:manage}（红证：给 PUT 挂读码 ⇒ 本条红，且
 *       {@code test_rbac_submenu_granularity} 的「写动词挂读码」台账会被撑大）。</li>
 * </ol>
 */
@DisplayName("WorkerPageConfigController 工人端页面开关端点（V141 / 母单 #5161）")
class WorkerPageConfigControllerTest extends BaseControllerTest {

    private static final String URL = "/api/admin/worker-page-config";

    private WorkerPageConfigService service;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        service = mock(WorkerPageConfigService.class);
        mockMvc = buildMockMvc(new WorkerPageConfigController(service));
    }

    @Test
    @DisplayName("GET：租户取自 TenantContext，source 原样透传")
    void getPassesThroughSourceAndTenant() throws Exception {
        when(service.get(TEST_TENANT_ID)).thenReturn(response("default", List.of("report", "order")));

        mockMvc.perform(get(URL))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.source").value("default"))
                .andExpect(jsonPath("$.data.pages[0]").value("report"));

        verify(service).get(eq(TEST_TENANT_ID));
    }

    @Test
    @DisplayName("PUT：请求体原样交给服务（控制器不补默认值、不改键名）")
    void putHandsBodyOverVerbatim() throws Exception {
        when(service.put(eq(TEST_TENANT_ID), any())).thenReturn(response("stored", List.of("shipment")));

        mockMvc.perform(put(URL).contentType(APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of("pages", List.of("shipment")))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.source").value("stored"));

        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(service).put(eq(TEST_TENANT_ID), captor.capture());
        assertThat(captor.getValue()).containsOnlyKeys("pages");
    }

    @Test
    @DisplayName("PUT：服务层 422 ⇒ 逐条理由原样透传（不吞成 500、不丢 details）")
    void putKeepsValidationDetails() throws Exception {
        when(service.put(eq(TEST_TENANT_ID), any())).thenThrow(
                BusinessException.validationError("工人端页面配置有 1 处不合法",
                        List.of(BusinessException.detail("pages[1]", "不是工人端页面键：stock")),
                        "按逐条理由修正后重试"));

        mockMvc.perform(put(URL).contentType(APPLICATION_JSON).content("{\"pages\":[\"report\",\"stock\"]}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.details[0].field").value("pages[1]"));
    }

    @Test
    @DisplayName("权限面：GET=production:view；PUT=类级 processing:manage")
    void permissionSurfaceIsExplicit() throws Exception {
        RequirePermission classLevel = WorkerPageConfigController.class.getAnnotation(RequirePermission.class);
        assertThat(classLevel).isNotNull();
        assertThat(classLevel.value()).isEqualTo("processing:manage");

        RequirePermission get = WorkerPageConfigController.class
                .getMethod("get").getAnnotation(RequirePermission.class);
        assertThat(get).isNotNull();
        assertThat(get.value()).isEqualTo("production:view");

        // PUT 刻意**不**声明方法级码 ⇒ 继承类级写码（写动词挂读码会撑大「只许缩短」的台账）
        assertThat(WorkerPageConfigController.class.getMethod("put", Map.class)
                .getAnnotation(RequirePermission.class)).isNull();
    }

    private static Map<String, Object> response(String source, List<String> pages) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("source", source);
        data.put("pages", pages);
        data.put("labels", Map.of("report", "报工"));
        return data;
    }
}
