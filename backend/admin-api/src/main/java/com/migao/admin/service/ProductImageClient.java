package com.migao.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.exception.BusinessException;
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

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 商品图生成客户端（issue #7335）——调 ai-agent 内部端点
 * {@code POST /api/internal/images/generate}（Service Token 认证）。
 *
 * <p>与 {@link ImageRecognitionClient} / {@link CraftCalcClient} 同一条既有范式：
 * 商家侧只认 admin-api（JWT + 权限码 + 租户上下文），AI 能力一律由 admin-api 用
 * {@code X-Service-Token} 反调 ai-agent。<b>不新增第二条内部调用约定</b>。</p>
 *
 * <p>🔴 <b>不落库</b>：本类只「问 + 取」，返回百炼的临时图片 URL；转存 OSS 与
 * 「是否采用」分别在 {@link ProductImageGenerationService} / 商家页面。</p>
 */
@Slf4j
@Component
public class ProductImageClient {

    private static final String GENERATE_PATH = "/api/internal/images/generate";
    private static final int CONNECT_TIMEOUT_MS = 3_000;

    /** 生图比识别慢（实测 30~60s，长尾可能到 120s）⇒ 读超时给足，但不无限等。 */
    static final int GENERATE_READ_TIMEOUT_MS = 200_000;

    /** fail-closed 错误码（对外 422 + suggestion，与图片识别同口径）。 */
    public static final String ERR_AI_IMAGE_UNAVAILABLE = "AI_PRODUCT_IMAGE_UNAVAILABLE";

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final RestTemplate restTemplate;

    @Value("${ai-agent.base-url:http://localhost:8000}")
    private String baseUrl;

    @Value("${ai-agent.service-token:}")
    private String serviceToken;

    public ProductImageClient() {
        this(new RestTemplate(factory()));
    }

    /** 供测试注入 MockRestTemplate。 */
    ProductImageClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    private static SimpleClientHttpRequestFactory factory() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(CONNECT_TIMEOUT_MS);
        factory.setReadTimeout(GENERATE_READ_TIMEOUT_MS);
        return factory;
    }

    /**
     * 样图 → 一张生成图（**临时 URL**，尚未转存 OSS）。
     *
     * @param imageUrl    商家上传的样图（https）
     * @param productName 商品名（提示词用）
     * @param kind        main / texture / craft / scene（调用方已校验）
     * @return 临时图 URL + 实际使用的模型名
     * @throws BusinessException 422：未配置 token / 端点可达但失败 / 响应缺 {@code data.image_url}
     */
    public GeneratedImage generate(String imageUrl, String productName, String kind) {
        String url = endpoint();
        if (!StringUtils.hasText(serviceToken)) {
            throw unavailable(url, "未配置 ai-agent.service-token", null);
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        Long tenantId = TenantContext.getTenantId();
        payload.put("tenant_id", tenantId == null ? 0L : tenantId);
        payload.put("image_url", imageUrl);
        payload.put("product_name", productName);
        payload.put("kind", kind);

        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            headers.set("X-Service-Token", serviceToken);

            ResponseEntity<String> response = restTemplate.exchange(
                    url, HttpMethod.POST, new HttpEntity<>(payload, headers), String.class);

            JsonNode root = objectMapper.readTree(response.getBody());
            if (root == null || !root.path("success").asBoolean(false)) {
                log.error("商品图生成端点返回失败: url={}, status={}, body={}",
                        url, response.getStatusCode(), response.getBody());
                throw unavailable(url, "商品图生成端点返回 success != true", null);
            }
            JsonNode data = root.path("data");
            String generatedUrl = data.path("image_url").asText(null);
            if (!StringUtils.hasText(generatedUrl)) {
                log.error("商品图生成端点响应缺 data.image_url: url={}, body={}", url, response.getBody());
                throw unavailable(url, "商品图生成端点响应缺少 data.image_url", null);
            }
            return new GeneratedImage(generatedUrl, data.path("model").asText(""));
        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            log.error("商品图生成端点不可达: url={}, err={}", url, e.getMessage());
            throw unavailable(url, e.getMessage(), e);
        }
    }

    private String endpoint() {
        String base = StringUtils.hasText(baseUrl) ? baseUrl : "http://localhost:8000";
        return base.endsWith("/") ? base.substring(0, base.length() - 1) + GENERATE_PATH : base + GENERATE_PATH;
    }

    private BusinessException unavailable(String url, String reason, Exception cause) {
        BusinessException e = new BusinessException(ERR_AI_IMAGE_UNAVAILABLE,
                "商品图生成服务（ai-agent）暂不可用，本次生成已中止：" + reason,
                422,
                "请稍后重试，或直接用「上传封面」手工传图 —— 生成只是辅助，不影响建品提交"
                        + "（当前服务地址 " + url + "）。");
        if (cause != null) {
            e.initCause(cause);
        }
        return e;
    }

    /**
     * 生成结果。
     *
     * @param imageUrl 百炼临时 URL（24h 过期，必须由上游转存）
     * @param model    实际使用的模型名（排障/成本归属用）
     */
    public record GeneratedImage(String imageUrl, String model) {
    }
}
