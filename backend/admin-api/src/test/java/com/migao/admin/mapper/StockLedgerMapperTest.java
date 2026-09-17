// case_ids: PR-005, AS-006
// 库存台账三源收敛（issue #4055）：Java 实体字段 ↔ 迁移 V53 列 ↔ bootstrap docs/sql/schema.sql。
// 只写实体不写迁移、或迁移不同步 schema.sql 都在此变红（跨源漂移守卫
// tests/unit_ci_workflows/test_schema_integrity.py 的用例级补充，同时覆盖 docker bootstrap 路径）。

package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.StockLedger;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * StockLedgerMapper 契约测试（库存台账，issue #4055，V53）
 * 验证：表映射 stock_ledger_entries + 实体字段与迁移 V53 / schema.sql 收敛 + IdType.AUTO（IDENTITY 全序）。
 */
@DisplayName("StockLedgerMapper 表/字段契约（库存台账）")
class StockLedgerMapperTest {

    @Test
    @DisplayName("实体映射 stock_ledger_entries 表")
    void entityMapsToTable() {
        TableName tableName = StockLedger.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("stock_ledger_entries");
    }

    @Test
    @DisplayName("实体字段与迁移 V53 列收敛（含 before/after/delta 三件套）")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(StockLedger.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "tenantId", "productId", "skuId", "skuCode", "delta", "beforeQty", "afterQty",
                "reason", "refNo", "note", "operator", "createdAt", "deleted"
        );
        ProductionMigrationSql.assertTableColumnsIn(
                "backend/admin-api/src/main/resources/db/migration/V53__create_stock_ledger.sql",
                "stock_ledger_entries",
                "id", "tenant_id", "product_id", "sku_id", "sku_code", "delta", "before_qty",
                "after_qty", "reason", "ref_no", "note", "operator", "created_at", "deleted");
    }

    @Test
    @DisplayName("id 为数据库自增（IDENTITY 单调 → 同 SKU 行定序，不靠 created_at 撞毫秒）")
    void idIsDatabaseGenerated() throws Exception {
        Field id = StockLedger.class.getDeclaredField("id");
        TableId tableId = id.getAnnotation(TableId.class);
        assertThat(tableId).as("id 必须标注 @TableId").isNotNull();
        assertThat(tableId.type().name()).isEqualTo("AUTO");
    }

    @Test
    @DisplayName("软删：deleted 标 @TableLogic（不设 TTL，随订单生命周期）")
    void deletedIsLogicalDelete() throws Exception {
        Field deleted = StockLedger.class.getDeclaredField("deleted");
        assertThat(deleted.getAnnotation(TableLogic.class)).as("deleted 必须标 @TableLogic").isNotNull();
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(StockLedgerMapper.class)).isTrue();
    }
}