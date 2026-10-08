package com.migao.admin.service;

// case_ids: CH-021

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
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
 * {@code ImageRecognitionClient.interpret}（issue #6367 包 P2）判据。
 *
 * <ol>
 *   <li>走内部端点 {@code POST /api/internal/vision/interpret} + {@code X-Service-Token}
 *       （与 {@code recognize} 同一套范式，不另立约定）；</li>
 *   <li>{@code hint} 可选：**空/缺省 ⇒ 请求体里不出现该键**（不发送空串 —— 上游会把它当成一次
 *       真实的文本提示）；有值 ⇒ 原样带；</li>
 *   <li>返回体 <b>page_fill 计划原样搬运</b>（含 {@code [米宝解读]} 来源与 {@code note_source}）；
 *       {@code degraded=true} / 空 fields 是<b>合法结果</b>，如实透传；</li>
 *   <li>不可达 / 外壳失败 / 缺 {@code data.fields} / {@code component != page_fill} ⇒ 422 fail-closed
 *       （可行动 suggestion，不 500 裸抛、不静默空计划）；</li>
 *   <li>🔴 推理多一次 LLM 调用 ⇒ **超时必须比 {@code recognize} 更宽**（同族上界 = 黄金策推理那档）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("ImageRecognitionClient interpret 客户端（issue #6367 包 P2）")
class ImageRecognitionInterpretTest {

    /** 冻结夹具：ai-agent 的 page_fill 形状（含 `[米宝解读]` 一格 + 歧义候选一格）。 */
    private static final String FROZEN_BODY = """
            {"success":true,"data":{"component":"page_fill","target_type":"product","fields":[
              {"key":"color","label":"颜色","value":"雾霾蓝","source":"[图片识别]","reason":null,
               "candidates":null,"note":null,"note_source":null},
              {"key":"material","label":"材质","value":"雪尼尔","source":"[米宝解读]","reason":null,
               "candidates":null,"note":"雪尼尔常用于客厅遮光帘","note_source":"[米宝解读]"},
              {"key":"craft","label":"工艺","value":null,"source":null,"reason":"目录里没有「韩褶双层」⇒ 宁可不填",
               "candidates":["韩褶","双层"],"note":"建议先确认是不是「韩褶」","note_source":"[米宝解读]"}
            ]}}
            """;

    @Mock
    private RestTemplate restTemplate;

    private ImageRecognitionClient client() {
        ImageRecognitionClient client = new ImageRecognitionClient(restTemplate, restTemplate);
        ReflectionTestUtils.setField(client, "serviceToken", "test-service-token");
        ReflectionTestUtils.setField(client, "baseUrl", "http://ai-agent:8001");
        return client;
    }

