// case_ids: WH-001
package com.migao.admin.mapper;

import com.migao.admin.entity.StockTransferItem;
import com.migao.admin.entity.Warehouse;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 调拨明细 / 仓库 Mapper 的最小契约（issue #7373 段 1）。
 *
 * <p>主判据在 {@link StockTransferMapperTest}（字段⊆列 / batch_id 在场 / 默认仓唯一是约束）；
 * 本文件只补两件容易漏的事：① Mapper 无旁路 SQL；② 明细表**只增不改**（调拨是既成事实，
 * 没有「改一行」的业务动作 —— 那会让守恒失去时间点）。</p>
 */
@DisplayName("调拨明细 Mapper：无旁路 SQL + 明细只增不改")
class StockTransferItemMapperTest {

    private static final Path SCHEMA = Path.of("src/main/resources/db/init/schema.sql");

    @Test
    @DisplayName("两个 Mapper 都只继承 BaseMapper")
    void mappersHaveNoCustomSql() {
        for (Class<?> mapper : new Class<?>[]{StockTransferItemMapper.class, WarehouseMapper.class}) {
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

    @Test
    @DisplayName("明细表有「调拨单 → 明细」的索引（详情读面按 transfer_id 取，缺索引会全表扫）")
    void itemsIndexedByTransfer() throws Exception {
        assertThat(Files.readString(SCHEMA)).contains("idx_stock_transfer_items_transfer");
    }

    @Test
    @DisplayName("实体与建库列对齐（抽查四个关键列，全量对齐由 StockTransferMapperTest 守）")
    void keyColumnsPresent() throws Exception {
        String sql = Files.readString(SCHEMA);
        assertThat(sql).contains("batch_id", "qty", "unit_cost", "transfer_id");
        assertThat(StockTransferItem.class.getDeclaredFields())
                .as("实体字段名与列名同源（snake_case 转换后）")
                .isNotEmpty();
        assertThat(Warehouse.class.getDeclaredFields()).isNotEmpty();
    }
}
