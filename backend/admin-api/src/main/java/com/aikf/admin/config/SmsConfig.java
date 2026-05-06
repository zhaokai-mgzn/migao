package com.aikf.admin.config;

import com.aliyun.dysmsapi20170525.Client;
import com.aliyun.teaopenapi.models.Config;
import lombok.Data;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 阿里云短信服务配置类
 */
@Slf4j
@Data
@Configuration
@ConfigurationProperties(prefix = "aliyun.sms")
public class SmsConfig {

    private String accessKeyId;
    private String accessKeySecret;
    private String signName;
    private String templateCode;

    /**
     * 创建阿里云短信客户端 Bean
     * 仅在配置了 accessKeyId 时才创建
     */
    @Bean
    @ConditionalOnExpression("!'${aliyun.sms.access-key-id:}'.isEmpty()")
    public Client smsClient() throws Exception {
        log.info("初始化阿里云短信客户端");
        Config config = new Config()
                .setAccessKeyId(accessKeyId)
                .setAccessKeySecret(accessKeySecret)
                .setEndpoint("dysmsapi.aliyuncs.com");
        return new Client(config);
    }
}
