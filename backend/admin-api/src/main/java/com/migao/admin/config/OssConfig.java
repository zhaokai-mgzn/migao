package com.migao.admin.config;

import com.aliyun.oss.OSS;
import com.aliyun.oss.OSSClientBuilder;
import lombok.Data;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.util.StringUtils;

/**
 * 阿里云 OSS 配置类
 */
@Slf4j
@Data
@Configuration
@ConfigurationProperties(prefix = "aliyun.oss")
public class OssConfig {

    private String endpoint;
    private String accessKeyId;
    private String accessKeySecret;
    private String bucketName;
    private String urlPrefix;

    // 双 Bucket 配置：永久存储（商品图片等）和临时存储（聊天图片）
    private String permanentBucketName;
    private String temporaryBucketName;

    /**
     * OSS 凭据是否齐备（三项都非空白）。
     *
     * 注意：不能用 `@ConditionalOnProperty(name = "aliyun.oss.endpoint")` 判断 ——
     * `application.yml` 把这三项都默认成**空字符串**（`${OSS_ENDPOINT:}`），
     * 而该注解的 `name` 只判「属性是否存在」，**空串也算存在** → 条件成立 →
     * 仍会去建 client。故这里显式做非空判断（issue #3270 实测踩坑）。
     */
    public boolean hasCredentials() {
        return StringUtils.hasText(endpoint)
                && StringUtils.hasText(accessKeyId)
                && StringUtils.hasText(accessKeySecret);
    }

    /**
     * 创建 OSS 客户端 Bean —— 仅在**凭据齐备**时创建，否则返回 null（不注册该 bean）。
     *
     * 为什么必须优雅降级（issue #3270 实测，2026-09-11）：
     * 空 endpoint + null 凭据会让 `OSSClientBuilder.build` 抛
     * `InvalidCredentialsException: Access key id should not be null or empty`；
     * 该异常发生在 bean 创建期 → `ossClient` → `ossService` → `uploadController`
     * 连锁失败 → **整个 Spring 上下文启动失败**（admin-api 容器 Exit 1）→
     * 本地/CI docker 栈根本起不来（C 端验收 9/9 全 failure 的最后一环）。
     *
     * 返回 null 后：`OssService` 因 `@ConditionalOnBean(OSS.class)` 不注册，
     * 由 {@link com.migao.admin.service.LocalFileStorageService} 作为
     * `FileStorageService` 的 fallback 提供上传能力 —— 上传是可选能力，
     * 不该阻塞整机启动。
     */
    /**
     * 条件表达式：三项凭据都非空白时才注册本 bean。
     *
     * 用 SpEL 直接判非空白（而非 `@ConditionalOnProperty` 的属性存在性），
     * 因为 application.yml 把三项都默认成空串，**属性存在性判断对空串恒成立**。
     * `@ConditionalOnBean(OSS.class)` 也不可用（@Service 先于 @Configuration 注册）。
     */
    public static final String REQUIRE_OSS_CREDENTIALS =
            "'${aliyun.oss.endpoint:}'.trim().length() > 0"
                    + " and '${aliyun.oss.access-key-id:}'.trim().length() > 0"
                    + " and '${aliyun.oss.access-key-secret:}'.trim().length() > 0";

    @Bean
    @ConditionalOnExpression(REQUIRE_OSS_CREDENTIALS)
    public OSS ossClient() {
        log.info("初始化 OSS 客户端: endpoint={}, bucket={}, permanentBucket={}, temporaryBucket={}",
                endpoint, bucketName, permanentBucketName, temporaryBucketName);
        return new OSSClientBuilder().build(endpoint, accessKeyId, accessKeySecret);
    }
}
