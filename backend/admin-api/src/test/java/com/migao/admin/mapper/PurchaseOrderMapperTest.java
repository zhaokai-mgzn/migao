// case_ids: SP-005
package com.migao.admin.mapper;

import com.migao.admin.entity.PurchaseOrder;
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
 * 采购单 Mapper：实体字段 ⊆ 建库脚本列（issue #7369 段 4）。
 *
 * <p>同其余 Mapper 判据的理由：Mapper 在单测里几乎总被 mock ⇒ 列名/字段对不上要等生产上第一次真跑才炸。
 * 守：实体字段 ⊆ 建库脚本列、租户列在场。</p>
 *
 * <p>红证方向：给实体加一个脚本里没有的字段 ⇒ 本类红。</p>
 */
@DisplayName("采购单 Mapper：实体字段 ⊆ 建库脚本列")
class PurchaseOrderMapperTest {

    private static final Path SCHEMA = Path.of("src/main/resources/db/init/schema.sql");

    private static Set<String> columnsOf(String table) throws Exception {
        String sql = Files.readString(SCHEMA);
        Matcher m = Pattern.compile(
                "CREATE TABLE IF NOT EXISTS " + table + " \\(([\\s\\S]*?)\\n\\);").matcher(sql);
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

    private static String toColumn(String field) {
        return field.replaceAll("([a-z0-9])([A-Z])", "$1_$2").toLowerCase();
    }

    @Test
    @DisplayName("采购单 Mapper：实体字段 ⊆ 建库脚本列")
    void everyEntityFieldHasAColumn() throws Exception {
        Set<String> columns = columnsOf("purchase_orders");
        assertThat(columns).isNotEmpty();
        Set<String> missing = java.util.Arrays.stream(PurchaseOrder.class.getDeclaredFields())
                .filter(f -> !Modifier.isStatic(f.getModifiers()) && !f.isSynthetic())
                .map(Field::getName).map(PurchaseOrderMapperTest::toColumn)
                .collect(Collectors.toCollection(LinkedHashSet::new));
        missing.removeAll(columns);
        assertThat(missing).as("实体字段缺列：%s（列面 = %s）", missing, columns).isEmpty();
    }

    @Test
    @DisplayName("采购单 Mapper：实体字段 ⊆ 建库脚本列：关键列在场")
    void keyColumnsArePresent() throws Exception {
        assertThat(columnsOf("purchase_orders")).contains("tenant_id", "po_no", "status", "total_amount", "supplier_id");
    }

    @Test
    @DisplayName("采购单 Mapper：实体字段 ⊆ 建库脚本列：只继承 BaseMapper")
    void mapperHasNoCustomSql() {
        long declared = java.util.Arrays.stream(PurchaseOrderMapper.class.getDeclaredMethods())
                .filter(m -> !m.isSynthetic()).count();
        assertThat(declared).isZero();
    }
}
