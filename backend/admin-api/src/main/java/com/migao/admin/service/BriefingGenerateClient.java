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

import java.util.Map;

/**
 * 智能每日经营简报生成客户端（issue #3468）
 * 调 ai-agent 内部端点 POST /api/internal/briefing/generate（Service Token 认证）。
 *
 * 数据安全：snapshot 只含聚合指标与脱敏事实（无客户 PII），
 * 生成失败返回 null —— 调用方落 failed 状态，绝不展示假数据（设计文档 §8.7）。
 */
@Slf4j
@Component
public class BriefingGenerateClient {

    private static final String GENERATE_PATH = "/api/internal/briefing/generate";
    private static final int CONNECT_TIMEOUT_MS = 3_000;
    private static final int READ_TIMEOUT_MS = 60_000;

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final RestTemplate restTemplate;

    @Value("${ai-agent.base-url:http://localhost:8000}")
    private String baseUrl;

    @Value("${ai-agent.service-token:}")
    private String serviceToken;

    public BriefingGenerateClient() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(CONNECT_TIMEOUT_MS);
        factory.setReadTimeout(READ_TIMEOUT_MS);
        this.restTemplate = new RestTemplate(factory);
    }

    /** 仅供测试注入 MockRestTemplate */
    BriefingGenerateClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    /**
     * 生成简报（LLM 组织层，见设计文档 §5）。
     *
     * @param tenantId 租户 ID
     * @param snapshot 聚合指标快照（纯数字 + 脱敏事实，无 PII）
     * @return 简报内容 JSON 节点（summary/review/todo/risks/suggestions）；失败返回 null
     */
    public JsonNode generate(Long tenantId, Map<String, Object> snapshot) {
        try {
            Map<String, Object> body = Map.of(
                    "tenant_id", tenantId,
                    "snapshot", snapshot);

            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            if (StringUtils.hasText(serviceToken)) {
                headers.set("X-Service-Token", serviceToken);
            }

            String url = (StringUtils.hasText(baseUrl) ? baseUrl : "http://localhost:8000")
                    .trim().replaceAll("/+$", "") + GENERATE_PATH;
            ResponseEntity<String> response = restTemplate.exchange(
                    url, HttpMethod.POST, new HttpEntity<>(body, headers), String.class);

            JsonNode root = objectMapper.readTree(response.getBody());
            if (root == null || !root.path("success").asBoolean(false)) {
                log.warn("简报生成接口返回失败: status={}, body={}", response.getStatusCode(), response.getBody());
                return null;
            }
            JsonNode briefing = root.path("data").path("briefing");
            if (briefing == null || briefing.isMissingNode() || briefing.isNull()) {
                log.warn("简报生成接口返回空 briefing");
                return null;
            }
            return briefing;
        } catch (Exception e) {
            log.warn("简报生成接口不可用，降级返回 null: {}", e.getMessage());
            return null;
        }
    }
}
