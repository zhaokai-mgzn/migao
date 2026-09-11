package com.migao.admin.config;

// case_ids: MC-012, DF-011

import com.aliyun.oss.OSS;
import com.migao.admin.service.FileStorageService;
import com.migao.admin.service.LocalFileStorageService;
import com.migao.admin.service.OssService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.context.annotation.ComponentScan;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.FilterType;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * OSS 未配置（空串）时的 Spring 上下文降级契约（issue #3270）。
 *
 * 用 {@link ApplicationContextRunner} 只加载 OSS 相关的两个 bean
 * （{@link OssConfig} + {@link OssService}），隔离掉 DataSource/MyBatis 等无关依赖，
 * 从而在**不起整机上下文**的前提下复现并锁定「启动期 bean 创建失败」这一故障模式。
 *
 * 修复前预期：`ossClient` 因 `OSSClientBuilder.build(endpoint="", accessKeyId=null)`
 * 抛 `InvalidCredentialsException: Access key id should not be null or empty` →
 * 上下文启动失败 → 本测试红。
 */
class OssEmptyConfigContextTest {

    /** 只扫这两个类，避免把 Mapper/Controller 等无关 bean 拉进上下文 */
    @Configuration
    @ComponentScan(
            basePackageClasses = {OssConfig.class, OssService.class},
            useDefaultFilters = false,
            includeFilters = @ComponentScan.Filter(
                    type = FilterType.ASSIGNABLE_TYPE,
                    classes = {OssConfig.class, OssService.class, LocalFileStorageService.class}))
    static class OssOnlyConfig {
    }

    private ApplicationContextRunner runner() {
        return new ApplicationContextRunner()
                .withUserConfiguration(OssOnlyConfig.class);
    }

    @Test
    @DisplayName("空凭据（application.yml 默认形态）下上下文仍能启动")
    void contextStartsWithEmptyCredentials() {
        runner()
                .withPropertyValues(
                        "aliyun.oss.endpoint=",
                        "aliyun.oss.access-key-id=",
                        "aliyun.oss.access-key-secret=")
                .run(ctx -> assertThat(ctx)
                        .as("空串凭据不得让上下文启动失败 —— 这是 #3270 中 admin-api Exit(1) 的根因")
                        .hasNotFailed());
    }

    @Test
    @DisplayName("空凭据下不存在 OSS client bean（@Bean 返回 null → Spring 移除定义）")
    void shouldNotExposeOssClientBean() {
        runner()
                .withPropertyValues(
                        "aliyun.oss.endpoint=",
                        "aliyun.oss.access-key-id=",
                        "aliyun.oss.access-key-secret=")
                .run(ctx -> {
                    assertThat(ctx).hasNotFailed();
                    assertThat(ctx.getBeanNamesForType(OSS.class))
                            .as("空凭据下不得注册真实 OSS client —— 否则启动期抛 "
                                    + "InvalidCredentialsException（issue #3270）")
                            .isEmpty();
                });
    }

    @Test
    @DisplayName("空凭据下 FileStorageService 必须降级为 LocalFileStorageService")
    void shouldFallbackToLocalStorage() {
        runner()
                .withPropertyValues(
                        "aliyun.oss.endpoint=",
                        "aliyun.oss.access-key-id=",
                        "aliyun.oss.access-key-secret=")
                .run(ctx -> assertThat(ctx.getBean(FileStorageService.class))
                        .as("OSS 不可用时必须降级本地存储：上传能力仍可用且应用能启动")
                        .isInstanceOf(LocalFileStorageService.class));
    }

    @Test
    @DisplayName("空凭据下不得注册 OssService")
    void shouldNotRegisterOssService() {
        runner()
                .withPropertyValues(
                        "aliyun.oss.endpoint=",
                        "aliyun.oss.access-key-id=",
                        "aliyun.oss.access-key-secret=")
                .run(ctx -> assertThat(ctx.getBeanNamesForType(OssService.class))
                        .as("OssService 构造器注入 OSS，空凭据下注册它会连带启动失败")
                        .isEmpty());
    }

    @Test
    @DisplayName("属性完全缺失时同样降级（不因缺 property 而失败）")
    void degradesWhenPropertiesAbsent() {
        runner().run(ctx -> {
            assertThat(ctx).hasNotFailed();
            assertThat(ctx.getBeanNamesForType(OSS.class)).isEmpty();
            assertThat(ctx.getBean(FileStorageService.class))
                    .isInstanceOf(LocalFileStorageService.class);
        });
    }
}
