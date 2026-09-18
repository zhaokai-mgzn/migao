package com.migao.admin.mapper;

// case_ids: PG-040

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProcessingFeeCombinationVersion;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProcessingFeeCombinationVersionMapper 契约测试（加工费组合定价版本账，issue #4386，V68）
 *
 * <p>验证：表映射 {@code processing_fee_combination_versions} + 实体字段与迁移 V68 /
 * {@code docs/sql/schema.sql} **双源收敛**（与 #4308 的 {@code production_routing_versions} 同构）。</p>
 *
 * <p><b>为什么需要本文件</b>：加工费单价是**订单金额**的直接输入 ⇒ 改价必须留痕。
 * 列漂移（如 {@code composition_key} 漏列）会让「这个组合昨天什么价」答不出来
 * （留痕形同虚设，且不会变红）。</p>
 */
@DisplayName("ProcessingFeeCombinationVersionMapper 表/字段契约（加工费组合定价版本账）")
class ProcessingFeeCombinationVersionMapperTest {

    /** V68 迁移路径（本包内**唯一**一份字面量：两个 Mapper 契约测试共用，避免两处漂移）。 */
    static final String V68 =
            "backend/admin-api/src/main/resources/db/migration/V68__create_processing_fee_combinations.sql";

    @Test
    @DisplayName("实体映射 processing_fee_combination_versions 表")
    void entityMapsToTable() {
        TableName tableName = ProcessingFeeCombinationVersion.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("processing_fee_combination_versions");
    }

    @Test
    @DisplayName("实体字段与迁移 V68 / bootstrap schema 列收敛（双源）")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(ProcessingFeeCombinationVersion.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "tenantId", "combinationId", "compositionKey", "unitPrice", "status", "deleted");
        ProductionMigrationSql.assertTableColumnsIn(V68,
                "processing_fee_combination_versions",
                "id", "tenant_id", "combination_id", "composition_key", "unit_price",
                "status", "created_at", "deleted");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProcessingFeeCombinationVersionMapper.class)).isTrue();
    }
}
