package com.migao.admin.service;

// case_ids: CH-021

import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowableOfType;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * ImageRecognitionClient 单元测试（issue #5321 包 1 · 页面快通道）。
 *
 * <p>判据：</p>
 * <ol>
 *   <li>走的是<b>既有内部 API 范式</b>：{@code POST /api/internal/vision/recognize} +
 *       {@code X-Service-Token}，请求体 snake_case（{@code tenant_id}/{@code target_type}/{@code images}）；</li>
 *   <li>字段表<b>原样搬运</b>：含 {@code value=null} 的留空格与它的 {@code reason}
 *       —— Java 侧不重建、不补默认值、不重算 {@code [图片识别]} 标注；</li>
 *   <li>{@code degraded=true} 是<b>合法结果</b>（没认出来 ≠ 服务故障）⇒ 正常返回，不抛；</li>
 *   <li>凭证/外壳/结构三类故障 fail-closed 抛 422（「端点没说」不得静默读成「没认出来」）；</li>
 *   <li>🔴 <b>不落库</b>：本类只依赖 {@code RestTemplate}（读面）——
 *       控制器侧另有依赖面反射断言（{@code ImageRecognitionControllerTest}），两层各锁一半。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("ImageRecognitionClient 图片识别客户端测试（issue #5321）")
class ImageRecognitionClientTest {

    /** 冻结夹具：ai-agent 真实返回形态（一个预填格 + 一个**故意留空**格）。 */
    private static final String FROZEN_BODY = """
            {"success":true,"data":{"target_type":"product","degraded":false,"fields":[
              {"key":"name","label":"商品名称","value":"雪尼尔遮光窗帘","source":"[图片识别]","reason":null},
              {"key":"door_width","label":"门幅","value":null,"source":null,"reason":"图片未标注门幅"}
            ]}}
            """;

    @Mock
    private RestTemplate restTemplate;

    /** 无 Spring 上下文 ⇒ `@Value` 字段未注入，测试里显式给（同 Repo 既有做法 ReflectionTestUtils）。 */
    private ImageRecognitionClient client() {
        ImageRecognitionClient client = new ImageRecognitionClient(restTemplate);
        ReflectionTestUtils.setField(client, "serviceToken", "test-service-token");
        ReflectionTestUtils.setField(client, "baseUrl", "http://ai-agent:8001");
        return client;
    }

    private void stub(String body) {
        when(restTemplate.exchange(anyString(), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok(body));
    }

    @Test
    @DisplayName("冻结夹具：字段表原样搬运（含留空格的 reason，不改写 [图片识别] 标注）")
    void recognise_passesFieldsThroughVerbatim() {
        stub(FROZEN_BODY);

        ImageRecognitionClient.ImageRecognitionResult result =
                client().recognize("product", List.of("https://oss.example.com/a.jpg"));

        assertThat(result.targetType()).isEqualTo("product");
        assertThat(result.degraded()).isFalse();
        assertThat(result.fields()).hasSize(2);
        assertThat(result.fields().get(0))
                .containsEntry("key", "name")
                .containsEntry("label", "商品名称")
                .containsEntry("value", "雪尼尔遮光窗帘")
                .containsEntry("source", "[图片识别]");
        // 留空的那一格：值必须是 null、理由必须原样带回（前端据此显示「未识别（原因）」）
        assertThat(result.fields().get(1)).containsEntry("key", "door_width");
        assertThat(result.fields().get(1)).containsEntry("reason", "图片未标注门幅");
        assertThat(result.fields().get(1).get("value")).isNull();
        assertThat(result.fields().get(1).get("source")).isNull();
    }

    @Test
    @DisplayName("内部端点路径含 /api 前缀，且请求体是 snake_case + Service Token")
    @SuppressWarnings("unchecked")
    void recognise_usesFullInternalPathAndServiceToken() {
        stub(FROZEN_BODY);

        client().recognize("order", List.of("https://oss.example.com/a.jpg"));

        ArgumentCaptor<String> urlCaptor = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<HttpEntity<?>> entityCaptor = ArgumentCaptor.forClass(HttpEntity.class);
        verify(restTemplate).exchange(urlCaptor.capture(), eq(HttpMethod.POST),
                entityCaptor.capture(), eq(String.class));

        assertThat(urlCaptor.getValue())
                .as("internal 路径必须含 /api 前缀（缺前缀 → ai-agent 404 → 整条页面入口不可用）")
                .endsWith("/api/internal/vision/recognize");

        Map<String, Object> payload = (Map<String, Object>) entityCaptor.getValue().getBody();
        assertThat(payload).containsEntry("target_type", "order");
        assertThat(payload.get("images")).isEqualTo(List.of("https://oss.example.com/a.jpg"));
        assertThat(payload).containsKey("tenant_id");

        HttpHeaders headers = entityCaptor.getValue().getHeaders();
        assertThat(headers.getFirst("X-Service-Token")).isEqualTo("test-service-token");
    }

    @Test
    @DisplayName("degraded=true 是合法结果：正常返回（没认出来 ≠ 服务故障）")
    void recognise_degradedIsAResultNotAnError() {
        stub("{\"success\":true,\"data\":{\"target_type\":\"order\",\"degraded\":true,\"fields\":[]}}");

        ImageRecognitionClient.ImageRecognitionResult result =
                client().recognize("order", List.of("https://oss.example.com/a.jpg"));

        assertThat(result.degraded()).isTrue();
        assertThat(result.fields()).isEmpty();
        assertThat(result.targetType()).isEqualTo("order");
    }

    @Test
    @DisplayName("响应缺 data.fields ⇒ 422（「端点没说」不得静默读成「没认出来」）")
    void recognise_missingFieldsFailsClosed() {
        stub("{\"success\":true,\"data\":{\"target_type\":\"product\"}}");

        BusinessException ex = catchThrowableOfType(
                () -> client().recognize("product", List.of("https://oss.example.com/a.jpg")),
                BusinessException.class);

        assertThat(ex.getCode()).isEqualTo(ImageRecognitionClient.ERR_IMAGE_RECOGNITION_UNAVAILABLE);
        assertThat(ex.getHttpStatus()).isEqualTo(422);
        assertThat(ex.getMessage()).contains("缺少 data.fields");
    }

    @Test
    @DisplayName("外壳 success != true ⇒ 422 fail-closed（不把失败当「没认出来」放行）")
    void recognise_envelopeFailureFailsClosed() {
        stub("{\"success\":false,\"error\":{\"code\":\"VISION_FAILED\"}}");

        BusinessException ex = catchThrowableOfType(
                () -> client().recognize("product", List.of("https://oss.example.com/a.jpg")),
                BusinessException.class);

        assertThat(ex.getHttpStatus()).isEqualTo(422);
        assertThat(ex.getMessage()).contains("success != true");
    }

    @Test
    @DisplayName("网络异常 ⇒ 422 fail-closed（suggestion 给出「也可以直接手工填表」的退路）")
    void recognise_networkFailureFailsClosedWithAManualFallback() {
        when(restTemplate.exchange(anyString(), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenThrow(new RuntimeException("connection refused"));

        BusinessException ex = catchThrowableOfType(
                () -> client().recognize("product", List.of("https://oss.example.com/a.jpg")),
                BusinessException.class);

        assertThat(ex.getMessage()).contains("图片识别服务（ai-agent）不可用");
        assertThat(ex.getSuggestion()).contains("手工填写表单");
    }
}