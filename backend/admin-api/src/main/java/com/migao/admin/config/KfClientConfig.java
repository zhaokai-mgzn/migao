package com.migao.admin.config;

import com.migao.admin.service.kf.SecretCipher;
import com.migao.admin.service.kf.WechatKfClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** 微信客服通道 bean（仅在 wechat.kf.enabled=true 时装配）。 */
@Configuration
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfClientConfig {

    @Bean
    public WechatKfClient wechatKfClient() {
        return new WechatKfClient();
    }

    @Bean
    public SecretCipher kfSecretCipher(@Value("${wechat.kf.secret-master-key:}") String masterKey) {
        return new SecretCipher(masterKey, "default");
    }
}
