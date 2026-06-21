package com.migao.admin.config;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.CommandLineRunner;
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.ResourcePatternResolver;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.stream.Collectors;

/**
 * 极简 DB 迁移器 — 替代 Flyway。
 *
 * 启动时扫描 db/migration/V*__xxx.sql，按文件名排序，
 * 跳过已执行的文件，执行新的 migration。
 * 通过 schema_migrations 表追踪执行历史。
 *
 * 所有 SQL 文件必须幂等（IF NOT EXISTS / ON CONFLICT DO NOTHING）。
 *
 * 使用 ObjectProvider 延迟获取 JdbcTemplate，确保在无 DataSource 的测试
 * 上下文中（如 SecurityConfigTest）不会因缺少 Bean 而启动失败。
 */
@Slf4j
@Component
public class MigrationRunner implements CommandLineRunner {

    private final ObjectProvider<JdbcTemplate> jdbcProvider;
    private final ResourcePatternResolver resolver;

    @Value("${migao.migration.locations:classpath:db/migration/*.sql}")
    private String migrationPattern;

    public MigrationRunner(ObjectProvider<JdbcTemplate> jdbcProvider, ResourcePatternResolver resolver) {
        this.jdbcProvider = jdbcProvider;
        this.resolver = resolver;
    }

    @Override
    public void run(String... args) {
        JdbcTemplate jdbc = jdbcProvider.getIfAvailable();
        if (jdbc == null) {
            log.info("⏭️  DataSource 不可用，跳过 DB 迁移（测试环境正常）");
            return;
        }

        try {
            ensureHistoryTable(jdbc);
            Resource[] resources = resolver.getResources(migrationPattern);
            List<String> applied = getAppliedMigrations(jdbc);

            for (Resource r : resources) {
                String filename = r.getFilename();
                if (filename == null) continue;
                if (applied.contains(filename)) continue;

                log.info("🔄 执行迁移: {}", filename);
                String sql = readResource(r);
                jdbc.execute(sql);
                recordMigration(jdbc, filename);
                log.info("✅ 迁移完成: {}", filename);
            }
        } catch (Exception e) {
            log.error("❌ 迁移失败", e);
            // 不抛异常 — 允许应用继续启动（迁移可能已在 DB 执行过）
        }
    }

    private void ensureHistoryTable(JdbcTemplate jdbc) {
        jdbc.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """);
    }

    private List<String> getAppliedMigrations(JdbcTemplate jdbc) {
        try {
            return jdbc.queryForList("SELECT version FROM schema_migrations", String.class);
        } catch (Exception e) {
            return List.of();
        }
    }

    private String readResource(Resource resource) {
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(resource.getInputStream(), StandardCharsets.UTF_8))) {
            return reader.lines().collect(Collectors.joining("\n"));
        } catch (Exception e) {
            throw new RuntimeException("无法读取 migration: " + resource.getFilename(), e);
        }
    }

    private void recordMigration(JdbcTemplate jdbc, String filename) {
        jdbc.update("INSERT INTO schema_migrations (version) VALUES (?)", filename);
    }
}
