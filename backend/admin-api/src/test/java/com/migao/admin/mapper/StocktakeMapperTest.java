// case_ids: STK-001
package com.migao.admin.mapper;

import com.migao.admin.entity.Stocktake;
import com.migao.admin.entity.StocktakeItem;
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
 * 盘点 Mapper / 实体 ↔ 建库脚本（issue #7373 段 2）。
 *
 * <p>守三条：① 实体字段 ⊆ 建库列；② 账面快照列（`book_qty`）必须是 **NOT NULL**（缺它就失去复算依据）；
 * ③ 「同仓同时只能一个进行中的盘点」必须是**数据库约束**（部分唯一索引），不能只靠服务层查一遍。</p>
 */
@DisplayName("盘点 Mapper：字段 ⊆ 列 + 账面快照非空 + 同仓唯一进行中")
class StocktakeMapperTest {

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

    private static void assertEntityCovered(Class<?> entity, String table) throws Exception {
        Set<String> columns = columnsOf(table);
        assertThat(columns).isNotEmpty();
        Set<String> missing = java.util.Arrays.stream(entity.getDeclaredFields())
                .filter(f -> !Modifier.isStatic(f.getModifiers()) && !f.isSynthetic())
                .map(Field::getName)
                .map(n -> n.replaceAll("([a-z0-9])([A-Z])", "$1_$2").toLowerCase())
                .collect(Collectors.toCollection(LinkedHashSet::new));
        missing.removeAll(columns);
        assertThat(missing).as("%s 实体字段缺列：%s", table, missing).isEmpty();
    }

    @Test
    @DisplayName("两张表的实体字段都有对应列")
    void entitiesMatchSchema() throws Exception {
        assertEntityCovered(Stocktake.class, "stocktakes");
        assertEntityCovered(StocktakeItem.class, "stocktake_items");
    }

    @Test
    @DisplayName("🔴 账面快照必须 NOT NULL（缺它就失去「当时为什么判它少 3 米」的依据）")
    void bookQtyIsNotNull() throws Exception {
        String sql = schemaSql();
        assertThat(sql).contains("book_qty NUMERIC(12,1) NOT NULL");
    }

    @Test
    @DisplayName("🔴 「同仓同时只能一个进行中盘点」是数据库约束")
    void oneOpenStocktakePerWarehouseIsAConstraint() throws Exception {
        assertThat(schemaSql()).contains("uk_stocktakes_one_open_per_warehouse");
        assertThat(schemaSql()).as("必须是**部分**唯一索引（按 status 过滤）")
                .contains("WHERE status = 'counting'");
    }

    @Test
    @DisplayName("两个 Mapper 都只继承 BaseMapper")
    void mappersHaveNoCustomSql() {
        for (Class<?> mapper : new Class<?>[]{StocktakeMapper.class, StocktakeItemMapper.class}) {
            long declared = java.util.Arrays.stream(mapper.getDeclaredMethods())
                    .filter(m -> !m.isSynthetic()).count();
            assertThat(declared).as("%s 不应有自定义方法", mapper.getSimpleName()).isZero();
        }
    }
}
