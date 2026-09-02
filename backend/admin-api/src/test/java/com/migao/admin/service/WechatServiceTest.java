// case_ids: API-010
package com.migao.admin.service;

import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;

import java.util.HashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

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

    // ======================== 真实微信 code2Session ========================

    private RestTemplate restTemplate = mock(RestTemplate.class);

    private void mockWechatResponse(String body, String contentType) {
        // 微信官方接口（尤其错误场景）返回 Content-Type: text/plain，
        // 修复前 RestTemplate.getForObject(url, Map.class) 会转换失败。
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.parseMediaType(contentType));
        ResponseEntity<String> entity = new ResponseEntity<>(body, headers, HttpStatus.OK);
        when(restTemplate.getForEntity(anyString(), any(Class.class)))
                .thenReturn(entity);
    }

    @Test
    @DisplayName("真实模式 - 微信返回 text/plain 内容类型也能正确解析 openid（修复 #API-010 集成 bug）")
    void code2Session_TextPlainContentType_ParsesOpenid() {
        ReflectionTestUtils.setField(wechatService, "appId", "wx-test-appid");
        ReflectionTestUtils.setField(wechatService, "appSecret", "secret");
        ReflectionTestUtils.setField(wechatService, "mockEnabled", false);
        ReflectionTestUtils.setField(wechatService, "restTemplate", restTemplate);

        // 微信成功响应用 application/json，但同接口错误响应是 text/plain；
        // 用 text/plain 返回成功 JSON，验证解析不依赖 Content-Type。
        mockWechatResponse(
                "{\"openid\":\"o6_bmjrPTlm6_2sgVt7hMZOPfL2M\",\"session_key\":\"tiihtNczf5v6AKRyjwEUhQ==\"}",
                "text/plain;charset=UTF-8");

        WechatService.Code2SessionResult result = wechatService.code2Session("wx-code-123");

        assertThat(result).isNotNull();
        assertThat(result.getOpenid()).isEqualTo("o6_bmjrPTlm6_2sgVt7hMZOPfL2M");
        assertThat(result.getSessionKey()).isEqualTo("tiihtNczf5v6AKRyjwEUhQ==");
    }

    @Test
    @DisplayName("真实模式 - 微信返回 errcode 错误（text/plain）→ 抛出 WECHAT_API_ERROR 且映射友好文案")
    void code2Session_WechatError_TextPlain_MapsFriendlyMessage() {
        ReflectionTestUtils.setField(wechatService, "appId", "wx-test-appid");
        ReflectionTestUtils.setField(wechatService, "appSecret", "secret");
        ReflectionTestUtils.setField(wechatService, "mockEnabled", false);
        ReflectionTestUtils.setField(wechatService, "restTemplate", restTemplate);

        mockWechatResponse(
                "{\"errcode\":40029,\"errmsg\":\"invalid code\"}",
                "text/plain;charset=UTF-8");

        assertThatThrownBy(() -> wechatService.code2Session("expired-code"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("code 无效");
    }

    @Test
    @DisplayName("真实模式 - 微信返回非 JSON 文本（如 HTML 错误页）→ 抛 WECHAT_API_ERROR 而非转换异常")
    void code2Session_NonJsonBody_ThrowsBusinessException() {
        ReflectionTestUtils.setField(wechatService, "appId", "wx-test-appid");
        ReflectionTestUtils.setField(wechatService, "appSecret", "secret");
        ReflectionTestUtils.setField(wechatService, "mockEnabled", false);
        ReflectionTestUtils.setField(wechatService, "restTemplate", restTemplate);

        mockWechatResponse("<html>Bad Gateway</html>", "text/plain;charset=UTF-8");

        assertThatThrownBy(() -> wechatService.code2Session("wx-code"))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getCode()).isEqualTo("WECHAT_API_ERROR");
                });
    }

    // ======================== getPhoneNumber（手机号授权换取）=======================

    @Test
    @DisplayName("Mock 模式 - getPhoneNumber 返回确定性的 11 位手机号（联调用）")
    void getPhoneNumber_MockMode_ReturnsDeterministicPhone() {
        ReflectionTestUtils.setField(wechatService, "appId", "");
        ReflectionTestUtils.setField(wechatService, "appSecret", "");
        ReflectionTestUtils.setField(wechatService, "mockEnabled", true);

        WechatService.PhoneNumberResult result = wechatService.getPhoneNumber("phone-code-abc");

        assertThat(result).isNotNull();
        assertThat(result.getPurePhoneNumber()).matches("^1[3-9]\\d{9}$");
        // 同一 code → 同一手机号（确定性，便于联调与断言）
        WechatService.PhoneNumberResult again = wechatService.getPhoneNumber("phone-code-abc");
        assertThat(again.getPurePhoneNumber()).isEqualTo(result.getPurePhoneNumber());
    }

    @Test
    @DisplayName("Mock 未显式启用且微信未配置 → getPhoneNumber 拒绝（fail-closed）")
    void getPhoneNumber_MockDisabled_Rejects() {
        ReflectionTestUtils.setField(wechatService, "appId", "");
        ReflectionTestUtils.setField(wechatService, "appSecret", "");
        ReflectionTestUtils.setField(wechatService, "mockEnabled", false);

        assertThatThrownBy(() -> wechatService.getPhoneNumber("phone-code"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("微信");
    }

    @Test
    @DisplayName("真实模式 - 先取 access_token 再换手机号，返回 purePhoneNumber")
    void getPhoneNumber_RealMode_ReturnsPhone() {
        ReflectionTestUtils.setField(wechatService, "appId", "wx-test-appid");
        ReflectionTestUtils.setField(wechatService, "appSecret", "secret");
        ReflectionTestUtils.setField(wechatService, "mockEnabled", false);
        ReflectionTestUtils.setField(wechatService, "restTemplate", restTemplate);

        // 第一次调用：token 未缓存 → 请求 cgi-bin/token
        mockWechatResponse("{\"access_token\":\"ACCESS_TOKEN_1\",\"expires_in\":7200}",
                "application/json;charset=UTF-8");

        // POST /wxa/business/getuserphonenumber 换号
        HttpHeaders postHeaders = new HttpHeaders();
        postHeaders.setContentType(MediaType.APPLICATION_JSON);
        ResponseEntity<String> phoneEntity = new ResponseEntity<>(
                "{\"errcode\":0,\"errmsg\":\"ok\",\"phone_info\":{\"phoneNumber\":\"+8613800138000\",\"purePhoneNumber\":\"13800138000\",\"countryCode\":\"86\"}}",
                postHeaders, HttpStatus.OK);
        when(restTemplate.postForEntity(anyString(), any(), any(Class.class)))
                .thenReturn(phoneEntity);

        WechatService.PhoneNumberResult result = wechatService.getPhoneNumber("phone-code-real");

        assertThat(result).isNotNull();
        assertThat(result.getPurePhoneNumber()).isEqualTo("13800138000");
        assertThat(result.getPhoneNumber()).isEqualTo("+8613800138000");
    }

    @Test
    @DisplayName("真实模式 - 换号接口返回 errcode → 抛 WECHAT_API_ERROR")
    void getPhoneNumber_WechatError_Throws() {
        ReflectionTestUtils.setField(wechatService, "appId", "wx-test-appid");
        ReflectionTestUtils.setField(wechatService, "appSecret", "secret");
        ReflectionTestUtils.setField(wechatService, "mockEnabled", false);
        ReflectionTestUtils.setField(wechatService, "restTemplate", restTemplate);

        mockWechatResponse("{\"access_token\":\"ACCESS_TOKEN_1\",\"expires_in\":7200}",
                "application/json;charset=UTF-8");

        HttpHeaders postHeaders = new HttpHeaders();
        postHeaders.setContentType(MediaType.APPLICATION_JSON);
        ResponseEntity<String> phoneEntity = new ResponseEntity<>(
                "{\"errcode\":40029,\"errmsg\":\"invalid code\"}",
                postHeaders, HttpStatus.OK);
        when(restTemplate.postForEntity(anyString(), any(), any(Class.class)))
                .thenReturn(phoneEntity);

        assertThatThrownBy(() -> wechatService.getPhoneNumber("phone-code-error"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("code 无效");
    }
}
