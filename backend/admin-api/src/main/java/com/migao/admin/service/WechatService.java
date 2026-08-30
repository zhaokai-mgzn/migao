package com.migao.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.exception.BusinessException;
import lombok.Data;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestTemplate;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/**
 * 微信服务类
 * 负责调用微信 API（code2Session 等）
 * 开发阶段支持 Mock 模式（AppID/Secret 未配置时自动启用）
 */
@Slf4j
@Service
public class WechatService {

    @Value("${wechat.mini.appid:}")
    private String appId;

    @Value("${wechat.mini.secret:}")
    private String appSecret;

    /**
     * Mock 模式开关（审计 07 P1-1）：默认 false = 生产 fail-closed。
     * 仅 dev/CI 环境显式设置 WECHAT_MOCK_ENABLED=true 启用；
     * 未配置真实微信 appid/secret 且 mock 未启用时，登录直接拒绝（禁止伪造 openid）。
     */
    @Value("${wechat.mock-enabled:false}")
    private boolean mockEnabled;

    /**
     * HTTP 客户端。微信官方接口（尤其错误场景）返回 Content-Type: text/plain，
     * 不能直接 getForObject(url, Map.class)（缺转换器），必须按 String 接收后手动解析 JSON。
     * 包级可见字段 + 包级构造器，便于测试注入 MockRestTemplate（见 RegistrationReviewClient 同款模式）。
     */
    RestTemplate restTemplate = new RestTemplate();

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private static final String CODE2SESSION_URL =
            "https://api.weixin.qq.com/sns/jscode2session?appid=%s&secret=%s&js_code=%s&grant_type=authorization_code";

    /**
     * 微信 code2Session 响应
     */
    @Data
    public static class Code2SessionResult {
        private String openid;
        private String sessionKey;
        private String unionid;
    }

    /**
     * 调用微信 code2Session 接口
     * AppID/Secret 未配置时：仅当显式启用 wechat.mock-enabled（dev/CI）才使用 Mock 模式，
     * 否则拒绝登录（fail-closed，防伪造 openid 冒充任意用户，审计 07 P1-1）。
     *
     * @param code 微信小程序 wx.login() 返回的 code
     * @return Code2SessionResult
     */
    public Code2SessionResult code2Session(String code) {
        if (!StringUtils.hasText(appId) || !StringUtils.hasText(appSecret)) {
            if (mockEnabled) {
                log.warn("【Mock 模式】微信 AppID/Secret 未配置，使用 Mock 模式处理 code2Session");
                return mockCode2Session(code);
            }
            throw new BusinessException("WECHAT_CONFIG_MISSING",
                    "微信小程序登录未配置，请联系管理员（仅 dev 环境可用 Mock 模式）", 503);
        }

        return realCode2Session(code);
    }

    /**
     * 真实调用微信 code2Session API
     * 按 String 接收响应后手动解析 JSON：微信官方接口（尤其错误场景）
     * 返回 Content-Type: text/plain，RestTemplate 无 text/plain → Map 的转换器，
     * 直接 getForObject(url, Map.class) 会抛 HttpMessageConverter 异常（线上实测发现）。
     */
    private Code2SessionResult realCode2Session(String code) {
        String url = String.format(CODE2SESSION_URL, appId, appSecret, code);
        log.info("调用微信 code2Session 接口: appId={}", appId);

        try {
            ResponseEntity<String> response = restTemplate.getForEntity(url, String.class);
            String body = response.getBody();
            if (body == null || body.isBlank()) {
                throw new BusinessException("WECHAT_API_ERROR", "微信 API 返回为空");
            }

            JsonNode root = OBJECT_MAPPER.readTree(body);
            if (root == null) {
                throw new BusinessException("WECHAT_API_ERROR", "微信 API 返回为空");
            }

            // 检查错误码
            int errcode = root.path("errcode").asInt(0);
            if (errcode != 0) {
                String errmsg = root.path("errmsg").asText("");
                log.error("微信 code2Session 失败: errcode={}, errmsg={}", errcode, errmsg);

                String errorMessage = switch (errcode) {
                    case 40029 -> "code 无效（可能已使用或过期）";
                    case 45011 -> "API 调用频率限制";
                    case 40226 -> "高风险等级用户，小程序登录被拦截";
                    case -1 -> "微信系统繁忙，请稍后再试";
                    default -> "微信 API 错误: " + errmsg;
                };

                throw new BusinessException("WECHAT_API_ERROR", errorMessage);
            }

            Code2SessionResult result = new Code2SessionResult();
            result.setOpenid(root.path("openid").asText(null));
            result.setSessionKey(root.path("session_key").asText(null));
            result.setUnionid(root.path("unionid").asText(null));

            if (!StringUtils.hasText(result.getOpenid())) {
                throw new BusinessException("WECHAT_API_ERROR", "微信 API 未返回 openid");
            }

            log.info("微信 code2Session 成功: openid={}", result.getOpenid());
            return result;

        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            log.error("调用微信 code2Session 接口异常: {}", e.getMessage(), e);
            throw new BusinessException("WECHAT_API_ERROR", "调用微信 API 异常: " + e.getMessage());
        }
    }

    /**
     * Mock 模式：根据 code 生成固定的 openid
     */
    private Code2SessionResult mockCode2Session(String code) {
        String mockOpenid = "mock_openid_" + sha256Short(code);
        log.warn("【Mock 模式】生成 Mock openid: {}", mockOpenid);

        Code2SessionResult result = new Code2SessionResult();
        result.setOpenid(mockOpenid);
        result.setSessionKey("mock_session_key");
        return result;
    }

    /**
     * 对字符串做 SHA-256 并截取前 16 位
     */
    private String sha256Short(String input) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest(input.getBytes(StandardCharsets.UTF_8));
            StringBuilder hexString = new StringBuilder();
            for (byte b : hash) {
                String hex = Integer.toHexString(0xff & b);
                if (hex.length() == 1) hexString.append('0');
                hexString.append(hex);
            }
            return hexString.substring(0, 16);
        } catch (NoSuchAlgorithmException e) {
            log.error("SHA-256 算法不可用，回退到 hashCode: {}", e.getMessage());
            return String.valueOf(Math.abs(input.hashCode()));
        }
    }
}
