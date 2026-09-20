// case_ids: PG-018
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProcessingSetPartToken;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProcessingSetPartTokenMapper 契约测试（一部位一码 token，切片 ⓪ / issue #4698，V92）。
 * 验证：表映射 processing_set_part_tokens + 实体字段与 V92 / schema.sql 收敛。
 * 扫码解析的**第一优先**形态：新 token（带套带部位）⇒ 部位由码给出、工人不选（设计 §2.3 / §2.6）。
 */
@DisplayName("ProcessingSetPartTokenMapper 表/字段契约（一部位一码）")
class ProcessingSetPartTokenMapperTest {

    private static final String V92 =
            "backend/admin-api/src/main/resources/db/migration/V92__add_processing_order_sets_and_scan_loop.sql";

    @Test
    @DisplayName("实体映射 processing_set_part_tokens 表")
    void entityMapsToTable() {
        TableName tableName = ProcessingSetPartToken.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("processing_set_part_tokens");
    }

    @Test
    @DisplayName("实体字段与迁移 V92 列收敛")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(ProcessingSetPartToken.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains("tenantId", "processingOrderId", "setId", "orderItemId",
                "positionKind", "token", "deleted");
        ProductionMigrationSql.assertTableColumnsIn(V92, "processing_set_part_tokens",
                "id", "tenant_id", "processing_order_id", "set_id", "order_item_id", "position_kind",
                "token", "deleted");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProcessingSetPartTokenMapper.class)).isTrue();
    }
}
