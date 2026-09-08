package com.migao.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestTemplate;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 会话知识提炼客户端（LLM WIKI 板块 P5b，issue #3051）
 * 调 ai-agent 内部端点 POST /internal/knowledge/distill（Service Token 认证）。
 * 失败/不可用降级返回空列表（不阻断提炼流程，与 RegistrationReviewClient fail-closed 语义一致）。
 */
@Slf4j
@Component
public class KnowledgeDistillClient {

    private static final String DISTILL_PATH = "/internal/knowledge/distill";
    private static final int CONNECT_TIMEOUT_MS = 3_000;
    private static final int READ_TIMEOUT_MS = 30_000;

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final RestTemplate restTemplate;

    @Value("${ai-agent.base-url:http://localhost:8000}")
    private String baseUrl;

    @Value("${ai-agent.service-token:}")
    private String serviceToken;

    public KnowledgeDistillClient() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(CONNECT_TIMEOUT_MS);
        factory.setReadTimeout(READ_TIMEOUT_MS);
        this.restTemplate = new RestTemplate(factory);
    }

    /** 仅供测试注入 MockRestTemplate */
    KnowledgeDistillClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    /**
     * 提炼客服会话文本 → 候选知识卡片列表。
     *
     * @param conversationText 会话对话文本（顾客/客服轮次）
     * @param maxCandidates    单会话提炼上限
     * @return 候选列表（title/answer/category/keywords/confidence/evidence）；失败返回空列表
     */
    public List<JsonNode> distill(String conversationText, int maxCandidates, Long tenantId) {
        try {
            Map<String, Object> body = new HashMap<>();
            body.put("tenant_id", tenantId);
            body.put("conversation_text", conversationText);
            body.put("max_candidates", maxCandidates);

            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            if (StringUtils.hasText(serviceToken)) {
                headers.set("X-Service-Token", serviceToken);
            }

            String url = (StringUtils.hasText(baseUrl) ? baseUrl : "http://localhost:8000")
                    .trim().replaceAll("/+$", "") + DISTILL_PATH;
            ResponseEntity<String> response = restTemplate.exchange(
                    url, HttpMethod.POST, new HttpEntity<>(body, headers), String.class);

            JsonNode root = objectMapper.readTree(response.getBody());
            if (root == null || !root.path("success").asBoolean(false)) {
                log.warn("知识提炼接口返回失败: status={}, body={}", response.getStatusCode(), response.getBody());
                return List.of();
            }
            List<JsonNode> candidates = new ArrayList<>();
            for (JsonNode c : root.path("data").path("candidates")) {
                candidates.add(c);
            }
            return candidates;
        } catch (Exception e) {
            log.warn("知识提炼接口不可用，降级返回空候选: {}", e.getMessage());
            return List.of();
        }
    }
}
