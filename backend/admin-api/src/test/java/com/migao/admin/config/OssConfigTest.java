package com.migao.admin.config;

import com.aliyun.oss.OSS;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.*;

/**
 * OssConfig 单元测试
 * 覆盖属性绑定、OSS 客户端创建、双 Bucket 配置
 */
class OssConfigTest {

    // ======================== 属性绑定测试 ========================

    @Nested
    @DisplayName("属性绑定")
    class PropertyBinding {

        @Test
        @DisplayName("应正确绑定 endpoint")
        void shouldBindEndpoint() {
            OssConfig cfg = new OssConfig();
            cfg.setEndpoint("oss-cn-hangzhou.aliyuncs.com");
            assertThat(cfg.getEndpoint()).isEqualTo("oss-cn-hangzhou.aliyuncs.com");
        }

        @Test
        @DisplayName("应正确绑定 accessKeyId")
        void shouldBindAccessKeyId() {
            OssConfig cfg = new OssConfig();
            cfg.setAccessKeyId("LTAI5tTestOssKey");
            assertThat(cfg.getAccessKeyId()).isEqualTo("LTAI5tTestOssKey");
        }

        @Test
        @DisplayName("应正确绑定 accessKeySecret")
        void shouldBindAccessKeySecret() {
            OssConfig cfg = new OssConfig();
            cfg.setAccessKeySecret("oss-secret");
            assertThat(cfg.getAccessKeySecret()).isEqualTo("oss-secret");
        }

        @Test
        @DisplayName("应正确绑定 bucketName")
        void shouldBindBucketName() {
            OssConfig cfg = new OssConfig();
            cfg.setBucketName("migao-images");
            assertThat(cfg.getBucketName()).isEqualTo("migao-images");
        }

        @Test
        @DisplayName("应正确绑定 urlPrefix")
        void shouldBindUrlPrefix() {
            OssConfig cfg = new OssConfig();
            cfg.setUrlPrefix("https://cdn.migao.com");
            assertThat(cfg.getUrlPrefix()).isEqualTo("https://cdn.migao.com");
        }

        @Test
        @DisplayName("应正确绑定所有基础属性")
        void shouldBindAllBasicProperties() {
            OssConfig cfg = new OssConfig();
            cfg.setEndpoint("oss-cn-beijing.aliyuncs.com");
            cfg.setAccessKeyId("ak");
            cfg.setAccessKeySecret("sk");
            cfg.setBucketName("bucket");
            cfg.setUrlPrefix("https://cdn.example.com");

            assertThat(cfg.getEndpoint()).isEqualTo("oss-cn-beijing.aliyuncs.com");
            assertThat(cfg.getAccessKeyId()).isEqualTo("ak");
            assertThat(cfg.getAccessKeySecret()).isEqualTo("sk");
            assertThat(cfg.getBucketName()).isEqualTo("bucket");
            assertThat(cfg.getUrlPrefix()).isEqualTo("https://cdn.example.com");
        }
    }

    // ======================== 双 Bucket 配置测试 ========================

    @Nested
    @DisplayName("双 Bucket 配置")
    class DualBucketConfig {

        @Test
        @DisplayName("应正确绑定 permanentBucketName")
        void shouldBindPermanentBucketName() {
            OssConfig cfg = new OssConfig();
            cfg.setPermanentBucketName("migao-permanent");
            assertThat(cfg.getPermanentBucketName()).isEqualTo("migao-permanent");
        }

        @Test
        @DisplayName("应正确绑定 temporaryBucketName")
        void shouldBindTemporaryBucketName() {
            OssConfig cfg = new OssConfig();
            cfg.setTemporaryBucketName("migao-temporary");
            assertThat(cfg.getTemporaryBucketName()).isEqualTo("migao-temporary");
        }

        @Test
        @DisplayName("双 Bucket 可独立配置")
        void dualBuckets_canBeConfiguredIndependently() {
            OssConfig cfg = new OssConfig();
            cfg.setPermanentBucketName("permanent");
            cfg.setTemporaryBucketName("temporary");

            assertThat(cfg.getPermanentBucketName()).isEqualTo("permanent");
            assertThat(cfg.getTemporaryBucketName()).isEqualTo("temporary");
            assertThat(cfg.getPermanentBucketName()).isNotEqualTo(cfg.getTemporaryBucketName());
        }
    }

    // ======================== OSS 客户端创建测试 ========================

    @Nested
    @DisplayName("ossClient() 方法")
    class OssClientCreation {

        @Test
        @DisplayName("所有属性设置时应返回非 null OSS Client")
        void shouldReturnNonNullClient_whenPropertiesSet() {
            OssConfig cfg = new OssConfig();
            cfg.setEndpoint("oss-cn-hangzhou.aliyuncs.com");
            cfg.setAccessKeyId("LTAI5tTestKey");
            cfg.setAccessKeySecret("test-secret");
            cfg.setBucketName("test-bucket");

            OSS client = cfg.ossClient();

            assertThat(client).isNotNull();
        }

        @Test
        @DisplayName("不同 Region endpoint 时应正常创建")
        void shouldCreateClientWithDifferentRegion() {
            OssConfig cfg = new OssConfig();
            cfg.setEndpoint("oss-cn-beijing.aliyuncs.com");
            cfg.setAccessKeyId("LTAI5tBKey");
            cfg.setAccessKeySecret("b-secret");

            OSS client = cfg.ossClient();

            assertThat(client).isNotNull();
        }

        @Test
        @DisplayName("不设置双 Bucket 属性时也能创建 Client")
        void shouldCreateClientWithoutDualBucketConfig() {
            OssConfig cfg = new OssConfig();
            cfg.setEndpoint("oss-cn-shanghai.aliyuncs.com");
            cfg.setAccessKeyId("LTAI5tKey");
            cfg.setAccessKeySecret("secret");

            OSS client = cfg.ossClient();

            assertThat(client).isNotNull();
        }
    }

    // ======================== 注解验证测试 ========================

    @Test
    @DisplayName("应有 @Configuration 注解")
    void shouldHaveConfigurationAnnotation() {
        var annotation = OssConfig.class.getAnnotation(
                org.springframework.context.annotation.Configuration.class);
        assertThat(annotation).isNotNull();
    }

    @Test
    @DisplayName("@ConfigurationProperties prefix 应为 aliyun.oss")
    void shouldHaveCorrectConfigurationPropertiesPrefix() {
        org.springframework.boot.context.properties.ConfigurationProperties annotation = OssConfig.class.getAnnotation(
                org.springframework.boot.context.properties.ConfigurationProperties.class);
        assertThat(annotation).isNotNull();
        assertThat(annotation.prefix()).isEqualTo("aliyun.oss");
    }

    @Test
    @DisplayName("@Bean 方法应有 @ConditionalOnProperty 注解")
    void ossClientMethod_shouldHaveConditionalAnnotation() throws NoSuchMethodException {
        var method = OssConfig.class.getMethod("ossClient");
        var annotation = method.getAnnotation(
                org.springframework.boot.autoconfigure.condition.ConditionalOnProperty.class);
        assertThat(annotation).isNotNull();
        assertThat(annotation.name()).contains("aliyun.oss.endpoint");
    }
}
