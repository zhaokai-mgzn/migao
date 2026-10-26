package com.migao.admin.service;

// case_ids: UI-129

import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.RestTemplate;

import java.nio.charset.StandardCharsets;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * ProductImageClient 单测（issue #7335；失败码分叉 = issue #7552）。
 *
 * <p>判据：</p>
 * <ol>
 *   <li>成功外壳 ⇒ 原样取 {@code data.image_url} / {@code data.model}（Java 侧不重建）；</li>
 *   <li>缺 {@code image_url} / 外壳失败 ⇒ 422 fail-closed（不把「端点没说」当空结果）；</li>
 *   <li>未配置 service token ⇒ 422 且**不发任何外部请求**；</li>
 *   <li>上游 503 的 {@code code} ⇒ **不同**的本侧错误码与话术（issue #7552：模型不支持 /
 *       额度用尽 / 未启用 / 未配 Key / 瞬时不可用 五类互不相同）；</li>
 *   <li>对外 message / suggestion **不含**服务名与内部地址（§31 P3）；「稍后重试」
 *       只出现在真·瞬时那一条 —— 模型不支持时等多久都不会好。</li>
 * </ol>
 */
@DisplayName("ProductImageClient（issue #7335 / #7552）")
class ProductImageClientTest {

    private static ProductImageClient clientWith(RestTemplate restTemplate, String token) {
        ProductImageClient client = new ProductImageClient(restTemplate);
        ReflectionTestUtils.setField(client, "baseUrl", "http://ai-agent:8000");
        ReflectionTestUtils.setField(client, "serviceToken", token);
        return client;
    }

    /** ai-agent 503 的响应体（issue #7552：顶层 {@code code} 与 {@code detail} 并存）。 */
    private static HttpServerErrorException upstream503(String body) {
        return HttpServerErrorException.create(HttpStatus.SERVICE_UNAVAILABLE, "Service Unavailable",
                null, body.getBytes(StandardCharsets.UTF_8), StandardCharsets.UTF_8);
    }

