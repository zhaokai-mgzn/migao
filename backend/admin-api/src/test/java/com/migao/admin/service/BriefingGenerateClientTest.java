package com.migao.admin.service;

// case_ids: DA-009

import com.fasterxml.jackson.databind.JsonNode;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.RestTemplate;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

/**
 * BriefingGenerateClient 单元测试（智能每日经营简报，issue #3468）
 * 客户端：成功解析 briefing / 接口失败 / 空 briefing / 网络异常 → 均降级 null（fail-closed，
 * 调用方落 failed 记录，绝不展示假数据 —— 数据安全红线 4）。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("BriefingGenerateClient 简报生成客户端测试")
class BriefingGenerateClientTest {

    @Mock
    private RestTemplate restTemplate;

    @Test
    @DisplayName("成功：解析 data.briefing 返回内容")
    void generate_success_parsesBriefing() {
        BriefingGenerateClient client = new BriefingGenerateClient(restTemplate);
        when(restTemplate.exchange(anyString(), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok("{\"success\":true,\"data\":{\"briefing\":{\"summary\":\"昨日经营平稳\"}}}"));

        JsonNode briefing = client.generate(1L, Map.of("metrics", Map.of("today_orders", 5)));

        assertThat(briefing).isNotNull();
        assertThat(briefing.path("summary").asText()).isEqualTo("昨日经营平稳");
    }

    @Test
    @DisplayName("接口返回失败 → null（不编造简报）")
    void generate_apiFailure_returnsNull() {
        BriefingGenerateClient client = new BriefingGenerateClient(restTemplate);
        when(restTemplate.exchange(anyString(), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok("{\"success\":false,\"error\":{\"code\":\"X\"}}"));

        assertThat(client.generate(1L, Map.of())).isNull();
    }

    @Test
    @DisplayName("data.briefing 为空 → null")
    void generate_emptyBriefing_returnsNull() {
        BriefingGenerateClient client = new BriefingGenerateClient(restTemplate);
        when(restTemplate.exchange(anyString(), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok("{\"success\":true,\"data\":{\"briefing\":null}}"));

        assertThat(client.generate(1L, Map.of())).isNull();
    }

    @Test
    @DisplayName("请求 URL 为完整 internal 路径（含 /api 前缀）")
    void generate_usesFullInternalPath() {
        BriefingGenerateClient client = new BriefingGenerateClient(restTemplate);
        when(restTemplate.exchange(anyString(), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok("{\"success\":true,\"data\":{\"briefing\":{\"summary\":\"x\"}}}"));

        client.generate(1L, Map.of("metrics", Map.of()));

        var captor = org.mockito.ArgumentCaptor.forClass(String.class);
        org.mockito.Mockito.verify(restTemplate).exchange(captor.capture(), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class));
        org.assertj.core.api.Assertions.assertThat(captor.getValue())
                .as("internal 路径必须含 /api 前缀（缺前缀 → ai-agent 404 → 降级 null）")
                .endsWith("/api/internal/briefing/generate");
    }

    @Test
    @DisplayName("网络异常 → null（fail-closed 降级，不展示假数据）")
    void generate_exception_returnsNull() {
        BriefingGenerateClient client = new BriefingGenerateClient(restTemplate);
        when(restTemplate.exchange(anyString(), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenThrow(new RuntimeException("connection refused"));

        assertThat(client.generate(1L, Map.of())).isNull();
    }
}
