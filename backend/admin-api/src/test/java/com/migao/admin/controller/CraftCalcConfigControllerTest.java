package com.migao.admin.controller;

// case_ids: OR-041

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.CraftCalcConfigService;
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
 * 算料配置读写端点测试（issue #4528 = 包 E）。
 *
 * <p>判据（每条都能红）：</p>
 * <ol>
 *   <li>{@code GET /api/admin/production/craft-calc-config} 无行 ⇒ 200 +
 *       {@code data.source='default'} + 默认值（红证：凭空造一份默认 / 把 source 写成 stored ⇒ 红）；</li>
 *   <li>{@code PUT} 合法 ⇒ 200 + {@code data.source='stored'}，且**请求体原样**交给服务
 *       （控制器不补默认值、不改写键名 —— 补默认值 = 第二份口径）；</li>
 *   <li>非法值 ⇒ <b>422 + {@code error.details[].{field,message}} 逐条理由</b>
 *       （红证：静默回退默认值 ⇒ 200 ⇒ 红）；</li>
 *   <li>权限 = {@code processing:manage}（与工序库 / 工艺路线写面同口径）。</li>
 * </ol>
 */
@DisplayName("CraftCalcConfigController 算料配置端点（issue #4528）")
class CraftCalcConfigControllerTest extends BaseControllerTest {

    private static final String URL = "/api/admin/production/craft-calc-config";

    private CraftCalcConfigService service;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        service = mock(CraftCalcConfigService.class);
        mockMvc = buildMockMvc(new CraftCalcConfigController(service));
    }

    private static Map<String, Object> defaultResponse() {
        Map<String, Object> config = new LinkedHashMap<>();
        config.put("per_fold_single", 0.25);
        config.put("min_fullness", 1.5);
        config.put("default_formula", "pleat");
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("source", "default");
        data.put("config", config);
        return data;
    }

    @Test
    @DisplayName("GET 无配置行 ⇒ 200 + source=default + 引擎默认值（本租户=BaseControllerTest 的 1 号）")
    void getReturnsEngineDefaultsWhenNoRow() throws Exception {
        when(service.get(TEST_TENANT_ID)).thenReturn(defaultResponse());

        mockMvc.perform(get(URL))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.source").value("default"))
                .andExpect(jsonPath("$.data.config.per_fold_single").value(0.25))
                .andExpect(jsonPath("$.data.config.min_fullness").value(1.5));

        verify(service).get(eq(TEST_TENANT_ID));   // 租户来自 TenantContext（不来自请求参数）
    }

    @Test
    @DisplayName("GET 有配置行 ⇒ source=stored（页面据此区分「商家配置」与「系统默认值」）")
    void getReturnsStoredWhenRowExists() throws Exception {
        Map<String, Object> data = defaultResponse();
        data.put("source", "stored");
        when(service.get(TEST_TENANT_ID)).thenReturn(data);

        mockMvc.perform(get(URL))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.source").value("stored"));
    }

    @Test
    @DisplayName("PUT 合法 ⇒ 200 + source=stored，且请求体**原样**交给服务（不补默认值、不改键名）")
    void putPassesBodyThroughVerbatim() throws Exception {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("per_fold_single", 0.5);
        body.put("default_formula", "fullness");
        Map<String, Object> stored = defaultResponse();
        stored.put("source", "stored");
        when(service.put(eq(TEST_TENANT_ID), any())).thenReturn(stored);

        mockMvc.perform(put(URL).contentType(APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(body)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.source").value("stored"));

        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(service).put(eq(TEST_TENANT_ID), captor.capture());
        // 只搬运：两个键原样在，且**没有**被补上第三个键（补默认值 = 第二份口径）
        assertThat(captor.getValue()).containsOnlyKeys("per_fold_single", "default_formula");
        assertThat(captor.getValue()).containsEntry("per_fold_single", 0.5);
    }

    @Test
    @DisplayName("PUT 非法值 ⇒ 422 + error.details 逐条理由（静默回退默认值 ⇒ 红）")
    void putInvalidValueReturns422WithDetails() throws Exception {
        when(service.put(eq(TEST_TENANT_ID), any())).thenThrow(BusinessException.validationError(
                "算料配置有 2 处不合法，已整份拒绝（**不静默回退默认值**）",
                List.of(BusinessException.detail("min_fullness", "不得低于行业红线 1.5"),
                        BusinessException.detail("default_formula", "必须是 [pleat, fullness] 之一")),
                "请按逐条理由修正后重新提交"));

        mockMvc.perform(put(URL).contentType(APPLICATION_JSON)
                        .content("{\"min_fullness\":1.0,\"default_formula\":\"hanzhe\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.details.length()").value(2))
                .andExpect(jsonPath("$.error.details[0].field").value("min_fullness"))
                .andExpect(jsonPath("$.error.details[0].message").value("不得低于行业红线 1.5"))
                .andExpect(jsonPath("$.error.details[1].field").value("default_formula"));
    }

    @Test
    @DisplayName("权限 = processing:manage（与工序库 / 工艺路线写面同口径）")
    void requiresProcessingManagePermission() {
        RequirePermission annotation = CraftCalcConfigController.class.getAnnotation(RequirePermission.class);
        assertThat(annotation).isNotNull();
        assertThat(annotation.value()).isEqualTo("processing:manage");
    }

    @Test
    @DisplayName("端点路径冻结（前端与契约账本同源，改路径 = 三端同改）")
    void endpointMappingFrozen() {
        assertThat(CraftCalcConfigController.class.getAnnotation(
                org.springframework.web.bind.annotation.RequestMapping.class).value())
                .containsExactly(URL);
    }
}
