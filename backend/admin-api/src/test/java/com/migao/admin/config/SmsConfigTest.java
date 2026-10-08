package com.migao.admin.config;

import com.aliyun.dysmsapi20170525.Client;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.*;

/**
 * SmsConfig 单元测试
 * 覆盖属性绑定、SMS 客户端创建
 */
class SmsConfigTest {

    // ======================== 属性绑定测试 ========================

    @Nested
    @DisplayName("属性绑定")
    class PropertyBinding {

        @Test
        @DisplayName("应正确绑定 accessKeyId")
        void shouldBindAccessKeyId() {
            SmsConfig cfg = new SmsConfig();
            cfg.setAccessKeyId("LTAI5tTestKey");
            assertThat(cfg.getAccessKeyId()).isEqualTo("LTAI5tTestKey");
        }

        @Test
        @DisplayName("应正确绑定 accessKeySecret")
        void shouldBindAccessKeySecret() {
            SmsConfig cfg = new SmsConfig();
            cfg.setAccessKeySecret("test-secret");
            assertThat(cfg.getAccessKeySecret()).isEqualTo("test-secret");
        }

        @Test
        @DisplayName("应正确绑定 signName")
        void shouldBindSignName() {
            SmsConfig cfg = new SmsConfig();
            cfg.setSignName("米高布艺");
            assertThat(cfg.getSignName()).isEqualTo("米高布艺");
        }

        @Test
        @DisplayName("应正确绑定 templateCode")
        void shouldBindTemplateCode() {
            SmsConfig cfg = new SmsConfig();
            cfg.setTemplateCode("SMS_123456789");
            assertThat(cfg.getTemplateCode()).isEqualTo("SMS_123456789");
        }

        @Test
        @DisplayName("应正确绑定所有属性")
        void shouldBindAllProperties() {
            SmsConfig cfg = new SmsConfig();
            cfg.setAccessKeyId("ak-id");
            cfg.setAccessKeySecret("ak-secret");
            cfg.setSignName("sign-name");
            cfg.setTemplateCode("tpl-code");

            assertThat(cfg.getAccessKeyId()).isEqualTo("ak-id");
            assertThat(cfg.getAccessKeySecret()).isEqualTo("ak-secret");
            assertThat(cfg.getSignName()).isEqualTo("sign-name");
            assertThat(cfg.getTemplateCode()).isEqualTo("tpl-code");
        }
    }

    // ======================== SMS 客户端创建测试 ========================

    @Nested
    @DisplayName("smsClient() 方法")
    class SmsClientCreation {

        @Test
        @DisplayName("所有属性设置时应返回非 null Client")
        void shouldReturnNonNullClient_whenAllPropertiesSet() throws Exception {
            SmsConfig cfg = new SmsConfig();
            cfg.setAccessKeyId("LTAI5tTestKey");
            cfg.setAccessKeySecret("test-secret");

            Client client = cfg.smsClient();

            assertThat(client).isNotNull();
        }

        @Test
        @DisplayName("配置不同 accessKeyId 时应正常创建")
        void shouldCreateClientWithDifferentAccessKey() throws Exception {
            SmsConfig cfg = new SmsConfig();
            cfg.setAccessKeyId("LTAI5tAnotherKey");
            cfg.setAccessKeySecret("another-secret");

            Client client = cfg.smsClient();

            assertThat(client).isNotNull();
        }

        @Test
        @DisplayName("即使 signName 和 templateCode 未设置也应创建 Client")
        void shouldCreateClientEvenWithoutSignAndTemplate() throws Exception {
            SmsConfig cfg = new SmsConfig();
            cfg.setAccessKeyId("LTAI5tMinimal");

            // smsClient() 只依赖 accessKeyId 和 accessKeySecret
            // signName/templateCode 是发送短信时使用，不影响客户端创建
            Client client = cfg.smsClient();

            assertThat(client).isNotNull();
        }
    }

    // ======================== ConfigurationProperties 前缀验证 ========================

    @Test
    @DisplayName("@ConfigurationProperties prefix 应为 aliyun.sms")
    void shouldHaveCorrectConfigurationPropertiesPrefix() {
        org.springframework.boot.context.properties.ConfigurationProperties annotation = SmsConfig.class.getAnnotation(
                org.springframework.boot.context.properties.ConfigurationProperties.class);
        assertThat(annotation).isNotNull();
        assertThat(annotation.prefix()).isEqualTo("aliyun.sms");
    }

    // ======================== @Configuration 注解验证 ========================

    @Test
    @DisplayName("应有 @Configuration 注解")
    void shouldHaveConfigurationAnnotation() {
        org.springframework.context.annotation.Configuration annotation =
                SmsConfig.class.getAnnotation(org.springframework.context.annotation.Configuration.class);
        assertThat(annotation).isNotNull();
    }

    @Test
    @DisplayName("@Bean 方法应有 @ConditionalOnExpression 注解")
    void smsClientMethod_shouldHaveConditionalAnnotation() throws NoSuchMethodException {
        var method = SmsConfig.class.getMethod("smsClient");
        var annotation = method.getAnnotation(
                org.springframework.boot.autoconfigure.condition.ConditionalOnExpression.class);
        assertThat(annotation).isNotNull();
        assertThat(annotation.value()).contains("aliyun.sms.access-key-id");
    }
}
