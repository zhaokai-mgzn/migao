// case_ids: SP-004
package com.migao.admin.mapper;

import com.migao.admin.entity.SupplierPayment;
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
 * 付款单 Mapper / 实体 ↔ 建库脚本（issue #7369 段 3-B）。
 *
 * <p>同 {@code SupplierMapperTest} 的理由：Mapper 在单测里几乎总被 mock ⇒ 列名/字段对不上要等
 * **生产上第一次真跑** 才炸（那是 500）。守两条：实体字段 ⊆ 脚本列、租户列在场。</p>
 *
 * <p>红证方向：把 {@code SupplierPayment} 的 {@code referenceNo} 改名而脚本未加列 ⇒ 本类红。</p>
 */
@DisplayName("付款单 Mapper：实体字段 ⊆ 建库脚本列 + 租户列在场")
class SupplierPaymentMapperTest {

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
    @DisplayName("实体每个字段都有对应列（加字段不加列 ⇒ 每次 SQL 都炸）")
    void everyEntityFieldHasAColumn() throws Exception {
        Set<String> columns = columnsOf("supplier_payments");
        assertThat(columns).isNotEmpty();
        Set<String> missing = java.util.Arrays.stream(SupplierPayment.class.getDeclaredFields())
                .filter(f -> !Modifier.isStatic(f.getModifiers()) && !f.isSynthetic())
                .map(Field::getName).map(SupplierPaymentMapperTest::toColumn)
                .collect(Collectors.toCollection(LinkedHashSet::new));
        missing.removeAll(columns);
        assertThat(missing).as("实体字段缺列：%s（列面 = %s）", missing, columns).isEmpty();
    }

    @Test
    @DisplayName("租户列在场 + 金额/状态/方式三列在场（涉钱面的最小列契约）")
    void moneyColumnsArePresent() throws Exception {
        assertThat(columnsOf("supplier_payments"))
                .contains("tenant_id", "amount", "status", "method", "supplier_id");
    }

    @Test
    @DisplayName("Mapper 只继承 BaseMapper（手写 SQL 不走租户插件 ⇒ 必须另补判据）")
    void mapperHasNoCustomSql() {
        long declared = java.util.Arrays.stream(SupplierPaymentMapper.class.getDeclaredMethods())
                .filter(m -> !m.isSynthetic()).count();
        assertThat(declared).isZero();
    }
}
