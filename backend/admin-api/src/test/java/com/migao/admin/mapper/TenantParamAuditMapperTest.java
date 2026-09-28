package com.migao.admin.mapper;

// case_ids: OR-041

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.TenantParamAudit;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * TenantParamAuditMapper 表/列契约测试（企业参数**变更留痕**，issue #5131 = §22 P6，V131）。
 *
 * <p>为什么这类表值得一条契约测试：本表的**三条不变式**是「账本可信」的全部依据 ——
 * 同值行不许写（{@code ck_tenant_param_audit_changed}）、来源只有两个取值
 * （{@code ck_tenant_param_audit_source}）、**「不知道是谁」必须带原因**
 * （{@code ck_tenant_param_audit_unknown}）。它们必须**同时**落在迁移与建库脚本上
 * （新建库不跑迁移链 ⇒ 只改一处就会得到一份没有约束的账本，而任何东西都不会变红）。</p>
 *
 * <p>形态照既有先例 {@code WorkerReportAuditMapperTest}（同族的只追加旁路账）：三源收敛
 * （实体 ↔ 迁移 ↔ 建库脚本）逐列断言。</p>
 */
@DisplayName("TenantParamAuditMapper 表/列契约（企业参数变更留痕）")
class TenantParamAuditMapperTest {

    private static final String MIGRATION =
            "backend/admin-api/src/main/resources/db/migration/V131__create_tenant_param_audit.sql";

    /** 14 列（顺序 = 迁移里的声明顺序；实体字段名 = 列名的驼峰形态）。 */
    private static final List<String> COLUMNS = List.of(
            "id", "tenant_id", "param_domain", "param_key", "old_value", "new_value",
            "actor_id", "actor_name", "actor_source", "actor_unknown_reason",
            "operation", "operation_id", "created_at", "deleted");

    @Test
    @DisplayName("实体映射 tenant_param_audit 表")
    void entityMapsToTable() {
        TableName tableName = TenantParamAudit.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("tenant_param_audit");
    }

    @Test
    @DisplayName("实体字段与 V131 迁移 + 建库脚本列收敛（14 列，含身份来源三列与 operation_id）")
    void entityFieldsMatchMigrationAndBootstrap() {
        List<String> fields = Arrays.stream(TenantParamAudit.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).containsExactly(
                "id", "tenantId", "paramDomain", "paramKey", "oldValue", "newValue",
                "actorId", "actorName", "actorSource", "actorUnknownReason",
                "operation", "operationId", "createdAt", "deleted");
        // 一次调用同时覆盖**两源**（helper 的语义就是「迁移 + 建库脚本」，见 ProductionMigrationSql）
        ProductionMigrationSql.assertTableColumnsIn(MIGRATION, "tenant_param_audit",
                COLUMNS.toArray(String[]::new));
    }

    @Test
    @DisplayName("🔴 三条不变式在迁移里（同值行 / 来源白名单 / 未知必带原因）—— 不只在 Java 侧")
    void migrationPinsTheThreeInvariants() {
        String migration = ProductionMigrationSql.read(MIGRATION);
        assertThat(migration)
                .as("一行 = 一次真变更")
                .contains("ck_tenant_param_audit_changed")
                .contains("old_value IS DISTINCT FROM new_value");
        assertThat(migration)
                .as("来源只有 security_context / unknown")
                .contains("ck_tenant_param_audit_source")
                .contains("actor_source IN ('security_context', 'unknown')");
        assertThat(migration)
                .as("「不知道是谁」必须带原因（两个条件同真同假）")
                .contains("ck_tenant_param_audit_unknown")
                .contains("(actor_source = 'unknown') = (actor_unknown_reason IS NOT NULL)");
        // 终态对账块必须点名三条约束（否则约束缺失时迁移照旧「成功」）
        assertThat(migration).contains("V131 终态对账失败");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper；本单不提前加没人调用的查询方法（读面属增量 3）")
    void mapperStaysMinimal() {
        assertThat(BaseMapper.class.isAssignableFrom(TenantParamAuditMapper.class)).isTrue();
        assertThat(TenantParamAuditMapper.class.getDeclaredMethods())
                .as("只追加写面：读面（「这个参数被谁改过」）落地时再加")
                .isEmpty();
    }
}
