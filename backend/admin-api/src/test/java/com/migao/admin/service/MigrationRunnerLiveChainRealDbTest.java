package com.migao.admin.service;

// case_ids: MC-012

import com.migao.admin.config.MigrationRunner;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.util.ReflectionTestUtils;

import javax.sql.DataSource;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * **活迁移链的 runner 事务语义**（issue #4778）—— 真 PG 上真跑 {@link MigrationRunner}。
 *
 * <h2>为什么必须有这条判据（病灶形态）</h2>
 *
 * 本仓对「迁移怎么被执行」的既有判据**全是文本断言或 mock 分支**（逐条清单见 issue #4778 的
 * 收口评论）。于是**执行语义**——「整份文件是一个事务吗？」「失败的那份会不会留下半成品？」
 * 「失败的会不会被记账（⇒ 永不重试）？」——在 CI 里**从未被真跑过**，只有上线时才知道；
 * 本仓的 V79 事故（整文件回滚）正是这一类。更危险的是**判据自己会静默变空**：
 * {@code MigrationBaselineSemanticsTest} 的 {@code realRunner()} 把 {@code migrationPattern}
 * 指向一个**空临时目录**（当时迁移链已整链归档，注释写的也是「活目录为空」），
 * 而此后 {@code db/migration/} 又长回了活迁移（V123 …）——注释与判据**一起过期而没有任何东西变红**。
 *
 * <h2>判据（两条，都在真库上）</h2>
 *
 * <ol>
 *   <li><b>活链本身</b>（{@link #liveMigrationChainReallyRunsOnBootstrapDatabaseAndIsIdempotent()}）：
 *       把 {@code migrationPattern} 指向**仓库里那份真的** {@code db/migration/*.sql}，
 *       {@code initScriptLocation} 指向**仓库里那份真的** {@code db/init/schema.sql}
 *       （空库 → 基线建终态 → 活链增量），断言零真失败、每条活迁移都记入台账、
 *       **首轮一条都没被台账跳过**（否则「跑了」是假的）；再跑第二轮：全部按台账跳过、
 *       台账行数不变、schema 指纹逐字节不变（= 幂等、不重复应用）。</li>
 *   <li><b>失败整份回滚 + 不记账</b>（{@link #faultyMultiStatementMigrationRollsBackWholeFileAndIsNotRecorded()}）：
 *       临时目录里两份**注入的**坏迁移（① 无显式事务控制的多语句；② 与活链同形的
 *       {@code BEGIN … COMMIT} 块内失败），各在自己的**建表之后**踩一条主键冲突 ⇒
 *       断言两张「半成品」表**都不存在**（半成品状态不可观测），且两条都**不在台账里**
 *       （失败必须可重试）。同目录放一条健康迁移作**对照组**：它必须建出表并记账 ——
 *       否则「坏迁移没留半成品」可能只是「这一轮压根没跑」。</li>
 * </ol>
 *
 * <h2>夹具为什么不碰真迁移</h2>
 *
 * 坏迁移写在**临时目录**（{@link #fixtureMigrations()}），只经由 {@code migrationPattern} 被扫到：
 * 已发布迁移有逐字节指纹账本（{@code tests/unit_ci_workflows/migration_fingerprints.json}）冻结，
 * 判据**不得**靠改写真文件来造红（那既是「改已发布迁移」，也会让判据与被测对象同源）。
 *
 * <h2>红证（注入式，实测输出见 PR）</h2>
 *
 * <ul>
 *   <li><b>把 runner 改成逐语句 autocommit</b>（{@code jdbc.execute(sql)} → 按 {@code ;} 拆开逐句执行）
 *       ⇒ 判据 2 的「半成品表不存在」转红（半成品变得可观测）；改回即绿。</li>
 *   <li><b>把活迁移目录指向一个空目录</b>（复现「全链归档后」的世界）⇒ 判据 1 的**前置自断言**转红：
 *       「没跑」必须长得像「没跑」，不许静默退化成空断言。</li>
 * </ul>
 *
 * <h2>射程（如实登记）</h2>
 *
 * <ul>
 *   <li>覆盖的是 **runner 在真 PG 上的执行语义**，不等价于「生产部署已验证」（那要起整套 docker 栈）；</li>
 *   <li>归档链（{@code db/migration-archive/V1 …}）**不重放** —— 空库建终态走基线脚本是本仓的现行路径，
 *       重放归档链是另一个问题；本判据覆盖的是**同一种执行路径**（整份文件一次 {@code jdbc.execute}）
 *       与**同一种文件形态**（多语句 / 显式 {@code BEGIN … COMMIT}），归档链里的 V97 属同一形态；</li>
 *   <li>真库装配复用共用件 {@link PgCluster}：缺 PG 二进制时本机显式 skip、CI（{@code MIGAO_REQUIRE_REALDB=1}）
 *       **fail-closed 判红**，该语义一字未改。</li>
 * </ul>
 */
@DisplayName("#4778 活迁移链 runner 语义：真 PG 上真跑 + 失败整份回滚 + 不记账 + 二跑幂等")
class MigrationRunnerLiveChainRealDbTest {

    /** 活迁移目录（相对仓库根）—— 本判据的被测对象，**不指向空目录**。 */
    private static final String LIVE_MIGRATION_DIR = "backend/admin-api/src/main/resources/db/migration";
    /** 空库建出终态的唯一路径（基线脚本）；活链的前置。 */
    private static final String INIT_SCRIPT = "backend/admin-api/src/main/resources/db/init/schema.sql";

    private static final String HEALTHY_NAME = "V899__healthy_sibling.sql";
    private static final String IMPLICIT_NAME = "V900__faulty_implicit_txn.sql";
    private static final String EXPLICIT_NAME = "V901__faulty_explicit_txn.sql";
    private static final String HEALTHY_TABLE = "migao_4778_healthy";
    private static final String IMPLICIT_TABLE = "migao_4778_partial_implicit";
    private static final String EXPLICIT_TABLE = "migao_4778_partial_explicit";
    private static final String BASELINE_FIXTURE_NAME = "migao_4778_baseline_fixture.sql";
    private static final String BASELINE_FIXTURE_TABLE = "migao_4778_baseline_marker";

    /** 显式事务控制的形态标记（前置自断言用：活链里必须真的还有这种文件）。 */
    private static final Pattern BEGIN_LINE = Pattern.compile("(?m)^\\s*BEGIN\\s*;");
    private static final Pattern COMMIT_LINE = Pattern.compile("(?m)^\\s*COMMIT\\s*;");

    /** 真 PG 集群（懒启动：拿不到集群时由 {@link PgCluster#startOrAbort()} 按本机/CI 分流）。 */
    private static PgCluster cluster;
    private static DataSource adminDataSource;

    @AfterAll
    static void stopCluster() {
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ── 判据 1：活链真跑 + 二跑幂等 ─────────────────────────────────────────────

    @Test
    @DisplayName("判据 1：活迁移目录（真文件）在 bootstrap 库上真跑 ⇒ 零失败 + 全记账 + 二跑全部跳过且终态逐字节不变")
    void liveMigrationChainReallyRunsOnBootstrapDatabaseAndIsIdempotent() throws Exception {
        List<String> liveNames = liveMigrationNames();
        // 前置自断言（#4778 的病灶就在这里）：活目录空掉时，本判据会**静默退化成空断言** ——
        // 那种「绿」不是通过。故先把「判据还在被测对象上」钉死。
        assertThat(liveNames)
                .as("前置：%s 必须真的还有活迁移（全链归档后本判据即失效，必须红而不是静默空跑）",
                        LIVE_MIGRATION_DIR)
                .isNotEmpty();
        assertThat(liveMigrationsWithExplicitTransactionControl())
                .as("前置：活迁移里必须至少有一条显式 BEGIN/COMMIT（本判据要覆盖的形态；形态消失即判据不再覆盖它）")
                .isNotEmpty();

        JdbcTemplate jdbc = new JdbcTemplate(freshDatabase("migao_4778_live_chain"));
        MigrationRunner runner = realRunner(jdbc, repoPath(INIT_SCRIPT).toString(), liveMigrationPattern());
        runner.run();

        assertThat(runner.getLastFailedRealCount())
                .as("活链在 bootstrap 库上必须零真失败（有失败就是本判据要抓的形态；失败清单=%s）",
                        runner.getLastFailedMigrations())
                .isZero();
        assertThat(runner.getLastSkippedByLedger())
                .as("首轮只许跳过**基线那一条**（%s）—— 任何一条活迁移被跳过都说明「活链真的被执行过」是假的",
                        INIT_SCRIPT)
                .isEqualTo(1);
        assertThat(tableExists(jdbc, "tenants")).as("基线必须先建出终态（活链的前置）").isTrue();
        assertThat(ledgerKeys(jdbc))
                .as("每条活迁移都必须记入台账（= 真的被执行过；缺一条即静默漏跑）")
                .containsAll(liveNames);

        String terminalBefore = schemaSignature(jdbc);
        int ledgerBefore = ledgerKeys(jdbc).size();

        runner.run();   // 第二轮：同一条链、同一个库

        assertThat(runner.getLastFailedRealCount()).as("二跑仍须零真失败").isZero();
        assertThat(runner.getLastSkippedByLedger())
                .as("二跑必须**全部**按台账跳过（活迁移 %d 条 + 基线键 1 条）—— 这就是「不重复应用」",
                        liveNames.size())
                .isEqualTo(liveNames.size() + 1);
        assertThat(ledgerKeys(jdbc)).as("二跑不得新增任何台账行（重复应用会在这里留下第二行）")
                .hasSize(ledgerBefore);
        assertThat(schemaSignature(jdbc)).as("二跑后终态必须逐字节不变（幂等）").isEqualTo(terminalBefore);
    }

    // ── 判据 2：失败 ⇒ 整份回滚 + 不记账 ────────────────────────────────────────

    @Test
    @DisplayName("判据 2：多语句迁移中途失败 ⇒ 整份回滚（无半成品）+ 不记账；同目录健康迁移照常成功")
    void faultyMultiStatementMigrationRollsBackWholeFileAndIsNotRecorded() throws Exception {
        JdbcTemplate jdbc = new JdbcTemplate(freshDatabase("migao_4778_faulty_chain"));
        Path fixtures = fixtureMigrations();

        MigrationRunner runner = realRunner(jdbc,
                fixtureInitScript().toString(), "file:" + fixtures + "/*.sql");
        runner.run();

        assertThat(runner.getLastFailedRealCount())
                .as("两条坏迁移各失败一次（失败清单=%s）", runner.getLastFailedMigrations())
                .isEqualTo(2);
        assertThat(runner.getLastFailedMigrations())
                .as("失败必须点名到**文件**（归因层：不许只记「有失败」）")
                .containsExactlyInAnyOrder(IMPLICIT_NAME, EXPLICIT_NAME);
        assertThat(tableExists(jdbc, HEALTHY_TABLE))
                .as("对照组：同目录的健康迁移必须真的建出表 —— 否则「没留半成品」可能只是这一轮没跑")
                .isTrue();
        assertThat(tableExists(jdbc, IMPLICIT_TABLE))
                .as("① 无显式事务控制的多语句：第 3 句主键冲突 ⇒ 整份单事务回滚，建表 + 已插入行都不得留下")
                .isFalse();
        assertThat(tableExists(jdbc, EXPLICIT_TABLE))
                .as("② 显式 BEGIN/COMMIT 且失败发生在 COMMIT 之前 ⇒ 无任何已提交内容，半成品表不得留下")
                .isFalse();
        assertThat(ledgerKeys(jdbc))
                .as("失败的两条**不得记账**（记了账 ⇒ 永不重试）；成功的那条必须记账")
                .contains(HEALTHY_NAME)
                .doesNotContain(IMPLICIT_NAME, EXPLICIT_NAME);

        // 二跑：失败的按既有语义**重试并再次失败**（仍不许留下半成品），成功的那条按台账跳过。
        runner.run();

        assertThat(runner.getLastFailedRealCount()).as("二跑仍点名同一批失败（不因首跑而变绿）").isEqualTo(2);
        assertThat(tableExists(jdbc, IMPLICIT_TABLE)).as("二跑后①仍不得有半成品").isFalse();
        assertThat(tableExists(jdbc, EXPLICIT_TABLE)).as("二跑后②仍不得有半成品").isFalse();
        assertThat(ledgerKeys(jdbc)).as("二跑不得给失败的迁移补记账").doesNotContain(IMPLICIT_NAME, EXPLICIT_NAME);
    }

    // ── 夹具 ──

    /** 活迁移目录里的文件名，按 runner 的**同一个**比较器排序（不另写一套排序口径）。 */
    private static List<String> liveMigrationNames() throws Exception {
        Path dir = liveMigrationDir();
        List<String> names = new ArrayList<>();
        try (Stream<Path> files = Files.list(dir)) {
            for (Path file : files.toList()) {
                if (file.getFileName().toString().endsWith(".sql")) {
                    names.add(file.getFileName().toString());
                }
            }
        }
        return MigrationRunner.sortMigrationNames(names);
    }

    /** 活迁移里含显式 {@code BEGIN} **且** {@code COMMIT} 的那些（前置自断言用；读的是真文件）。 */
    private static List<String> liveMigrationsWithExplicitTransactionControl() throws Exception {
        Path dir = liveMigrationDir();
        List<String> withTransactionControl = new ArrayList<>();
        for (String name : liveMigrationNames()) {
            String sql = Files.readString(dir.resolve(name), StandardCharsets.UTF_8);
            if (BEGIN_LINE.matcher(sql).find() && COMMIT_LINE.matcher(sql).find()) {
                withTransactionControl.add(name);
            }
        }
        return withTransactionControl;
    }

    /** **被测对象**的唯一定位点（活迁移目录）—— 三条调用点共用，红证注入也只改这一处。 */
    private static Path liveMigrationDir() {
        return repoPath(LIVE_MIGRATION_DIR);
    }

    /**
     * 注入用的坏迁移 + 对照组，写在**临时目录**里（真迁移有指纹账本冻结，判据不得靠改写它造红）。
     *
     * <p>两份坏迁移的失败点都在**建表之后**：半成品如果留下，就一定看得见。</p>
     */
    private static Path fixtureMigrations() throws Exception {
        Path dir = Files.createTempDirectory("migao-4778-fixtures");
        Files.writeString(dir.resolve(HEALTHY_NAME), """
                -- 对照组（issue #4778）：同目录里必须成功的那条 —— 没有它，「坏迁移没留下半成品」
                -- 可能只是「这一轮压根没跑」。
                CREATE TABLE IF NOT EXISTS %s (id INTEGER PRIMARY KEY);
                """.formatted(HEALTHY_TABLE), StandardCharsets.UTF_8);
        Files.writeString(dir.resolve(IMPLICIT_NAME), """
                -- 形态①（issue #4778）：**无**显式事务控制的多语句。runner 把整份文本一次
                -- `jdbc.execute(...)` ⇒ PG 单一隐式事务 ⇒ 第 3 句主键冲突时整份回滚。
                -- 半成品（表 + 第 2 句那行）若能被观测到，就是判据 2 要抓的形态。
                CREATE TABLE %s (id INTEGER PRIMARY KEY);
                INSERT INTO %s (id) VALUES (1);
                INSERT INTO %s (id) VALUES (1);
                INSERT INTO %s (id) VALUES (2);
                """.formatted(IMPLICIT_TABLE, IMPLICIT_TABLE, IMPLICIT_TABLE, IMPLICIT_TABLE),
                StandardCharsets.UTF_8);
        Files.writeString(dir.resolve(EXPLICIT_NAME), """
                -- 形态②（issue #4778）：与活链 V123/V124/V125/V127/V129 同形 —— 文件内显式
                -- BEGIN/COMMIT，失败发生在 COMMIT **之前** ⇒ 不该有任何已提交内容。
                BEGIN;
                CREATE TABLE %s (id INTEGER PRIMARY KEY);
                INSERT INTO %s (id) VALUES (1);
                INSERT INTO %s (id) VALUES (1);
                COMMIT;
                """.formatted(EXPLICIT_TABLE, EXPLICIT_TABLE, EXPLICIT_TABLE), StandardCharsets.UTF_8);
        return dir;
    }

    /** 夹具基线脚本：放在**另一个**临时目录（否则会被 {@code *.sql} 当成又一份迁移重复执行）。 */
    private static Path fixtureInitScript() throws Exception {
        Path dir = Files.createTempDirectory("migao-4778-init");
        Path file = dir.resolve(BASELINE_FIXTURE_NAME);
        Files.writeString(file, "CREATE TABLE IF NOT EXISTS " + BASELINE_FIXTURE_TABLE + " (id INTEGER PRIMARY KEY);\n",
                StandardCharsets.UTF_8);
        return file;
    }

    private static MigrationRunner realRunner(JdbcTemplate jdbc, String initScriptLocation, String pattern) {
        MigrationRunner runner = new MigrationRunner(provider(jdbc), new PathMatchingResourcePatternResolver());
        ReflectionTestUtils.setField(runner, "migrationPattern", pattern);
        ReflectionTestUtils.setField(runner, "initScriptLocation", "file:" + initScriptLocation);
        return runner;
    }

    private static String liveMigrationPattern() {
        return "file:" + liveMigrationDir().toAbsolutePath() + "/*.sql";
    }

    /** 仓库根相对路径的绝对定位（从测试工作目录逐级上溯；找不到即抛，不静默）。 */
    private static Path repoPath(String relative) {
        Path cur = Paths.get("").toAbsolutePath();
        while (cur != null) {
            Path candidate = cur.resolve(relative);
            if (Files.isDirectory(candidate) || Files.isRegularFile(candidate)) {
                return candidate;
            }
            cur = cur.getParent();
        }
        throw new IllegalStateException("找不到仓库内的 " + relative + "（测试工作目录 = " + Paths.get("").toAbsolutePath() + "）");
    }

    @SuppressWarnings("unchecked")
    private static ObjectProvider<JdbcTemplate> provider(JdbcTemplate jdbc) {
        ObjectProvider<JdbcTemplate> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(jdbc);
        return provider;
    }

    /** 每条判据一个**全新 database**（同一个一次性集群内），避免判据之间互相污染。 */
    private static DataSource freshDatabase(String name) throws Exception {
        DataSource admin = realDataSource();
        try (Connection conn = admin.getConnection(); Statement st = conn.createStatement()) {
            st.execute("DROP DATABASE IF EXISTS " + name);
            st.execute("CREATE DATABASE " + name);
        }
        String url = ((DriverManagerDataSource) admin).getUrl()
                .replaceFirst("/postgres\\?", "/" + name + "?");
        DriverManagerDataSource ds = new DriverManagerDataSource(url, "postgres", "");
        ds.setDriverClassName("org.postgresql.Driver");
        return ds;
    }

    private static DataSource realDataSource() throws Exception {
        if (cluster == null) {
            cluster = PgCluster.startOrAbort();   // 缺 PG 二进制 ⇒ CI 判红 / 本机显式 skip
            adminDataSource = cluster.dataSource();
        }
        return adminDataSource;
    }

    private static boolean tableExists(JdbcTemplate jdbc, String table) {
        Boolean present = jdbc.queryForObject(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = ?)",
                Boolean.class, table);
        return Boolean.TRUE.equals(present);
    }

    private static List<String> ledgerKeys(JdbcTemplate jdbc) {
        return jdbc.queryForList("SELECT version FROM schema_migrations", String.class);
    }

    /**
     * `public` 下「表 + 列 + 类型」的指纹（排序后取 md5）—— 用来判「二跑后终态是否逐字节不变」。
     * 比「表数量相等」强：后者对「列被删/类型被改」完全无感。
     */
    private static String schemaSignature(JdbcTemplate jdbc) {
        return jdbc.queryForObject("""
                SELECT COALESCE(md5(string_agg(table_name || '.' || column_name || ':' || data_type,
                                             ',' ORDER BY table_name, column_name)), 'empty')
                FROM information_schema.columns
                WHERE table_schema = 'public'
                """, String.class);
    }
}
