package com.migao.admin.mapper;

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
}
