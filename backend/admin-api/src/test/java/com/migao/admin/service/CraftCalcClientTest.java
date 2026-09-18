package com.migao.admin.service;

// case_ids: OR-032

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;

import java.lang.reflect.Field;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 算料试算客户端测试（issue #4421 Java 接线）
 *
 * 守三条会被下一位验收者重开的判据：
 *   ① 冻结契约逐字：全路径 {@code POST /api/internal/production/craft-calc} + {@code X-Service-Token}
 *      头 + {@code {width,height,open_count,mounting,craft_tier,style}} 请求体 +
 *      {@code {success,data:{fabric_meters,pleat_count,…,formula_text}}} 响应外壳；
 *   ② 解析逐值：数值 → BigDecimal、{@code formula_text} → 原文（**公式串由后端产出**，
 *      Java 侧只搬运，绝不自拼 —— 自拼 = 第二份算料逻辑）；
 *   ③ **fail-closed**：未配置 token / 不可达 / {@code success != true} / 响应缺
 *      {@code data.fabric_meters} 或 {@code data.formula_text} ⇒ 一律 422 + 可行动 suggestion，
 *      **不得**返回 0 或空公式（静默给 0 米会让商家按 0 下单）。
 *
 * 红证（实现前）：{@code CraftCalcClient} 不存在 ⇒ 本文件编译失败（找不到符号）。
 */
@DisplayName("CraftCalcClient 算料试算客户端（issue #4421）")
class CraftCalcClientTest {

    private static final String URL = "http://agent:8000/api/internal/production/craft-calc";

    private RestTemplate restTemplate;
    private CraftCalcClient client;

    @BeforeEach
    void setUp() throws Exception {
        restTemplate = mock(RestTemplate.class);
        client = new CraftCalcClient(restTemplate);
        inject("baseUrl", "http://agent:8000/");   // 尾斜杠必须被归一（既有 ProductionOperationQtyClient 同款）
        inject("serviceToken", "svc-token-1");
    }

    private void inject(String field, String value) throws Exception {
        Field f = CraftCalcClient.class.getDeclaredField(field);
        f.setAccessible(true);
        f.set(client, value);
    }

