// case_ids: MC-193
package com.migao.admin.service;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;

/**
 * B 端小程序（bmini）凭据缺失时的**启动期告警**（issue #8196 的 ① 面）。
 *
 * <p>治的形态：`wechat.bmini.appid/secret` 的默认值是空（`${WECHAT_BMINI_APPID:}`），
 * 部署环境漏接线时**没有任何读数会变红** —— 现场表现是 B 端员工小程序登录 / 手机号换取
 * fail-closed 回「系统繁忙」（`wechat.mock-enabled=false` 是生产默认），而 admin-api
 * 看起来完全健康（同 AGENTS.md 记的 `AI_AGENT_SERVICE_TOKEN` 那个坑）。</p>
 *
 * <p><b>双向判据</b>（只判一半会假绿）：两个都空 ⇒ 至少一条 WARN 且点名缺哪个 / 影响 / 补法；
 * 两个都给 ⇒ 一条 WARN/ERROR 都不打；**半配也算缺**，且只点缺的那一个；空白 / null 与不写等价。</p>
 *
 * <p>⚠️ 缺失**不许**变成启动失败：整站可用性与「B 端小程序能否登录」是两件事，
 * 生产 fail-closed 已由 `wechat.mock-enabled=false` 兜底 —— 在这里再 fail-closed 一次，
 * 会把「A 档不可用」放大成「整站起不来」。</p>
 *
 * <p>接线形态（compose 的注入面 / 变量名入仓 / 值不入库）由
 * `tests/unit_ci_workflows/test_wechat_bmini_env_wiring.py` 判；本文件只判**行为**。</p>
 */
@DisplayName("WechatService bmini 凭据缺失告警（issue #8196）")
class WechatServiceBminiWiringTest {

    private Logger logger;
    private ListAppender<ILoggingEvent> appender;

    @BeforeEach
    void attachAppender() {
        logger = (Logger) LoggerFactory.getLogger(WechatService.class);
        appender = new ListAppender<>();
        appender.start();
        logger.addAppender(appender);
    }

    @AfterEach
    void detachAppender() {
        logger.detachAppender(appender);
        appender.stop();
    }

    private WechatService serviceWith(String bminiAppId, String bminiAppSecret, boolean mockEnabled) {
        WechatService service = new WechatService();
        ReflectionTestUtils.setField(service, "bminiAppId", bminiAppId);
        ReflectionTestUtils.setField(service, "bminiAppSecret", bminiAppSecret);
        ReflectionTestUtils.setField(service, "mockEnabled", mockEnabled);
        return service;
    }

    /** 只认 WARN 及以上：低于 WARN 不算「出声」（部署日志里会被 INFO 淹掉）。 */
    private List<String> loudLines() {
        List<String> lines = new ArrayList<>();
        for (ILoggingEvent event : appender.list) {
            if (event.getLevel().isGreaterOrEqual(Level.WARN)) {
                lines.add(event.getFormattedMessage());
            }
        }
        return lines;
    }

    @Test
    @DisplayName("两个都空 ⇒ 至少一条 WARN，点名「缺哪个 / 影响 / 怎么补」，且不阻止启动")
    void bothBlankWarnsOutLoud() {
        WechatService service = serviceWith("", "", false);

        assertThatCode(service::logBminiCredentialWarningIfMissing).doesNotThrowAnyException();

        List<String> warnings = loudLines();
        String text = String.join("\n", warnings);
        List<String> problems = new ArrayList<>();
        if (warnings.isEmpty()) {
            problems.add("wechat.bmini.appid/secret 两个都空，却没有一条 WARN/ERROR —— 漏接线在日志里不可见");
        }
        for (String must : List.of("WECHAT_BMINI_APPID", "WECHAT_BMINI_SECRET", "fail-closed", ".env.admin-api")) {
            if (!text.contains(must)) {
                problems.add("告警文本缺「" + must + "」—— 必须写清缺哪个 / 影响 / 怎么补");
            }
        }
        assertThat(problems).isEmpty();
    }

    @Test
    @DisplayName("半配也算缺：只给 appid 时点名 secret，不谎称 appid 也缺")
    void halfConfiguredPointsAtTheMissingSecret() {
        WechatService service = serviceWith("test-appid-not-a-secret", "", false);
        service.logBminiCredentialWarningIfMissing();

        String text = String.join("\n", loudLines());
        List<String> problems = new ArrayList<>();
        if (!text.contains("缺 WECHAT_BMINI_SECRET")) {
            problems.add("只给 appid 时没有点名「缺 WECHAT_BMINI_SECRET」（半配必须当缺）：" + text);
        }
        if (text.contains("缺 WECHAT_BMINI_APPID")) {
            problems.add("只给 appid 时却报「缺 WECHAT_BMINI_APPID」—— 指名错了，运维会去补已经有的那个：" + text);
        }
        assertThat(problems).isEmpty();
    }

    @Test
    @DisplayName("半配反向：只给 secret 时点名 appid，不谎称 secret 也缺")
    void halfConfiguredPointsAtTheMissingAppId() {
        WechatService service = serviceWith("", "test-secret-not-a-secret", false);
        service.logBminiCredentialWarningIfMissing();

        String text = String.join("\n", loudLines());
        List<String> problems = new ArrayList<>();
        if (!text.contains("缺 WECHAT_BMINI_APPID")) {
            problems.add("只给 secret 时没有点名「缺 WECHAT_BMINI_APPID」（半配必须当缺）：" + text);
        }
        if (text.contains("缺 WECHAT_BMINI_SECRET")) {
            problems.add("只给 secret 时却报「缺 WECHAT_BMINI_SECRET」—— 指名错了：" + text);
        }
        assertThat(problems).isEmpty();
    }

    @Test
    @DisplayName("两个都给 ⇒ 一条 WARN/ERROR 都不打（防「恒告警」的假绿）")
    void fullyConfiguredIsSilent() {
        WechatService service = serviceWith("test-appid-not-a-secret", "test-secret-not-a-secret", false);
        service.logBminiCredentialWarningIfMissing();

        assertThat(loudLines())
                .as("配齐了还告警 ⇒ 告警退化成噪音，真缺的时候就没人看了")
                .isEmpty();
    }

    @Test
    @DisplayName("空白 / null 与不写等价（`KEY=` 这种最常见）")
    void blankAndNullCountAsMissing() {
        WechatService service = serviceWith("   ", null, false);
        service.logBminiCredentialWarningIfMissing();

        List<String> problems = new ArrayList<>();
        if (loudLines().isEmpty()) {
            problems.add("空白 / null 没有被当成缺失 —— 部署到底写成空串时，告警不会出声");
        }
        assertThat(problems).isEmpty();
    }
}
