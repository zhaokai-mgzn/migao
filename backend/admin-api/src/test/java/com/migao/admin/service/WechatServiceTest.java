package com.migao.admin.service;

import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * WechatService 冒烟测试
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("WechatService 冒烟测试")
class WechatServiceTest {

    @InjectMocks
    private WechatService wechatService;

    @Test
    @DisplayName("Mock 模式（显式启用）- code2Session 返回模拟 openid")
    void code2Session_MockMode() {
        // 不设置 appId/appSecret，但显式开启 wechat.mock-enabled（仅 dev/CI）
        ReflectionTestUtils.setField(wechatService, "appId", "");
        ReflectionTestUtils.setField(wechatService, "appSecret", "");
        ReflectionTestUtils.setField(wechatService, "mockEnabled", true);

        WechatService.Code2SessionResult result = wechatService.code2Session("test_code_123");

        assertThat(result).isNotNull();
        assertThat(result.getOpenid()).isNotEmpty();
        assertThat(result.getOpenid()).startsWith("mock_openid_");
    }

    @Test
    @DisplayName("Mock 未显式启用（生产默认）且微信未配置 → 拒绝登录（fail-closed，审计 07 P1-1）")
    void code2Session_MockDisabled_Rejects() {
        // 生产默认 mockEnabled=false：未配置 appid 时禁止伪造 openid
        ReflectionTestUtils.setField(wechatService, "appId", "");
        ReflectionTestUtils.setField(wechatService, "appSecret", "");
        ReflectionTestUtils.setField(wechatService, "mockEnabled", false);

        assertThatThrownBy(() -> wechatService.code2Session("test_code_123"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("微信");
    }
}