    /** 冻结样例（issue #4421 判据）：6.6m / 2.5m / 双开 / 韩褶 / 标准档 ⇒ 52 折 / 13.3 米。 */
    private static Map<String, Object> request() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("width", 6.6);
        body.put("height", 2.5);
        body.put("open_count", 2);
        body.put("mounting", "s_hook");
        body.put("craft_tier", "standard");
        return body;
    }

    private static String responseBody() {
        return """
                {"success":true,"data":{
                  "fabric_meters":13.3,"pleat_count":52,"per_panel_pleats":26,"open_count":2,
                  "margin":0.3,"per_fold":0.25,"fullness":2.0,"fullness_actual":2.02,
                  "formula_used":"fixed_height_pleats",
                  "formula_text":"(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米",
                  "source":"formula","craft_tier":"standard","warning":""},
                 "requestId":"req_1","timestamp":1758100000}
                """;
    }

    @Test
    @DisplayName("冻结契约：全路径 + X-Service-Token + 请求体逐字 + 响应逐值解析")
    void sendsFrozenContractAndParsesVerbatim() {
        when(restTemplate.exchange(eq(URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok(responseBody()));

        CraftCalcClient.CraftCalcResult result = client.calc(request());

        assertThat(result.fabricMeters()).isEqualByComparingTo("13.3");
        assertThat(result.pleatCount()).isEqualTo(52);
        assertThat(result.perPanelPleats()).isEqualTo(26);
        assertThat(result.perFold()).isEqualByComparingTo("0.25");
        assertThat(result.fullness()).isEqualByComparingTo("2.0");
        assertThat(result.fullnessActual()).isEqualByComparingTo("2.02");
        assertThat(result.formulaUsed()).isEqualTo("fixed_height_pleats");
        assertThat(result.formulaText())
                .isEqualTo("(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米");
        assertThat(result.source()).isEqualTo("formula");
        assertThat(result.craftTier()).isEqualTo("standard");
        assertThat(result.warning()).isEmpty();
    }

    @Test
    @DisplayName("拼色样例：per_fold=0.65 + 34.1 米逐值解析（系数由后端给，Java 侧不自算）")
    void parsesMixedColorPerFoldVerbatim() {
        when(restTemplate.exchange(eq(URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok("""
                        {"success":true,"data":{
                          "fabric_meters":34.1,"pleat_count":52,"per_panel_pleats":26,
                          "per_fold":0.65,"open_count":2,"margin":0.3,
                          "fullness":2.0,"fullness_actual":5.17,
                          "formula_used":"fixed_height_pleats",
                          "formula_text":"(6.6+0.3)×2 → 52折 → 0.65×52+0.3 = 34.1米",
                          "source":"formula","craft_tier":"standard","warning":""}}
                        """));

        CraftCalcClient.CraftCalcResult result = client.calc(Map.of(
                "width", 6.6, "open_count", 2, "style", "拼色", "special_options", List.of("拼1次")));

        assertThat(result.fabricMeters()).isEqualByComparingTo("34.1");
        assertThat(result.perFold()).isEqualByComparingTo("0.65");
        assertThat(result.formulaText()).contains("0.65×52");
    }

    @Test
    @DisplayName("请求体形态逐字：这是与 ai-agent 端点的冻结契约，改了必须两边同改")
    @SuppressWarnings("rawtypes")
    void sendsRequestBodyVerbatim() {
        when(restTemplate.exchange(eq(URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok(responseBody()));

        client.calc(request());

        org.mockito.ArgumentCaptor<HttpEntity> captor = org.mockito.ArgumentCaptor.forClass(HttpEntity.class);
        verify(restTemplate).exchange(eq(URL), eq(HttpMethod.POST), captor.capture(), eq(String.class));
        assertThat(captor.getValue().getHeaders().getFirst("X-Service-Token")).isEqualTo("svc-token-1");
        Map<String, Object> body = new ObjectMapper().convertValue(captor.getValue().getBody(), Map.class);
        assertThat(body).isEqualTo(request());
    }

    @Test
    @DisplayName("缺省入参由服务端给：不传 height/open_count/craft_tier 时**不自行编造**（不塞默认值）")
    void doesNotInventDefaults() {
        when(restTemplate.exchange(eq(URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok(responseBody()));

        client.calc(Map.of("width", 6.6));

        @SuppressWarnings("rawtypes")
        org.mockito.ArgumentCaptor<HttpEntity> captor = org.mockito.ArgumentCaptor.forClass(HttpEntity.class);
        verify(restTemplate).exchange(eq(URL), eq(HttpMethod.POST), captor.capture(), eq(String.class));
        Map<String, Object> body = new ObjectMapper().convertValue(captor.getValue().getBody(), Map.class);
        assertThat(body).containsOnlyKeys("width");
    }

    @Test
    @DisplayName("fail-closed：未配置 ai-agent.service-token ⇒ 422 + 建议，且**不发请求**")
    void missingServiceTokenFailsClosedWithoutCalling() throws Exception {
        inject("serviceToken", "");

        assertThatThrownBy(() -> client.calc(request()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("算料服务")
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getCode()).isEqualTo("CRAFT_CALC_UNAVAILABLE");
                    assertThat(be.getHttpStatus()).isEqualTo(422);
                    assertThat(be.getSuggestion()).contains("ai-agent.service-token");
                });

        verify(restTemplate, never()).exchange(anyString(), any(), any(), eq(String.class));
    }

    @Test
    @DisplayName("fail-closed：ai-agent 不可达 ⇒ 422 + 可行动建议（绝不静默给 0 米）")
    void unreachableServiceFailsClosed() {
        when(restTemplate.exchange(eq(URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenThrow(new ResourceAccessException("Connection refused"));

        assertThatThrownBy(() -> client.calc(request()))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getCode()).isEqualTo("CRAFT_CALC_UNAVAILABLE");
                    assertThat(be.getHttpStatus()).isEqualTo(422);
                    assertThat(be.getSuggestion()).contains(URL);
                });
    }

    @Test
    @DisplayName("fail-closed：外壳 success != true ⇒ 422（不把失败当成功解析）")
    void successFalseFailsClosed() {
        when(restTemplate.exchange(eq(URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok("{\"success\":false,\"data\":null}"));

        assertThatThrownBy(() -> client.calc(request()))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getCode())
                        .isEqualTo("CRAFT_CALC_UNAVAILABLE"));
    }

    @Test
    @DisplayName("fail-closed：响应缺 fabric_meters ⇒ 422（不把 0 当用料交给商家）")
    void missingFabricMetersFailsClosed() {
        when(restTemplate.exchange(eq(URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok("""
                        {"success":true,"data":{"pleat_count":52,
                         "formula_text":"x","source":"formula"}}
                        """));

        assertThatThrownBy(() -> client.calc(request()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("fabric_meters");
    }

    @Test
    @DisplayName("fail-closed：响应缺 formula_text ⇒ 422（公式串必须由后端给，Java 侧不自拼）")
    void missingFormulaTextFailsClosed() {
        when(restTemplate.exchange(eq(URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok("""
                        {"success":true,"data":{"fabric_meters":13.3,"pleat_count":52,
                         "source":"formula"}}
                        """));

        assertThatThrownBy(() -> client.calc(request()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("formula_text");
    }

    @Test
    @DisplayName("空请求短circuit：无宽度 ⇒ 不发请求，直接 422（宽度是必填）")
    void blankWidthFailsClosedWithoutCalling() {
        assertThatThrownBy(() -> client.calc(Map.of()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("width");
        assertThatThrownBy(() -> client.calc(null))
                .isInstanceOf(BusinessException.class);
        verify(restTemplate, never()).exchange(anyString(), any(), any(), eq(String.class));
    }
}
