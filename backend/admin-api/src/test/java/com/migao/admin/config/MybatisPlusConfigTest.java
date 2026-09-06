package com.migao.admin.config;
// case_ids: ST-004, ST-005

import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * MybatisPlusConfig 多租户插件表忽略规则测试（issue #2965/#2972 回归防护）
 *
 * 背景：通知模板/规则是「系统内置(tenant_id=0) + 租户自定义」混合表，
 * 查询条件 (tenant_id=当前租户 OR tenant_id=0) 由业务层显式过滤；
 * 若租户插件自动追加 tenant_id=当前租户，系统内置种子会被静默过滤
 * （生产实证：种子在库但 API total=0、事件触发匹配不到模板）。
 * 本测试锁定这两张表必须忽略租户插件，notifications（纯租户数据）必须保留过滤。
 */
@DisplayName("MybatisPlusConfig 租户插件表忽略规则测试")
class MybatisPlusConfigTest {

    private final MybatisPlusConfig config = new MybatisPlusConfig();

    private boolean isIgnored(String table) {
        TenantLineHandler handler = config.tenantLineInnerInterceptor().getTenantLineHandler();
        return handler.ignoreTable(table);
    }

    @Test
    @DisplayName("notification_templates / notification_rules 忽略租户插件（支持系统级+租户级混合查询）")
    void notificationConfigTables_ignoredByTenantPlugin() {
        assertThat(isIgnored("notification_templates")).as("模板表必须忽略租户插件，否则系统种子被过滤").isTrue();
        assertThat(isIgnored("notification_rules")).as("规则表必须忽略租户插件，否则系统规则被过滤").isTrue();
    }

    @Test
    @DisplayName("notifications 保留租户过滤（纯租户数据，多租户隔离不放松）")
    void notifications_keepsTenantFilter() {
        assertThat(isIgnored("notifications")).isFalse();
    }

    @Test
    @DisplayName("既有的租户基础表忽略规则不回退")
    void existingIgnoreRules_unchanged() {
        assertThat(isIgnored("tenants")).isTrue();
        assertThat(isIgnored("platform_admins")).isTrue();
        assertThat(isIgnored("users")).isFalse();
    }
}