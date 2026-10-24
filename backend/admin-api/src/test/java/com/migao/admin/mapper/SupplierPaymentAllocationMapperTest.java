// case_ids: SP-004
package com.migao.admin.mapper;

import com.migao.admin.entity.SupplierPaymentAllocation;
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
 * 冲抵明细 Mapper / 实体 ↔ 建库脚本（issue #7369 段 3-B）。
 *
 * <p>额外守一条**业务底线**：明细表必须同时带 `payment_id` 与 `inbound_order_id` ——
 * 少了任何一个，这张表就退化成「有钱流动但不知道对应哪个付款/哪张单」的孤行。</p>
 */
@DisplayName("冲抵明细 Mapper：实体字段 ⊆ 建库脚本列 + 两侧引用在场")
class SupplierPaymentAllocationMapperTest {

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
    @DisplayName("实体每个字段都有对应列")
    void everyEntityFieldHasAColumn() throws Exception {
        Set<String> columns = columnsOf("supplier_payment_allocations");
        assertThat(columns).isNotEmpty();
        Set<String> missing = java.util.Arrays.stream(SupplierPaymentAllocation.class.getDeclaredFields())
                .filter(f -> !Modifier.isStatic(f.getModifiers()) && !f.isSynthetic())
                .map(Field::getName).map(SupplierPaymentAllocationMapperTest::toColumn)
                .collect(Collectors.toCollection(LinkedHashSet::new));
        missing.removeAll(columns);
        assertThat(missing).as("实体字段缺列：%s", missing).isEmpty();
    }

    @Test
    @DisplayName("两侧引用与金额列在场（缺 payment_id / inbound_order_id = 孤行，账对不上）")
    void bothReferencesArePresent() throws Exception {
        assertThat(columnsOf("supplier_payment_allocations"))
                .contains("tenant_id", "payment_id", "inbound_order_id", "amount");
    }

    @Test
    @DisplayName("Mapper 只继承 BaseMapper")
    void mapperHasNoCustomSql() {
        long declared = java.util.Arrays.stream(SupplierPaymentAllocationMapper.class.getDeclaredMethods())
                .filter(m -> !m.isSynthetic()).count();
        assertThat(declared).isZero();
    }
}
