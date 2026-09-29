package com.migao.admin.mapper;

// case_ids: UI-070

import com.migao.admin.entity.Order;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * OrderMapper 自定义 SQL 验证测试
 * 验证 @Select 注解中不包含手写 tenant_id（由 TenantLineInnerInterceptor 自动注入）
 */
@DisplayName("OrderMapper SQL 验证")
class OrderMapperTest {

    @Test
    @DisplayName("selectOrderTrend — SQL 不含手写 tenant_id")
    void selectOrderTrend_noManualTenantId() throws Exception {
        Method method = OrderMapper.class.getMethod(
                "selectOrderTrend", java.time.OffsetDateTime.class);

        Select select = method.getAnnotation(Select.class);
        assertThat(select).isNotNull();
        String sql = String.join(" ", select.value());

        // SQL 不应该包含手写的 tenant_id = #{tenantId}
        assertThat(sql).doesNotContain("tenant_id = #{tenantId}");
        // 也不应该有任何手写的 tenant_id =
        assertThat(sql).doesNotContainPattern("(?i)tenant_id\\s*=\\s*#\\{tenantId\\}");

        // 参数中不应该有 tenantId
        boolean hasTenantIdParam = false;
        for (Parameter param : method.getParameters()) {
            Param p = param.getAnnotation(Param.class);
            if (p != null && "tenantId".equals(p.value())) {
                hasTenantIdParam = true;
            }
        }
        assertThat(hasTenantIdParam).as("should not have tenantId parameter").isFalse();

        // 应该包含业务字段
        assertThat(sql).contains("deleted = 0");
        assertThat(sql).contains("created_at");
    }

    @Test
    @DisplayName("selectOrderStatusDistribution — SQL 不含手写 tenant_id")
    void selectOrderStatusDistribution_noManualTenantId() throws Exception {
        Method method = OrderMapper.class.getMethod("selectOrderStatusDistribution");

        Select select = method.getAnnotation(Select.class);
        assertThat(select).isNotNull();
        String sql = String.join(" ", select.value());

        assertThat(sql).doesNotContain("tenant_id = #{tenantId}");
        assertThat(sql).doesNotContainPattern("(?i)tenant_id\\s*=\\s*#\\{tenantId\\}");

        // 方法不应有参数
        assertThat(method.getParameterCount()).isEqualTo(0);

        assertThat(sql).contains("deleted = 0");
        assertThat(sql).contains("GROUP BY status");
    }

    @Test
    @DisplayName("继承 BaseMapper — 标准 CRUD 由拦截器覆盖")
    void extendsBaseMapper_standardCrudCoveredByInterceptor() {
        assertThat(BaseMapper.class.isAssignableFrom(OrderMapper.class))
                .as("OrderMapper should extend BaseMapper<Order>")
                .isTrue();
    }

    @Test
    @DisplayName("issue #5792：看板聚合含「待支付」计数 + 本月营收带上界（口径形态钉死）")
    void dashboardStatsAggregateShape() throws Exception {
        Method method = OrderMapper.class.getMethod("selectDashboardOrderStats",
                java.time.OffsetDateTime.class, java.time.OffsetDateTime.class,
                java.time.OffsetDateTime.class, java.time.OffsetDateTime.class,
                java.time.OffsetDateTime.class, java.time.OffsetDateTime.class);
        Select select = method.getAnnotation(Select.class);
        assertThat(select).as("方法必须带 @Select（判据空跑即红）").isNotNull();
        String sql = String.join(" ", select.value());

        // 待支付订单数：给「钱还没到」的风险面一个真计数
        // ⚠️ 不得用 /dashboard/pending-tasks 代替 —— 那是上限 5 条的**任务列表**，
        //    拿它当计数会把「≤5」误报成总数。
        assertThat(sql).contains("COUNT(*) FILTER (WHERE status = 'pending') AS pending_payment_orders");

        // 本月营收必须有**上界**（与上月窗口对称）—— 否则未来创建时间的单会虚增本月
        assertThat(sql).contains("created_at >= #{monthStart} AND created_at < #{nextMonthStart}");
        assertThat(sql).contains("created_at >= #{lastMonthStart} AND created_at < #{monthStart}");
    }
}
