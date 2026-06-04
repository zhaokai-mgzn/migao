package com.aikf.admin.config;

import com.aliyun.oss.OSS;
import com.aliyun.oss.OSSClientBuilder;
import lombok.Data;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

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
     * 创建 OSS 客户端 Bean
     * 仅在 aliyun.oss.endpoint 环境变量存在时才创建
     */
    @Bean
    @ConditionalOnProperty(name = "aliyun.oss.endpoint")
    public OSS ossClient() {
        log.info("初始化 OSS 客户端: endpoint={}, bucket={}, permanentBucket={}, temporaryBucket={}",
                endpoint, bucketName, permanentBucketName, temporaryBucketName);
        return new OSSClientBuilder().build(endpoint, accessKeyId, accessKeySecret);
    }
}