    private static BusinessException failureFor(String upstreamBody) {
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(anyString(), eq(HttpMethod.POST), any(), eq(String.class)))
                .thenThrow(upstream503(upstreamBody));
        return assertThrows(BusinessException.class, () -> clientWith(restTemplate, "tok")
                .generate("https://oss/sample.png", "回归布帘", "main", 0));
    }

    @Test
    @DisplayName("成功：解析 data.image_url / data.model")
    void parsesResponse() {
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(anyString(), eq(HttpMethod.POST), any(), eq(String.class)))
                .thenReturn(new ResponseEntity<>("""
                        {"success":true,"data":{"image_url":"https://oss/tmp.png","model":"qwen-image-3.0"}}
                        """, HttpStatus.OK));

        ProductImageClient.GeneratedImage generated =
                clientWith(restTemplate, "tok").generate("https://oss/sample.png", "回归布帘", "main", 0);

        assertThat(generated.imageUrl()).isEqualTo("https://oss/tmp.png");
        assertThat(generated.model()).isEqualTo("qwen-image-3.0");
    }

    @Test
    @DisplayName("响应缺 data.image_url ⇒ 422（不把「端点没说」当空图），细节不上屏")
    void missingImageUrl_failsClosed() {
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(anyString(), eq(HttpMethod.POST), any(), eq(String.class)))
                .thenReturn(new ResponseEntity<>("{\"success\":true,\"data\":{}}", HttpStatus.OK));

        BusinessException failure = assertThrows(BusinessException.class,
                () -> clientWith(restTemplate, "tok")
                        .generate("https://oss/sample.png", "回归布帘", "main", 0));
        assertThat(failure.getCode()).isEqualTo(ProductImageClient.ERR_AI_IMAGE_UNAVAILABLE);
        assertNoInternalIdentifiers(failure);
    }

    @Test
    @DisplayName("未配置 service token ⇒ 422 且不发请求（按「平台侧未配置」话术，不说稍后重试）")
    void missingToken_failsClosedWithoutCall() {
        RestTemplate restTemplate = mock(RestTemplate.class);

        BusinessException failure = assertThrows(BusinessException.class,
                () -> clientWith(restTemplate, "")
                        .generate("https://oss/sample.png", "回归布帘", "main", 0));
        assertThat(failure.getCode()).isEqualTo(ProductImageClient.ERR_AI_IMAGE_NOT_CONFIGURED);
        assertThat(failure.getSuggestion()).contains("已反馈平台").doesNotContain("稍后重试");
        assertNoInternalIdentifiers(failure);
        verifyNoInteractions(restTemplate);
    }

    @Test
    @DisplayName("上游 503 的 code ⇒ 五类互不相同的错误码与话术（issue #7552）")
    void mapsUpstreamFailureCodesToDistinctActions() {
        BusinessException modelUnsupported = failureFor("""
                {"code":"IMAGE_GEN_MODEL_UNSUPPORTED","detail":"生图模型不可用：配置的 1 个模型都不接这类图生图请求（非配额原因）"}
                """);
        BusinessException quotaExceeded = failureFor("""
                {"code":"IMAGE_GEN_QUOTA_EXCEEDED","detail":"生图额度已用尽（1 个模型均不可用）"}
                """);
        BusinessException disabled = failureFor(
                "{\"code\":\"IMAGE_GEN_DISABLED\",\"detail\":\"商品图生成未启用\"}");
        BusinessException noKey = failureFor(
                "{\"code\":\"IMAGE_GEN_NO_KEY\",\"detail\":\"未配置 IMAGE_GEN_API_KEY / ASR_API_KEY\"}");
        BusinessException transientFailure = failureFor("{\"detail\":\"上游网关超时\"}");

        assertThat(modelUnsupported.getCode()).isEqualTo("AI_PRODUCT_IMAGE_MODEL_UNSUPPORTED");
        assertThat(quotaExceeded.getCode()).isEqualTo("AI_PRODUCT_IMAGE_QUOTA_EXCEEDED");
        assertThat(disabled.getCode()).isEqualTo("AI_PRODUCT_IMAGE_DISABLED");
        assertThat(noKey.getCode()).isEqualTo("AI_PRODUCT_IMAGE_NOT_CONFIGURED");
        assertThat(transientFailure.getCode()).isEqualTo(ProductImageClient.ERR_AI_IMAGE_UNAVAILABLE);
        // 判据自证：五类确实是五个不同的码，不是同一句话换地方（与 #7545 的「四分语义」同口径）
        assertThat(List.of(modelUnsupported.getCode(), quotaExceeded.getCode(), disabled.getCode(),
                        noKey.getCode(), transientFailure.getCode()))
                .doesNotHaveDuplicates();

        // 模型不支持：该找平台，不该劝「稍后重试」（等多久都不会好）
        assertThat(modelUnsupported.getSuggestion()).contains("已反馈平台", "上传封面")
                .doesNotContain("稍后重试");
        assertThat(disabled.getSuggestion()).doesNotContain("稍后重试");
        assertThat(noKey.getSuggestion()).doesNotContain("稍后重试");
        // 额度：说清是额度，给出「明天再试」与手工传图出路
        assertThat(quotaExceeded.getSuggestion()).contains("额度").doesNotContain("稍后重试");
        // 真·瞬时不可用：这才是「稍后重试」该出现的地方
        assertThat(transientFailure.getSuggestion()).contains("稍后重试");

        for (BusinessException failure : List.of(
                modelUnsupported, quotaExceeded, disabled, noKey, transientFailure)) {
            assertThat(failure.getHttpStatus()).isEqualTo(422);
            assertNoInternalIdentifiers(failure);
        }
    }

    /** §31 P3：商家可见面上不摆服务名 / 内部地址 / 配置键名。 */
    private static void assertNoInternalIdentifiers(BusinessException failure) {
        assertThat(failure.getMessage() + " " + failure.getSuggestion())
                .doesNotContain("ai-agent", "http://", "https://", "localhost", "service-token",
                        "IMAGE_GEN_", "data.image_url");
    }
}
