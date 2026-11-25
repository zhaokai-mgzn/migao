package com.migao.admin.service.kf;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestTemplate;

import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

/**
 * 微信客服语义判定客户端（issue #9196 / 母单 #9194 子项 1）。
 *
 * <p>调 ai-agent 内部端点 {@code POST /api/internal/kf/judge}（Service Token 认证），
 * 取 intent / risk / emotion / confidence / escalate。</p>
 *
 * <p><b>失败语义 = fail-open 到规则</b>（与 {@code RegistrationReviewClient} 的 fail-closed 反向）：
 * 超时 / 非 2xx / 响应不可解析 / 业务失败 ⇒ 返回 {@link Optional#empty()}，由
 * {@link KfDecisionService} 按规则结论放行 —— **判定服务不可用时拒答客户是更坏的故障**。
 * 读超时默认 800ms（母单口径），可用 {@code wechat.kf.judge-timeout-ms} 覆盖。</p>
 */
@Slf4j
@Component
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfJudgeClient {

    private static final String JUDGE_PATH = "/api/internal/kf/judge";
    /** 判定在客户消息的关键路径上 ⇒ 连接也短：连不上就是不可用，不必等。 */
    private static final int CONNECT_TIMEOUT_MS = 300;
    private static final int DEFAULT_READ_TIMEOUT_MS = 800;
    private static final String READ_TIMEOUT_PROPERTY =
            "${wechat.kf.judge-timeout-ms:" + DEFAULT_READ_TIMEOUT_MS + "}";

    private final ObjectMapper objectMapper = new ObjectMapper();
    private RestTemplate restTemplate;

    @Value("${ai-agent.base-url:http://localhost:8000}")
    private String baseUrl;

    @Value("${ai-agent.service-token:}")
    private String serviceToken;

    @Value(READ_TIMEOUT_PROPERTY)
    private int readTimeoutMs = DEFAULT_READ_TIMEOUT_MS;

    public KfJudgeClient() {
        this.restTemplate = buildRestTemplate(DEFAULT_READ_TIMEOUT_MS);
    }

    /** 仅供测试注入 MockRestTemplate。 */
    KfJudgeClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    /** {@code @Value} 在构造之后注入 ⇒ 配了非默认值才按它重建（测试注入的实例不动）。 */
    @PostConstruct
    void applyConfiguredTimeout() {
        if (readTimeoutMs != DEFAULT_READ_TIMEOUT_MS) {
            this.restTemplate = buildRestTemplate(readTimeoutMs);
        }
    }

    private static RestTemplate buildRestTemplate(int readTimeoutMs) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(CONNECT_TIMEOUT_MS);
        factory.setReadTimeout(readTimeoutMs);
        return new RestTemplate(factory);
    }

    /**
     * 语义判定。
     *
     * @return 判定结论；调用失败 / 不可解析 / 空文本 ⇒ {@link Optional#empty()}（调用方回退规则）
     */
    public Optional<Verdict> judge(long tenantId, String sessionId, String text) {
        if (!StringUtils.hasText(text)) {
            return Optional.empty();
        }
        try {
            Map<String, Object> body = new HashMap<>();
            body.put("tenant_id", tenantId);
            body.put("session_id", sessionId);
            body.put("text", text);

            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            if (StringUtils.hasText(serviceToken)) {
                headers.set("X-Service-Token", serviceToken);
            }

            String url = baseUrl.trim().replaceAll("/+$", "") + JUDGE_PATH;
            ResponseEntity<String> response = restTemplate.exchange(
                    url, HttpMethod.POST, new HttpEntity<>(body, headers), String.class);

            JsonNode root = objectMapper.readTree(response.getBody());
            if (root == null || !root.path("success").asBoolean(false)) {
                log.warn("语义判定返回失败（回退规则）: status={}", response.getStatusCode());
                return Optional.empty();
            }
            JsonNode data = root.path("data");
            if (!data.isObject() || data.isEmpty()) {
                log.warn("语义判定响应缺 data（回退规则）");
                return Optional.empty();
            }
            return Optional.of(new Verdict(
                    data.path("intent").asText("other"),
                    data.path("risk").asText("none"),
                    data.path("emotion").asText("calm"),
                    data.path("confidence").asDouble(0.0),
                    data.path("escalate").asBoolean(false),
                    data.path("reason").asText("")
            ));
        } catch (Exception e) {
            log.warn("调用语义判定失败（回退规则）: baseUrl={}, err={}", baseUrl, e.getMessage());
            return Optional.empty();
        }
    }

    /** 语义判定结论。 */
    public record Verdict(String intent, String risk, String emotion,
                          double confidence, boolean escalate, String reason) {
    }
}
