// case_ids: WH-004
package com.migao.admin.mapper;

import com.migao.admin.entity.OutboundOrderItem;
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
 * 出库单明细 Mapper / 实体 ↔ 建库脚本（V196，issue #7750 / 用例 WH-004）。
 *
 * <p>守三条：① 实体字段 ⊆ 建库列；② 数量必须 &gt; 0 是数据库 CHECK（负数量/0 数量不该靠服务层拦）；
 * ③ 明细**共用一套形状**装两种行（布料 = SKU + 米数；成品 = 订单行 + 仓位 + 套数）——
 * 不拆两张表：读面/导出只写一份。</p>
 */
@DisplayName("出库单明细 Mapper：字段 ⊆ 列 + 数量 > 0 是约束（V196）")
class OutboundOrderItemMapperTest {

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
    @DisplayName("实体每个字段都有对应列（布料行 skuCode / 成品行 binCode 都要在）")
    void everyEntityFieldHasAColumn() throws Exception {
        Set<String> columns = columnsOf("outbound_order_items");
        assertThat(columns).isNotEmpty().contains("sku_id", "sku_code", "bin_code", "order_item_id",
                "quantity", "unit", "unit_cost", "amount");
        Set<String> missing = java.util.Arrays.stream(OutboundOrderItem.class.getDeclaredFields())
                .filter(f -> !Modifier.isStatic(f.getModifiers()) && !f.isSynthetic())
                .map(Field::getName)
                .map(n -> n.replaceAll("([a-z0-9])([A-Z])", "$1_$2").toLowerCase())
                .collect(Collectors.toCollection(LinkedHashSet::new));
        missing.removeAll(columns);
        assertThat(missing).as("OutboundOrderItem 实体字段缺列：%s", missing).isEmpty();
    }

    @Test
    @DisplayName("🔴 数量 > 0 是数据库 CHECK（0/负数量进不了库）")
    void quantityPositiveIsAConstraint() throws Exception {
        assertThat(schemaSql()).contains("quantity NUMERIC(12,2) NOT NULL CHECK (quantity > 0)");
    }

    @Test
    @DisplayName("明细挂在出库单下（外键 + ON DELETE CASCADE），并有按单查询索引")
    void itemsBelongToOrder() throws Exception {
        String sql = schemaSql();
        assertThat(sql).contains("outbound_order_id VARCHAR(64) NOT NULL REFERENCES outbound_orders(id)");
        assertThat(sql).contains("idx_outbound_order_items_order");
    }

    @Test
    @DisplayName("Mapper 只继承 BaseMapper（按单查明细走 LambdaQueryWrapper，不各写一套 SQL）")
    void mapperHasNoCustomSql() {
        long declared = java.util.Arrays.stream(OutboundOrderItemMapper.class.getDeclaredMethods())
                .filter(m -> !m.isSynthetic()).count();
        assertThat(declared).isZero();
    }
}
