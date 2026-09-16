// case_ids: PG-001, PG-005, PG-008

package com.migao.admin.mapper;

import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProcessingOrderMapper 自定义 SQL 验证测试（issue #3340）
 * 验证：显式租户参数（tenant_id = #{tenantId}，fail-closed 双保险）、活跃/完成态过滤语义正确。
 */
@DisplayName("ProcessingOrderMapper SQL 验证")
class ProcessingOrderMapperTest {

    @Test
    @DisplayName("selectActiveByOrderId — 活跃态过滤 + 显式租户参数")
    void selectActiveByOrderId_sqlShape() throws Exception {
        Method method = ProcessingOrderMapper.class.getMethod("selectActiveByOrderId", String.class, Long.class);
        Select select = method.getAnnotation(Select.class);
        assertThat(select).isNotNull();
        String sql = String.join(" ", select.value());
        assertThat(sql).contains("tenant_id = #{tenantId}");
        assertThat(sql).contains("status IN ('generated','issued','in_processing','completed')");
        assertThat(sql).contains("deleted = 0");
        assertThat(sql).contains("LIMIT 1");
    }

    @Test
    @DisplayName("countCompletedByOrderId — 仅统计 completed")
    void countCompletedByOrderId_sqlShape() throws Exception {
        Method method = ProcessingOrderMapper.class.getMethod("countCompletedByOrderId", String.class, Long.class);
        Select select = method.getAnnotation(Select.class);
        assertThat(select).isNotNull();
        String sql = String.join(" ", select.value());
        assertThat(sql).contains("tenant_id = #{tenantId}");
        assertThat(sql).contains("status = 'completed'");
        assertThat(sql).contains("deleted = 0");
    }

    @Test
    @DisplayName("selectByKeyword — 加工单号/订单号/UUID 三路解析")
    void selectByKeyword_sqlShape() throws Exception {
        Method method = ProcessingOrderMapper.class.getMethod("selectByKeyword", String.class, Long.class);
        Select select = method.getAnnotation(Select.class);
        assertThat(select).isNotNull();
        String sql = String.join(" ", select.value());
        assertThat(sql).contains("tenant_id = #{tenantId}");
        assertThat(sql).contains("LEFT JOIN orders o ON po.order_id = o.id");
        assertThat(sql).contains("po.processing_order_no");
        assertThat(sql).contains("o.order_no");
        assertThat(sql).contains("LIMIT 10");
    }
}
