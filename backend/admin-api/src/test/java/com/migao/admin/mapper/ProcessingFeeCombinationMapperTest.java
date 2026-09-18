package com.migao.admin.mapper;

// case_ids: PG-040

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProcessingFeeCombination;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProcessingFeeCombinationMapper 契约测试（加工费组合定价，issue #4386，V68）
 *
 * <p>验证：表映射 {@code processing_fee_combinations} + 实体字段与迁移 V68 /
 * {@code docs/sql/schema.sql} **双源收敛**。</p>
 *
 * <p><b>为什么需要本文件</b>：本表是**下单侧唯一取价源**（组合 → 单价 元/米）。
 * 列一旦与实体漂移（如 {@code unit_price} 改名/漏列），取价会读到 null ⇒ 静默变成「0 元」
 * 或抛错，而**不会有任何东西变红**（同 #4308 的版本账风险）。</p>
 */
@DisplayName("ProcessingFeeCombinationMapper 表/字段契约（加工费组合定价）")
class ProcessingFeeCombinationMapperTest {

    /** V68 迁移路径（本包内**唯一**一份字面量：两个 Mapper 契约测试共用，避免两处漂移）。 */
    static final String V68 =
            "backend/admin-api/src/main/resources/db/migration/V68__create_processing_fee_combinations.sql";

    @Test
    @DisplayName("实体映射 processing_fee_combinations 表")
    void entityMapsToTable() {
        TableName tableName = ProcessingFeeCombination.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("processing_fee_combinations");
    }

    @Test
    @DisplayName("实体字段与迁移 V68 / bootstrap schema 列收敛（双源）")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(ProcessingFeeCombination.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "tenantId", "compositionKey", "items", "unitPrice",
                "status", "sortOrder", "source", "deleted");
        ProductionMigrationSql.assertTableColumnsIn(V68,
                "processing_fee_combinations",
                "id", "tenant_id", "composition_key", "items", "unit_price",
                "status", "sort_order", "source", "created_at", "updated_at", "deleted");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProcessingFeeCombinationMapper.class)).isTrue();
    }
}
