package com.migao.admin.config;

// case_ids: DF-017

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * OSS 配置 fail-closed 测试
 *
 * 契约：文件存储仅支持阿里云 OSS。OSS 配置缺失时应用启动必须直接失败
 * （抛出 IllegalStateException），禁止静默降级为本地磁盘存储。
 */
class OssConfigFailFastTest {

    private final ApplicationContextRunner contextRunner =
            new ApplicationContextRunner().withUserConfiguration(OssConfig.class);

    @Test
    @DisplayName("OSS 配置缺失时应用上下文启动必须失败（禁止降级本地磁盘）")
    void contextWithoutOssConfig_shouldFailToStart() {
        contextRunner.run(context -> {
            assertThat(context)
                    .as("OSS 配置缺失时上下文必须启动失败，不得静默降级")
                    .hasFailed();
            assertThat(context.getStartupFailure())
                    .rootCause()
                    .isInstanceOf(IllegalStateException.class)
                    .hasMessageContaining("OSS");
        });
    }

    @Test
    @DisplayName("validateOssConfig — 四项配置全部缺失时报错并列出全部缺失项")
    void validateOssConfig_allMissing_shouldThrowWithAllNames() {
        assertThat(org.junit.jupiter.api.Assertions.assertThrows(
                IllegalStateException.class,
                () -> OssConfig.validateOssConfig(null, null, null, null)))
                .hasMessageContaining("OSS_ENDPOINT")
                .hasMessageContaining("OSS_ACCESS_KEY_ID")
                .hasMessageContaining("OSS_ACCESS_KEY_SECRET")
                .hasMessageContaining("OSS_PERMANENT_BUCKET");
    }

    @Test
    @DisplayName("validateOssConfig — 部分缺失时只列出缺失项")
    void validateOssConfig_partiallyMissing_shouldListOnlyMissing() {
        assertThat(org.junit.jupiter.api.Assertions.assertThrows(
                IllegalStateException.class,
                () -> OssConfig.validateOssConfig(
                        "oss-cn-hangzhou.aliyuncs.com", "ak", null, "bucket")))
                .hasMessageContaining("OSS_ACCESS_KEY_SECRET")
                .hasMessageNotContaining("OSS_ENDPOINT")
                .hasMessageNotContaining("OSS_ACCESS_KEY_ID")
                .hasMessageNotContaining("OSS_PERMANENT_BUCKET");
    }

    @Test
    @DisplayName("validateOssConfig — 配置完整时不抛异常")
    void validateOssConfig_complete_shouldNotThrow() {
        org.junit.jupiter.api.Assertions.assertDoesNotThrow(() ->
                OssConfig.validateOssConfig(
                        "oss-cn-hangzhou.aliyuncs.com",
                        "ak",
                        "sk",
                        "ai-customer-service-admin-dev"));
    }
}
