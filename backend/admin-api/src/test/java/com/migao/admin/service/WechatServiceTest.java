package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * WechatService 冒烟测试
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("WechatService 冒烟测试")
class WechatServiceTest {

    @InjectMocks
    private WechatService wechatService;

    @Test
    @DisplayName("Mock 模式 - code2Session 返回模拟 openid")
    void code2Session_MockMode() {
        // 不设置 appId/appSecret，自动进入 Mock 模式
        ReflectionTestUtils.setField(wechatService, "appId", "");
        ReflectionTestUtils.setField(wechatService, "appSecret", "");

        WechatService.Code2SessionResult result = wechatService.code2Session("test_code_123");

        assertThat(result).isNotNull();
        assertThat(result.getOpenid()).isNotEmpty();
        assertThat(result.getOpenid()).startsWith("mock_openid_");
    }
}
