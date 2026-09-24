package com.migao.admin.mapper;

// case_ids: PR-039

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.AgentBatch;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * AgentBatchMapper 契约测试（批量更新的批次，V127 / issue #5314 服务端包）。
 *
 * <p>三源收敛 = Java 实体 ↔ 迁移 {@code V127__create_agent_batches.sql} ↔
 * bootstrap {@code backend/admin-api/src/main/resources/db/init/schema.sql}
 * （只写实体不写迁移、或迁移不同步建库脚本 ⇒ 新建库缺表 / 存量库缺列 ⇒ 端点 500）。</p>
 *
 * <p>另钉两条**状态机在 DB 层**的判据：白名单与状态取值必须由 CHECK 约束承载
 * —— 靠代码自觉的取值域，在下一个写入点就会被绕过。</p>
 */
@DisplayName("AgentBatchMapper 表/字段契约（批量更新的批次）")
class AgentBatchMapperTest {

    private static final String V127 =
            "backend/admin-api/src/main/resources/db/migration/V127__create_agent_batches.sql";

    @Test
    @DisplayName("实体映射 agent_batches 表；含租户列（插件按 tenant_id 过滤）")
    void entityMapsToTable() {
        TableName tableName = AgentBatch.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("agent_batches");

        List<String> fields = Arrays.stream(AgentBatch.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "id", "tenantId", "batchType", "status", "itemCount", "successCount",
                "failCount", "createdBy", "createdAt", "executedAt", "revertedAt");
    }

    @Test
    @DisplayName("契约列在**迁移**与**建库脚本**两源齐备（冻结契约逐字）")
    void contractColumnsExistInBothSources() {
        ProductionMigrationSql.assertTableColumnsIn(V127, "agent_batches",
                "id", "tenant_id", "batch_type", "status", "item_count", "success_count",
                "fail_count", "created_by", "created_at", "executed_at", "reverted_at");
    }

    @Test
    @DisplayName("id 为 UUID 形态（响应里的 batchId 立刻可回带；服务层显式赋值）")
    void idIsAssignedUuid() throws Exception {
        TableId tableId = AgentBatch.class.getDeclaredField("id").getAnnotation(TableId.class);
        assertThat(tableId).as("id 必须标注 @TableId").isNotNull();
        assertThat(tableId.type().name()).isEqualTo("ASSIGN_UUID");
        assertThat(BaseMapper.class.isAssignableFrom(AgentBatchMapper.class)).isTrue();
    }

    @Test
    @DisplayName("🔴 状态机与 batchType 白名单由 DB 约束钉住（不是靠代码自觉）")
    void stateMachineAndWhitelistArePinnedByConstraints() {
        String sql = ProductionMigrationSql.read(V127);
        assertThat(sql)
                .as("状态机取值域必须由 CHECK 承载：preview → executing → done | partial → reverted | revert_partial")
                .contains("CONSTRAINT ck_agent_batch_status")
                .contains("status IN ('preview', 'executing', 'done', 'partial', 'reverted', 'revert_partial')");
        assertThat(sql)
                .as("batchType 白名单必须由 CHECK 承载（本单只做两个具名批量，不做通用批量）")
                .contains("batch_type IN ('product_price', 'product_status')");
        assertThat(sql)
                .as("计数如实：成功 + 失败不得超过条目数")
                .contains("success_count + fail_count <= item_count");
    }

    @Test
    @DisplayName("批次按 (tenant_id, created_at DESC) 可查（进度/最近批次读面）")
    void indexSupportsTenantRecentLookup() {
        String sql = ProductionMigrationSql.read(V127);
        assertThat(sql).contains("idx_agent_batches_tenant_created");
        assertThat(ProductionMigrationSql.read(ProductionMigrationSql.SCHEMA))
                .as("bootstrap 终态同样给该索引（新建库路径不跑历史迁移链）")
                .contains("idx_agent_batches_tenant_created");
    }
}