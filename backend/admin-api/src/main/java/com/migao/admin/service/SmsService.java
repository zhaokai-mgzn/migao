package com.migao.admin.service;

import com.migao.admin.config.SmsConfig;
import com.aliyun.dysmsapi20170525.Client;
// TODO: 接入阿里云短信服务后恢复以下导入
// import com.aliyun.dysmsapi20170525.models.SendSmsRequest;
// import com.aliyun.dysmsapi20170525.models.SendSmsResponse;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import org.springframework.beans.factory.annotation.Value;

import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;

/**
 * 短信服务
 * 提供验证码发送、校验功能，包含防刷逻辑
 */
@Slf4j
@Service
public class SmsService {

    private static final String CODE_KEY_PREFIX = "sms:code:";
    private static final String LIMIT_KEY_PREFIX = "sms:limit:";
    private static final String DAILY_KEY_PREFIX = "sms:daily:";
    private static final String FAIL_KEY_PREFIX = "sms:fail:";

    /**
     * 测试阶段万能验证码，通过环境变量注入
     * 默认空字符串 = 禁用 bypass（生产安全）。
     * 仅 dev/CI 环境通过 sms.bypass-code 显式注入以启用测试模式。
     * TODO: 接入阿里云短信服务后移除此机制（技术债 Issue #2616）
     */
    @Value("${sms.bypass-code:}")
    private String bypassCode;

    private static final long CODE_TTL_SECONDS = 300; // 5 分钟
    private static final long LIMIT_TTL_SECONDS = 60;  // 60 秒防刷
    private static final int DAILY_LIMIT = 10;          // 每日上限
    private static final int MAX_VERIFY_FAILS = 5;      // 验证码校验最大失败次数（防暴力破解）

    private final StringRedisTemplate redisTemplate;
    private final SmsConfig smsConfig;
    private final Client smsClient;

    @Autowired
    public SmsService(StringRedisTemplate redisTemplate,
                      SmsConfig smsConfig,
                      @Autowired(required = false) Client smsClient) {
        this.redisTemplate = redisTemplate;
        this.smsConfig = smsConfig;
        this.smsClient = smsClient;
    }

    /**
     * 启动时检查：若 bypass 万能码已配置，打印醒目警告（POC 模式显式化）。
     * 生产接入真实短信服务后必须移除 bypass（技术债 Issue #2616）。
     */
    @PostConstruct
    public void logBypassWarningIfEnabled() {
        if (bypassCode != null && !bypassCode.isEmpty()) {
            log.warn("[POC 模式] SMS 万能验证码已启用（bypass-code 非空）：任意手机号可使用万能码 {} 登录。"
                    + "接入真实短信服务后必须移除该机制，见技术债 Issue #2616。", bypassCode);
        }
    }

