// case_ids: PG-018
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProcessingOrderSet;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProcessingOrderSetMapper 契约测试（套号载体，切片 ⓪ / issue #4698，V92）。
 * 验证：表映射 processing_order_sets + 实体字段与 V92 / schema.sql 收敛。
 * 一套 = 一樘窗（用户裁定 2026-09-20），扫码解析按 {@code set_id} 取套号做归属校验与响应。
 */
@DisplayName("ProcessingOrderSetMapper 表/字段契约（套号载体）")
class ProcessingOrderSetMapperTest {

    private static final String V92 =
            "backend/admin-api/src/main/resources/db/migration-archive/V92__add_processing_order_sets_and_scan_loop.sql";

    @Test
    @DisplayName("实体映射 processing_order_sets 表")
    void entityMapsToTable() {
        TableName tableName = ProcessingOrderSet.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("processing_order_sets");
    }

    @Test
    @DisplayName("实体字段与迁移 V92 列收敛")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(ProcessingOrderSet.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains("tenantId", "processingOrderId", "setIndex", "setNo", "deleted");
        ProductionMigrationSql.assertTableColumnsIn(V92, "processing_order_sets",
                "id", "tenant_id", "processing_order_id", "set_index", "set_no", "deleted");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProcessingOrderSetMapper.class)).isTrue();
    }
}
