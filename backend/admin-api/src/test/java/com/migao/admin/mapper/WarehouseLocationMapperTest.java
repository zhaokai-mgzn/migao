// case_ids: WH-003
package com.migao.admin.mapper;

import com.migao.admin.entity.WarehouseLocation;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Select;
import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import org.apache.ibatis.annotations.Update;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 仓位 Mapper / 实体 ↔ 建库脚本（V196，issue #7750 / 用例 WH-003）。
 *
 * <p>守三条：① 实体字段 ⊆ 建库列；② 仓位号**租户内唯一**是数据库约束（部分唯一索引，软删不占位）；
 * ③ 「空闲」由 {@code finished_goods_stock} 的 {@code in_stock} 行判定 —— 仓位表**没有**占用标志列
 * （第二份真相：发货/撤销漏改一次就永久占位）。</p>
 */
@DisplayName("仓位 Mapper：字段 ⊆ 列 + 仓位号唯一是约束 + 空闲判定无第二份真相（V196）")
class WarehouseLocationMapperTest {

    private static final Path SCHEMA = Path.of("src/main/resources/db/init/schema.sql");

    private static String schemaSql() throws Exception {
        return Files.readString(SCHEMA);
    }

    private static Set<String> columnsOf(String table) throws Exception {
        Matcher m = Pattern.compile(
                "CREATE TABLE IF NOT EXISTS " + table + " \\(([\\s\\S]*?)\\n\\);").matcher(schemaSql());
        assertThat(m.find()).as("建库脚本里必须有 %s 表", table).isTrue();
        Set<String> cols = new LinkedHashSet<>();
        for (String line : m.group(1).split("\n")) {
            Matcher c = Pattern.compile("^\\s{4}([a-z_]+)\\s+[A-Z]").matcher(line);
            if (c.find()) {
                cols.add(c.group(1));
            }
        }
        return cols;
    }

    private static String sqlOf(String method, Class<?> annotation) throws Exception {
        for (Method m : WarehouseLocationMapper.class.getDeclaredMethods()) {
            if (!m.getName().equals(method)) {
                continue;
            }
            if (annotation.equals(Select.class)) {
                return String.join(" ", m.getAnnotation(Select.class).value());
            }
            if (annotation.equals(Insert.class)) {
                return String.join(" ", m.getAnnotation(Insert.class).value());
            }
        }
        throw new AssertionError("WarehouseLocationMapper 缺方法：" + method);
    }

    @Test
    @DisplayName("实体每个字段都有对应列（含 zone_code / bin_code / status）")
    void everyEntityFieldHasAColumn() throws Exception {
        Set<String> columns = columnsOf("warehouse_locations");
        assertThat(columns).isNotEmpty().contains("zone_code", "zone_name", "bin_code", "status");
        Set<String> missing = java.util.Arrays.stream(WarehouseLocation.class.getDeclaredFields())
                .filter(f -> !Modifier.isStatic(f.getModifiers()) && !f.isSynthetic())
                .map(Field::getName)
                .map(n -> n.replaceAll("([a-z0-9])([A-Z])", "$1_$2").toLowerCase())
                .collect(Collectors.toCollection(LinkedHashSet::new));
        missing.removeAll(columns);
        assertThat(missing).as("WarehouseLocation 实体字段缺列：%s", missing).isEmpty();
    }

    @Test
    @DisplayName("🔴 仓位号租户内唯一是**数据库约束**（部分唯一索引、软删不占位）")
    void binCodeIsUniquePerTenantInDatabase() throws Exception {
        String sql = schemaSql();
        assertThat(sql).contains("uk_warehouse_locations_bin");
        assertThat(sql).as("仓位号唯一必须是 (tenant_id, bin_code) + deleted = 0 的部分唯一索引")
                .contains("ON warehouse_locations (tenant_id, bin_code) WHERE deleted = 0");
    }

    @Test
    @DisplayName("🔴 空闲判定 = NOT EXISTS(in_stock 成品行)；仓位表**没有**占用标志列")
    void freeBinIsDerivedFromStockRows() throws Exception {
        String sql = sqlOf("selectFirstFreeBin", Select.class);
        assertThat(sql).contains("tenant_id = #{tenantId}", "deleted = 0", "status = 'active'");
        assertThat(sql).as("空闲必须由成品在库行派生（不是仓位表上的一个标志列）")
                .contains("NOT EXISTS", "finished_goods_stock", "s.status = 'in_stock'");
        assertThat(columnsOf("warehouse_locations"))
                .as("仓位表不得有 occupied/is_used 之类第二份真相列")
                .doesNotContain("occupied", "is_occupied", "is_used", "used");
    }

    @Test
    @DisplayName("🔴 占号是原子的：INSERT … ON CONFLICT DO NOTHING（冲突 ⇒ 0 行、事务不 aborted）")
    void claimBinIsAtomic() throws Exception {
        String sql = sqlOf("claimBin", Insert.class).toUpperCase();
        assertThat(sql).contains("ON CONFLICT DO NOTHING");
        assertThat(sql).contains("TENANT_ID", "BIN_CODE", "WAREHOUSE_ID");
    }


    @Test
    @DisplayName("🔴 类级守卫：每条手写 SQL 都标 @InterceptorIgnore(tenantLine=true)（自己写 tenant_id，禁止插件二次注入）")
    void everyHandWrittenSqlOptsOutOfTenantPlugin() {
        java.util.List<String> offenders = new java.util.ArrayList<>();
        for (Method m : WarehouseLocationMapper.class.getDeclaredMethods()) {
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

    @Test
    @DisplayName("手写 SQL 都显式写 tenant_id（不过租户插件 ⇒ 漏写即跨租户串位）")
    void handWrittenSqlFiltersTenant() throws Exception {
        assertThat(sqlOf("selectFirstFreeBin", Select.class)).contains("l.tenant_id = #{tenantId}");
        assertThat(sqlOf("countBinsInZone", Select.class)).contains("tenant_id = #{tenantId}");
        assertThat(sqlOf("selectByBinCode", Select.class)).contains("tenant_id = #{tenantId}");
    }

}