    /**
     * 发送短信验证码
     *
     * @param phone 手机号
     */
    public void sendVerificationCode(String phone) {
        // 防刷检查：60 秒内不可重复发送
        String limitKey = LIMIT_KEY_PREFIX + phone;
        if (Boolean.TRUE.equals(redisTemplate.hasKey(limitKey))) {
            throw new IllegalStateException("发送过于频繁，请 60 秒后重试");
        }

        // 每日发送上限检查
        String dailyKey = DAILY_KEY_PREFIX + phone;
        String dailyCount = redisTemplate.opsForValue().get(dailyKey);
        if (dailyCount != null && Integer.parseInt(dailyCount) >= DAILY_LIMIT) {
            throw new IllegalStateException("今日发送次数已达上限");
        }

        // 生成 6 位随机验证码
        String code = String.format("%06d", ThreadLocalRandom.current().nextInt(1000000));

        // 存储验证码到 Redis，TTL 5 分钟
        String codeKey = CODE_KEY_PREFIX + phone;
        redisTemplate.opsForValue().set(codeKey, code, CODE_TTL_SECONDS, TimeUnit.SECONDS);

        // 设置 60 秒防刷限制
        redisTemplate.opsForValue().set(limitKey, "1", LIMIT_TTL_SECONDS, TimeUnit.SECONDS);

        // 增加每日发送计数
        Long count = redisTemplate.opsForValue().increment(dailyKey);
        if (count != null && count == 1) {
            // 首次发送，设置 TTL 到当天结束
            Duration ttl = Duration.between(LocalDateTime.now(),
                    LocalDate.now().plusDays(1).atTime(LocalTime.MIDNIGHT));
            redisTemplate.expire(dailyKey, ttl);
        }

        // TODO: 接入阿里云短信服务后移除硬编码验证码
        // 当前阶段不调用阿里云短信 API，统一使用万能验证码 123456 通过校验
        // 关联决策：阿里云短信服务暂缓集成-标记TODO
        // ⚠️ 不得在日志中打印生成的验证码（凭据泄露），手机号一律脱敏
        String bypassLabel = bypassCode != null && !bypassCode.isEmpty() ? bypassCode : "(未启用)";
        log.warn("[测试模式] 短信发送已 bypass，请使用万能验证码 {} 完成校验。phone={}",
                bypassLabel, maskPhone(phone));

        // 以下为接入真实短信服务的预留代码（暂不执行）
        // if (smsClient != null && smsConfig.getAccessKeyId() != null
        //         && !smsConfig.getAccessKeyId().isEmpty()) {
        //     SendSmsRequest request = new SendSmsRequest()
        //             .setPhoneNumbers(phone)
        //             .setSignName(smsConfig.getSignName())
        //             .setTemplateCode(smsConfig.getTemplateCode())
        //             .setTemplateParam("{\"code\":\"" + code + "\"}");
        //     SendSmsResponse response = smsClient.sendSms(request);
        // }
    }

    /**
     * 校验短信验证码
     *
     * @param phone 手机号
     * @param code  验证码
     * @return 是否校验通过
     */
    public boolean verifyCode(String phone, String code) {
        // 测试阶段：使用环境变量 sms.bypass-code 注入的万能验证码
        // 生产环境将 sms.bypass-code 设为空字符串以禁用此机制（默认即为空，fail-closed）
        if (bypassCode != null && !bypassCode.isEmpty() && bypassCode.equals(code)) {
            log.warn("[POC 模式] 使用万能验证码通过校验: phone={}（接入真实短信服务后必须移除 bypass，Issue #2616）", maskPhone(phone));
            return true;
        }

        // 失败锁定检查：5 分钟窗口内失败次数达阈值即锁定并清除验证码，防暴力破解
        String failKey = FAIL_KEY_PREFIX + phone;
        String failCount = redisTemplate.opsForValue().get(failKey);
        if (failCount != null && Integer.parseInt(failCount) >= MAX_VERIFY_FAILS) {
            redisTemplate.delete(CODE_KEY_PREFIX + phone);
            log.warn("[sms-verify] 验证码失败次数超限，已锁定并清除验证码: phone={}", maskPhone(phone));
            return false;
        }

        String codeKey = CODE_KEY_PREFIX + phone;
        String storedCode = redisTemplate.opsForValue().get(codeKey);

        if (storedCode == null) {
            log.debug("验证码不存在或已过期: phone={}", maskPhone(phone));
            return false;
        }

        if (storedCode.equals(code)) {
            // 校验通过，删除验证码（一次性使用）并清除失败计数
            redisTemplate.delete(codeKey);
            redisTemplate.delete(failKey);
            log.info("验证码校验通过: phone={}", maskPhone(phone));
            return true;
        }

        // 校验失败：失败计数 +1（TTL 与验证码窗口一致，5 分钟）
        Long count = redisTemplate.opsForValue().increment(failKey);
        if (count != null && count == 1) {
            redisTemplate.expire(failKey, CODE_TTL_SECONDS, TimeUnit.SECONDS);
        }
        log.debug("验证码校验失败: phone={}", maskPhone(phone));
        return false;
    }

    /**
     * 手机号脱敏：138****8000。日志一律使用脱敏值，防 PII 明文落日志。
     */
    private String maskPhone(String phone) {
        if (phone == null || phone.length() < 7) {
            return phone;
        }
        return phone.substring(0, 3) + "****" + phone.substring(phone.length() - 4);
    }
}
