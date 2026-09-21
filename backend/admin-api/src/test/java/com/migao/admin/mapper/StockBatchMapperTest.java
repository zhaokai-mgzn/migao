package com.migao.admin.mapper;

// case_ids: PR-039

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.StockBatch;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * StockBatchMapper 契约测试（批次台账，V111 / issue #5034）。
 *
 * <p>批次号是**印在卷标上的追溯标识**（AHFA 要求卷标带 Lot number，见
 * {@code docs/curtain-selling-method-industry-research.md} §1/S10）⇒ 它的唯一索引与
 * 「租户内唯一」口径必须有可执行判据：漏了索引，重号不会被任何检查发现。</p>
 */
@DisplayName("StockBatchMapper 表/字段契约（批次台账）")
class StockBatchMapperTest {

    private static final String V111 =
            "backend/admin-api/src/main/resources/db/migration/V111__create_inbound_orders_and_batches.sql";

    @Test
    @DisplayName("实体映射 stock_batches 表")
    void entityMapsToTable() {
        TableName tableName = StockBatch.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("stock_batches");
    }

    @Test
    @DisplayName("实体字段与 V111 列收敛（批次号/缸号/来源单/收货日期）")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(StockBatch.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "tenantId", "batchNo", "productId", "skuId", "skuCode", "inboundOrderId",
                "inboundItemId", "inboundNo", "quantity", "unitCost", "amount", "dyeLot",
                "rollLengthM", "supplier", "warehouse", "receivedDate", "remark", "createdAt", "deleted");
        ProductionMigrationSql.assertTableColumnsIn(V111, "stock_batches",
                "id", "tenant_id", "batch_no", "product_id", "sku_id", "sku_code",
                "inbound_order_id", "inbound_item_id", "inbound_no", "quantity", "unit_cost",
                "amount", "dye_lot", "roll_length_m", "supplier", "warehouse", "received_date",
                "remark", "created_at", "deleted");
    }

    @Test
    @DisplayName("批次号**租户内唯一**索引必须在（漏了它 ⇒ 重号不会被任何检查发现）")
    void batchNoHasTenantScopedUniqueIndex() {
        String sql = ProductionMigrationSql.read(V111);
        assertThat(sql).contains("CREATE UNIQUE INDEX IF NOT EXISTS uk_stock_batches_no");
        // 唯一键是 (tenant_id, batch_no) 而非全局 batch_no —— 多租户各自的序号空间独立
        assertThat(sql).contains("ON stock_batches (tenant_id, batch_no)");
    }

    @Test
    @DisplayName("id 为数据库自增；软删标 @TableLogic；Mapper 继承 BaseMapper")
    void idSoftDeleteAndBaseMapper() throws Exception {
        TableId tableId = StockBatch.class.getDeclaredField("id").getAnnotation(TableId.class);
        assertThat(tableId).as("id 必须标注 @TableId").isNotNull();
        assertThat(tableId.type().name()).isEqualTo("AUTO");
        assertThat(StockBatch.class.getDeclaredField("deleted").getAnnotation(TableLogic.class))
                .as("deleted 必须标 @TableLogic").isNotNull();
        assertThat(BaseMapper.class.isAssignableFrom(StockBatchMapper.class)).isTrue();
    }
}
