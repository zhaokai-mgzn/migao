package com.migao.admin.service;

import com.migao.admin.config.SmsConfig;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * SmsService 冒烟测试 — 验证码发送与校验
 */
@ExtendWith(MockitoExtension.class)
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
}
