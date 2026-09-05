// case_ids: DA-004

package com.migao.admin.mapper;

import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * SessionMessageMapper 自定义 SQL 验证测试
 * #2886：验证批量取会话最后一条消息的 DISTINCT ON 查询（替代每会话一次 LIMIT 1 的 N+1），
 * 且不包含手写 tenant_id（由 TenantLineInnerInterceptor 自动注入）。
 */
@DisplayName("SessionMessageMapper SQL 验证")
class SessionMessageMapperTest {

    @Test
    @DisplayName("selectLastMessageBySessionIds — DISTINCT ON 批量一次，无手写 tenant_id")
    void selectLastMessageBySessionIds_distinctOnBatch() throws Exception {
        Method method = SessionMessageMapper.class.getMethod(
                "selectLastMessageBySessionIds", java.util.List.class);
        Select select = method.getAnnotation(Select.class);
        assertThat(select).isNotNull();
        String sql = String.join(" ", select.value());

        assertThat(sql).doesNotContainPattern("(?i)tenant_id");
        // DISTINCT ON 按会话取首行（created_at DESC 后即最后一条）
        assertThat(sql).contains("DISTINCT ON (session_id)");
        assertThat(sql).contains("ORDER BY session_id, created_at DESC");
        assertThat(sql).contains("foreach");
        assertThat(sql).contains("session_id IN");
        assertThat(sql).contains("deleted = 0");
    }

    @Test
    @DisplayName("selectLastMessageBySessionIds — 无 tenantId 参数（租户由拦截器注入）")
    void selectLastMessageBySessionIds_noTenantParam() throws Exception {
        Method method = SessionMessageMapper.class.getMethod(
                "selectLastMessageBySessionIds", java.util.List.class);
        for (Parameter param : method.getParameters()) {
            Param p = param.getAnnotation(Param.class);
            if (p != null) {
                assertThat(p.value()).isNotEqualTo("tenantId");
            }
        }
    }
}