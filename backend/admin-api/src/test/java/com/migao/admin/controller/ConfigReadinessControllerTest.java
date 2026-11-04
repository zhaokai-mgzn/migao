// case_ids: MC-189
package com.migao.admin.controller;

import com.migao.admin.security.PermissionInterceptor;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ConfigReadinessService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * {@code GET /api/admin/config-readiness} 的端点契约（issue #6579）。
 *
 * <p>判据（每条都能红）：</p>
 * <ol>
 *   <li><b>权限码 = {@code production:view}，且声明在方法级</b>（反射现取）。
 *       红证：改成类级或换码 ⇒ 断言当场红（该页第一屏码 / 菜单节点码 / 路由守卫码三处会跟着脱钩）。</li>
 *   <li><b>跨码步骤按调用方权限省略</b>：不持 {@code processing:manage} ⇒ 传给服务的
 *       {@code includeRemnantSizes=false}，响应里没有 {@code steps['remnant-sizes']}；
 *       持码 ⇒ {@code true} 且该步在。红证：把布尔写死成 {@code true}（或把码写成别的一串）
 *       ⇒ {@code verify} 与响应体断言同时红。</li>
 *   <li><b>响应只给事实</b>：没有 {@code state} 键、也不出现三态字面量（那是前端判据模块的活）。</li>
 * </ol>
 *
 * <p>响应体用 {@code ObjectMapper} 读成 {@code Map} 再断言，不用 JsonPath 的括号语法 ——
 * 步骤键里有连字符（{@code remnant-sizes} / {@code default-route}），把语法细节押在表达式上会让
 * 「断言写错」与「实现错了」长得一样。</p>
 */
@DisplayName("ConfigReadinessController 配置就绪度端点（issue #6579）")
class ConfigReadinessControllerTest extends BaseControllerTest {

    private static final String URL = "/api/admin/config-readiness";

    private ConfigReadinessService service;
    private PermissionInterceptor permissionInterceptor;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        service = mock(ConfigReadinessService.class);
        permissionInterceptor = mock(PermissionInterceptor.class);
        mockMvc = buildMockMvc(new ConfigReadinessController(service, permissionInterceptor));
    }

    /** 一份最小的状态无关载荷：只区分「有没有 remnant-sizes 那一步」。 */
    private static Map<String, Object> payload(boolean withRemnantSizes) {
        Map<String, Object> steps = new LinkedHashMap<>();
        steps.put(ConfigReadinessService.STEP_OPERATIONS,
                Map.of("facts", Map.of("total", 3, "unpriced", 1, "orphans", 1),
                        "href", "/production/routings"));
        if (withRemnantSizes) {
            steps.put(ConfigReadinessService.STEP_REMNANT_SIZES,
                    Map.of("facts", Map.of("configured", true, "items", 1),
                            "href", "/settings?domain=remnant-sizes"));
        }
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("steps", steps);
        return data;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> stepsOf(MvcResult result) throws Exception {
        Map<String, Object> body = new com.fasterxml.jackson.databind.ObjectMapper()
                .readValue(result.getResponse().getContentAsString(StandardCharsets.UTF_8), Map.class);
        Map<String, Object> data = (Map<String, Object>) body.get("data");
        assertThat(data).as("响应缺 data（ApiResponse 壳被改？）").isNotNull();
        return (Map<String, Object>) data.get("steps");
    }

    @Test
    @DisplayName("① 权限码 = production:view，且是**方法级**（不是类级）")
    void declaresMethodLevelProductionView() throws Exception {
        Method readiness = ConfigReadinessController.class.getMethod("readiness");
        RequirePermission annotation = readiness.getAnnotation(RequirePermission.class);

        assertThat(annotation).as("readiness() 缺方法级 @RequirePermission ⇒ 该端点没有任何码把守")
                .isNotNull();
        assertThat(annotation.value()).isEqualTo("production:view");
        assertThat(ConfigReadinessController.class.getAnnotation(RequirePermission.class))
                .as("本控制器的码必须声明在方法级（类级会让「这个端点用哪个码」失去源码证据）")
                .isNull();
    }

    @Test
    @DisplayName("② 不持 processing:manage ⇒ 响应里没有 remnant-sizes 那一步（负控）")
    void omitsRemnantSizesWhenCallerLacksTheCode() throws Exception {
        when(permissionInterceptor.holdsPermission(ConfigReadinessService.REMNANT_SIZES_READ_CODE))
                .thenReturn(false);
        when(service.readiness(TEST_TENANT_ID, false)).thenReturn(payload(false));

        MvcResult result = mockMvc.perform(get(URL))
                .andExpect(status().isOk())
                .andReturn();

        Map<String, Object> steps = stepsOf(result);
        assertThat(steps.keySet()).containsExactly(ConfigReadinessService.STEP_OPERATIONS);

        // 负控的承重处：问的必须是**余料尺寸读面的那个码**（写成别的串 ⇒ 这里红）
        verify(permissionInterceptor).holdsPermission(ConfigReadinessService.REMNANT_SIZES_READ_CODE);
        verify(service).readiness(eq(TEST_TENANT_ID), eq(false));
    }

    @Test
    @DisplayName("③ 持 processing:manage ⇒ 那一步在，且 facts / href 逐值可读")
    void includesRemnantSizesForHolders() throws Exception {
        when(permissionInterceptor.holdsPermission(ConfigReadinessService.REMNANT_SIZES_READ_CODE))
                .thenReturn(true);
        when(service.readiness(TEST_TENANT_ID, true)).thenReturn(payload(true));

        MvcResult result = mockMvc.perform(get(URL))
                .andExpect(status().isOk())
                .andReturn();

        Map<String, Object> steps = stepsOf(result);
        assertThat(steps).containsKey(ConfigReadinessService.STEP_REMNANT_SIZES);
        assertThat(String.valueOf(steps.get(ConfigReadinessService.STEP_REMNANT_SIZES)))
                .contains("configured=true", "items=1", "href=/settings?domain=remnant-sizes");
        verify(service).readiness(eq(TEST_TENANT_ID), eq(true));
    }

    @Test
    @DisplayName("④ 响应只给事实：没有 state 键、也不出现三态字面量")
    void responseCarriesFactsOnly() throws Exception {
        when(permissionInterceptor.holdsPermission(ConfigReadinessService.REMNANT_SIZES_READ_CODE))
                .thenReturn(false);
        when(service.readiness(TEST_TENANT_ID, false)).thenReturn(payload(false));

        MvcResult result = mockMvc.perform(get(URL))
                .andExpect(status().isOk())
                .andReturn();
        String body = result.getResponse().getContentAsString(StandardCharsets.UTF_8);

        assertThat(body).doesNotContain("\"state\"", "\"done\"", "\"todo\"", "\"unknown\"");
        // 事实与出处两件套：facts + href（少一个 ⇒ 前端要么画不出数、要么「去配置」成死链）
        assertThat(String.valueOf(stepsOf(result).get(ConfigReadinessService.STEP_OPERATIONS)))
                .contains("facts=", "href=/production/routings");
    }
}
