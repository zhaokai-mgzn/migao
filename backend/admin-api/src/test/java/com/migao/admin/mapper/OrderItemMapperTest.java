// case_ids: DA-001, DA-006, DA-007

package com.migao.admin.mapper;

import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * OrderItemMapper 自定义 SQL 验证测试
 * #2886：验证新增聚合查询 SQL（含加工待发货 JOIN / 商品排行 GROUP BY / 上期销量 IN 批量），
 * 且不包含手写 tenant_id（由 TenantLineInnerInterceptor 自动注入）。
 */
@DisplayName("OrderItemMapper SQL 验证")
class OrderItemMapperTest {

    @Test
    @DisplayName("selectProcessingPendingOrdersCount — JOIN 一次统计，无手写 tenant_id")
    void selectProcessingPendingOrdersCount_noManualTenantId() throws Exception {
        Method method = OrderItemMapper.class.getMethod("selectProcessingPendingOrdersCount");
        Select select = method.getAnnotation(Select.class);
        assertThat(select).isNotNull();
        String sql = String.join(" ", select.value());

        assertThat(sql).doesNotContainPattern("(?i)tenant_id");
        assertThat(sql).contains("COUNT(DISTINCT oi.order_id)");
        assertThat(sql).contains("JOIN orders o ON oi.order_id = o.id");
        assertThat(sql).contains("o.status IN ('confirmed','producing')");
        assertThat(sql).contains("oi.processing_info IS NOT NULL");
        assertThat(sql).contains("oi.deleted = 0");
    }

    @Test
    @DisplayName("selectProductRanking — SQL 聚合 + TOP-N 排序，无手写 tenant_id")
    void selectProductRanking_sqlAggregation() throws Exception {
        Method method = OrderItemMapper.class.getMethod(
                "selectProductRanking", java.time.OffsetDateTime.class, int.class);
        Select select = method.getAnnotation(Select.class);
        assertThat(select).isNotNull();
        String sql = String.join(" ", select.value());

        assertThat(sql).doesNotContainPattern("(?i)tenant_id");
        // GROUP BY product_id 一次聚合 + LIMIT 截断 topN（JOIN orders 后列名带 oi. 前缀限定，防与 orders 同名列冲突）
        assertThat(sql).startsWith("SELECT oi.product_id");
        assertThat(sql).contains("FROM order_items oi");
        assertThat(sql).contains("GROUP BY oi.product_id");
        assertThat(sql).contains("ORDER BY qty DESC");
        assertThat(sql).contains("LIMIT #{limit}");
        assertThat(sql).contains("COALESCE(SUM(oi.quantity), 0)");
        // FLOOR(subtotal) 与旧逻辑逐行 longValue() 截断语义一致
        assertThat(sql).contains("SUM(FLOOR(oi.subtotal))");
        assertThat(sql).contains("MAX(oi.product_name)");
        // #2984：排行只统计有效订单（已付款/在履行中），排除 pending(未付款)/cancelled(已取消)
        // JOIN orders 过滤状态（租户条件仍由 TenantLineInnerInterceptor 注入，与线上一致）
        assertThat(sql).contains("JOIN orders o ON oi.order_id = o.id");
        assertThat(sql).contains("o.status IN ('confirmed','producing','shipped','completed')");
        assertThat(sql).contains("o.deleted = 0");
        assertThat(sql).doesNotContain("'pending'");
        assertThat(sql).doesNotContain("'cancelled'");
        // #2989：排除 product_id 为 NULL/空 的幽灵明细（生产实证 276 条脏数据被 GROUP BY 聚合成不存在商品行）
        assertThat(sql).contains("oi.product_id IS NOT NULL");
        assertThat(sql).contains("oi.product_id <> ''");
    }

    @Test
    @DisplayName("selectPrevPeriodQuantities — IN 批量一次，无手写 tenant_id")
    void selectPrevPeriodQuantities_inBatch() throws Exception {
        Method method = OrderItemMapper.class.getMethod(
                "selectPrevPeriodQuantities", java.util.List.class,
                java.time.OffsetDateTime.class, java.time.OffsetDateTime.class);
        Select select = method.getAnnotation(Select.class);
        assertThat(select).isNotNull();
        String sql = String.join(" ", select.value());

        assertThat(sql).doesNotContainPattern("(?i)tenant_id");
        assertThat(sql).contains("<script>");
        assertThat(sql).contains("foreach");
        assertThat(sql).contains("product_id IN");
        assertThat(sql).contains("GROUP BY oi.product_id");
        // #2984：上期销量与本期同口径 —— JOIN orders 过滤有效状态，排除 pending/cancelled
        assertThat(sql).contains("JOIN orders o ON oi.order_id = o.id");
        assertThat(sql).contains("o.status IN ('confirmed','producing','shipped','completed')");
        assertThat(sql).contains("o.deleted = 0");
        assertThat(sql).doesNotContain("'pending'");
        assertThat(sql).doesNotContain("'cancelled'");
        // #2989：上期口径与本期一致 —— 排除 product_id 为 NULL/空 的幽灵明细
        assertThat(sql).contains("oi.product_id IS NOT NULL");
        assertThat(sql).contains("oi.product_id <> ''");
    }

    @Test
    @DisplayName("selectPrevPeriodQuantities — 无 tenantId 参数（租户由拦截器注入）")
    void selectPrevPeriodQuantities_noTenantParam() throws Exception {
        Method method = OrderItemMapper.class.getMethod(
                "selectPrevPeriodQuantities", java.util.List.class,
                java.time.OffsetDateTime.class, java.time.OffsetDateTime.class);
        for (Parameter param : method.getParameters()) {
            Param p = param.getAnnotation(Param.class);
            if (p != null) {
                assertThat(p.value()).isNotEqualTo("tenantId");
            }
        }
    }
}