package com.migao.admin.config;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ConfigTest {

    @Test
    void smsConfig_shouldHaveProperties() {
        SmsConfig cfg = new SmsConfig();
        cfg.setAccessKeyId("test-key");
        cfg.setSignName("test-sign");
        assertEquals("test-key", cfg.getAccessKeyId());
        assertEquals("test-sign", cfg.getSignName());
    }

    @Test
    void ossConfig_shouldHaveProperties() {
        OssConfig cfg = new OssConfig();
        cfg.setEndpoint("oss-cn-hangzhou.aliyuncs.com");
        cfg.setBucketName("test-bucket");
        assertEquals("oss-cn-hangzhou.aliyuncs.com", cfg.getEndpoint());
        assertEquals("test-bucket", cfg.getBucketName());
    }
}
