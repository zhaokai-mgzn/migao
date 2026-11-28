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
 * 微信客服回复生成客户端（{@code AI_REPLY} 一跳：C 端对话内核产文）。
 *
 * <p>调 ai-agent 内部端点 {@code POST /api/internal/kf/reply}（Service Token 认证），取
 * <b>客户可见回复正文</b>（纯文本）。真正的发送不在这里 —— 由调用方交给
 * {@link KfSendService#enqueueReply}，预算 / 48h 窗口 / {@code msgid} 幂等全在那一侧。</p>
 *
 * <p><b>失败语义 = fail-closed</b>（与 {@link KfJudgeClient} 的 fail-open 反向）：
 * 超时 / 非 2xx / 响应不可解析 / 空正文 ⇒ {@link Optional#empty()}，由 {@link KfAiReplyLoop}
 * 转人工 —— <b>宁可转人工，也不把半句话或空话发给客户</b>。</p>
 */
@Slf4j
@Component
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfReplyClient {

    private static final String REPLY_PATH = "/api/internal/kf/reply";
    /** 连接不可用即视为不可用，不必等（与判定同一口径）。 */
    private static final int CONNECT_TIMEOUT_MS = 300;
    /** 生成要跑完整对话内核 ⇒ 读超时比判定（800ms）宽，默认 8s（设计文档 §5.2 的非流式口径）。 */
    private static final int DEFAULT_READ_TIMEOUT_MS = 8000;
    private static final String READ_TIMEOUT_PROPERTY =
            "${wechat.kf.reply-timeout-ms:" + DEFAULT_READ_TIMEOUT_MS + "}";

    private final ObjectMapper objectMapper = new ObjectMapper();
    private RestTemplate restTemplate;

    @Value("${ai-agent.base-url:http://localhost:8000}")
    private String baseUrl;

    @Value("${ai-agent.service-token:}")
    private String serviceToken;

    @Value(READ_TIMEOUT_PROPERTY)
    private int readTimeoutMs = DEFAULT_READ_TIMEOUT_MS;

    public KfReplyClient() {
        this.restTemplate = buildRestTemplate(DEFAULT_READ_TIMEOUT_MS);
    }

    /** 仅供测试注入 MockRestTemplate。 */
    KfReplyClient(RestTemplate restTemplate) {
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

    /** 供测试注入 MockRestTemplate 之外的唯一入口。 */
    public record Generated(String text, int toolCalls) {
    }

    /**
     * 生成一条客户可见回复正文。
     *
     * @return 非空正文 + 本轮工具调用次数；调用失败 / 不可解析 / 空正文 ⇒ {@link Optional#empty()}（调用方转人工）
     */
    public Optional<Generated> generate(long tenantId, String sessionId, String text) {
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

            String url = baseUrl.trim().replaceAll("/+$", "") + REPLY_PATH;
            ResponseEntity<String> response = restTemplate.exchange(
                    url, HttpMethod.POST, new HttpEntity<>(body, headers), String.class);

            JsonNode root = objectMapper.readTree(response.getBody());
            if (root == null || !root.path("success").asBoolean(false)) {
                log.warn("回复生成返回失败（转人工）: status={}", response.getStatusCode());
                return Optional.empty();
            }
            String reply = root.path("data").path("text").asText("");
            if (!StringUtils.hasText(reply)) {
                log.warn("回复生成返回空正文（转人工）");
                return Optional.empty();
            }
            return Optional.of(new Generated(
                    reply.strip(), root.path("data").path("tool_calls").asInt(0)));
        } catch (Exception e) {
            log.warn("调用回复生成失败（转人工）: baseUrl={}, err={}", baseUrl, e.getMessage());
            return Optional.empty();
        }
    }
}
