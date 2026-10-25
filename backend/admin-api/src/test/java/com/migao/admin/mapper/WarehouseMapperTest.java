// case_ids: WH-001
package com.migao.admin.mapper;

import com.migao.admin.entity.Warehouse;
import org.apache.ibatis.annotations.Insert;
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
    @DisplayName("类型是封闭集合：实体常量与表 CHECK 逐字一致（V196 起含原料仓 / 成品仓）")
    void warehouseTypesMatchCheckConstraint() throws Exception {
        String sql = schemaSql();
        assertThat(sql).contains("'" + Warehouse.TYPE_STORE + "'", "'" + Warehouse.TYPE_PROCESSING + "'",
                "'" + Warehouse.TYPE_MATERIAL + "'", "'" + Warehouse.TYPE_FINISHED + "'");
        assertThat(Warehouse.TYPES).containsExactly(Warehouse.TYPE_STORE, Warehouse.TYPE_PROCESSING,
                Warehouse.TYPE_MATERIAL, Warehouse.TYPE_FINISHED);
    }

    @Test
    @DisplayName("🔴 「同租户只能一个默认仓」写在数据库约束里（并发下也只有一个）")
    void singleDefaultIsAConstraint() throws Exception {
        String sql = schemaSql();
        assertThat(sql).contains("uk_warehouses_single_default");
        assertThat(sql).as("默认仓唯一必须是**部分**唯一索引").contains("WHERE is_default");
    }

    @Test
    @DisplayName("Mapper 只有一条手写 SQL（原子占号），唯一性仍交给索引：必须是 ON CONFLICT DO NOTHING")
    void mapperOnlyDeclaresAtomicClaim() {
        java.lang.reflect.Method[] methods = java.util.Arrays.stream(WarehouseMapper.class.getDeclaredMethods())
                .filter(m -> !m.isSynthetic()).toArray(java.lang.reflect.Method[]::new);
        // 唯一性口径仍是「索引说了算」：手写 SQL 只允许一条，且必须是「冲突 ⇒ 0 行」的形态，
        // 不许写成「先 exists 判重、再 insert」（那正是并发下建出两个仓的那条路）
        assertThat(methods).hasSize(1);
        Insert insert = methods[0].getAnnotation(Insert.class);
        assertThat(insert).as("占号必须走 INSERT ... ON CONFLICT DO NOTHING").isNotNull();
        assertThat(String.join(" ", insert.value()).toUpperCase()).contains("ON CONFLICT DO NOTHING");
    }
}
