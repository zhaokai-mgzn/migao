package com.migao.admin.mapper;

// case_ids: PR-039

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.InboundOrderItem;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * InboundOrderItemMapper 契约测试（入库单明细，V111 / issue #5034）。
 *
 * <p>明细是「**一个 SKU 行 = 一个批次**」的落点 ⇒ 批次号/缸号两列必须在实体与迁移里都在，
 * 且**不得**合成一列（合成会逼系统在商家没填缸号时编一个 = 假真值）。</p>
 */
@DisplayName("InboundOrderItemMapper 表/字段契约（入库单明细）")
class InboundOrderItemMapperTest {

    private static final String V111 =
            "backend/admin-api/src/main/resources/db/migration-archive/V111__create_inbound_orders_and_batches.sql";

    @Test
    @DisplayName("实体映射 inbound_order_items 表")
    void entityMapsToTable() {
        TableName tableName = InboundOrderItem.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("inbound_order_items");
    }

    @Test
    @DisplayName("实体字段与 V111 列收敛（批次号与缸号**两列并存**）")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(InboundOrderItem.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "tenantId", "inboundOrderId", "skuId", "productId", "skuCode", "colorName",
                "doorWidth", "quantity", "unitCost", "amount", "batchNo", "dyeLot",
                "rollLengthM", "remark", "createdAt", "deleted");
        // 批次号与缸号是**两件事**：batch_no 是系统生成的内部批次标识，dye_lot 是供应商给的外部事实
        assertThat(fields).contains("batchNo", "dyeLot");
        ProductionMigrationSql.assertTableColumnsIn(V111, "inbound_order_items",
                "id", "tenant_id", "inbound_order_id", "sku_id", "product_id", "sku_code",
                "color_name", "door_width", "quantity", "unit_cost", "amount", "batch_no",
                "dye_lot", "roll_length_m", "remark", "created_at", "deleted");
    }

    @Test
    @DisplayName("id 为数据库自增（IDENTITY）：明细行内顺序稳定")
    void idIsDatabaseGenerated() throws Exception {
        TableId tableId = InboundOrderItem.class.getDeclaredField("id").getAnnotation(TableId.class);
        assertThat(tableId).as("id 必须标注 @TableId").isNotNull();
        assertThat(tableId.type().name()).isEqualTo("AUTO");
    }

    @Test
    @DisplayName("数量是 INTEGER（与 product_skus.stock 同粒度）；批次号可空（过账时才写）")
    void quantityIsIntegerAndBatchNoNullable() {
        String sql = ProductionMigrationSql.read(V111);
        // 数量列必须是 INTEGER —— 改成 NUMERIC 会让「非整数米不支持」这条边界静默失效
        assertThat(sql).contains("quantity INT NOT NULL");
        // 批次号列可空：草稿态为 NULL（批次号 = 「真的收货了」的标识）。
        // ⚠️ 判据取**明细表建表段内**的那一行 —— stock_batches 的 batch_no 是 NOT NULL（那是
        //    批次台账，批次号是它的主标识），全局 doesNotContain 会被那张表误判成红。
        String itemsDdl = sql.substring(sql.indexOf("CREATE TABLE IF NOT EXISTS inbound_order_items"),
                                        sql.indexOf("CREATE TABLE IF NOT EXISTS stock_batches"));
        assertThat(itemsDdl).contains("batch_no VARCHAR(32),");
        assertThat(itemsDdl).doesNotContain("batch_no VARCHAR(32) NOT NULL");
    }

    @Test
    @DisplayName("软删：deleted 标 @TableLogic；Mapper 继承 BaseMapper")
    void deletedIsLogicalDeleteAndMapperExtendsBase() throws Exception {
        assertThat(InboundOrderItem.class.getDeclaredField("deleted").getAnnotation(TableLogic.class))
                .as("deleted 必须标 @TableLogic").isNotNull();
        assertThat(BaseMapper.class.isAssignableFrom(InboundOrderItemMapper.class)).isTrue();
    }
}
