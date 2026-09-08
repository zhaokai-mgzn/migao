package com.migao.admin.service;

// case_ids: API-020

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.RestTemplate;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

/**
 * KnowledgeDistillClient 单元测试（LLM WIKI 板块 P5b，issue #3051）
 * 提炼客户端：成功解析候选 / 失败降级空列表（fail-closed）
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("KnowledgeDistillClient 提炼客户端测试")
class KnowledgeDistillClientTest {

    @Mock
    private RestTemplate restTemplate;

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    @DisplayName("成功：解析 data.candidates 返回候选列表")
    void distill_success_parsesCandidates() {
        KnowledgeDistillClient client = new KnowledgeDistillClient(restTemplate);
        when(restTemplate.exchange(anyString(), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok("{\"success\":true,\"data\":{\"candidates\":["
                        + "{\"title\":\"T1\",\"answer\":\"A1\",\"category\":\"faq\",\"confidence\":0.9},"
                        + "{\"title\":\"T2\",\"answer\":\"A2\"}"
                        + "]}}"));

        List<com.fasterxml.jackson.databind.JsonNode> candidates =
                client.distill("顾客：x\n客服：y", 5, 1L, "conversation");

        assertThat(candidates).hasSize(2);
        assertThat(candidates.get(0).path("title").asText()).isEqualTo("T1");
    }

    @Test
    @DisplayName("接口返回失败 → 空列表（不阻断）")
    void distill_apiFailure_returnsEmpty() {
        KnowledgeDistillClient client = new KnowledgeDistillClient(restTemplate);
        when(restTemplate.exchange(anyString(), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok("{\"success\":false,\"error\":{\"code\":\"X\"}}"));

        List<com.fasterxml.jackson.databind.JsonNode> candidates =
                client.distill("文本", 5, 1L, "document");

        assertThat(candidates).isEmpty();
    }

    @Test
    @DisplayName("请求 URL 为完整 internal 路径（含 /api 前缀，issue #3063 修复）")
    void distill_usesFullInternalPath() {
        KnowledgeDistillClient client = new KnowledgeDistillClient(restTemplate);
        when(restTemplate.exchange(anyString(), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenReturn(ResponseEntity.ok("{\"success\":true,\"data\":{\"candidates\":[]}}"));

        client.distill("文本", 5, 1L, "document");

        var captor = org.mockito.ArgumentCaptor.forClass(String.class);
        org.mockito.Mockito.verify(restTemplate).exchange(captor.capture(), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class));
        org.assertj.core.api.Assertions.assertThat(captor.getValue())
                .as("internal 路径必须含 /api 前缀（缺前缀 → ai-agent 404 → 降级空候选）")
                .endsWith("/api/internal/knowledge/distill");
    }

    @Test
    @DisplayName("网络异常 → 空列表（fail-closed 降级）")
    void distill_exception_returnsEmpty() {
        KnowledgeDistillClient client = new KnowledgeDistillClient(restTemplate);
        when(restTemplate.exchange(anyString(), eq(HttpMethod.POST), any(HttpEntity.class), eq(String.class)))
                .thenThrow(new RuntimeException("connection refused"));

        List<com.fasterxml.jackson.databind.JsonNode> candidates =
                client.distill("文本", 5, 1L, "document");

        assertThat(candidates).isEmpty();
    }
}
