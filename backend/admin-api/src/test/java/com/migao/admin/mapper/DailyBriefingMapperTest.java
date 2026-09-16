package com.migao.admin.mapper;

// case_ids: DA-010

import com.migao.admin.entity.DailyBriefing;
import com.baomidou.mybatisplus.annotation.TableName;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * DailyBriefingMapper 契约测试（智能每日经营简报，issue #3468）
 * 验证：表映射 daily_briefings + 实体字段与迁移 V44 / schema.sql 收敛
 * （防「文档-代码状态漂移」，self-consistency-checklist P0-3 同模式）。
 */
@DisplayName("DailyBriefingMapper 表/字段契约")
class DailyBriefingMapperTest {

    @Test
    @DisplayName("实体映射 daily_briefings 表")
    void entityMapsToDailyBriefingsTable() {
        TableName tableName = DailyBriefing.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("daily_briefings");
    }

    @Test
    @DisplayName("实体包含租户隔离 + 内容/快照/校验状态字段")
    void entityFieldsPresent() throws Exception {
        assertThat(field("tenantId")).isNotNull();
        assertThat(field("bizDate")).isNotNull();
        assertThat(field("content")).isNotNull();
        assertThat(field("sourceSnapshot")).isNotNull();
        assertThat(field("verifyStatus")).isNotNull();
        assertThat(field("generatedAt")).isNotNull();
    }

    private Field field(String name) throws NoSuchFieldException {
        return DailyBriefing.class.getDeclaredField(name);
    }

    @Test
    @DisplayName("schema.sql 包含 daily_briefings 建表与 RLS 策略（防双源漂移）")
    void schemaSqlContainsDailyBriefings() throws Exception {
        java.nio.file.Path root = findRepoRoot();
        assertThat(root).isNotNull();
        String schema = java.nio.file.Files.readString(root.resolve("docs/sql/schema.sql"));
        assertThat(schema).as("schema.sql 应包含 daily_briefings 建表").contains("CREATE TABLE IF NOT EXISTS daily_briefings");
        assertThat(schema).as("schema.sql 应包含 RLS 策略").contains("tenant_isolation_daily_briefings");
        assertThat(schema).as("schema.sql 应包含 tenants.briefing_enabled").contains("briefing_enabled BOOLEAN DEFAULT FALSE");
    }

    @Test
    @DisplayName("V44 迁移包含建表 + RLS + tenants 加列")
    void migrationV44Present() throws Exception {
        java.nio.file.Path root = findRepoRoot();
        assertThat(root).isNotNull();
        String migration = java.nio.file.Files.readString(root.resolve(
                "backend/admin-api/src/main/resources/db/migration/V44__create_daily_briefings.sql"));
        assertThat(migration).contains("CREATE TABLE IF NOT EXISTS daily_briefings");
        assertThat(migration).contains("ENABLE ROW LEVEL SECURITY");
        assertThat(migration).contains("briefing_enabled BOOLEAN DEFAULT FALSE");
        assertThat(migration).contains("briefing_generate_time VARCHAR(5) DEFAULT '06:00'");
    }

    private static java.nio.file.Path findRepoRoot() {
        java.nio.file.Path p = java.nio.file.Paths.get("").toAbsolutePath();
        for (int i = 0; i < 6 && p != null; i++) {
            if (java.nio.file.Files.exists(p.resolve("AGENTS.md"))) {
                return p;
            }
            p = p.getParent();
        }
        return null;
    }
}
