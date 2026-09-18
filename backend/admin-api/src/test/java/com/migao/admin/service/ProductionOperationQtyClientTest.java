package com.migao.admin.service;

// case_ids: PG-022

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
 * 工序应做数量客户端测试（issue #4208 Java 接线）
 *
 * 守三条会被下一位验收者重开的判据：
 *   ① 冻结契约逐字：全路径 {@code POST /api/internal/production/operation-qty} + {@code X-Service-Token}
 *      头 + {@code {positions:[{position_name, operations[], calc_info}]}} 请求体 +
 *      {@code {success,data:{positions:[{position_name, qty_by_operation, qty_source_by_operation}]}}} 响应外壳；
 *   ② 解析逐值：{@code qty_by_operation} → BigDecimal、{@code qty_source_by_operation} → 原文；
 *   ③ **fail-closed**（本单要治的缺陷的反面）：未配置 token / 不可达 / {@code success != true} /
 *      响应条数不符 ⇒ 一律 422 + 可行动 suggestion，**不得**返回空结果或静默降级
 *      （静默回退订单数量正是 issue #4208 的病根）。
 *
 * 红证（实现前）：`ProductionOperationQtyClient` 不存在 ⇒ 本文件编译失败（找不到符号）。
 */
@DisplayName("ProductionOperationQtyClient 算料数量客户端（issue #4208）")
class ProductionOperationQtyClientTest {

    private static final String URL = "http://agent:8000/api/internal/production/operation-qty";

    private RestTemplate restTemplate;
    private ProductionOperationQtyClient client;

    @BeforeEach
    void setUp() throws Exception {
        restTemplate = mock(RestTemplate.class);
        client = new ProductionOperationQtyClient(restTemplate);
        inject("baseUrl", "http://agent:8000/");   // 尾斜杠必须被归一（既有 BriefingGenerateClient 同款）
        inject("serviceToken", "svc-token-1");
    }

    private void inject(String field, String value) throws Exception {
        Field f = ProductionOperationQtyClient.class.getDeclaredField(field);
        f.setAccessible(true);
        f.set(client, value);
    }

    private static List<Map<String, Object>> requestPositions() {
        Map<String, Object> calcInfo = new LinkedHashMap<>();
        calcInfo.put("fabric_meters", 12.3);
        calcInfo.put("pleat_count", 24);
        Map<String, Object> position = new LinkedHashMap<>();
        position.put("position_name", "2699系列雪尼尔窗帘面料");
        position.put("operations", List.of("精裁-布", "布三边", "韩褶-布", "外帘装袋"));
        position.put("calc_info", calcInfo);
        return List.of(position);
    }

    private static String responseBody() {
        return """
                {"success":true,"data":{"positions":[
                  {"position_name":"2699系列雪尼尔窗帘面料",
                   "qty_by_operation":{"精裁-布":12.3,"布三边":12.3,"韩褶-布":24.0,"外帘装袋":1.0},
                   "qty_source_by_operation":{"精裁-布":"fabric_meters","布三边":"fabric_meters",
                                              "韩褶-布":"pleat_count","外帘装袋":"fallback"}}]},
                 "requestId":"req_1","timestamp":1758100000}
                """;
    }

