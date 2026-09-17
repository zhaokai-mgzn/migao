// case_ids: PG-001, PG-005, PG-008, PG-018

package com.migao.admin.mapper;

import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.time.OffsetDateTime;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProcessingOrderMapper 自定义 SQL 验证测试（issue #3340）
 * 验证：显式租户参数（tenant_id = #{tenantId}，fail-closed 双保险）、活跃/完成态过滤语义正确、
 * 生产完工的唯一写路径（markCompletedIfActive，issue #4117）不被改回「订单侧直写状态」。
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

    @Test
    @DisplayName("markCompletedIfActive — 只置**加工单** completed（活跃集 + 显式租户参数 + 首次完工时间不覆盖）")
    void markCompletedIfActive_sqlShape() throws Exception {
        Method method = ProcessingOrderMapper.class.getMethod(
                "markCompletedIfActive", String.class, Long.class, OffsetDateTime.class);
        Update update = method.getAnnotation(Update.class);
        assertThat(update).isNotNull();
        String sql = String.join(" ", update.value());
        // 写的是 processing_orders（**不是** orders：订单状态机是唯一真相源，生产侧不得直写订单状态）
        assertThat(sql).startsWith("UPDATE processing_orders");
        assertThat(sql).contains("SET status = 'completed'");
        assertThat(sql).contains("completed_at = COALESCE(completed_at, #{completedAt})");
        // 与 selectActiveByOrderId 同活跃集：并发取消的加工单不会被复活；已是 completed 时幂等
        assertThat(sql).contains("status IN ('generated','issued','in_processing','completed')");
        assertThat(sql).contains("tenant_id = #{tenantId}");
        assertThat(sql).contains("deleted = 0");
    }
}
