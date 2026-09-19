// case_ids: PG-020
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionOperationPositionPriceVersion;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 部位价目矩阵格单价版本表契约测试（issue #4587 ⑤，V86）。
 *
 * <p>守三条会被下一位验收者重开的判据：</p>
 * <ol>
 *   <li><b>三源收敛</b>：实体字段 ↔ V86 迁移 ↔ {@code docs/sql/schema.sql}（bootstrap 路径不跑迁移链，
 *       只写迁移不写 schema.sql ⇒ 全新库缺表 ⇒ 矩阵改价端点 500）；</li>
 *   <li><b>{@code unit_price} 必须**可空**</b>：这是本表与 V55 的**唯一**差别 —— 不可空 ⇒
 *       「改回未定价」「明确不做 ⇒ 价清空」两条语义**根本写不进去**（而它们正是三态里的两态）；</li>
 *   <li><b>幂等</b>：{@code CREATE TABLE/INDEX IF NOT EXISTS}（bootstrap-first 会让迁移在建好终态的
 *       库上再跑一遍），且索引能按 {@code (position_row_id, created_at DESC)} 取最新、只算未软删行。</li>
 * </ol>
 */
@DisplayName("部位价目矩阵格单价版本表/实体契约（V86，issue #4587）")
class ProductionOperationPositionPriceVersionMapperTest {

    private static final String MIGRATION =
            "backend/admin-api/src/main/resources/db/migration/V86__create_operation_position_price_versions.sql";

    private static final String TABLE = "production_operation_position_price_versions";

    @Test
    @DisplayName("实体映射 production_operation_position_price_versions 表")
    void entityMapsToTable() {
        TableName tableName = ProductionOperationPositionPriceVersion.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo(TABLE);
    }

    @Test
    @DisplayName("实体字段 ↔ V86 迁移 ↔ schema.sql 三源收敛（列名/列数逐条一致）")
    void entityFieldsMatchMigrationAndSchema() {
        List<String> fields = Arrays.stream(
                        ProductionOperationPositionPriceVersion.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "id", "tenantId", "positionRowId", "unitPrice", "createdAt", "deleted");
        ProductionMigrationSql.assertTableColumnsIn(MIGRATION, TABLE,
                "id", "tenant_id", "position_row_id", "unit_price", "created_at", "deleted");
    }

    @Test
    @DisplayName("unit_price **可空**（与 V55 的唯一差别）：改回未定价 / 明确不做 ⇒ 价清空")
    void unitPriceIsNullable() {
        String sql = ProductionMigrationSql.read(MIGRATION);
        assertThat(sql).contains("unit_price NUMERIC(10,2),");
        assertThat(sql).as("unit_price 不可空 ⇒ 三态里的两态（未定价 / 不做）写不进去")
                .doesNotContain("unit_price NUMERIC(10,2) NOT NULL");
    }

    @Test
    @DisplayName("V86 幂等：建表/建索引 IF NOT EXISTS + 索引按 (position_row_id, created_at DESC) 只算未软删")
    void migrationIsIdempotent() {
        String sql = ProductionMigrationSql.read(MIGRATION);
        assertThat(sql).contains("CREATE TABLE IF NOT EXISTS " + TABLE);
        assertThat(sql).contains("CREATE INDEX IF NOT EXISTS idx_op_position_price_versions_row");
        assertThat(sql).contains("(position_row_id, created_at DESC)");
        assertThat(sql).contains("WHERE deleted = 0");
        // 版本行必须挂在矩阵格上（外键 = 不会留下指向不存在格子的孤儿版本）
        assertThat(sql).contains("REFERENCES production_operation_positions(id)");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(
                ProductionOperationPositionPriceVersionMapper.class)).isTrue();
    }
}
