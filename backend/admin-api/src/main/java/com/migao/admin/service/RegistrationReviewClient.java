package com.migao.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.RegistrationRequest;
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
 * 企业入驻申请 AI 合规甄别客户端
 *
 * 调用 ai-agent-service 内部端点 POST /api/internal/registration/review
 * （Service Token 认证），对入驻申请做规则层 + 大模型层合规甄别。
 *
 * 失败语义：网络异常 / 非 2xx / 响应解析失败 / 业务失败 → 返回 null，
 * 由调用方（RegistrationService）按 fail-closed 兜底（系统繁忙驳回），
 * 绝不在甄别服务不可用时放行。
 */
@Slf4j
@Component
public class RegistrationReviewClient {

    private static final String REVIEW_PATH = "/api/internal/registration/review";
    private static final int CONNECT_TIMEOUT_MS = 5000;
    private static final int READ_TIMEOUT_MS = 30000;

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final RestTemplate restTemplate;

    @Value("${ai-agent.base-url:http://localhost:8000}")
    private String baseUrl;

    @Value("${ai-agent.service-token:}")
    private String serviceToken;

    public RegistrationReviewClient() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(CONNECT_TIMEOUT_MS);
        factory.setReadTimeout(READ_TIMEOUT_MS);
        this.restTemplate = new RestTemplate(factory);
    }

    /** 仅供测试注入 MockRestTemplate */
    RegistrationReviewClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    /**
     * 调用 AI 甄别服务审查入驻申请
     *
     * @param dto 入驻申请请求
     * @return 甄别结论；服务不可用时返回 null（fail-closed）
     */
    public ReviewVerdict review(RegistrationRequest dto) {
        try {
            Map<String, Object> body = new HashMap<>();
            body.put("company_name", dto.getCompanyName());
            body.put("contact_name", dto.getContactName());
            body.put("phone", dto.getPhone());
            body.put("industry", dto.getIndustry());
            body.put("address", dto.getAddress());
            body.put("description", dto.getDescription());
            body.put("business_license_url", dto.getBusinessLicenseUrl());

            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            if (StringUtils.hasText(serviceToken)) {
                headers.set("X-Service-Token", serviceToken);
            }

            String url = baseUrl.trim().replaceAll("/+$", "") + REVIEW_PATH;
            ResponseEntity<String> response = restTemplate.exchange(
                    url,
                    HttpMethod.POST,
                    new HttpEntity<>(body, headers),
                    String.class
            );

            JsonNode root = objectMapper.readTree(response.getBody());
            if (root == null || !root.path("success").asBoolean(false)) {
                log.error("AI 甄别接口返回失败: status={}, body={}",
                        response.getStatusCode(), safeTruncate(response.getBody()));
                return null;
            }

            JsonNode data = root.path("data");
            String decision = data.path("decision").asText("");
            if (!"approve".equals(decision) && !"reject".equals(decision)) {
                log.error("AI 甄别返回未知决策: decision={}", decision);
                return null;
            }

            List<RiskFlag> flags = new ArrayList<>();
            for (JsonNode f : data.path("risk_flags")) {
                flags.add(new RiskFlag(
                        f.path("level").asText("medium"),
                        f.path("code").asText(""),
                        f.path("reason").asText("")
                ));
            }

            ReviewVerdict verdict = new ReviewVerdict(
                    decision,
                    data.path("confidence").asDouble(0.0),
                    data.path("reason").asText(""),
                    flags,
                    data.path("summary").asText(""),
                    data.path("review_source").asText("ai")
            );
            log.info("AI 甄别完成: decision={}, reviewSource={}, riskFlags={}",
                    verdict.decision(), verdict.reviewSource(), verdict.riskFlags().size());
            return verdict;
        } catch (Exception e) {
            log.error("调用 AI 甄别服务失败（fail-closed，返回 null）: baseUrl={}, err={}",
                    baseUrl, e.getMessage());
            return null;
        }
    }

    private static String safeTruncate(String s) {
        if (s == null) {
            return "";
        }
        return s.length() > 500 ? s.substring(0, 500) + "..." : s;
    }

    /**
     * AI 甄别结论
     */
    public record ReviewVerdict(
            String decision,
            double confidence,
            String reason,
            List<RiskFlag> riskFlags,
            String summary,
            String reviewSource
    ) {
    }

    /**
     * 风险标记
     */
    public record RiskFlag(String level, String code, String reason) {
    }
}
