package com.migao.admin.config;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.CommandLineRunner;
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.ResourcePatternResolver;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.ConnectException;
import java.net.SocketTimeoutException;
import java.net.UnknownHostException;
import java.nio.charset.StandardCharsets;
import java.sql.SQLTransientConnectionException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
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
 *   2. **单条迁移失败不得中断其余迁移** —— 但"一律只记 ERROR"**并非总是对的**（见下条），
 *      而让整条链停下会让 V28 之后的 V29–V41 与单数字的 V5–V9 **全部不执行**，
 *      于是 `orders.actual_amount` 之类的列永远缺失 → admin-api 查询 500 →
 *      ai-agent 工具「服务暂时不可用」→ 熔断 → 评测被污染。
 *      **例外（issue #4241）**：**连接类**失败不算「单条迁移失败」，见下条 —— 它必须 fail-closed。
 *
 * ⚠️ **失败分两类（issue #4241 实测）**：判据是**失败的性质**，不是失败发生在哪一步。
 *   - **连接类**（`CannotGetJdbcConnectionException` / `SQLTransientConnectionException` / 连接超时等，
 *     见 {@link #isConnectionFailure}）：库抖动是**暂时**的 ⇒ 有限次退避重试；重试耗尽
 *     **抛错让应用启动失败**（`MigrationConnectionFailureException`）。
 *     旧行为是 fail-open：`ensureHistoryTable` 拿不到连接 ⇒ 整轮迁移被外层 catch 吞掉、
 *     **一条都不跑**，而 `/actuator/health` 照报 UP ⇒ 新迁移没落库、业务端点随机 500
 *     （实测改工序单价 500「relation "production_operation_price_versions" does not exist」，
 *     DB 恢复后**重启一次即好**），且启动后永不重试 ⇒ 抖动窗口过去也不会自愈。
 *   - **内容类**（SQL 语法/约束，即 `execute` 抛的 `DataAccessException` 子类）：维持既有语义
 *     **逐字不变**（跳过该条 + 继续其余 + 记账 + ERROR，见下条），**不重试、不拒启动**。
 *
 * ⚠️ **失败分级（issue #3714）**：bootstrap-first 评测栈上，`KNOWN_BENIGN_LEGACY` 里那几条
 * 已诊断的**历史非幂等**迁移**每次起栈必失败**（目标态已由 `docs/sql/schema.sql` 建出，
 * 失败真因是"目标已存在"而非"对象缺失"）。旧实现对它们一律打 ERROR +
 * 「请立即修复并在修复后重跑」—— 一句**必然为假**的行动指令（无物可修、重跑必复现）。
 * 长期后果是**真失败与永久噪音同形** → 归因层失效（本仓库自认的最大失败模式）。
 * ⇒ 命中该集合者降级为 INFO、并在汇总行**单独计数**；**未命中的真失败照旧 ERROR + 非零计数**。
 * 决不静默：只有已诊断的存量降级。该集合与 Python 侧登记表的对应关系由 L0 测试锁死（见其注释）。
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

    /**
     * 连接类失败的重试上限（含首次尝试）。连接抖动是**暂时**的，重试能自愈；
     * 上限则保证「持续连不上」不会把启动无限挂死。
     * 默认 5 次 + 退避（2s/4s/8s/10s）⇒ 最坏 ~24s 后 fail-closed。
     */
    @Value("${migao.migration.connect-retry.max-attempts:5}")
    private int maxConnectAttempts = 5;

    /** 连接类失败首次重试前的退避毫秒数（逐次翻倍，封顶 {@link #MAX_BACKOFF_MS}）。 */
    @Value("${migao.migration.connect-retry.backoff-ms:2000}")
    private long connectRetryBackoffMs = 2000;

    /** 退避封顶（防指数退避把启动拖长）。 */
    private static final long MAX_BACKOFF_MS = 10_000L;

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

        for (int attempt = 1; ; attempt++) {
            try {
                migrate(jdbc);
                return;
            } catch (Exception e) {
                if (!isConnectionFailure(e)) {
                    // 既有语义**逐字不变**（issue #3714/#3615 口径）：内容类失败不抛异常，允许应用继续启动
                    log.error("❌ 迁移失败", e);
                    return;
                }
                if (attempt >= maxConnectAttempts) {
                    // fail-closed（issue #4241）：拿不到连接时**绝不能**让应用以 healthy 状态起来服务 ——
                    // 那会让 /actuator/health 谎报 UP、把故障面后移到业务 500
                    // （实测：一条迁移都没跑 ⇒ 改工序单价 500「relation ... does not exist」，重启即好），
                    // 且启动后永不重试 ⇒ 抖动窗口过去也不会自愈。
                    // 抛错 = 启动失败 = 编排/部署层能看见的信号（Spring 记 `Application run failed`
                    // 并把异常抛给 main ⇒ 进程非 0 退出，`docker compose up --wait` 直接失败）。
                    log.error("❌ 迁移失败（连接类）：已尝试 {} 次仍拿不到 DB 连接 —— 拒绝以「schema 未知」状态启动",
                            attempt, e);
                    throw new MigrationConnectionFailureException(
                            "数据库迁移失败（连接类失败，重试 " + attempt + " 次耗尽）—— 拒绝启动", e);
                }
                long backoffMs = Math.min(connectRetryBackoffMs << (attempt - 1), MAX_BACKOFF_MS);
                log.warn("⚠️ 迁移失败（连接类，第 {}/{} 次尝试）：{} —— {}ms 后退避重试",
                        attempt, maxConnectAttempts, rootCause(e), backoffMs);
                try {
                    Thread.sleep(backoffMs);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    throw new MigrationConnectionFailureException("迁移重试等待被中断 —— 拒绝启动", ie);
                }
            }
        }
    }

    /**
     * 跑**一轮**迁移。可安全重入（连接类失败重试即「从中断处续跑」）：
     * 已记账的迁移在下一轮被 `applied.contains` 跳过，不会重复执行。
     */
    private void migrate(JdbcTemplate jdbc) throws Exception {
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
                // 连接类失败**不是**「这条迁移坏」：此刻整条链都拿不到连接，逐条吞掉只会把
                // 「一条都没跑」记成「N 条迁移失败」并让应用照常 UP（issue #4241 的同族形态）。
                // ⇒ 交给外层有限退避重试；重试耗尽即 fail-closed 拒绝启动。
                if (isConnectionFailure(e)) {
                    throw e;
                }
                // 单条失败**只跳过这一条**，继续跑后面的 —— 一条坏迁移不得冻结整个 schema。
                // 实测（issue #3270）：V28 失败后整链中断，V29–V41 与 V5–V9 全未执行，
                // 于是 orders.actual_amount 等列永远缺失、admin-api 500、
                // 评测被熔断污染，而日志里只有一行 ERROR，没人发现。
                failed.add(filename);
                if (isKnownBenignLegacy(filename)) {
                    log.info("ℹ️ 迁移失败（已知存量非幂等，目标态已达成，无需修复）: {} — {}",
                            filename, KNOWN_BENIGN_LEGACY.get(filename));
                } else {
                    log.error("❌ 迁移失败（已跳过，继续执行其余迁移）: {}", filename, e);
                }
            }
        }
        reportFailures(failed);
    }

    /**
     * 是否**连接类**失败（而非迁移内容/SQL 有错）—— 决定走「重试 + fail-closed」还是维持 #3615 跳过语义。
     *
     * 判据取**整条 cause 链**（驱动层异常总被 Spring 包一层）：
     *   - `DataAccessResourceFailureException` 家族（实测 `CannotGetJdbcConnectionException`：
     *     「Failed to obtain JDBC Connection」，Spring 对驱动层连不上/认证失败的统一翻法）
     *     与 `SQLTransientConnectionException`（连接池拿不到连接）；
     *   - 网络层：`ConnectException`（连不上）、`SocketTimeoutException`（连接超时）、
     *     `UnknownHostException`（域名解析失败）—— 实测形态
     *     `PSQLException: 尝试连线已失败。` + `Caused by: java.net.ConnectException`。
     *
     * ⚠️ **不得**把 `DataAccessException` 一律算连接类：那会把 #3615 已裁定的内容类失败
     * （SQL 语法/约束）也拿去重试、并最终拒绝启动 —— 一条坏迁移冻结整个 schema，
     * 正是 #3270 的原始病灶。
     */
    static boolean isConnectionFailure(Throwable e) {
        for (Throwable t = e; t != null; t = t.getCause()) {
            if (t instanceof DataAccessResourceFailureException
                    || t instanceof SQLTransientConnectionException
                    || t instanceof ConnectException
                    || t instanceof SocketTimeoutException
                    || t instanceof UnknownHostException) {
                return true;
            }
            if (t.getCause() == t) {
                break;
            }
        }
        return false;
    }

    /** 最内层原因 —— 重试日志用一行说清真因（如「PSQLException: 尝试连线已失败。」）。 */
    private static Throwable rootCause(Throwable e) {
        Throwable t = e;
        while (t.getCause() != null && t.getCause() != t) {
            t = t.getCause();
        }
        return t;
    }

    /**
     * 连接类失败重试耗尽 —— **拒绝以「schema 未知」状态启动**（issue #4241）。
     *
     * 为什么选「抛异常让启动失败」而不是「照常启动 + health 报 DOWN」：编排/部署层只认
     * **启动成功与否**，health 是应用自己报的（实测它谎报过 UP）；runner 抛出的异常由 Spring
     * 记为 `Application run failed` 并原样抛给 main（实测 Spring Boot 3.3.9，**不**再包一层
     * `Failed to execute CommandLineRunner`）⇒ 进程非 0 退出 ⇒ `docker compose up --wait` 直接失败。
     */
    static class MigrationConnectionFailureException extends IllegalStateException {
        MigrationConnectionFailureException(String message, Throwable cause) {
            super(message, cause);
        }
    }

    /**
     * 本次失败的汇总行 —— **真失败与已知存量分开计数、分开级别**（issue #3714）。
     *
     * ⚠️ 为什么必须分开（本仓库核心痛点是「归因层是最大失败模式」）：bootstrap-first 评测栈
     * 上这 3 条存量迁移**每次起栈必失败**，若一律打 ERROR + 「请立即修复并在修复后重跑」——
     * 那是一句**必然为假**的行动指令（无物可修、重跑必复现）→ 告警疲劳 → 真 schema 不一致
     * 与永久噪音**长得一模一样**，真失败被淹没。
     *
     * ⚠️ 决不静默：未知失败照旧 ERROR + 非零计数 + 行动指令；只有**已诊断的存量**降级。
     */
    private void reportFailures(List<String> failed) {
        List<String> benign = failed.stream().filter(MigrationRunner::isKnownBenignLegacy).toList();
        List<String> real = failed.stream().filter(f -> !isKnownBenignLegacy(f)).toList();

        if (!benign.isEmpty()) {
            log.info("ℹ️ 本次有 {} 条迁移失败属**已知存量非幂等**（目标态已由 docs/sql/schema.sql 引导"
                            + "达成，无需修复、重跑亦会复现；见 #3615/#3714）：{}",
                    benign.size(), benign);
        }
        if (!real.isEmpty()) {
            log.error("❌ 本次有 {} 条迁移失败，schema 可能与代码不一致（请立即修复并在修复后重跑）：{}",
                    real.size(), real);
        }
    }

    // ── 已知良性存量迁移（单一事实源，与 Python 侧同测；见下）──

    /**
     * 已诊断的**历史非幂等**迁移 → 理由。命中即降级为 INFO 并单独计数，**不**触发
     * 「请立即修复并在修复后重跑」。
     *
     * 为什么这 3 条是良性的（不是「猜」）：bootstrap-first 库由
     * `docker-entrypoint-initdb.d/001_schema.sql`（即 `docs/sql/schema.sql`）建出**终态**，
     * 逐条比对确认它已覆盖这 3 条迁移的全部业务对象（`daily_briefings` 表/索引/RLS 策略、
     * `tenants.briefing_enabled`/`briefing_generate_time`、`knowledge_cards` 终态 + 3 索引），
     * 失败真因是 `ALTER ... IF EXISTS` **只守卫源对象、不守卫目标**、以及裸 `CREATE POLICY`
     * （PG 不支持 `CREATE POLICY IF NOT EXISTS`）—— 即「目标已存在」而非「对象缺失」。
     * 代价仅为噪音 + `schema_migrations` 账本失真（40/42），**无表/列缺失**。
     *
     * ⚠️ **单一事实源（#3701 教训：同一判据两份实现 ⇒ 必然漂移）**：本集合的**键集合**必须与
     * `tests/unit_ci_workflows/test_migration_idempotency.py::LEGACY_UNGUARDED` **完全相等**，
     * 由该文件的 `TestKnownBenignSetSingleSourceOfTruth`（L0，秒级零依赖）锁死 ——
     * 多一条 = 真失败被当噪音吞掉；少一条 = 哨兵兜底失效。两边必须**同步增删**。
     *
     * ⚠️ **本集合只能变短**：一旦用新迁移补齐（或存量被裁决豁免后修好），
     * 两边同时销账；陈旧登记由 Python 侧 `test_legacy_registry_matches_reality`（:313 语义）报红。
     * **新增迁移一律不得进本表**（前向防护：新迁移必须自带幂等守卫）。
     *
     * ⚠️ 解析契约（勿改形状）：常量下方那对 `MIGAO_BENIGN_LEGACY_*` 起止标记之间的**字符串字面量**
     * 会被 L0 测试按 `V{n}__desc.sql` 形态提取为键 ⇒ 键必须写成 `"文件名", "理由"` 成对出现。
     * 该标记在**全文件内必须恰好各出现一次**（本注释不能写出标记原文，否则计数为 2 → 测试 fail-closed 报红）。
     */
    // MIGAO_BENIGN_LEGACY_BEGIN
    static final Map<String, String> KNOWN_BENIGN_LEGACY = Map.of(
            "V37__rename_knowledge_entries_to_cards.sql",
            "表/索引改名目标已存在（ALTER ... IF EXISTS 只守卫源）；终态由 schema.sql 引导达成（见 #3615/#3714）",
            "V42__reconcile_knowledge_table_name.sql",
            "索引改名目标已存在（干净 bootstrap 顺序下靠 V37 的 DROP TABLE 连带删源索引而侥幸通过）；终态已达成（见 #3615/#3714）",
            "V44__create_daily_briefings.sql",
            "裸 CREATE POLICY，而 schema.sql:1212 已建同名策略 tenant_isolation_daily_briefings（PG 不支持 CREATE POLICY IF NOT EXISTS）；终态已达成（见 #3615/#3714）");
    // MIGAO_BENIGN_LEGACY_END

    /** 是否为已诊断的存量非幂等迁移（唯一实现点，`reportFailures` 与本类日志共用）。 */
    static boolean isKnownBenignLegacy(String filename) {
        return filename != null && KNOWN_BENIGN_LEGACY.containsKey(filename);
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
