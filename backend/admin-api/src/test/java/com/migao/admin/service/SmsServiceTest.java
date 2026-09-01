package com.migao.admin.service;
// case_ids: API-010

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.migao.admin.config.SmsConfig;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * SmsService 冒烟测试 — 验证码发送与校验
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("SmsService 冒烟测试")
class SmsServiceTest {

    @Mock
    private StringRedisTemplate redisTemplate;

    @Mock
    private SmsConfig smsConfig;

    @Mock
    private ValueOperations<String, String> valueOps;

    @InjectMocks
    private SmsService smsService;

    @BeforeEach
    void setUp() {
        when(redisTemplate.opsForValue()).thenReturn(valueOps);
    }

    @Test
    @DisplayName("发送验证码 - 正常写入 Redis")
    void sendVerificationCode_Success() {
        String phone = "13800138000";

        smsService.sendVerificationCode(phone);

        verify(valueOps).set(
            startsWith("sms:code:" + phone),
            anyString(),
            anyLong(),
            eq(TimeUnit.SECONDS)
        );
    }

    @Test
    @DisplayName("验证码校验 - 正确验证码返回 true")
    void verifyCode_Correct() {
        String phone = "13800138000";
        String code = "123456";

        when(valueOps.get("sms:code:" + phone)).thenReturn(code);

        assertThat(smsService.verifyCode(phone, code)).isTrue();
    }

    @Test
    @DisplayName("验证码校验 - 错误验证码返回 false")
    void verifyCode_Wrong() {
        String phone = "13800138000";

        when(valueOps.get("sms:code:" + phone)).thenReturn("654321");

        assertThat(smsService.verifyCode(phone, "000000")).isFalse();
    }

    @Test
    @DisplayName("验证码校验 - bypass 未配置时万能码 123456 被拒绝（生产 fail-closed 默认）")
    void verifyCode_BypassDisabled_RejectsMagicCode() {
        String phone = "13800138000";
        // 默认 bypassCode 为空字符串 = 禁用万能码（生产安全）
        ReflectionTestUtils.setField(smsService, "bypassCode", "");

        when(valueOps.get("sms:code:" + phone)).thenReturn("654321");

        assertThat(smsService.verifyCode(phone, "123456")).isFalse();
    }

    @Test
    @DisplayName("验证码校验 - 失败次数达阈值后锁定并清除验证码（防爆破）")
    void verifyCode_ExceedMaxFails_LocksAndDeletesCode() {
        String phone = "13800138000";
        // 已有 5 次失败记录（达到 MAX_VERIFY_FAILS）
        when(valueOps.get("sms:fail:" + phone)).thenReturn("5");

        assertThat(smsService.verifyCode(phone, "000000")).isFalse();

        // 锁定后清除验证码，即使后续输入正确码也无法校验
        verify(redisTemplate).delete("sms:code:" + phone);
    }

    @Test
    @DisplayName("验证码校验 - 错误码触发失败计数，首次失败设置 5 分钟 TTL")
    void verifyCode_WrongCode_IncrementsFailCount() {
        String phone = "13800138000";
        when(valueOps.get("sms:code:" + phone)).thenReturn("654321");
        when(valueOps.increment("sms:fail:" + phone)).thenReturn(1L);

        assertThat(smsService.verifyCode(phone, "000000")).isFalse();

        verify(valueOps).increment("sms:fail:" + phone);
        verify(redisTemplate).expire("sms:fail:" + phone, 300L, TimeUnit.SECONDS);
    }

    @Test
    @DisplayName("验证码校验 - 校验成功后清除失败计数")
    void verifyCode_Success_ClearsFailCount() {
        String phone = "13800138000";
        when(valueOps.get("sms:code:" + phone)).thenReturn("123456");
        when(valueOps.get("sms:fail:" + phone)).thenReturn("2");

        assertThat(smsService.verifyCode(phone, "123456")).isTrue();

        verify(redisTemplate).delete("sms:fail:" + phone);
    }

    @Test
    @DisplayName("发送验证码 - 日志不泄露生成的验证码（PII/凭据脱敏）")
    void sendVerificationCode_LogDoesNotLeakGeneratedCode() {
        String phone = "13800138000";

        ListAppender<ILoggingEvent> appender = attachListAppender();
        try {
            smsService.sendVerificationCode(phone);

            List<ILoggingEvent> events = appender.list;
            // 日志中不得出现 6 位验证码或 generatedCode 字样
            assertThat(events).noneMatch(e ->
                    e.getMessage().contains("generatedCode")
                            || e.getMessage().matches(".*code=\\d{6}.*"));
            // 手机号应脱敏（不出现完整明文）
            assertThat(events).noneMatch(e -> e.getMessage().contains(phone));
        } finally {
            detachListAppender(appender);
        }
    }

    @Test
    @DisplayName("验证码校验 - bypass 万能码命中时输出 WARN 警告日志（POC 模式显式化）")
    void verifyCode_BypassMatch_LogsWarning() {
        String phone = "13800138000";
        ReflectionTestUtils.setField(smsService, "bypassCode", "123456");

        ListAppender<ILoggingEvent> appender = attachListAppender();
        try {
            assertThat(smsService.verifyCode(phone, "123456")).isTrue();

            List<ILoggingEvent> warnEvents = appender.list.stream()
                    .filter(e -> e.getLevel() == Level.WARN)
                    .toList();
            assertThat(warnEvents).anySatisfy(e ->
                    assertThat(e.getMessage()).contains("bypass").contains("万能验证码"));
        } finally {
            detachListAppender(appender);
        }
    }

    @Test
    @DisplayName("启动检查 - bypass 已配置时输出 WARN 警告")
    void logBypassWarningIfEnabled_BypassSet_LogsWarning() {
        ReflectionTestUtils.setField(smsService, "bypassCode", "123456");

        ListAppender<ILoggingEvent> appender = attachListAppender();
        try {
            smsService.logBypassWarningIfEnabled();

            List<ILoggingEvent> warnEvents = appender.list.stream()
                    .filter(e -> e.getLevel() == Level.WARN)
                    .toList();
            assertThat(warnEvents).anySatisfy(e ->
                    assertThat(e.getMessage()).contains("POC 模式").contains("万能验证码"));
        } finally {
            detachListAppender(appender);
        }
    }

    @Test
    @DisplayName("启动检查 - bypass 未配置时不输出警告")
    void logBypassWarningIfEnabled_NoBypass_NoWarning() {
        ReflectionTestUtils.setField(smsService, "bypassCode", "");

        ListAppender<ILoggingEvent> appender = attachListAppender();
        try {
            smsService.logBypassWarningIfEnabled();

            assertThat(appender.list).noneMatch(e ->
                    e.getLevel() == Level.WARN && e.getMessage().contains("万能验证码"));
        } finally {
            detachListAppender(appender);
        }
    }

    private ListAppender<ILoggingEvent> attachListAppender() {
        ch.qos.logback.classic.Logger logger =
                (ch.qos.logback.classic.Logger) LoggerFactory.getLogger(SmsService.class);
        ListAppender<ILoggingEvent> appender = new ListAppender<>();
        appender.start();
        logger.addAppender(appender);
        return appender;
    }

    private void detachListAppender(ListAppender<ILoggingEvent> appender) {
        ch.qos.logback.classic.Logger logger =
                (ch.qos.logback.classic.Logger) LoggerFactory.getLogger(SmsService.class);
        logger.detachAppender(appender);
    }
}
