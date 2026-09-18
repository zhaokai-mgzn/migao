package com.migao.admin.controller;

// case_ids: OR-032

import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.CraftCalcClient;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.http.MediaType.APPLICATION_JSON;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 算料试算控制器测试（issue #4421）
 *
 * 判据：
 *   ① 端点 `POST /api/admin/orders/craft-calc` 返回 `{success,data}` 外壳，`data` 含
 *      `fabricMeters` / `pleatCount` / `formulaText`（**公式串由后端（ai-agent）产出**，
 *      控制器只搬运，绝不自拼）；
 *   ② 入参校验 fail-closed：缺 width / width ≤ 0 ⇒ 400，且**不调** ai-agent；
 *   ③ 权限：`@RequirePermission("order:list")`（下单页试算属订单读域）；
 *   ④ 不落库：控制器只调 `CraftCalcClient`，不碰任何 Repository/Service 写路径
 *      （试算 = 纯读，落库由下单接口负责）。
 *
 * 红证（实现前）：`CraftCalcController` 不存在 ⇒ 本文件编译失败（找不到符号）。
 */
@DisplayName("CraftCalcController 算料试算端点（issue #4421）")
class CraftCalcControllerTest extends BaseControllerTest {

    private static final String URL = "/api/admin/orders/craft-calc";

    private CraftCalcClient craftCalcClient;
    private CraftCalcController controller;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        craftCalcClient = mock(CraftCalcClient.class);
        controller = new CraftCalcController(craftCalcClient);
        mockMvc = buildMockMvc(controller);
    }

    private static CraftCalcClient.CraftCalcResult frozen() {
        return new CraftCalcClient.CraftCalcResult(
                new BigDecimal("13.3"), 52, 26,
                new BigDecimal("2.0"), new BigDecimal("2.02"),
                "fixed_height_pleats",
                "(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米",
                "formula", "standard", "");
    }

    @Test
    @DisplayName("冻结样例：6.6m/2.5m/双开/标准档 ⇒ 13.3 米 / 52 折 + 后端公式串")
    void returnsFrozenSampleWithFormulaText() throws Exception {
        when(craftCalcClient.calc(any())).thenReturn(frozen());

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("""
                        {"width":6.6,"height":2.5,"open_count":2,"mounting":"s_hook","craft_tier":"standard"}
                        """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.fabricMeters").value(13.3))
                .andExpect(jsonPath("$.data.pleatCount").value(52))
                .andExpect(jsonPath("$.data.perPanelPleats").value(26))
                .andExpect(jsonPath("$.data.fullness").value(2.0))
                .andExpect(jsonPath("$.data.fullnessActual").value(2.02))
                .andExpect(jsonPath("$.data.source").value("formula"))
                .andExpect(jsonPath("$.data.formulaText")
                        .value("(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米"));
    }

    @Test
    @DisplayName("入参原样透传给 ai-agent：控制器不补默认值、不重算（防第二份算料逻辑）")
    @SuppressWarnings("unchecked")
    void passesRequestBodyThroughVerbatim() throws Exception {
        when(craftCalcClient.calc(any())).thenReturn(frozen());

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("""
                        {"width":6.6,"height":2.5,"open_count":2,"mounting":"s_hook","craft_tier":"standard"}
                        """))
                .andExpect(status().isOk());

        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(craftCalcClient).calc(captor.capture());
        assertThat(captor.getValue())
                .containsEntry("width", 6.6)
                .containsEntry("height", 2.5)
                .containsEntry("open_count", 2)
                .containsEntry("mounting", "s_hook")
                .containsEntry("craft_tier", "standard");
    }

    @Test
    @DisplayName("缺 width ⇒ 400 且**不调** ai-agent（fail-closed，不猜窗宽）")
    void missingWidthRejectedWithoutCalling() throws Exception {
        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("{\"height\":2.5}"))
                .andExpect(status().isBadRequest());

        verify(craftCalcClient, never()).calc(any());
    }

    @Test
    @DisplayName("width ≤ 0 ⇒ 400 且**不调** ai-agent")
    void nonPositiveWidthRejectedWithoutCalling() throws Exception {
        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("{\"width\":0}"))
                .andExpect(status().isBadRequest());
        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("{\"width\":-1}"))
                .andExpect(status().isBadRequest());

        verify(craftCalcClient, never()).calc(any());
    }

    @Test
    @DisplayName("ai-agent 不可用 ⇒ 422 透传错误码（不静默给 0 米）")
    void unavailableAgentPropagatesFailClosed() throws Exception {
        when(craftCalcClient.calc(any())).thenThrow(new BusinessException(
                CraftCalcClient.ERR_CRAFT_CALC_UNAVAILABLE, "算料服务（ai-agent）不可用", 422, "请确认服务已启动"));

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("{\"width\":6.6}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("CRAFT_CALC_UNAVAILABLE"));
    }

    @Test
    @DisplayName("权限声明：试算属订单读域 order:list（下单页可用，无需管理权限）")
    void requiresOrderListPermission() throws Exception {
        RequirePermission annotation = CraftCalcController.class
                .getMethod("craftCalc", Map.class).getAnnotation(RequirePermission.class);
        assertThat(annotation).isNotNull();
        assertThat(annotation.value()).isEqualTo("order:list");
    }
}
