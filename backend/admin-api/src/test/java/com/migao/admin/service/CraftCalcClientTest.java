package com.migao.admin.service;

// case_ids: OR-032, OR-041

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.CraftCalcConfig;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CraftCalcConfigMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;

import java.lang.reflect.Field;
import java.math.BigDecimal;
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
    private CraftCalcConfigMapper craftCalcConfigMapper;
    private CraftCalcClient client;

    @BeforeEach
    void setUp() throws Exception {
        restTemplate = mock(RestTemplate.class);
        craftCalcConfigMapper = mock(CraftCalcConfigMapper.class);
        client = new CraftCalcClient(restTemplate, craftCalcConfigMapper);
        TenantContext.clear();   // ThreadLocal：防上一条用例的租户泄漏进下一条
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
        // issue #4527：用料计算方法（pleat 韩折公式 / fullness 褶倍数公式）—— Java 侧只**透传**
        body.put("formula", "pleat");
        return body;
    }

    private static String responseBody() {
        return """
                {"success":true,"data":{
                  "fabric_meters":13.3,"pleat_count":52,"per_panel_pleats":26,"open_count":2,
                  "margin":0.3,"per_fold":0.25,"fullness":2.0,"fullness_actual":2.02,
                  "formula_used":"fixed_height_pleats",
                  "formula_text":"韩折公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米",
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
                .isEqualTo("韩折公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米");
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
    @DisplayName("#4527 formula 透传：Java 侧不校验、不改写、不补默认值（算料口径只属引擎）")
    @SuppressWarnings("rawtypes")
    void passesFormulaThroughVerbatim() {
        when(restTemplate.exchange(eq(URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok(responseBody()));

        Map<String, Object> body = new LinkedHashMap<>(request());
        body.put("formula", "fullness");
        client.calc(body);

        org.mockito.ArgumentCaptor<HttpEntity> captor = org.mockito.ArgumentCaptor.forClass(HttpEntity.class);
        verify(restTemplate).exchange(eq(URL), eq(HttpMethod.POST), captor.capture(), eq(String.class));
        Map<String, Object> sent = new ObjectMapper().convertValue(captor.getValue().getBody(), Map.class);
        assertThat(sent).containsEntry("formula", "fullness");
    }

    @Test
    @DisplayName("#4527 褶倍数公式响应：11.0 米 + 公式串由后端给（Java 侧只搬运，不自拼公式）")
    void parsesFullnessFormulaResultVerbatim() {
        when(restTemplate.exchange(eq(URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok("""
                        {"success":true,"data":{
                          "fabric_meters":11.0,"pleat_count":null,"per_panel_pleats":null,
                          "open_count":2,"margin":null,"per_fold":null,
                          "fullness":2.0,"fullness_actual":null,
                          "formula_used":"fixed_height_fullness",
                          "formula_text":"褶倍数公式：(5.5÷2)×2 → 每片 2.75×2=5.5米 ×2片 = 11.0米",
                          "source":"formula","craft_tier":"standard","warning":""}}
                        """));

        CraftCalcClient.CraftCalcResult result = client.calc(Map.of(
                "width", 5.5, "open_count", 2, "craft_tier", "standard", "formula", "fullness"));

        assertThat(result.fabricMeters()).isEqualByComparingTo("11.0");
        assertThat(result.formulaUsed()).isEqualTo("fixed_height_fullness");
        assertThat(result.formulaText()).startsWith("褶倍数公式：").endsWith("= 11.0米");
        // 折数类字段在褶倍数公式下**如实缺席**（不发明「52 折」这种数）：端点回 null ⇒ Java 侧取到 0
        // （`fullness_actual` 有显式 null 判据 ⇒ null；`per_fold`/`pleat_count`/`per_panel_pleats`
        //   走 `decimalValue()`/`asInt()`，null ⇒ 0 —— 既有解析口径，本包不改）。
        assertThat(result.pleatCount()).isZero();
        assertThat(result.perPanelPleats()).isZero();
        assertThat(result.perFold()).isEqualByComparingTo("0");
        assertThat(result.fullnessActual()).isNull();
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

    // ══════════════════════════════════════════════════════════════════════
    // issue #4528（包 E）：租户级配置注入 + 引擎默认值
    // ══════════════════════════════════════════════════════════════════════

    private static final String DEFAULTS_URL = "http://agent:8000/api/internal/production/craft-calc-config";

    /** 本租户配置行（判据：改它 ⇒ 折数法用料随之变）。 */
    private static CraftCalcConfig storedRow(Long tenantId, String perFoldSingle, String marginMulti) {
        return CraftCalcConfig.builder()
                .id("ccc-" + tenantId)
                .tenantId(tenantId)
                .perFoldSingle(new BigDecimal(perFoldSingle))
                .perFoldMixedTimes(Map.of("1", new BigDecimal("0.65"), "2", new BigDecimal("1.2")))
                .marginSingle(new BigDecimal("0.2"))
                .marginMulti(new BigDecimal(marginMulti))
                .minFullness(new BigDecimal("1.5"))
                .tiers(Map.of("standard", Map.of("fullness", new BigDecimal("2.0"), "label", "标准工艺")))
                .defaultFormula("pleat")
                .sideMargin(new BigDecimal("0.3"))
                .metersRoundingStep(new BigDecimal("0.1"))
                .status("active")
                .deleted(0)
                .build();
    }

    @SuppressWarnings("rawtypes")
    private Map<String, Object> sentBody() {
        org.mockito.ArgumentCaptor<HttpEntity> captor = org.mockito.ArgumentCaptor.forClass(HttpEntity.class);
        verify(restTemplate).exchange(eq(URL), eq(HttpMethod.POST), captor.capture(), eq(String.class));
        return new ObjectMapper().convertValue(captor.getValue().getBody(), Map.class);
    }

    @Test
    @DisplayName("#4528 配置注入：本租户有配置行 ⇒ 随请求带上 config（键名 = 引擎配置键，零映射）")
    @SuppressWarnings("unchecked")
    void injectsTenantConfigWhenRowExists() {
        when(restTemplate.exchange(eq(URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok(responseBody()));
        when(craftCalcConfigMapper.selectActiveByTenant(7L)).thenReturn(storedRow(7L, "0.5", "0.3"));
        TenantContext.setTenantId(7L);

        Map<String, Object> original = request();
        client.calc(original);

        Map<String, Object> config = (Map<String, Object>) sentBody().get("config");
        // 逐值比对用字符串形态：数值在线上是 JSON 数字，Java 侧是 BigDecimal
        //（`BigDecimal.equals(Double)` 恒 false —— 按 equals 断言会得到「0.5 != 0.5」的假红）
        assertThat(String.valueOf(config.get("per_fold_single"))).isEqualTo("0.5");
        assertThat(String.valueOf(config.get("margin_multi"))).isEqualTo("0.3");
        assertThat(config).containsEntry("default_formula", "pleat");
        assertThat(config).containsKeys("per_fold_mixed_times", "margin_single", "min_fullness",
                "tiers", "side_margin", "meters_rounding_step");
        // 调用方的 map **不得**被就地改（上游可能复用同一个请求对象）
        assertThat(original).doesNotContainKey("config");
    }

    @Test
    @DisplayName("#4528 缺行 = 引擎默认值：不传 config ⇒ 未配置租户的算料结果与包 D 逐值一致")
    void doesNotInjectConfigWhenNoRow() {
        when(restTemplate.exchange(eq(URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok(responseBody()));
        when(craftCalcConfigMapper.selectActiveByTenant(7L)).thenReturn(null);
        TenantContext.setTenantId(7L);

        client.calc(request());

        // 红证：Java 侧自行补一份「默认配置」发过去 ⇒ 本断言红（那是第二份会漂的默认值）
        assertThat(sentBody()).doesNotContainKey("config");
    }

    @Test
    @DisplayName("#4528 不跨租户串：两次调用各带各的配置（无字段/静态缓存）")
    @SuppressWarnings("unchecked")
    void doesNotLeakConfigAcrossTenants() {
        when(restTemplate.exchange(eq(URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok(responseBody()));
        when(craftCalcConfigMapper.selectActiveByTenant(7L)).thenReturn(storedRow(7L, "0.5", "0.3"));
        when(craftCalcConfigMapper.selectActiveByTenant(8L)).thenReturn(storedRow(8L, "0.2", "0.9"));

        TenantContext.setTenantId(7L);
        client.calc(request());
        Map<String, Object> first = (Map<String, Object>) sentBody().get("config");

        org.mockito.Mockito.reset(restTemplate);
        when(restTemplate.exchange(eq(URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok(responseBody()));
        TenantContext.setTenantId(8L);
        client.calc(request());
        Map<String, Object> second = (Map<String, Object>) sentBody().get("config");

        assertThat(String.valueOf(first.get("per_fold_single"))).isEqualTo("0.5");
        assertThat(String.valueOf(second.get("per_fold_single"))).isEqualTo("0.2");   // 红证：缓存 A 的配置 ⇒ 这里仍是 0.5
        assertThat(String.valueOf(second.get("margin_multi"))).isEqualTo("0.9");
    }

    @Test
    @DisplayName("#4528 引擎默认值：GET 内部端点逐值解析（Java 侧不写第二份默认常量）")
    void readsEngineDefaults() {
        when(restTemplate.exchange(eq(DEFAULTS_URL), eq(HttpMethod.GET), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok("""
                        {"success":true,"data":{"config":{
                          "per_fold_single":0.25,"per_fold_mixed_times":{"1":0.65,"2":1.2},
                          "margin_single":0.2,"margin_multi":0.3,"min_fullness":1.5,
                          "tiers":{"standard":{"fullness":2.0,"label":"标准工艺"},
                                   "economy":{"fullness":1.8,"label":"经济工艺"}},
                          "default_formula":"pleat","side_margin":0.3,"meters_rounding_step":0.1}}}
                        """));

        Map<String, Object> config = client.defaultConfig();

        assertThat(config).containsEntry("per_fold_single", 0.25);
        assertThat(config).containsEntry("min_fullness", 1.5);
        assertThat(config).containsEntry("default_formula", "pleat");
        assertThat(config).containsEntry("meters_rounding_step", 0.1);
        assertThat(config).hasSize(9);
    }

    @Test
    @DisplayName("#4528 fail-closed：默认值端点缺 data.config ⇒ 422（拒绝凭空造一份默认值）")
    void missingEngineDefaultsFailsClosed() {
        when(restTemplate.exchange(eq(DEFAULTS_URL), eq(HttpMethod.GET), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok("{\"success\":true,\"data\":{}}"));

        assertThatThrownBy(() -> client.defaultConfig())
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("data.config")
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(422));
    }
}
