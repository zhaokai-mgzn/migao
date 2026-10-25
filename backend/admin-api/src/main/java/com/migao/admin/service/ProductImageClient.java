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
import org.springframework.web.client.HttpStatusCodeException;
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
 *
 * <p>🔴 <b>失败理由必须如实</b>（issue #7552）：ai-agent 的 503 带稳定机器可读 {@code code}，
 * 本类据此产出**不同**的错误码与 suggestion ——「模型接不了这类请求」劝「稍后重试」是错的动作
 * （等多久都不会好），额度用尽该等额度。对外话术不含服务名 / 地址（§31 P3）。</p>
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
    /** 上游确认「模型接不了这类请求」⇒ 该找平台换模型，劝「稍后重试」是错的动作（issue #7552）。 */
    public static final String ERR_AI_IMAGE_MODEL_UNSUPPORTED = "AI_PRODUCT_IMAGE_MODEL_UNSUPPORTED";
    /** 今日额度用尽 ⇒ 该等额度恢复，不是「马上再点一次」。 */
    public static final String ERR_AI_IMAGE_QUOTA_EXCEEDED = "AI_PRODUCT_IMAGE_QUOTA_EXCEEDED";
    /** 平台侧未启用（上游开关关闭）。 */
    public static final String ERR_AI_IMAGE_DISABLED = "AI_PRODUCT_IMAGE_DISABLED";
    /** 平台侧未配置（上游没生图 Key / 本侧没 service token）。 */
    public static final String ERR_AI_IMAGE_NOT_CONFIGURED = "AI_PRODUCT_IMAGE_NOT_CONFIGURED";

    /**
     * 平台侧不可用的统一出路（§31 P3：不出现服务名 / 地址 / 配置键名）。
     * 也不劝「稍后重试」—— 模型不支持、开关关闭这些成因，等多久都不会好。
     */
    private static final String PLATFORM_ACTION =
            "该能力暂不可用，已反馈平台；可先用「上传封面」手工传图，不影响建品提交";

    /** 真·瞬时不可用（网络 / 超时 / 上游没说原因）才给「稍后重试」。 */
    private static final Failure UNAVAILABLE = new Failure(ERR_AI_IMAGE_UNAVAILABLE,
            "商品图生成暂不可用，本次生成已中止",
            "请稍后重试，或直接用「上传封面」手工传图 —— 生成只是辅助，不影响建品提交");

    private static final Failure NOT_CONFIGURED = new Failure(ERR_AI_IMAGE_NOT_CONFIGURED,
            "商品图 AI 生成未配置完成", PLATFORM_ACTION);

    /**
     * ai-agent 503 响应体的机器可读 {@code code}（issue #7552）⇒ 本侧错误码与话术。
     *
     * <p>四类成因分开，是因为商家的**下一个动作**不同：找平台换模型 / 等额度恢复 /
     * 平台侧修配置。合成一个「暂不可用」会让前两种都变成「稍后重试」，而它们都不会自己好。</p>
     */
    private static final Map<String, Failure> UPSTREAM_FAILURES = Map.of(
            "IMAGE_GEN_MODEL_UNSUPPORTED", new Failure(ERR_AI_IMAGE_MODEL_UNSUPPORTED,
                    "商品图 AI 生成暂不可用：当前不支持这类样图", PLATFORM_ACTION),
            "IMAGE_GEN_QUOTA_EXCEEDED", new Failure(ERR_AI_IMAGE_QUOTA_EXCEEDED,
                    "今日商品图生成额度已用完",
                    "今日额度已用完，可明天再试；也可先用「上传封面」手工传图"),
            "IMAGE_GEN_DISABLED", new Failure(ERR_AI_IMAGE_DISABLED,
                    "商品图 AI 生成未启用", PLATFORM_ACTION),
            "IMAGE_GEN_NO_KEY", new Failure(ERR_AI_IMAGE_NOT_CONFIGURED,
                    "商品图 AI 生成未配置完成", PLATFORM_ACTION));

    /** 对外话术三元组（走既有的 code / message / suggestion 字段，不新造响应字段）。 */
    private record Failure(String code, String message, String suggestion) {
    }

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
     * @param kind        main / white / texture / craft / scene（调用方已校验）
     * @param variant     主图构图变体（0/1/2，其它用途无意义；见 issue #7782）
     * @return 临时图 URL + 实际使用的模型名
     * @throws BusinessException 422：未配置 token / 端点可达但失败 / 响应缺 {@code data.image_url}
     */
    public GeneratedImage generate(String imageUrl, String productName, String kind, int variant) {
        String url = endpoint();
        if (!StringUtils.hasText(serviceToken)) {
            throw fail(NOT_CONFIGURED, "未配置 ai-agent.service-token", null);
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        Long tenantId = TenantContext.getTenantId();
        payload.put("tenant_id", tenantId == null ? 0L : tenantId);
        payload.put("image_url", imageUrl);
        payload.put("product_name", productName);
        payload.put("kind", kind);
        payload.put("variant", variant);

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
                throw fail(UNAVAILABLE, "商品图生成端点返回 success != true", null);
            }
            JsonNode data = root.path("data");
            String generatedUrl = data.path("image_url").asText(null);
            if (!StringUtils.hasText(generatedUrl)) {
                log.error("商品图生成端点响应缺 data.image_url: url={}, body={}", url, response.getBody());
                throw fail(UNAVAILABLE, "商品图生成端点响应缺少 data.image_url", null);
            }
            return new GeneratedImage(generatedUrl, data.path("model").asText(""));
        } catch (BusinessException e) {
            throw e;
        } catch (HttpStatusCodeException e) {
            // 上游 503 带机器可读 code（issue #7552）⇒ 分叉成不同的对外错误码/话术；
            // 无 code（旧版本 / 非 JSON）⇒ 按真·瞬时不可用，向后兼容。
            String upstreamCode = upstreamFailureCode(e.getResponseBodyAsString());
            log.error("商品图生成端点返回 {}: url={}, code={}, body={}",
                    e.getStatusCode(), url, upstreamCode, e.getResponseBodyAsString());
            throw fail(UPSTREAM_FAILURES.getOrDefault(upstreamCode, UNAVAILABLE),
                    "upstream " + e.getStatusCode() + " code=" + upstreamCode, e);
        } catch (Exception e) {
            log.error("商品图生成端点不可达: url={}, err={}", url, e.getMessage());
            throw fail(UNAVAILABLE, e.getMessage(), e);
        }
    }

    private String endpoint() {
        String base = StringUtils.hasText(baseUrl) ? baseUrl : "http://localhost:8000";
        return base.endsWith("/") ? base.substring(0, base.length() - 1) + GENERATE_PATH : base + GENERATE_PATH;
    }

    /**
     * 从 503 响应体取机器可读失败码（issue #7552）。取不到（旧版本 / 非 JSON / 没带 code）
     * ⇒ 空串 ⇒ 按真·瞬时不可用处理（不把「没码」猜成某一种具体成因）。
     */
    private String upstreamFailureCode(String body) {
        try {
            JsonNode root = objectMapper.readTree(body);
            return root == null ? "" : root.path("code").asText("");
        } catch (Exception e) {
            return "";
        }
    }

    private BusinessException fail(Failure failure, String reason, Exception cause) {
        // 诊断细节只进日志：商家可见面不摆服务名 / 地址 / 配置键名（§31 P3）
        log.warn("商品图生成失败: code={}, reason={}", failure.code(), reason);
        BusinessException e = new BusinessException(
                failure.code(), failure.message(), 422, failure.suggestion());
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
