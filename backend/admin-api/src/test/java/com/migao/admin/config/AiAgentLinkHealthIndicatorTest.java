package com.migao.admin.config;
// case_ids: MC-099

import com.migao.admin.config.AiAgentLinkHealthIndicator.ProbeResult;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.Status;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * admin-api → ai-agent 这条内部调用腿的**可观测性**契约（issue #6896）。
 *
 * <h2>为什么需要</h2>
 * 六个客户端各自读 {@code ai-agent.base-url} / {@code ai-agent.service-token}，两个默认值都是坏的
 * （8000 是容器内端口、token 默认空串被对端 fail-closed）。漏设环境变量时的形态是「静默」：
 * 应用 UP、探活 200、ai-agent 自己看着健康，只有真实入驻被驳回成「系统繁忙」。
 * 本仓对同类失效已有范式（#5184 到期扫描腿、#4517 迁移腿），本类把同一范式接到内部调用腿上。
 *
 * <h2>本测试钉的四件事（每条都有红证）</h2>
 * ① 去掉 {@code token_configured} 这个键 ⇒ 红；② 有人把不可达改成熔断（返回 DOWN）⇒ 红；
 * ③ 有人把 token 原文塞进 details（泄密）⇒ 红；④ base-url 未配置时抛异常而不是摆事实 ⇒ 红。
 */
class AiAgentLinkHealthIndicatorTest {

    private static Health healthOf(String baseUrl, String token, ProbeResult probeResult) {
        return healthOfProbe(baseUrl, token, url -> probeResult);
    }

    private static Health healthOfProbe(String baseUrl, String token,
                                        AiAgentLinkHealthIndicator.LinkProbe probe) {
        return new AiAgentLinkHealthIndicator(baseUrl, token, probe).health();
    }

    @Test
    @DisplayName("token 没配 ⇒ 把事实摆出来，但仍然 UP（本仓裁定：health 不掺依赖熔断）")
    void unconfiguredTokenIsSurfacedButStillUp() {
        Health health = healthOf("http://localhost:8001", "", new ProbeResult(true, null));

        assertThat(health.getStatus()).isEqualTo(Status.UP);
        assertThat(health.getDetails()).containsEntry("token_configured", false);
    }

    @Test
    @DisplayName("配了 token ⇒ 只暴露「配了没有」，绝不暴露值")
    void tokenValueNeverLeaksIntoDetails() {
        Health health = healthOf("http://localhost:8001", "super-secret-token-value", new ProbeResult(true, null));

        assertThat(health.getDetails()).containsEntry("token_configured", true);
        assertThat(health.getDetails().toString()).doesNotContain("super-secret-token-value");
    }

    @Test
    @DisplayName("腿不可达 ⇒ reachable=false 且带原因，但 status 仍 UP（改成 DOWN 就红）")
    void unreachableLinkIsReportedNotTripped() {
        Health health = healthOf("http://localhost:8000", "tok",
                new ProbeResult(false, "ResourceAccessException: connect timed out"));

        assertThat(health.getStatus())
                .as("把 /actuator/health 打成 DOWN 会连带部署腿/探活/负载均衡一起红（同 #5184 #4517 的裁定）")
                .isEqualTo(Status.UP);
        Map<String, Object> details = health.getDetails();
        assertThat(details).containsEntry("reachable", false);
        assertThat((String) details.get("probe_error")).contains("connect timed out");
    }

    @Test
    @DisplayName("base-url 未配置 ⇒ 摆事实而不是抛异常")
    void blankBaseUrlDegradesToFacts() {
        Health health = healthOfProbe("   ", "tok", url -> {
            throw new IllegalStateException("不该被探测");
        });

        assertThat(health.getStatus()).isEqualTo(Status.UP);
        assertThat(health.getDetails())
                .containsEntry("base_url_configured", false)
                .containsEntry("reachable", false);
        assertThat((String) health.getDetails().get("probe_error")).contains("base_url");
    }

    @Test
    @DisplayName("可达时 reachable=true，且每次 health 都带探测时刻")
    void reachableLinkReportsTimestamp() {
        Health health = healthOf("http://localhost:8001", "tok", new ProbeResult(true, null));

        assertThat(health.getDetails()).containsEntry("reachable", true);
        assertThat((String) health.getDetails().get("probed_at")).isNotBlank();
    }
}
