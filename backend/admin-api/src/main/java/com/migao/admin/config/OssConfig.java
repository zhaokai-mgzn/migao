package com.migao.admin.config;

import com.aliyun.oss.OSS;
import com.aliyun.oss.OSSClientBuilder;
import lombok.Data;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.List;

/**
 * 阿里云 OSS 配置类
 *
 * <p>文件存储仅支持阿里云 OSS：OSS 配置缺失时应用启动直接失败
 * （fail-closed，抛出 {@link IllegalStateException}），
 * 禁止静默降级为本地磁盘存储。
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
     * 创建 OSS 客户端 Bean。
     *
     * <p>无任何条件注解：OSS 是唯一的文件存储后端。
     * 配置不完整时在启动阶段直接抛异常，应用拒绝启动。
     */
    @Bean
    public OSS ossClient() {
        validateOssConfig(endpoint, accessKeyId, accessKeySecret, permanentBucketName);
        log.info("初始化 OSS 客户端: endpoint={}, bucket={}, permanentBucket={}, temporaryBucket={}",
                endpoint, bucketName, permanentBucketName, temporaryBucketName);
        return new OSSClientBuilder().build(endpoint, accessKeyId, accessKeySecret);
    }

    /**
     * Fail-closed 校验：OSS 必需配置缺失时抛出 {@link IllegalStateException}，
     * 错误信息中列出全部缺失项，便于运维直接补齐环境变量。
     *
     * @param endpoint            OSS endpoint（OSS_ENDPOINT）
     * @param accessKeyId         AccessKey ID（OSS_ACCESS_KEY_ID）
     * @param accessKeySecret     AccessKey Secret（OSS_ACCESS_KEY_SECRET）
     * @param permanentBucketName 永久存储 Bucket（OSS_PERMANENT_BUCKET）
     */
    public static void validateOssConfig(
            String endpoint, String accessKeyId, String accessKeySecret, String permanentBucketName) {
        List<String> missing = new ArrayList<>();
        if (!StringUtils.hasText(endpoint)) {
            missing.add("OSS_ENDPOINT");
        }
        if (!StringUtils.hasText(accessKeyId)) {
            missing.add("OSS_ACCESS_KEY_ID");
        }
        if (!StringUtils.hasText(accessKeySecret)) {
            missing.add("OSS_ACCESS_KEY_SECRET");
        }
        if (!StringUtils.hasText(permanentBucketName)) {
            missing.add("OSS_PERMANENT_BUCKET");
        }
        if (!missing.isEmpty()) {
            throw new IllegalStateException(
                    "OSS 存储配置缺失: " + String.join(", ", missing)
                            + "。文件存储仅支持阿里云 OSS，禁止降级为本地磁盘，请补齐环境变量后重启。");
        }
    }
}