    @Test
    @DisplayName("冻结契约：全路径 + X-Service-Token + 请求体逐字 + 响应逐值解析")
    void sendsFrozenContractAndParsesQtyVerbatim() throws Exception {
        when(restTemplate.exchange(eq(URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok(responseBody()));

        List<ProductionOperationQtyClient.PositionQty> resolved = client.resolve(requestPositions());

        assertThat(resolved).hasSize(1);
        ProductionOperationQtyClient.PositionQty position = resolved.get(0);
        assertThat(position.positionName()).isEqualTo("2699系列雪尼尔窗帘面料");
        assertThat(position.qtyByOperation()).containsOnlyKeys("精裁-布", "布三边", "韩褶-布", "外帘装袋");
        assertThat(position.qtyByOperation().get("精裁-布")).isEqualByComparingTo("12.3");
        assertThat(position.qtyByOperation().get("韩褶-布")).isEqualByComparingTo("24.0");
        assertThat(position.qtyByOperation().get("外帘装袋")).isEqualByComparingTo("1");
        assertThat(position.qtySourceByOperation().get("精裁-布")).isEqualTo("fabric_meters");
        assertThat(position.qtySourceByOperation().get("韩褶-布")).isEqualTo("pleat_count");
        assertThat(position.qtySourceByOperation().get("外帘装袋")).isEqualTo("fallback");

        // 请求体形态（外壳 + 鉴权头）逐字：这是与 ai-agent 端点的冻结契约，改了必须两边同改
        @SuppressWarnings("rawtypes")
        org.mockito.ArgumentCaptor<HttpEntity> captor = org.mockito.ArgumentCaptor.forClass(HttpEntity.class);
        verify(restTemplate).exchange(eq(URL), eq(HttpMethod.POST), captor.capture(), eq(String.class));
        assertThat(captor.getValue().getHeaders().getFirst("X-Service-Token")).isEqualTo("svc-token-1");
        Map<String, Object> body = new ObjectMapper().convertValue(captor.getValue().getBody(), Map.class);
        assertThat(body).containsOnlyKeys("positions");
        assertThat(body.get("positions")).isEqualTo(requestPositions());
    }

    @Test
    @DisplayName("fail-closed：未配置 ai-agent.service-token ⇒ 422 + 建议，且**不发请求**")
    void missingServiceTokenFailsClosedWithoutCalling() throws Exception {
        inject("serviceToken", "");

        assertThatThrownBy(() -> client.resolve(requestPositions()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不回退订单数量")
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getCode()).isEqualTo("PRODUCTION_OPERATION_QTY_UNAVAILABLE");
                    assertThat(be.getHttpStatus()).isEqualTo(422);
                    assertThat(be.getSuggestion()).contains("ai-agent.service-token");
                });

        verify(restTemplate, never()).exchange(anyString(), any(), any(), eq(String.class));
    }

    @Test
    @DisplayName("fail-closed：ai-agent 不可达 ⇒ 422 + 可行动建议（绝不静默回退订单数量）")
    void unreachableServiceFailsClosed() {
        when(restTemplate.exchange(eq(URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenThrow(new ResourceAccessException("Connection refused"));

        assertThatThrownBy(() -> client.resolve(requestPositions()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("算料服务")
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getCode()).isEqualTo("PRODUCTION_OPERATION_QTY_UNAVAILABLE");
                    assertThat(be.getHttpStatus()).isEqualTo(422);
                    assertThat(be.getSuggestion()).contains(URL).contains("重新生成加工单");
                });
    }

    @Test
    @DisplayName("fail-closed：外壳 success != true ⇒ 422（不把失败当成功解析）")
    void successFalseFailsClosed() {
        when(restTemplate.exchange(eq(URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok("{\"success\":false,\"data\":null}"));

        assertThatThrownBy(() -> client.resolve(requestPositions()))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getCode())
                        .isEqualTo("PRODUCTION_OPERATION_QTY_UNAVAILABLE"));
    }

    @Test
    @DisplayName("fail-closed：响应条数与请求不符 ⇒ 422（不返回部分结果，避免张冠李戴）")
    void responseShapeMismatchFailsClosed() {
        when(restTemplate.exchange(eq(URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok("{\"success\":true,\"data\":{\"positions\":[]}}"));

        assertThatThrownBy(() -> client.resolve(requestPositions()))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("条数与请求不符");
    }

    @Test
    @DisplayName("空请求不触发远端调用（无部位 ⇒ 无数量可问）")
    void emptyRequestShortCircuits() {
        assertThat(client.resolve(List.of())).isEmpty();
        verify(restTemplate, never()).exchange(anyString(), any(), any(), eq(String.class));
    }

    @Test
    @DisplayName("缺键兜底值由端点给出：客户端**不**自行补 1（防第二份兜底口径）")
    void clientDoesNotInventFallbackValues() throws Exception {
        when(restTemplate.exchange(eq(URL), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok("""
                        {"success":true,"data":{"positions":[
                          {"position_name":"2699系列雪尼尔窗帘面料",
                           "qty_by_operation":{"精裁-布":1.0},
                           "qty_source_by_operation":{"精裁-布":"fallback"}}]}}
                        """));

        List<ProductionOperationQtyClient.PositionQty> resolved = client.resolve(requestPositions());

        assertThat(resolved.get(0).qtyByOperation()).containsOnlyKeys("精裁-布");
        assertThat(resolved.get(0).qtyByOperation().get("精裁-布")).isEqualByComparingTo(BigDecimal.ONE);
    }
}
