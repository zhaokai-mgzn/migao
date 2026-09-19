package com.migao.admin.mapper;

// case_ids: PG-021

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionPieceworkSettlement;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProductionPieceworkSettlementMapper 契约测试（issue #4483 = 母单 #4347 §二.4，V75）。
 *
 * <p>验证：表映射 {@code production_piecework_settlements} + 实体字段与迁移终态收敛。
 * 为什么必须有（门禁口径）：新增 Mapper 缺契约测试 ⇒ QA Growth Gate **阻塞合并**；
 * 且实体↔schema 漂移会让建库后相关接口 **500**。</p>
 */
@DisplayName("ProductionPieceworkSettlementMapper 表/字段契约（production_piecework_settlements）")
class ProductionPieceworkSettlementMapperTest {

    @Test
    @DisplayName("实体映射 production_piecework_settlements 表")
    void entityMapsToTable() {
        TableName tableName = ProductionPieceworkSettlement.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("production_piecework_settlements");
    }

    @Test
    @DisplayName("实体字段与 V75 终态列收敛（含金额快照与锁定状态）")
    void entityFieldsMatchSchema() {
        List<String> fields = Arrays.stream(ProductionPieceworkSettlement.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains("tenantId", "period", "workerKey", "workerName",
                "amount", "qty", "lineCount", "status", "settledAt", "settledBy", "deleted");
        ProductionMigrationSql.assertTableColumnsIn(
                "backend/admin-api/src/main/resources/db/migration/V75__create_piecework_settlements.sql",
                "production_piecework_settlements",
                "id", "tenant_id", "period", "worker_id", "worker_key", "worker_name",
                "amount", "qty", "line_count", "status", "settled_at", "settled_by", "remark",
                "created_at", "updated_at", "deleted");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(ProductionPieceworkSettlementMapper.class)).isTrue();
    }
}
