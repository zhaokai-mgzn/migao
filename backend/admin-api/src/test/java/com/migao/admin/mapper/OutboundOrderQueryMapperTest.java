// case_ids: WH-004
package com.migao.admin.mapper;

import org.apache.ibatis.annotations.Select;
import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Update;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 出库单列表读面（V196，issue #7750 / 用例 WH-004）。
 *
 * <p>这是**手写 SQL**：不走 MyBatis 的租户插件 ⇒ {@code tenant_id} 必须自己写，
 * 而且**单头与聚合子查询两侧都要写**（只写一侧 = 跨租户串单 / 数量合计把别人的算进来）。
 * 判据是静态文本（不需要 DB）：读注解原文，逐条断言。</p>
 */
@DisplayName("出库单列表读面：租户条件两侧都在 + 软删不计 + 别名 ⇄ DTO（V196）")
class OutboundOrderQueryMapperTest {

    private static String sql() throws Exception {
        Method m = OutboundOrderQueryMapper.class.getDeclaredMethod("selectOrderLines",
                Long.class, String.class, String.class, int.class);
        return String.join(" ", m.getAnnotation(Select.class).value());
    }

    @Test
    @DisplayName("🔴 tenant_id 在**外层**与**聚合子查询**两侧都写（手写 SQL 不过租户插件）")
    void tenantFilterOnBothSides() throws Exception {
        String sql = sql();
        assertThat(sql).contains("o.tenant_id = #{tenantId}");
        assertThat(sql).contains("WHERE tenant_id = #{tenantId} AND deleted = 0");
    }

    @Test
    @DisplayName("软删不计：单头与明细**各自**都有 deleted = 0（两处，一处都不能少）")
    void softDeletedRowsExcluded() throws Exception {
        String sql = sql();
        assertThat(sql).contains("o.deleted = 0");
        assertThat(sql).contains("FROM outbound_order_items");
        // 单头一处 + 聚合子查询一处；少任何一处都会把软删行算进列表/合计数
        assertThat(sql.split("deleted = 0", -1).length - 1).isEqualTo(2);
    }

    @Test
    @DisplayName("聚合别名 ⇄ DTO 字段名逐字（itemCount / totalQuantity，MyBatis 按别名映射）")
    void aggregateAliasesMatchDto() throws Exception {
        String sql = sql();
        assertThat(sql).contains("AS itemCount", "AS totalQuantity", "AS outboundNo", "AS bizCategory");
    }

    @Test
    @DisplayName("过滤面：关键词（单号/仓库/订单号）+ 业务类别；分页上限由参数给")
    void filtersAndLimit() throws Exception {
        String sql = sql();
        assertThat(sql).contains("o.outbound_no ILIKE", "o.warehouse ILIKE", "o.order_no ILIKE");
        assertThat(sql).contains("o.biz_category = #{bizCategory}");
        assertThat(sql).contains("LIMIT #{limit}");
    }

    @Test
    @DisplayName("🔴 类级守卫：每条手写 SQL 都标 @InterceptorIgnore(tenantLine=true)（自己写 tenant_id，禁止插件二次注入）")
    void everyHandWrittenSqlOptsOutOfTenantPlugin() {
        java.util.List<String> offenders = new java.util.ArrayList<>();
        for (Method m : OutboundOrderQueryMapper.class.getDeclaredMethods()) {
            if (m.isSynthetic()) {
                continue;
            }
            boolean handWritten = m.isAnnotationPresent(Select.class) || m.isAnnotationPresent(Insert.class)
                    || m.isAnnotationPresent(Update.class);
            if (!handWritten) {
                continue;
            }
            InterceptorIgnore ignore = m.getAnnotation(InterceptorIgnore.class);
            if (ignore == null || ignore.tenantLine() == null || !ignore.tenantLine().contains("true")) {
                offenders.add(m.getName());
            }
        }
        assertThat(offenders)
                .as("手写 SQL 未标 @InterceptorIgnore(tenantLine=true)：%s（全局租户插件会二次注入 tenant_id，"
                        + "在 INSERT … ON CONFLICT / 子查询上改出错误 SQL）", offenders)
                .isEmpty();
    }
}
