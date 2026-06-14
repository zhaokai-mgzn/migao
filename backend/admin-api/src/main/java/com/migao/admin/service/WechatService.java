package com.migao.admin.service;

import com.migao.admin.exception.BusinessException;
import lombok.Data;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestTemplate;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Map;

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
     * 如果 AppID/Secret 未配置则使用 Mock 模式
     *
     * @param code 微信小程序 wx.login() 返回的 code
     * @return Code2SessionResult
     */
    public Code2SessionResult code2Session(String code) {
        if (!StringUtils.hasText(appId) || !StringUtils.hasText(appSecret)) {
            log.warn("【Mock 模式】微信 AppID/Secret 未配置，使用 Mock 模式处理 code2Session");
            return mockCode2Session(code);
        }

        return realCode2Session(code);
    }

    /**
     * 真实调用微信 code2Session API
     */
    @SuppressWarnings("unchecked")
    private Code2SessionResult realCode2Session(String code) {
        String url = String.format(CODE2SESSION_URL, appId, appSecret, code);
        log.info("调用微信 code2Session 接口: appId={}", appId);

        try {
            RestTemplate restTemplate = new RestTemplate();
            Map<String, Object> response = restTemplate.getForObject(url, Map.class);

            if (response == null) {
                throw new BusinessException("WECHAT_API_ERROR", "微信 API 返回为空");
            }

            // 检查错误码
            Integer errcode = (Integer) response.get("errcode");
            if (errcode != null && errcode != 0) {
                String errmsg = (String) response.get("errmsg");
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
            result.setOpenid((String) response.get("openid"));
            result.setSessionKey((String) response.get("session_key"));
            result.setUnionid((String) response.get("unionid"));

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