    private void stub(String body) {
        when(restTemplate.exchange(anyString(), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok(body));
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> payloadOf() {
        ArgumentCaptor<HttpEntity<?>> entityCaptor = ArgumentCaptor.forClass(HttpEntity.class);
        verify(restTemplate).exchange(anyString(), eq(HttpMethod.POST), entityCaptor.capture(), eq(String.class));
        return (Map<String, Object>) entityCaptor.getValue().getBody();
    }

    @Test
    @DisplayName("冻结夹具：page_fill 计划原样搬运（含 [米宝解读] 来源、note、candidates）")
    void interpret_passesPageFillThroughVerbatim() {
        stub(FROZEN_BODY);

        ImageRecognitionClient.PageFillResult result =
                client().interpret("product", List.of("https://oss.example.com/a.jpg"), "客厅雪尼尔");

        assertThat(result.component()).isEqualTo("page_fill");
        assertThat(result.targetType()).isEqualTo("product");
        assertThat(result.fields()).hasSize(3);
        assertThat(result.fields().get(0)).containsEntry("source", "[图片识别]");
        assertThat(result.fields().get(1))
                .containsEntry("source", "[米宝解读]")
                .containsEntry("value", "雪尼尔")
                .containsEntry("note", "雪尼尔常用于客厅遮光帘")
                .containsEntry("note_source", "[米宝解读]");
        // 歧义格：值留空 + 候选 + 理由，一个字都不许被 Java 侧改写
        assertThat(result.fields().get(2).get("value")).isNull();
        assertThat(result.fields().get(2).get("candidates")).isEqualTo(List.of("韩褶", "双层"));
        assertThat((String) result.fields().get(2).get("reason")).contains("宁可不填");
    }

    @Test
    @DisplayName("内部端点含 /api 前缀 + Service Token，请求体 snake_case 且带 hint")
    @SuppressWarnings("unchecked")
    void interpret_usesInternalPathAndCarriesHint() {
        stub(FROZEN_BODY);

        client().interpret("order", List.of("https://oss.example.com/a.jpg"), "手写单，客户电话在右上角");

        ArgumentCaptor<String> urlCaptor = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<HttpEntity<?>> entityCaptor = ArgumentCaptor.forClass(HttpEntity.class);
        verify(restTemplate).exchange(urlCaptor.capture(), eq(HttpMethod.POST),
                entityCaptor.capture(), eq(String.class));

        assertThat(urlCaptor.getValue()).endsWith("/api/internal/vision/interpret");

        Map<String, Object> payload = (Map<String, Object>) entityCaptor.getValue().getBody();
        assertThat(payload).containsEntry("target_type", "order");
        assertThat(payload).containsEntry("hint", "手写单，客户电话在右上角");
        assertThat(payload.get("images")).isEqualTo(List.of("https://oss.example.com/a.jpg"));
        assertThat(payload).containsKey("tenant_id");

        HttpHeaders headers = entityCaptor.getValue().getHeaders();
        assertThat(headers.getFirst("X-Service-Token")).isEqualTo("test-service-token");
    }

    @Test
    @DisplayName("🔴 空 hint ⇒ 请求体**不出现** hint 键（不发送空串当提示）")
    void interpret_blankHintOmitsTheKey() {
        stub(FROZEN_BODY);

        client().interpret("product", List.of("https://oss.example.com/a.jpg"), "   ");

        assertThat(payloadOf()).doesNotContainKey("hint");
    }

    @Test
    @DisplayName("degraded/空 fields ⇒ 合法结果，如实透传（不抛、不编造格）")
    void interpret_emptyFieldsIsAResultNotAnError() {
        stub("{\"success\":true,\"data\":{\"component\":\"page_fill\",\"target_type\":\"product\",\"fields\":[]}}");

        ImageRecognitionClient.PageFillResult result =
                client().interpret("product", List.of("https://oss.example.com/a.jpg"), null);

        assertThat(result.fields()).isEmpty();
        assertThat(result.component()).isEqualTo("page_fill");
        assertThat(result.targetType()).isEqualTo("product");
    }

    @Test
    @DisplayName("响应缺 data.fields ⇒ 422（「端点没说」不得静默读成「没推理出来」）")
    void interpret_missingFieldsFailsClosed() {
        stub("{\"success\":true,\"data\":{\"component\":\"page_fill\",\"target_type\":\"product\"}}");

        BusinessException ex = catchThrowableOfType(
                () -> client().interpret("product", List.of("https://oss.example.com/a.jpg"), null),
                BusinessException.class);

        assertThat(ex.getCode()).isEqualTo(ImageRecognitionClient.ERR_IMAGE_RECOGNITION_UNAVAILABLE);
        assertThat(ex.getHttpStatus()).isEqualTo(422);
        assertThat(ex.getMessage()).contains("缺少 data.fields");
    }

    @Test
    @DisplayName("component != page_fill ⇒ 422 fail-closed（形状不认得的计划不得当成计划用）")
    void interpret_unexpectedComponentFailsClosed() {
        stub("{\"success\":true,\"data\":{\"component\":\"interactive\",\"target_type\":\"product\",\"fields\":[]}}");

        BusinessException ex = catchThrowableOfType(
                () -> client().interpret("product", List.of("https://oss.example.com/a.jpg"), null),
                BusinessException.class);

        assertThat(ex.getHttpStatus()).isEqualTo(422);
        assertThat(ex.getMessage()).contains("component");
    }

    @Test
    @DisplayName("外壳 success != true ⇒ 422 fail-closed（不把失败当空计划放行）")
    void interpret_envelopeFailureFailsClosed() {
        stub("{\"success\":false,\"error\":{\"code\":\"INTERPRET_FAILED\"}}");

        BusinessException ex = catchThrowableOfType(
                () -> client().interpret("product", List.of("https://oss.example.com/a.jpg"), null),
                BusinessException.class);

        assertThat(ex.getHttpStatus()).isEqualTo(422);
        assertThat(ex.getMessage()).contains("success != true");
    }

    @Test
    @DisplayName("网络异常/超时 ⇒ 422 fail-closed + 可行动 suggestion（不 500 裸抛）")
    void interpret_networkFailureFailsClosedWithAManualFallback() {
        when(restTemplate.exchange(anyString(), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenThrow(new RuntimeException("Read timed out"));

        BusinessException ex = catchThrowableOfType(
                () -> client().interpret("product", List.of("https://oss.example.com/a.jpg"), null),
                BusinessException.class);

        assertThat(ex.getHttpStatus()).isEqualTo(422);
        assertThat(ex.getCode()).isEqualTo(ImageRecognitionClient.ERR_IMAGE_RECOGNITION_UNAVAILABLE);
        assertThat(ex.getMessage()).contains("Read timed out");
        assertThat(ex.getSuggestion()).contains("手工填写表单");
    }

    @Test
    @DisplayName("🔴 推理端超时比 recognize 宽（多一次 LLM 调用），且不超黄金策推理那档量级")
    void interpretTimeoutIsWiderThanRecognizeButBounded() {
        assertThat(ImageRecognitionClient.INTERPRET_READ_TIMEOUT_MS)
                .as("interpret = vision 一次 + 文本 LLM 一次 ⇒ 必须比 recognize 宽，否则长尾必现假故障")
                .isGreaterThan(ImageRecognitionClient.RECOGNIZE_READ_TIMEOUT_MS);
        assertThat(ImageRecognitionClient.INTERPRET_READ_TIMEOUT_MS)
                .as("同族 AI 能力端点（briefing 60s / recognize 75s）档位内，不无限等")
                .isLessThanOrEqualTo(180_000);
        // 两个 RestTemplate 的确按各自超时建（字段名/数量即承载体，见 client 注释）
        assertThat(ImageRecognitionClient.class.getDeclaredFields())
                .extracting(java.lang.reflect.Field::getName)
                .contains("restTemplate", "interpretRestTemplate");
    }

    @Test
    @DisplayName("ObjectMapper 口径：PageFillPlan 序列化出的键是 snake_case（target_type 恒在）")
    void pageFillPlanSerializesWithFrozenKeys() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        JsonNode node = mapper.readTree(mapper.writeValueAsString(
                new com.migao.admin.dto.PageFillPlan("page_fill", "product", List.of())));

        assertThat(node.has("component")).isTrue();
        assertThat(node.has("target_type")).isTrue();
        assertThat(node.has("targetType")).isFalse();
        assertThat(node.get("fields").isArray()).isTrue();
    }
}
