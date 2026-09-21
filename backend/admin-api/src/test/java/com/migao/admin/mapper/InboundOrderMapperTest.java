package com.migao.admin.mapper;

// case_ids: PR-039

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.InboundOrder;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * InboundOrderMapper 契约测试（入库单，V111 / issue #5034）。
 *
 * <p>守「Java 实体 ↔ 迁移 V111 ↔ bootstrap schema」三源收敛：只写实体不写迁移、
 * 或迁移不同步 {@code docs/sql/schema.sql} 都在此变红（同 StockLedgerMapperTest 口径）。</p>
 */
@DisplayName("InboundOrderMapper 表/字段契约（入库单）")
class InboundOrderMapperTest {

    private static final String V111 =
            "backend/admin-api/src/main/resources/db/migration/V111__create_inbound_orders_and_batches.sql";

    @Test
    @DisplayName("实体映射 inbound_orders 表")
    void entityMapsToTable() {
        TableName tableName = InboundOrder.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("inbound_orders");
    }

    @Test
    @DisplayName("实体字段与 V111 列收敛（单据头字段一个不少）")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(InboundOrder.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "tenantId", "inboundNo", "supplier", "supplierDocNo", "warehouse", "inboundDate",
                "status", "totalAmount", "remark", "postedAt", "postedBy",
                "cancelledAt", "cancelledBy", "cancelledReason", "createdBy", "createdAt", "deleted");
        ProductionMigrationSql.assertTableColumnsIn(V111, "inbound_orders",
                "id", "tenant_id", "inbound_no", "supplier", "supplier_doc_no", "warehouse",
                "inbound_date", "status", "total_amount", "remark", "posted_at", "posted_by",
                "cancelled_at", "cancelled_by", "cancelled_reason", "created_by", "created_at", "deleted");
    }

    @Test
    @DisplayName("id 为应用侧 UUID（ASSIGN_UUID）：与既有单据同族，业务单号另列")
    void idIsAssignedUuid() throws Exception {
        TableId tableId = InboundOrder.class.getDeclaredField("id").getAnnotation(TableId.class);
        assertThat(tableId).as("id 必须标注 @TableId").isNotNull();
        assertThat(tableId.type().name()).isEqualTo("ASSIGN_UUID");
    }

    @Test
    @DisplayName("状态常量与 V111 的状态机注释一致（draft/posted/cancelled）")
    void statusConstantsMatchSchema() {
        assertThat(InboundOrder.STATUS_DRAFT).isEqualTo("draft");
        assertThat(InboundOrder.STATUS_POSTED).isEqualTo("posted");
        assertThat(InboundOrder.STATUS_CANCELLED).isEqualTo("cancelled");
        String sql = ProductionMigrationSql.read(V111);
        // 迁移里三个取值都要出现（列注释逐字 + DEFAULT 值）；
        // 不钉注释的分隔符/排版写法（那是排版，不是判据）
        assertThat(sql).contains("draft 草稿").contains("posted 已过账").contains("cancelled 已作废");
        assertThat(sql).contains("status VARCHAR(16) NOT NULL DEFAULT 'draft'");
    }

    @Test
    @DisplayName("软删：deleted 标 @TableLogic；Mapper 继承 BaseMapper")
    void deletedIsLogicalDeleteAndMapperExtendsBase() throws Exception {
        assertThat(InboundOrder.class.getDeclaredField("deleted").getAnnotation(TableLogic.class))
                .as("deleted 必须标 @TableLogic").isNotNull();
        assertThat(BaseMapper.class.isAssignableFrom(InboundOrderMapper.class)).isTrue();
    }
}
