// case_ids: WH-001
package com.migao.admin.mapper;

import com.migao.admin.entity.StockTransfer;
import com.migao.admin.entity.StockTransferItem;
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
 * 多仓/调拨 Mapper ↔ 建库脚本（issue #7373 段 1）。
 *
 * <p>额外守两条底线：① 调拨明细**必须**带 `batch_id`（缸号随行的载体，少了就按 SKU 调拨 ⇒ 缸号丢失）；
 * ② 「默认仓唯一」必须是**数据库约束**（部分唯一索引），不能只写在服务层。</p>
 */
@DisplayName("多仓 Mapper：字段 ⊆ 建库列 + 调拨按批次 + 默认仓唯一是约束")
class StockTransferMapperTest {

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
    @DisplayName("三张表的实体字段都有对应列")
    void entitiesMatchSchema() throws Exception {
        assertEntityCovered(Warehouse.class, "warehouses");
        assertEntityCovered(StockTransfer.class, "stock_transfers");
        assertEntityCovered(StockTransferItem.class, "stock_transfer_items");
    }

    @Test
    @DisplayName("🔴 调拨明细带 batch_id（缸号随行的载体；少了就按 SKU 调拨 ⇒ 缸号丢失）")
    void transferItemsAreBatchScoped() throws Exception {
        assertThat(columnsOf("stock_transfer_items")).contains("batch_id", "batch_no", "qty");
    }

    @Test
    @DisplayName("🔴 「同租户只能一个默认仓」写在数据库约束里（不只是服务层自觉）")
    void singleDefaultWarehouseIsAConstraint() throws Exception {
        assertThat(schemaSql()).contains("uk_warehouses_single_default");
        assertThat(schemaSql()).as("默认仓唯一必须是部分唯一索引（WHERE is_default）").contains("WHERE is_default");
    }

    @Test
    @DisplayName("调出 ≠ 调入 写在表约束里（同仓调拨无意义）")
    void sameWarehouseIsRejectedByConstraint() throws Exception {
        assertThat(schemaSql()).contains("ck_stock_transfers_not_same");
    }

    @Test
    @DisplayName("三个 Mapper 都只继承 BaseMapper（守恒与校验在服务层，不在 SQL 里各写一套）")
    void mappersHaveNoCustomSql() {
        for (Class<?> mapper : new Class<?>[]{WarehouseMapper.class, StockTransferMapper.class,
                StockTransferItemMapper.class}) {
            // 唯一的登记例外：`WarehouseMapper#claimWarehouse`（V196 / issue #7750）——
            // 成品仓「找或建」需要 `ON CONFLICT DO NOTHING` 的原子建档（先查后插会把事务打成
            // aborted，见该方法注释）。登记为**白名单**（不是放宽为零校验）：新增第二个自定义方法
            // 仍会红。
            var declared = java.util.Arrays.stream(mapper.getDeclaredMethods())
                    .filter(m -> !m.isSynthetic())
                    .map(java.lang.reflect.Method::getName)
                    .filter(n -> !(mapper.getSimpleName().equals("WarehouseMapper") && n.equals("claimWarehouse")))
                    .toList();
            assertThat(declared).as("%s 不应有自定义方法（WarehouseMapper#claimWarehouse 已在 #7750 登记）",
                    mapper.getSimpleName()).isEmpty();
        }
    }
}
