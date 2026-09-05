// case_ids: DA-001, DA-004

package com.migao.admin.mapper;

import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * SessionMapper 自定义 SQL 验证测试
 * #2886：验证新增的看板会话聚合查询（活跃会话/AI 会话一次 FILTER 聚合），
 * 且不包含手写 tenant_id（由 TenantLineInnerInterceptor 自动注入）。
 */
@DisplayName("SessionMapper SQL 验证")
class SessionMapperTest {

    @Test
    @DisplayName("selectDashboardSessionStats — SQL 一次 FILTER 聚合，无手写 tenant_id")
    void selectDashboardSessionStats_noManualTenantId() throws Exception {
        Method method = SessionMapper.class.getMethod(
                "selectDashboardSessionStats", java.time.OffsetDateTime.class);
        Select select = method.getAnnotation(Select.class);
        assertThat(select).isNotNull();
        String sql = String.join(" ", select.value());

        assertThat(sql).doesNotContainPattern("(?i)tenant_id");
        // 活跃/AI 会话两个指标在一条 SQL 内 FILTER 聚合（替代两次串行 count）
        assertThat(sql).contains("FILTER (WHERE updated_at >= #{activeThreshold})");
        assertThat(sql).contains("ai_enabled = true");
        assertThat(sql).contains("deleted = 0");
    }

    @Test
    @DisplayName("selectDashboardSessionStats — 无 tenantId 参数（租户由拦截器注入）")
    void selectDashboardSessionStats_noTenantParam() throws Exception {
        Method method = SessionMapper.class.getMethod(
                "selectDashboardSessionStats", java.time.OffsetDateTime.class);
        for (Parameter param : method.getParameters()) {
            Param p = param.getAnnotation(Param.class);
            if (p != null) {
                assertThat(p.value()).isNotEqualTo("tenantId");
            }
        }
    }
}