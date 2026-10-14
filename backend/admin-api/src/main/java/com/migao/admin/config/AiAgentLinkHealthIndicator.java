package com.migao.admin.config;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 把 **admin-api → ai-agent-service 这条内部调用腿**的接线事实暴露到 {@code /actuator/health}（issue #6896）。
 *
 * <h2>它解决什么</h2>
 * 六个客户端（{@code RegistrationReviewClient} / {@code CraftCalcClient} / {@code ImageRecognitionClient} /
 * {@code KnowledgeDistillClient} / {@code BriefingGenerateClient} / {@code ProductionOperationQtyClient}）
 * 各自读 {@code ai-agent.base-url} 与 {@code ai-agent.service-token}。两个默认值都是坏的：
 * base-url 默认 {@code http://localhost:8000}（8000 是容器内端口，本地直起在 8001），
 * token 默认空串（ai-agent 侧 {@code verify_service_token} 对空配置 fail-closed）。
 * 于是本地漏设环境变量时的形态是「**静默**」：应用 UP、探活 200、ai-agent 自己看着健康，
 * 只有真实入驻被驳回成「系统繁忙，可稍后重试」（{@code review_source=system}）—— 与
 * {@code AutoBatchDueScanHealthIndicator}（#5184）/ {@code MigrationHealthIndicator}（#4517）
 * 处理的是同一类失效，只是那条腿是内部调用。
 *
 * <h2>⚠️ 恒 UP，不熔断（沿用本仓既有裁定）</h2>
 * 与上面两个 indicator 同因：把 {@code /actuator/health} 打成 {@code DOWN} 会连带
 * 部署腿 / 探活 / 负载均衡一起红，那是比原问题更糟的故障。⇒ 本类**只把事实摆出来**
 * （{@code token_configured} / {@code reachable} / {@code probe_error}），
 * 「算不算故障」由观测方裁定。测试里专门钉了「不可达也必须 UP」这条，防止后人顺手改成熔断。
 *
 * <h2>不做什么（照实登记边界）</h2>
 * ① 不改六个客户端里各自重复的坏默认值 —— 那属于「把配置收敛到一处」的独立改动，
 *    且 8000 对 {@code deploy/docker-compose.yml} 的 {@code 8001:8000} 映射是正确的容器内地址，
 *    改默认值会弄坏容器那条路；② 不缓存探测结果 —— 每次 health 现探一次、超时 800ms 封顶，
 *    换来的是零后台线程与零陈旧态（health 不是热点路径）。
 */
@Component("aiAgentLinkHealth")
public class AiAgentLinkHealthIndicator implements HealthIndicator {

    /** 探测 ai-agent 的 {@code GET /health}（backend/ai-agent-service/app/main.py:196）。 */
    interface LinkProbe {
        ProbeResult probe(String baseUrl);
    }

    record ProbeResult(boolean reachable, String error) {
    }

    private static final int TIMEOUT_MILLIS = 800;

    private final String baseUrl;
    private final boolean tokenConfigured;
    private final LinkProbe probe;

    /** ⚠️ 本类有**两个**构造器（下面那个是测试用的假探针口）⇒ 这道 `@Autowired` 不可省：
     *  没有它 Spring 会去找无参构造器并以
     *  `No default constructor found` 让**整个应用上下文起不来**（实测 2026-10-14：`AdminApiApplicationTest`
     *  与 `SecurityConfigTest` 59 条全挂）。 */
    @Autowired
    public AiAgentLinkHealthIndicator(@Value("${ai-agent.base-url:}") String baseUrl,
                                      @Value("${ai-agent.service-token:}") String serviceToken) {
        this(baseUrl, serviceToken, new RestTemplateLinkProbe());
    }

    /** 仅供测试注入假探针（与 {@code RegistrationReviewClient} 的测试构造器同一手法）。 */
    AiAgentLinkHealthIndicator(String baseUrl, String serviceToken, LinkProbe probe) {
        this.baseUrl = baseUrl == null ? "" : baseUrl.trim();
        this.tokenConfigured = serviceToken != null && !serviceToken.isBlank();
        this.probe = probe;
    }

    @Override
    public Health health() {
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("base_url", baseUrl);
        details.put("base_url_configured", !baseUrl.isEmpty());
        // 只暴露「配了没有」，永不暴露值 —— 有测试钉住这一条。
        details.put("token_configured", tokenConfigured);
        if (baseUrl.isEmpty()) {
            details.put("reachable", false);
            details.put("probe_error", "base_url 未配置");
        } else {
            ProbeResult result = probe.probe(baseUrl);
            details.put("reachable", result.reachable());
            details.put("probe_error", result.error());
        }
        details.put("probed_at", OffsetDateTime.now().toString());
        return Health.up().withDetails(details).build();
    }

    private static final class RestTemplateLinkProbe implements LinkProbe {

        @Override
        public ProbeResult probe(String baseUrl) {
            try {
                SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
                factory.setConnectTimeout(TIMEOUT_MILLIS);
                factory.setReadTimeout(TIMEOUT_MILLIS);
                new RestTemplate(factory).getForObject(baseUrl + "/health", String.class);
                return new ProbeResult(true, null);
            } catch (Exception e) {
                return new ProbeResult(false, e.getClass().getSimpleName() + ": " + e.getMessage());
            }
        }
    }
}
