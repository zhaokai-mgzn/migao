package com.migao.admin.mapper;

// case_ids: PG-018

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionWorkLog;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProductionWorkLogMapper 契约测试（报工记录，issue #3995，V49）
 * 验证：表映射 production_work_logs + 实体字段与迁移 V49 / schema.sql 收敛。
 * 报工三态 normal/rework/scrap：qualified_qty 是计件口径，work_type 决定是否累加与计件。
 */
@DisplayName("ProductionWorkLogMapper 表/字段契约（报工记录）")
class ProductionWorkLogMapperTest {

    @Test
    @DisplayName("实体映射 production_work_logs 表")
    void entityMapsToTable() {
        TableName tableName = ProductionWorkLog.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("production_work_logs");
    }

    @Test
    @DisplayName("实体字段与迁移 V49 列收敛")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(ProductionWorkLog.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "tenantId", "processingOrderId", "operationId", "operationName",
                "workerId", "workerName", "qty", "qualifiedQty", "workType", "workDate", "deleted"
        );
        ProductionMigrationSql.assertTableColumns("production_work_logs",
                "id", "tenant_id", "processing_order_id", "operation_id", "operation_name",
                "worker_id", "worker_name", "qty", "qualified_qty", "work_type", "work_date",
                "created_at", "deleted");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProductionWorkLogMapper.class)).isTrue();
    }
}
