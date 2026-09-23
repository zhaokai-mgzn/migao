package com.migao.admin.mapper;

// case_ids: PG-018, BM-005

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.WorkerSession;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * WorkerSessionMapper 契约测试（工人登录态，issue #4733，V98）。
 *
 * <p>验证三件事：① 表/列三源收敛（实体 ↔ V98 迁移 ↔ backend/admin-api/src/main/resources/db/init/schema.sql）；
 * ② 三条 SQL 的 **fail-closed 谓词**逐字在位（`deleted = 0 AND ended_at IS NULL`）——
 * 缺了它，「已切换/已登出的会话」会被复活 ⇒ 把活记到上一个人头上（本单最忌的形态）；
 * ③ `endSession` 的 `ended_at IS NULL` 谓词 = 幂等（重复结束不改首次的原因）。</p>
 */
@DisplayName("WorkerSessionMapper 表/列 + fail-closed 谓词契约（工人登录态）")
class WorkerSessionMapperTest {

    private static final String MIGRATION =
            "backend/admin-api/src/main/resources/db/migration-archive/V98__create_worker_sessions_and_worker_no.sql";

    @Test
    @DisplayName("实体映射 worker_sessions 表")
    void entityMapsToTable() {
        TableName tableName = WorkerSession.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("worker_sessions");
    }

    @Test
    @DisplayName("实体字段与 V98 迁移 + schema.sql 列收敛")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(WorkerSession.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        assertThat(fields).contains(
                "id", "tenantId", "workerId", "workerNo", "workerName", "deviceLabel",
                "startedAt", "lastSeenAt", "idleExpiresAt", "endedAt", "endReason", "deleted");
        ProductionMigrationSql.assertTableColumnsIn(MIGRATION, "worker_sessions",
                "id", "tenant_id", "worker_id", "worker_no", "worker_name", "device_label",
                "started_at", "last_seen_at", "idle_expires_at", "ended_at", "end_reason",
                "created_at", "updated_at", "deleted");
    }

    @Test
    @DisplayName("工号列落在 users 表（V98 只加列，不动既有列）")
    void workerNoColumnAddedToUsers() {
        String migration = ProductionMigrationSql.read(MIGRATION);
        assertThat(migration).contains("ALTER TABLE users ADD COLUMN IF NOT EXISTS worker_no");
        assertThat(migration).contains("uk_users_tenant_worker_no");
        // 商家用户不受影响：唯一索引是**部分索引**（worker_no IS NOT NULL）
        assertThat(migration).contains("WHERE worker_no IS NOT NULL AND deleted = 0");
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(BaseMapper.class.isAssignableFrom(WorkerSessionMapper.class)).isTrue();
    }

    @Test
    @DisplayName("🔴 selectActiveById 只认未软删且未结束的会话（缺谓词 ⇒ 旧会话复活 ⇒ 记到上一个人头上）")
    void selectActiveByIdIsFailClosed() throws Exception {
        String sql = annotationSql(WorkerSessionMapper.class.getMethod("selectActiveById", String.class), Select.class);
        assertThat(sql).contains("deleted = 0");
        assertThat(sql).contains("ended_at IS NULL");
    }

    @Test
    @DisplayName("🔴 touch / endSession 同样只作用于活跃会话（已切换/已登出不得被续期）")
    void touchAndEndAreScopedToActiveSessions() throws Exception {
        String touch = annotationSql(WorkerSessionMapper.class.getMethod(
                "touch", String.class, java.time.OffsetDateTime.class, java.time.OffsetDateTime.class), Update.class);
        assertThat(touch).contains("deleted = 0").contains("ended_at IS NULL");
        assertThat(touch).contains("idle_expires_at = #{idleExpiresAt}");

        String end = annotationSql(WorkerSessionMapper.class.getMethod(
                "endSession", String.class, java.time.OffsetDateTime.class, String.class), Update.class);
        // ended_at IS NULL 谓词 = 幂等：重复结束不改首次的 ended_at / end_reason
        assertThat(end).contains("ended_at IS NULL");
        assertThat(end).contains("end_reason = #{endReason}");
    }

    /** 取注解里的 SQL 文本。 */
    private String annotationSql(Method method, Class<? extends java.lang.annotation.Annotation> type) {
        java.lang.annotation.Annotation annotation = method.getAnnotation(type);
        assertThat(annotation).as("%s 必须有 %s 注解", method.getName(), type.getSimpleName()).isNotNull();
        try {
            Object value = type.getMethod("value").invoke(annotation);
            // @Select/@Update 的 value 是 String[]（多段拼接）⇒ 逐段 join 后再断言
            return value instanceof String[] parts ? String.join(" ", parts) : String.valueOf(value);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException(e);
        }
    }
}
