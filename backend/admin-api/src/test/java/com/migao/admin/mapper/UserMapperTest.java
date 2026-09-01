package com.migao.admin.mapper;
// case_ids: API-010, DF-009

import com.migao.admin.entity.User;
import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * UserMapper 自定义 SQL 验证测试（审计 07 P1-2）
 * 验证跨租户手机号查询：返回全部活跃用户（禁止 LIMIT 1 静默落错租户）
 */
@DisplayName("UserMapper SQL 验证")
class UserMapperTest {

    @Test
    @DisplayName("selectActiveUsersByPhoneIgnoreTenant — 查询全部活跃用户且无 LIMIT 1")
    void selectActiveUsersByPhoneIgnoreTenant_noLimitOne() throws Exception {
        Method method = UserMapper.class.getMethod(
                "selectActiveUsersByPhoneIgnoreTenant", String.class);

        // 必须显式忽略租户拦截器（跨租户查询）
        InterceptorIgnore ignore = method.getAnnotation(InterceptorIgnore.class);
        assertThat(ignore).isNotNull();
        assertThat("true".equalsIgnoreCase(ignore.tenantLine())).isTrue();

        Select select = method.getAnnotation(Select.class);
        assertThat(select).isNotNull();
        String sql = String.join(" ", select.value());

        // 返回全部活跃用户，禁止 LIMIT 1（审计 07 P1-2：防登录落错租户）
        assertThat(sql).contains("WHERE phone = #{phone}");
        assertThat(sql).contains("status = 'active'");
        assertThat(sql).doesNotContain("LIMIT 1");
        assertThat(sql).contains("ORDER BY updated_at DESC");

        // 返回类型必须是 List（多租户歧义由业务层处理）
        assertThat(method.getReturnType()).isEqualTo(List.class);
    }

    @Test
    @DisplayName("旧方法 selectByPhoneIgnoreTenant 已移除（防止 LIMIT 1 回归）")
    void oldSelectByPhoneIgnoreTenant_removed() {
        boolean exists = false;
        for (Method m : UserMapper.class.getMethods()) {
            if ("selectByPhoneIgnoreTenant".equals(m.getName())) {
                exists = true;
            }
        }
        assertThat(exists).as("selectByPhoneIgnoreTenant 应已移除，统一走 selectActiveUsersByPhoneIgnoreTenant").isFalse();
    }
}
