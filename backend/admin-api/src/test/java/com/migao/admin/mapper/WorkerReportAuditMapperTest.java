package com.migao.admin.mapper;

// case_ids: PG-018, BM-006

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.WorkerReportAudit;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * WorkerReportAuditMapper 契约测试（报工身份旁路账，issue #4733，V98）。
 *
 * <p>为什么是旁路表：{@code production_work_logs} 是**冻结契约 + 红线**
 * （设计 §3.4 / {@code worker-scan-terminal.md} §7 逐字「不改 {@code production_work_logs}」）
 * ⇒ 「由哪个设备会话报的」+「身份来源是 session 还是 body」只能另立只追加表。</p>
 */
@DisplayName("WorkerReportAuditMapper 表/列契约（报工身份旁路账）")
class WorkerReportAuditMapperTest {

    private static final String MIGRATION =
            "backend/admin-api/src/main/resources/db/migration-archive/V98__create_worker_sessions_and_worker_no.sql";

    @Test
    @DisplayName("实体映射 worker_report_audits 表")
    void entityMapsToTable() {
        TableName tableName = WorkerReportAudit.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("worker_report_audits");
    }

    @Test
    @DisplayName("实体字段与 V98 迁移 + schema.sql 列收敛（含 identity_source / worker_session_id）")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(WorkerReportAudit.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "id", "tenantId", "processingOrderId", "workLogId", "operationId",
                "workerId", "workerName", "workerSessionId", "identitySource", "deleted");
        ProductionMigrationSql.assertTableColumnsIn(MIGRATION, "worker_report_audits",
                "id", "tenant_id", "processing_order_id", "work_log_id", "operation_id",
                "worker_id", "worker_name", "worker_session_id", "identity_source",
                "created_at", "deleted");
    }

    @Test
    @DisplayName("红线：V98 不给 production_work_logs 加列（只加旁路表）")
    void productionWorkLogsUntouched() {
        String migration = ProductionMigrationSql.read(MIGRATION);
        assertThat(migration)
                .as("production_work_logs 是冻结契约：V98 不得 ALTER 它")
                .doesNotContain("ALTER TABLE production_work_logs");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（只追加：insert/select 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(WorkerReportAuditMapper.class)).isTrue();
    }
}
