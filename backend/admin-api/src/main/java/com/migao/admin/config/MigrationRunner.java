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
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * 极简 DB 迁移器 — 替代 Flyway。
 *
 * 启动时扫描 db/migration/V*__xxx.sql，按**版本号数值**排序，
 * 跳过已执行的文件，执行新的 migration。
 * 通过 schema_migrations 表追踪执行历史。
 *
 * 所有 SQL 文件必须幂等（IF NOT EXISTS / ON CONFLICT DO NOTHING）。
 *
 * ⚠️ 两条硬约束（issue #3270 CI 实证，两者叠加曾让 schema 与代码长期脱节）：
 *   1. **必须按版本号数值排序**，不能按文件名字典序 —— 字典序下 `V5` 排在 `V40` 之后、
 *      `V2` 排在 `V19` 之后（本类注释曾误写成「V1 &lt; V2 &lt; … &lt; V30」）。
 *   2. **单条迁移失败不得中断其余迁移** —— 只记 ERROR 日志是对的（迁移可能已在 DB
 *      执行过），但让整条链停下会让 V28 之后的 V29–V41 与单数字的 V5–V9 **全部不执行**，
 *      于是 `orders.actual_amount` 之类的列永远缺失 → admin-api 查询 500 →
 *      ai-agent 工具「服务暂时不可用」→ 熔断 → 评测被污染。
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
            // 按文件名升序执行（V1 < V2 < ... < V30）：getResources 的返回顺序
            // 取决于 classpath 扫描（JAR 内 zip 遍历序），曾实测返回逆序——
            // 若依赖该顺序，V29 重建表会在 V30 种子之后执行，导致种子被 DROP 清空。
            Arrays.sort(resources, Comparator.comparing(Resource::getFilename,
                    Comparator.nullsLast(MIGRATION_ORDER)));
            List<String> applied = getAppliedMigrations(jdbc);

            List<String> failed = new ArrayList<>();
            for (Resource r : resources) {
                String filename = r.getFilename();
                if (filename == null) continue;
                if (applied.contains(filename)) continue;

                log.info("🔄 执行迁移: {}", filename);
                try {
                    String sql = readResource(r);
                    jdbc.execute(sql);
                    recordMigration(jdbc, filename);
                    log.info("✅ 迁移完成: {}", filename);
                } catch (Exception e) {
                    // 单条失败**只跳过这一条**，继续跑后面的 —— 一条坏迁移不得冻结整个 schema。
                    // 实测（issue #3270）：V28 失败后整链中断，V29–V41 与 V5–V9 全未执行，
                    // 于是 orders.actual_amount 等列永远缺失、admin-api 500、
                    // 评测被熔断污染，而日志里只有一行 ERROR，没人发现。
                    failed.add(filename);
                    log.error("❌ 迁移失败（已跳过，继续执行其余迁移）: {}", filename, e);
                }
            }
            if (!failed.isEmpty()) {
                log.error("❌ 本次有 {} 条迁移失败，schema 可能与代码不一致（请立即修复并在修复后重跑）：{}",
                        failed.size(), failed);
            }
        } catch (Exception e) {
            log.error("❌ 迁移失败", e);
            // 不抛异常 — 允许应用继续启动（迁移可能已在 DB 执行过）
        }
    }

    // ── 版本号排序（单一事实源，测试也用同一比较器）──

    /** V{n}__desc.sql 里的 n；无法解析返回 -1（排到最后，不得静默插队到中间） */
    private static final Pattern VERSION_RE = Pattern.compile("^V(\\d+)__");

    /**
     * 迁移执行顺序：按版本号**数值**升序；无法解析版本号的文件**排到最后**
     * （同段按文件名）。
     *
     * ⚠️ 不能直接 `comparingInt(versionOf)`：无法解析时 versionOf 返回 -1，
     * 会让"垃圾文件名"排到**最前面**（首版即此 bug，被单测 `unparsableNamesSortLast` 抓出）。
     * 故把 -1 映射为最大值：不可解析的宁可最后跑，也不许插队到中间。
     */
    public static final Comparator<String> MIGRATION_ORDER =
            Comparator.comparingInt(MigrationRunner::sortKey)
                    .thenComparing(Comparator.nullsLast(String::compareTo));

    /** 排序键：可解析 → 版本号；不可解析 → Integer.MAX_VALUE（排最后） */
    private static int sortKey(String filename) {
        int v = versionOf(filename);
        return v < 0 ? Integer.MAX_VALUE : v;
    }

    /** 解析迁移文件名里的版本号；无法解析返回 -1 */
    public static int versionOf(String filename) {
        if (filename == null) {
            return -1;
        }
        Matcher m = VERSION_RE.matcher(filename);
        if (!m.find()) {
            return -1;
        }
        try {
            return Integer.parseInt(m.group(1));
        } catch (NumberFormatException e) {
            return -1;
        }
    }

    /** 按执行顺序排序（测试用；与 run() 使用同一比较器） */
    public static List<String> sortMigrationNames(List<String> names) {
        List<String> copy = new ArrayList<>(names);
        copy.sort(MIGRATION_ORDER);
        return copy;
    }

    /** 列出 classpath 下 db/migration/*.sql 的文件名（测试用） */
    public static List<String> listMigrationNames() {
        try {
            Resource[] resources = new org.springframework.core.io.support.PathMatchingResourcePatternResolver()
                    .getResources("classpath:db/migration/*.sql");
            List<String> names = new ArrayList<>();
            for (Resource r : resources) {
                if (r.getFilename() != null) {
                    names.add(r.getFilename());
                }
            }
            return names;
        } catch (Exception e) {
            throw new IllegalStateException("无法列举迁移文件", e);
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
