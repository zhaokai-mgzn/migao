package com.migao.admin.service;

// case_ids: UI-129

import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * ProductImageClient 单测（issue #7335）。
 *
 * <p>判据：</p>
 * <ol>
 *   <li>成功外壳 ⇒ 原样取 {@code data.image_url} / {@code data.model}（Java 侧不重建）；</li>
 *   <li>缺 {@code image_url} / 外壳失败 ⇒ 422 fail-closed（不把「端点没说」当空结果）；</li>
 *   <li>未配置 service token ⇒ 422 且**不发任何外部请求**。</li>
 * </ol>
 */
@DisplayName("ProductImageClient（issue #7335）")
class ProductImageClientTest {

    private static ProductImageClient clientWith(RestTemplate restTemplate, String token) {
        ProductImageClient client = new ProductImageClient(restTemplate);
        ReflectionTestUtils.setField(client, "baseUrl", "http://ai-agent:8000");
        ReflectionTestUtils.setField(client, "serviceToken", token);
        return client;
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
                clientWith(restTemplate, "tok").generate("https://oss/sample.png", "回归布帘", "main");

        assertThat(generated.imageUrl()).isEqualTo("https://oss/tmp.png");
        assertThat(generated.model()).isEqualTo("qwen-image-3.0");
    }

    @Test
    @DisplayName("响应缺 data.image_url ⇒ 422（不把「端点没说」当空图）")
    void missingImageUrl_failsClosed() {
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(anyString(), eq(HttpMethod.POST), any(), eq(String.class)))
                .thenReturn(new ResponseEntity<>("{\"success\":true,\"data\":{}}", HttpStatus.OK));

        assertThatThrownBy(() -> clientWith(restTemplate, "tok")
                .generate("https://oss/sample.png", "回归布帘", "main"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("data.image_url");
    }

    @Test
    @DisplayName("未配置 service token ⇒ 422 且不发请求")
    void missingToken_failsClosedWithoutCall() {
        RestTemplate restTemplate = mock(RestTemplate.class);

        assertThatThrownBy(() -> clientWith(restTemplate, "")
                .generate("https://oss/sample.png", "回归布帘", "main"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("service-token");
        verifyNoInteractions(restTemplate);
    }
}
