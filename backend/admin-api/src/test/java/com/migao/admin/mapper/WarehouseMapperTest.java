// case_ids: WH-001
package com.migao.admin.mapper;

import com.migao.admin.entity.Warehouse;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
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
 * 仓库 Mapper / 实体 ↔ 建库脚本（issue #7373 段 1）。
 *
 * <p>守三条：① 实体字段 ⊆ 建库列；② 类型是封闭集合（`store` / `processing`，与表 CHECK 一致）；
 * ③ **「同租户只能一个默认仓」必须是数据库约束**（部分唯一索引）—— 只写在服务层的话，
 * 并发建两个默认仓这类事一定会发生，而事后没人能判断哪个「才是默认」。</p>
 */
@DisplayName("仓库 Mapper：字段 ⊆ 列 + 类型封闭 + 默认仓唯一是约束")
class WarehouseMapperTest {

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

    @Test
    @DisplayName("实体每个字段都有对应列")
    void everyEntityFieldHasAColumn() throws Exception {
        Set<String> columns = columnsOf("warehouses");
        assertThat(columns).isNotEmpty();
        Set<String> missing = java.util.Arrays.stream(Warehouse.class.getDeclaredFields())
                .filter(f -> !Modifier.isStatic(f.getModifiers()) && !f.isSynthetic())
                .map(Field::getName)
                .map(n -> n.replaceAll("([a-z0-9])([A-Z])", "$1_$2").toLowerCase())
                .collect(Collectors.toCollection(LinkedHashSet::new));
        missing.removeAll(columns);
        assertThat(missing).as("Warehouse 实体字段缺列：%s", missing).isEmpty();
    }

    @Test
    @DisplayName("关键列在场（编码 / 类型 / 默认仓 / 状态）")
    void keyColumnsPresent() throws Exception {
        assertThat(columnsOf("warehouses"))
                .contains("code", "name", "warehouse_type", "is_default", "status");
    }

    @Test
    @DisplayName("类型是封闭集合：实体常量与表 CHECK 逐字一致")
    void warehouseTypesMatchCheckConstraint() throws Exception {
        String sql = schemaSql();
        assertThat(sql).contains("'" + Warehouse.TYPE_STORE + "'", "'" + Warehouse.TYPE_PROCESSING + "'");
    }

    @Test
    @DisplayName("🔴 「同租户只能一个默认仓」写在数据库约束里（并发下也只有一个）")
    void singleDefaultIsAConstraint() throws Exception {
        String sql = schemaSql();
        assertThat(sql).contains("uk_warehouses_single_default");
        assertThat(sql).as("默认仓唯一必须是**部分**唯一索引").contains("WHERE is_default");
    }

    @Test
    @DisplayName("Mapper 只继承 BaseMapper（唯一性交给索引，不在 SQL 里各写一套）")
    void mapperHasNoCustomSql() {
        long declared = java.util.Arrays.stream(WarehouseMapper.class.getDeclaredMethods())
                .filter(m -> !m.isSynthetic()).count();
        assertThat(declared).isZero();
    }
}
