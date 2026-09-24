package com.migao.admin.mapper;

// case_ids: PR-039

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.AgentBatchItem;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * AgentBatchItemMapper 契约测试（批量更新的逐条明细，V127 / issue #5314 服务端包）。
 *
 * <p>明细是**撤销依据的载体** ⇒ 两条判据必须钉死：</p>
 * <ol>
 *   <li>{@code old_value} 在本表（预览阶段按 DB 当前值采集并持久化）——
 *       <b>不得</b>改用 {@code audit_logs}：审计是有界 fail-open（3s 超时丢行是允许的），
 *       拿它当依据 = 撤销会静默失去依据；</li>
 *   <li>{@code tenant_id} 列必须在实体与两源 DDL 里都在 ——
 *       {@code TenantLineInnerInterceptor} 会给本表注入 {@code tenant_id} 谓词，
 *       <b>缺列即每次查询/插入 SQL 报错</b>（这列不是冗余，是插件的前提）。</li>
 * </ol>
 */
@DisplayName("AgentBatchItemMapper 表/字段契约（批量更新的逐条明细）")
class AgentBatchItemMapperTest {

    private static final String V127 =
            "backend/admin-api/src/main/resources/db/migration/V127__create_agent_batches.sql";

    @Test
    @DisplayName("实体映射 agent_batch_items 表（不是 audit_logs）")
    void entityMapsToTable() {
        TableName tableName = AgentBatchItem.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("agent_batch_items");
        assertThat(tableName.value())
                .as("🔴 撤销依据必须落在自己的表上，不得复用 audit_logs（有界 fail-open、丢行允许）")
                .isNotEqualTo("audit_logs");

        List<String> fields = Arrays.stream(AgentBatchItem.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "id", "batchId", "tenantId", "resourceId", "field", "oldValue",
                "newValue", "status", "error");
    }

    @Test
    @DisplayName("契约列在**迁移**与**建库脚本**两源齐备（含 tenant_id —— 租户插件的前提）")
    void contractColumnsExistInBothSources() {
        ProductionMigrationSql.assertTableColumnsIn(V127, "agent_batch_items",
                "id", "batch_id", "tenant_id", "resource_id", "field", "old_value",
                "new_value", "status", "error");
    }

    @Test
    @DisplayName("🔴 old_value 的载体唯一：在本表；审计表没有这个列")
    void oldValueLivesHereNotInAuditLogs() {
        assertThat(ProductionMigrationSql.read(V127))
                .as("撤销依据必须是本表的**列**（不是审计行里的 JSON 约定）")
                .contains("old_value TEXT");
        assertThat(ProductionMigrationSql.read(ProductionMigrationSql.SCHEMA))
                .as("bootstrap 终态同样有该列")
                .contains("old_value TEXT");

        String schema = ProductionMigrationSql.read(ProductionMigrationSql.SCHEMA);
        int auditStart = schema.indexOf("CREATE TABLE audit_logs");
        assertThat(auditStart).as("审计表建表段必须找得到").isGreaterThan(0);
        String auditDdl = schema.substring(auditStart, schema.indexOf(");", auditStart));
        assertThat(auditDdl)
                .as("审计表不得长出 old_value 列 —— 一旦有人把它当撤销依据，这里先红")
                .doesNotContain("old_value");
    }

    @Test
    @DisplayName("id 为数据库自增（明细行序稳定：撤销按 id 升序逐条还原）")
    void idIsDatabaseGenerated() throws Exception {
        TableId tableId = AgentBatchItem.class.getDeclaredField("id").getAnnotation(TableId.class);
        assertThat(tableId).as("id 必须标注 @TableId").isNotNull();
        assertThat(tableId.type().name()).isEqualTo("AUTO");
        assertThat(BaseMapper.class.isAssignableFrom(AgentBatchItemMapper.class)).isTrue();
    }

    @Test
    @DisplayName("逐条状态取值域由 DB 约束钉住（部分失败逐条报告的载体）")
    void itemStatusDomainIsPinnedByConstraint() {
        String sql = ProductionMigrationSql.read(V127);
        assertThat(sql)
                .as("逐条状态必须由 CHECK 承载（含 skipped：执行阶段就失败过 ⇒ 撤销时无需还原）")
                .contains("CONSTRAINT ck_agent_batch_item_status")
                .contains("status IN ('pending', 'success', 'failed', 'reverted', 'revert_failed', 'skipped')");
        assertThat(sql)
                .as("field 白名单与 batchType 配对（不做通用批量 / 自由字段批量）")
                .contains("field IN ('basePrice', 'status')");
        assertThat(sql)
                .as("明细必须挂父批次（外键 + 级联）")
                .contains("batch_id VARCHAR(64) NOT NULL REFERENCES agent_batches(id) ON DELETE CASCADE");
    }
}