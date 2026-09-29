package com.migao.admin.mapper;

// case_ids: UI-068

import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * `PermissionMapper.tenantHasPermissionCode` 的**契约测试**（issue #5792）。
 *
 * <p>为什么要它（而不是只靠集成测）：这条 SQL 是「本租户是否启用智能客服」的唯一数据来源，
 * 且它是**跨角色的集合判定** —— 一旦租户过滤被写漏或写丢，就会变成**跨租户泄漏**
 * （A 租户的岗位配置决定 B 租户看不看得到某指标）。所以此处把**查询形态**钉死：
 * 两张表各自带 `tenant_id`、软删过滤在位、权限码是**参数化**而不是拼串。</p>
 *
 * <p>⚠️ 边界（如实登记）：本测试**不连库**，判的是「SQL 形态」而不是「SQL 跑出来的结果」；
 * 真正的租户隔离由 `TenantLineInnerInterceptor` + 真库用例覆盖。</p>
 */
@DisplayName("PermissionMapper 租户级持码查询（跨租户泄漏守卫）")
class PermissionMapperTest {

    private static String sqlOf() throws Exception {
        Method m = PermissionMapper.class.getMethod("tenantHasPermissionCode", Long.class, String.class);
        Select select = m.getAnnotation(Select.class);
        assertThat(select).as("方法必须带 @Select（判据空跑即红）").isNotNull();
        return String.join(" ", select.value());
    }

    @Test
    @DisplayName("🔴 两张表各自带 tenant_id 过滤（漏一边即跨租户泄漏）")
    void tenantScopedOnBothTables() throws Exception {
        String sql = sqlOf();
        assertThat(sql).contains("p.tenant_id = #{tenantId}");
        assertThat(sql).contains("rp.tenant_id = #{tenantId}");
    }

    @Test
    @DisplayName("软删过滤在位（否则已撤销的岗位授权会让指标误开）")
    void softDeleteFiltered() throws Exception {
        assertThat(sqlOf()).contains("rp.deleted = 0");
    }

    @Test
    @DisplayName("权限码是**参数化**入参（不是拼串）")
    void codeIsParameterized() throws Exception {
        String sql = sqlOf();
        assertThat(sql).contains("p.code = #{code}");
        Method m = PermissionMapper.class.getMethod("tenantHasPermissionCode", Long.class, String.class);
        assertThat(m.getParameters()[1].getAnnotation(Param.class).value()).isEqualTo("code");
    }
}
