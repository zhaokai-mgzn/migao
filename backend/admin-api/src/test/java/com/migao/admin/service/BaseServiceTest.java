package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;

/**
 * Service 测试基类 — 提供 TenantContext 公共初始化。
 */
public abstract class BaseServiceTest {

    protected static final Long TEST_TENANT_ID = 1L;

    @BeforeEach
    void baseSetUp() {
        TenantContext.setTenantId(TEST_TENANT_ID);
    }

    @AfterEach
    void baseTearDown() {
        TenantContext.clear();
    }
}
