package com.migao.admin.mapper;

// case_ids: PG-021

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionPieceworkSettlementLine;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProductionPieceworkSettlementLineMapper 契约测试（issue #4483，V75）。
 *
 * <p>逐笔明细是「逐笔可追溯」（真值源 §4）的载体：{@code work_log_id} 必须指回报工行。</p>
 */
@DisplayName("ProductionPieceworkSettlementLineMapper 表/字段契约（production_piecework_settlement_lines）")
class ProductionPieceworkSettlementLineMapperTest {

    @Test
    @DisplayName("实体映射 production_piecework_settlement_lines 表")
    void entityMapsToTable() {
        TableName tableName = ProductionPieceworkSettlementLine.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("production_piecework_settlement_lines");
    }

    @Test
    @DisplayName("实体字段与 V75 终态列收敛（含 work_log_id 逐笔锚点）")
    void entityFieldsMatchSchema() {
        List<String> fields = Arrays.stream(ProductionPieceworkSettlementLine.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains("tenantId", "settlementId", "workLogId", "processingOrderId",
                "operationName", "workDate", "amount", "qty", "deleted");
        ProductionMigrationSql.assertTableColumnsIn(
                "backend/admin-api/src/main/resources/db/migration/V75__create_piecework_settlements.sql",
                "production_piecework_settlement_lines",
                "id", "tenant_id", "settlement_id", "work_log_id", "processing_order_id",
                "operation_name", "work_date", "amount", "qty", "created_at", "deleted");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProductionPieceworkSettlementLineMapper.class)).isTrue();
    }
}
