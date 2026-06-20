package com.migao.admin.mapper;

import com.migao.admin.entity.Notification;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * NotificationMapper 自定义 SQL 验证测试
 * 验证 @Select 注解中不包含手写 tenant_id（由 TenantLineInnerInterceptor 自动注入）
 */
@DisplayName("NotificationMapper SQL 验证")
class NotificationMapperTest {

    @Test
    @DisplayName("selectByRecipientId — SQL 不含手写 tenant_id")
    void selectByRecipientId_noManualTenantId() throws Exception {
        Method method = NotificationMapper.class.getMethod(
                "selectByRecipientId", String.class, String.class, String.class,
                com.baomidou.mybatisplus.core.metadata.IPage.class);

        Select select = method.getAnnotation(Select.class);
        assertThat(select).isNotNull();
        String sql = String.join(" ", select.value());

        // SQL 不应该包含手写的 tenant_id
        assertThat(sql).doesNotContain("tenant_id = #{tenantId}");
        assertThat(sql).doesNotContain("tenant_id =");

        // 参数中不应该有 tenantId
        boolean hasTenantIdParam = false;
        for (Parameter param : method.getParameters()) {
            Param p = param.getAnnotation(Param.class);
            if (p != null && "tenantId".equals(p.value())) {
                hasTenantIdParam = true;
            }
        }
        assertThat(hasTenantIdParam).as("should not have tenantId parameter").isFalse();
    }

    @Test
    @DisplayName("countUnread — SQL 不含手写 tenant_id")
    void countUnread_noManualTenantId() throws Exception {
        Method method = NotificationMapper.class.getMethod(
                "countUnread", String.class);

        Select select = method.getAnnotation(Select.class);
        assertThat(select).isNotNull();
        String sql = String.join(" ", select.value());

        assertThat(sql).doesNotContain("tenant_id = #{tenantId}");
        assertThat(sql).doesNotContain("tenant_id =");

        boolean hasTenantIdParam = false;
        for (Parameter param : method.getParameters()) {
            Param p = param.getAnnotation(Param.class);
            if (p != null && "tenantId".equals(p.value())) {
                hasTenantIdParam = true;
            }
        }
        assertThat(hasTenantIdParam).as("should not have tenantId parameter").isFalse();
    }

    @Test
    @DisplayName("继承 BaseMapper — 标准 CRUD 由拦截器覆盖")
    void extendsBaseMapper_standardCrudCoveredByInterceptor() {
        assertThat(BaseMapper.class.isAssignableFrom(NotificationMapper.class))
                .as("NotificationMapper should extend BaseMapper<Notification>")
                .isTrue();
    }
}
