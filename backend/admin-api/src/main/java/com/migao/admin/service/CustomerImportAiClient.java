package com.migao.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.CustomerImportField;
import com.migao.admin.dto.MappingSuggestion;
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
 * 客户 Excel 列映射建议客户端（issue #8295）。
 *
 * <p>调用 ai-agent-service 内部端点 {@code POST /api/internal/migration/customer-mapping}。
 * AI 只给“表头 → canonical 字段”的建议，不写库、不执行导入；失败返回 {@code null}，
 * 由 {@link CustomerImportService} 用确定性表头别名兜底（迁移不被 AI 可用性阻断）。</p>
 */
@Slf4j
@Component
public class CustomerImportAiClient {

    private static final String PATH = "/api/internal/migration/customer-mapping";
    private static final int CONNECT_TIMEOUT_MS = 5000;
    private static final int READ_TIMEOUT_MS = 30000;

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final RestTemplate restTemplate;

    @Value("${ai-agent.base-url:http://localhost:8000}")
    private String baseUrl;

    @Value("${ai-agent.service-token:}")
    private String serviceToken;

    public CustomerImportAiClient() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(CONNECT_TIMEOUT_MS);
        factory.setReadTimeout(READ_TIMEOUT_MS);
        this.restTemplate = new RestTemplate(factory);
    }

    /** 仅供测试注入 MockRestTemplate。 */
    CustomerImportAiClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    /**
     * 请求 AI 列映射建议。
     *
     * @return null = AI 服务不可用/响应不可解析（调用方走确定性兜底）
     */
    public Result suggest(List<String> headers, List<List<String>> samples, List<CustomerImportField> fields) {
        try {
            Map<String, Object> body = new HashMap<>();
            body.put("headers", headers);
            body.put("samples", samples);
            body.put("fields", fields);

            HttpHeaders httpHeaders = new HttpHeaders();
            httpHeaders.setContentType(MediaType.APPLICATION_JSON);
            if (StringUtils.hasText(serviceToken)) {
                httpHeaders.set("X-Service-Token", serviceToken);
            }
            String url = baseUrl.trim().replaceAll("/+$", "") + PATH;
            ResponseEntity<String> response = restTemplate.exchange(
                    url, HttpMethod.POST, new HttpEntity<>(body, httpHeaders), String.class);

            JsonNode root = objectMapper.readTree(response.getBody());
            if (root == null || !root.path("success").asBoolean(false)) {
                log.warn("[customer-import] AI mapping 返回失败: status={}", response.getStatusCode());
                return null;
            }
            JsonNode data = root.path("data");
            if (!data.isObject()) {
                log.warn("[customer-import] AI mapping 响应缺 data");
                return null;
            }
            List<MappingSuggestion> suggestions = new ArrayList<>();
            for (JsonNode node : data.path("mappings")) {
                String target = node.path("target_field").asText("");
                if (!StringUtils.hasText(target)) {
                    continue;
                }
                suggestions.add(new MappingSuggestion(
                        node.path("source_index").asInt(-1),
                        node.path("source_header").asText(""),
                        target,
                        node.path("confidence").asDouble(0.0),
                        node.path("reason").asText("")
                ));
            }
            boolean degraded = data.path("degraded").asBoolean(false);
            String message = data.path("message").asText("");
            log.info("[customer-import] AI mapping: headers={}, mappings={}, degraded={}",
                    headers.size(), suggestions.size(), degraded);
            return new Result(suggestions, degraded, message);
        } catch (Exception e) {
            log.warn("[customer-import] 调用 AI 映射服务失败（走确定性兜底）: {}", e.getMessage());
            return null;
        }
    }

    /** AI 映射结果；degraded=true 表示服务降级但可能仍返回部分结果。 */
    public record Result(List<MappingSuggestion> suggestions, boolean degraded, String message) {
    }
}
