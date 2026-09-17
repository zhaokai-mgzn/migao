package com.migao.admin.mapper;

// case_ids: PG-018

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProcessingPositionOperation;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProcessingPositionOperationMapper 契约测试（工序实例，issue #3995，V49）
 * 验证：表映射 processing_position_operations + 实体字段与迁移 V49 / schema.sql 收敛。
 * 工序实例是扫码报工的推进单元（qty 应做数量 / done_qty 合格累计 / is_must_finish 必完）。
 */
@DisplayName("ProcessingPositionOperationMapper 表/字段契约（工序实例）")
class ProcessingPositionOperationMapperTest {

    @Test
    @DisplayName("实体映射 processing_position_operations 表")
    void entityMapsToTable() {
        TableName tableName = ProcessingPositionOperation.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("processing_position_operations");
    }

    @Test
    @DisplayName("实体字段与迁移 V49 列收敛")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(ProcessingPositionOperation.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "tenantId", "processingOrderId", "positionName", "seq", "operationName",
                "groupName", "unit", "qty", "unitPrice", "factor", "isMustFinish",
                "isStartMarker", "status", "doneQty", "deleted"
        );
        ProductionMigrationSql.assertTableColumns("processing_position_operations",
                "id", "tenant_id", "processing_order_id", "position_name", "seq", "operation_name",
                "group_name", "unit", "qty", "unit_price", "factor", "is_must_finish",
                "is_start_marker", "status", "done_qty", "created_at", "updated_at", "deleted");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProcessingPositionOperationMapper.class)).isTrue();
    }
}
