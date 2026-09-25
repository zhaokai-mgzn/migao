package com.migao.admin.service;

// case_ids: MC-012, API-013

import com.migao.admin.config.MigrationRunner;
import org.junit.jupiter.api.AfterAll;
import org.mockito.ArgumentCaptor;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;
import org.springframework.core.io.support.ResourcePatternResolver;
import org.springframework.jdbc.BadSqlGrammarException;
import org.springframework.jdbc.CannotGetJdbcConnectionException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.util.ReflectionTestUtils;

import javax.sql.DataSource;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * **基线语义**守卫（issue #5243）—— 唯一那份建库脚本 `db/init/schema.sql` 的四条语义。
 *
 * <h2>为什么必须有这条守卫（病灶形态）</h2>
 *
 * 迁移链（`V1` … ）整链归档到 `db/migration-archive/` 之后，**空库建出终态的唯一路径**就是
 * 基线脚本。于是「空库到底建没建」与「存量库会不会被重放」这两件事，从「迁移链的副作用」
 * 变成了**这份脚本自身的语义**。任何一条写错都**不会**被既有判据抓到：
 *
 * <ul>
 *   <li><b>该建不建</b>（空库分支漏了执行）⇒ 全新环境起来是一张空库，业务 500 而后移到运行期；</li>
 *   <li><b>不该建却建</b>（存量库分支漏了哨兵判断）⇒ 往**活库**重放整份建库脚本
 *       （终态种子 + 大量裸 `CREATE TABLE`）⇒ 比「少建一张表」严重得多的故障。</li>
 * </ul>
 *
 * <p>两条都**不会让既有门禁变红** —— 迁移链的守卫看的是迁移文件，与这份脚本无关。</p>
 *
 * <h2>判据（四条语义 + 一份自证）</h2>
 *
 * <ol>
 *   <li>台账已有该键 ⇒ 整段跳过（不读脚本、不执行、不重复记账）；</li>
 *   <li>台账无该键 ∧ 库**非空** ⇒ **只记账、不执行**（🔴 核心：存量库绝不重放）；</li>
 *   <li>台账无该键 ∧ 库**为空** ⇒ 执行后记账；</li>
 *   <li>失败分级与迁移逐字相同：内容类 ⇒ 记入真失败清单 + 不记账、**不拒绝启动**；
 *       连接类 ⇒ 抛（交给外层退避重试 / 重试耗尽 fail-closed）。</li>
 * </ol>
 *
 * <p>判据 1~4 用 mock 打**分支**（快、CI 恒跑）；另有**真 PG** 的三条端到端判据
 * （{@code 真库红证} 前缀），它们才是「空库真能建出终态 / 存量库真的没被执行」的正面证据。
 * 真库装配**复用共用件 {@link PgCluster}**（不复制第二份 initdb/pg_ctl）；缺 PG 二进制时
 * 由 {@link PgCluster#startOrAbort()} 按 CI/本机分流（本机显式 skip、CI fail-closed 判红）。</p>
 *
 * <h2>红证（注入式，实测输出见 PR）</h2>
 *
 * <ul>
 *   <li><b>注入坏建库脚本 + 空库</b> ⇒ 判据 3 那条端到端判据转红（脚本根本没建成终态）；</li>
 *   <li><b>同一份坏脚本 + 存量库</b> ⇒ 判据 2 仍绿（只记账、不执行）—— 证明「不执行」是**被断言的
 *       行为**而不是「碰巧没跑到」：真执行了就会留下失败计数。</li>
 * </ul>
 *
 * <p>⚠️ 射程（如实登记）：本测试覆盖的是 **runner 的基线分支与其在真 PG 上的效果**，
 * 不等价于「生产部署已验证」（那要起整套 docker 栈）。</p>
 */
@DisplayName("#5243 基线语义：唯一建库脚本的四条语义 + 真库红证")
class MigrationBaselineSemanticsTest {

    private static final String BASELINE_KEY = "schema.sql";
    private static final String LEDGER_INSERT = "INSERT INTO schema_migrations (version) VALUES (?)";
    /** 只有基线脚本才含的标记 —— 用来判「到底执行没执行」（比"某方法被调用"更贴近被测行为）。 */
    private static final String MARKER_TABLE = "baseline_marker_table";
    private static final String BASELINE_SQL = "CREATE TABLE " + MARKER_TABLE + " (id INTEGER);\n";

    /** 真 PG 集群（懒启动：mock 那几条判据不需要它，缺 PG 时不能让它们一起被 abort）。 */
    private static PgCluster cluster;
    private static DataSource adminDataSource;

    @AfterAll
    static void stopCluster() {
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ── 判据 1：台账已有该键 ⇒ 整段跳过 ────────────────────────────────────────

    @Test
    @DisplayName("判据 1：台账已有 schema.sql ⇒ 整段跳过（不探库、不读脚本、不重复记账）")
    void baselineIsSkippedWhenLedgerAlreadyHasTheKey() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        Resource baseline = mock(Resource.class);
        when(baseline.getFilename()).thenReturn(BASELINE_KEY);
        when(baseline.exists()).thenReturn(true);
        when(jdbc.queryForList("SELECT version FROM schema_migrations", String.class))
                .thenReturn(List.of(BASELINE_KEY));

        MigrationRunner runner = mockedRunner(jdbc, baseline, "classpath:db/init/schema.sql");
        runner.run();

        verify(baseline, never()).getInputStream();
        verify(jdbc, never()).queryForObject(anyString(), eq(Boolean.class), anyString());
        verify(jdbc, never()).update(eq(LEDGER_INSERT), eq(BASELINE_KEY));
        assertThat(runner.getLastFailedRealCount()).as("跳过不是失败").isZero();
    }

    // ── 判据 2：台账无该键 ∧ 库非空 ⇒ 只记账、不执行（🔴 核心） ────────────────

    @Test
    @DisplayName("判据 2：库非空（哨兵表 tenants 在）⇒ **只记账、不执行**（存量库绝不重放建库脚本）")
    void existingDatabaseRecordsBaselineWithoutExecutingIt() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        Resource baseline = mock(Resource.class);
        when(baseline.getFilename()).thenReturn(BASELINE_KEY);
        when(baseline.exists()).thenReturn(true);
        when(jdbc.queryForList("SELECT version FROM schema_migrations", String.class))
                .thenReturn(List.of());
        when(jdbc.queryForObject(anyString(), eq(Boolean.class), eq("tenants"))).thenReturn(true);

        MigrationRunner runner = mockedRunner(jdbc, baseline, "classpath:db/init/schema.sql");
        runner.run();

        // 🔴 核心断言：脚本**根本没被读**（读了才可能执行）。用「输入流未被取用」而不是
        // 「execute 未被调用」—— 后者会被 ensureHistoryTable 的 CREATE TABLE 误伤而写不出断言。
        verify(baseline, never()).getInputStream();
        verify(jdbc).update(LEDGER_INSERT, BASELINE_KEY);
        assertThat(runner.getLastFailedRealCount()).isZero();
    }

    // ── 判据 3：台账无该键 ∧ 库为空 ⇒ 执行后记账 ───────────────────────────────

    @Test
    @DisplayName("判据 3：空库（哨兵表不在）⇒ 执行建库脚本后记账")
    void emptyDatabaseExecutesBaselineThenRecordsIt() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        Resource baseline = mock(Resource.class);
        when(baseline.getFilename()).thenReturn(BASELINE_KEY);
        when(baseline.exists()).thenReturn(true);
        when(baseline.getInputStream()).thenAnswer(
                inv -> new ByteArrayInputStream(BASELINE_SQL.getBytes(StandardCharsets.UTF_8)));
        when(jdbc.queryForList("SELECT version FROM schema_migrations", String.class))
                .thenReturn(List.of());
        when(jdbc.queryForObject(anyString(), eq(Boolean.class), eq("tenants"))).thenReturn(false);

        MigrationRunner runner = mockedRunner(jdbc, baseline, "classpath:db/init/schema.sql");
        runner.run();

        assertThat(executedSql(jdbc))
                .as("空库必须**真的执行**了建库脚本")
                .anyMatch(sql -> sql.contains(MARKER_TABLE));
        verify(jdbc).update(LEDGER_INSERT, BASELINE_KEY);
        assertThat(runner.getLastFailedRealCount()).isZero();
    }

    // ── 判据 4：失败分级（内容类不拒启动；连接类抛） ────────────────────────────

    @Test
    @DisplayName("判据 4a：空库上建库脚本**内容**失败 ⇒ 记入真失败 + 不记账 + 不拒绝启动")
    void contentFailureOfBaselineIsRecordedButDoesNotBlockStartup() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        Resource baseline = mock(Resource.class);
        when(baseline.getFilename()).thenReturn(BASELINE_KEY);
        when(baseline.exists()).thenReturn(true);
        when(baseline.getInputStream()).thenAnswer(
                inv -> new ByteArrayInputStream(BASELINE_SQL.getBytes(StandardCharsets.UTF_8)));
        when(jdbc.queryForList("SELECT version FROM schema_migrations", String.class))
                .thenReturn(List.of());
        when(jdbc.queryForObject(anyString(), eq(Boolean.class), eq("tenants"))).thenReturn(false);
        doAnswer(inv -> {
            String sql = inv.getArgument(0, String.class);
            if (sql != null && sql.contains(MARKER_TABLE)) {
                throw new BadSqlGrammarException("基线", sql,
                        new SQLException("syntax error at or near \"boom\"", "42601"));
            }
            return null;
        }).when(jdbc).execute(anyString());

        MigrationRunner runner = mockedRunner(jdbc, baseline, "classpath:db/init/schema.sql");
        // 内容类失败**不抛**（#3615 / #3270 的刻意权衡，逐字未改）
        assertThatCode(runner::run).doesNotThrowAnyException();

        assertThat(runner.getLastFailedRealCount()).as("空库上建库失败必须算真失败（不是良性存量）")
                .isEqualTo(1);
        assertThat(runner.getLastFailedMigrations()).containsExactly(BASELINE_KEY);
        verify(jdbc, never()).update(eq(LEDGER_INSERT), eq(BASELINE_KEY));
    }

    @Test
    @DisplayName("判据 4b：探库/建库遇**连接类**失败 ⇒ 抛（外层退避重试，耗尽即 fail-closed）")
    void connectionFailurePropagatesAsFailClosed() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        Resource baseline = mock(Resource.class);
        when(baseline.getFilename()).thenReturn(BASELINE_KEY);
        when(baseline.exists()).thenReturn(true);
        when(jdbc.queryForList("SELECT version FROM schema_migrations", String.class))
                .thenReturn(List.of());
        when(jdbc.queryForObject(anyString(), eq(Boolean.class), eq("tenants")))
                .thenThrow(new CannotGetJdbcConnectionException("拿不到连接"));

        MigrationRunner runner = mockedRunner(jdbc, baseline, "classpath:db/init/schema.sql");
        // 只跑一次尝试，别让退避把单测拖成 ~24s
        ReflectionTestUtils.setField(runner, "maxConnectAttempts", 1);
        ReflectionTestUtils.setField(runner, "connectRetryBackoffMs", 0L);

        assertThatThrownBy(runner::run)
                .as("连接类失败必须 fail-closed 拒绝启动（不让 health 谎报 UP）")
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("拒绝启动");
    }

    @Test
    @DisplayName("判据 4c：脚本资源不存在 ⇒ 记入真失败 + 指名路径（不静默）")
    void missingBaselineResourceIsReportedNotSilentlyIgnored() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        Resource baseline = mock(Resource.class);
        when(baseline.getFilename()).thenReturn(BASELINE_KEY);
        when(baseline.exists()).thenReturn(false);
        when(jdbc.queryForList("SELECT version FROM schema_migrations", String.class))
                .thenReturn(List.of());

        MigrationRunner runner = mockedRunner(jdbc, baseline, "classpath:db/init/schema.sql");
        runner.run();

        assertThat(runner.getLastFailedRealCount()).isEqualTo(1);
        assertThat(runner.getLastFailedMigrations()).containsExactly(BASELINE_KEY);
    }

    // ── 真库（端到端）：空库真建得出终态 / 存量库真的没被执行 ──────────────────

    @Test
    @DisplayName("真库：空库 + **仓库里那份真的**建库脚本 ⇒ 建出终态（tenants 在）+ 记账 + 零失败")
    void realDatabaseEmptyBuildsTerminalStateFromTheRealInitScript() throws Exception {
        JdbcTemplate jdbc = new JdbcTemplate(freshDatabase("migao_baseline_empty"));
        assertThat(tableExists(jdbc, "tenants")).as("前置：新库必须是空的").isFalse();

        MigrationRunner runner = realRunner(jdbc, repoInitScript().toString());
        runner.run();

        assertThat(runner.getLastFailedRealCount()).as("空库上真脚本必须零失败").isZero();
        assertThat(tableExists(jdbc, "tenants")).as("空库必须被真的建出终态").isTrue();
        assertThat(ledgerContains(jdbc, BASELINE_KEY)).as("建完必须记账（幂等的前提）").isTrue();

        // 幂等：再跑一遍 ⇒ 走「台账已有该键」分支，一字不动、零失败
        runner.run();
        assertThat(runner.getLastFailedRealCount()).isZero();
    }

    @Test
    @DisplayName("真库红证（a）：空库 + **注入的坏脚本** ⇒ 基线走「执行」分支且失败（判据会红）")
    void realDatabaseEmptyWithFaultyInitScriptFails() throws Exception {
        JdbcTemplate jdbc = new JdbcTemplate(freshDatabase("migao_baseline_faulty_empty"));
        Path faulty = faultyInitScript("faulty-init.sql");
        assertThat(tableExists(jdbc, "tenants")).isFalse();

        MigrationRunner runner = realRunner(jdbc, faulty.toString());
        runner.run();

        assertThat(runner.getLastFailedRealCount())
                .as("空库上坏脚本 ⇒ 判据 3 的「建出终态」必然不成立 ⇒ 这里必须红")
                .isEqualTo(1);
        assertThat(runner.getLastFailedMigrations()).containsExactly("faulty-init.sql");
        assertThat(tableExists(jdbc, "tenants")).as("坏脚本建不出终态（这就是红）。").isFalse();
        assertThat(ledgerContains(jdbc, "faulty-init.sql")).as("失败不得记账（否则永远不再重试）")
                .isFalse();
    }

    @Test
    @DisplayName("真库红证（b）：**同一份坏脚本** + 存量库 ⇒ 只记账、不执行、零失败（判据 2 仍是绿的）")
    void realDatabaseExistingWithSameFaultyInitScriptIsUntouched() throws Exception {
        JdbcTemplate jdbc = new JdbcTemplate(freshDatabase("migao_baseline_faulty_existing"));
        // 造「存量库」：哨兵表在（等价于任何一张老库都有的 tenants）
        try (Connection conn = jdbc.getDataSource().getConnection();
             Statement st = conn.createStatement()) {
            st.execute("CREATE TABLE tenants (id BIGINT PRIMARY KEY)");
            st.execute("INSERT INTO tenants (id) VALUES (1)");
        }
        Path faulty = faultyInitScript("faulty-init.sql");

        MigrationRunner runner = realRunner(jdbc, faulty.toString());
        runner.run();

        assertThat(runner.getLastFailedRealCount())
                .as("存量库上**绝不执行** ⇒ 坏脚本没有机会失败（真执行了这里会是 1）")
                .isZero();
        assertThat(ledgerContains(jdbc, "faulty-init.sql")).as("只记账").isTrue();
        assertThat(rowCount(jdbc, "tenants")).as("存量数据一字未动").isEqualTo(1);
    }

    // ── 夹具 ──

    private static MigrationRunner mockedRunner(JdbcTemplate jdbc, Resource baseline, String location) {
        ResourcePatternResolver resolver = mock(ResourcePatternResolver.class);
        when(resolver.getResource(anyString())).thenReturn(baseline);
        try {
            when(resolver.getResources(anyString())).thenReturn(new Resource[0]);
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
        MigrationRunner runner = new MigrationRunner(provider(jdbc), resolver);
        ReflectionTestUtils.setField(runner, "migrationPattern", "classpath:db/migration/*.sql");
        ReflectionTestUtils.setField(runner, "initScriptLocation", location);
        return runner;
    }

    /**
     * 真库装配：**基线语义**判据专用。
     *
     * <p>⚠️ 此处**刻意**把 {@code migrationPattern} 指向一个**真的存在但为空**的临时目录（用不存在的
     * {@code file:} 目录会让 Spring 的路径匹配抛错，把判据变成「测夹具」）：本类三条真库判据断言的是
     * **基线分支**（台账已有该键 / 存量库 / 空库），若让活迁移链同时跑，两个被测对象会混在一个判据里
     * —— 活链里任何一条失败都会表现成「基线判据红」，归因层就废了。</p>
     *
     * <p>🔴 **这条注释曾经是错的**（issue #4778）：原文写「归档链后活目录为空」，而
     * {@code backend/admin-api/src/main/resources/db/migration/} 早已又长回活迁移
     * （写这句的时刻是 {@code V123} … {@code V129}，且会继续增长）—— 注释与判据**一起过期**，
     * 而没有任何东西会因此变红。活链的 runner 语义（单事务 / 失败整份回滚 / 不记账 / 二跑幂等）
     * 由 {@code MigrationRunnerLiveChainRealDbTest} 在真 PG 上**真跑**，其中有一条前置自断言：
     * 活目录空掉即判红。这里**不再复述**活目录的内容 —— 复述事实的注释必然腐烂，指路即可。</p>
     */
    private static MigrationRunner realRunner(JdbcTemplate jdbc, String initScriptLocation) {
        MigrationRunner runner = new MigrationRunner(provider(jdbc),
                new PathMatchingResourcePatternResolver());
        ReflectionTestUtils.setField(runner, "migrationPattern", emptyMigrationDir() + "/*.sql");
        ReflectionTestUtils.setField(runner, "initScriptLocation", "file:" + initScriptLocation);
        return runner;
    }

    /** 一个空目录的 `file:` 前缀（懒建一次，三条真库判据共用）。 */
    private static String emptyMigrationDir() {
        if (emptyDir == null) {
            try {
                emptyDir = "file:" + Files.createTempDirectory("migao-5243-no-migrations");
            } catch (Exception e) {
                throw new IllegalStateException(e);
            }
        }
        return emptyDir;
    }

    private static String emptyDir;

    @SuppressWarnings("unchecked")
    private static ObjectProvider<JdbcTemplate> provider(JdbcTemplate jdbc) {
        ObjectProvider<JdbcTemplate> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(jdbc);
        return provider;
    }

    /** 仓库里那份**真的**建库脚本（不手抄、不复制第二份路径常量）。 */
    private static Path repoInitScript() {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null
                && !Files.exists(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 backend/admin-api/src/main/resources/db/init/schema.sql")
                .isNotNull();
        return root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql");
    }

    /** 注入用的坏建库脚本：语法错（起手就炸，不会把库建成半成品）。 */
    private static Path faultyInitScript(String name) throws Exception {
        Path dir = Files.createTempDirectory("migao-5243-faulty");
        Path file = dir.resolve(name);
        Files.writeString(file, "CREATE TABLE broken_5243 (\n  id INTEGER\n-- 故意不闭合\n", StandardCharsets.UTF_8);
        file.toFile().deleteOnExit();
        return file;
    }

    /**
     * 每次判据一个**全新 database**（同一个一次性集群内）—— 三条真库判据的状态互不污染，
     * 否则「空库」判据会被前面建出来的 `tenants` 悄悄变成「存量库」判据（判据自己选择沉默）。
     */
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

    /** 所有被 `jdbc.execute(String)` 执行过的 SQL（判「到底执行没执行」用捕获，不用含糊的 matcher）。 */
    private static List<String> executedSql(JdbcTemplate jdbc) {
        ArgumentCaptor<String> captor = ArgumentCaptor.forClass(String.class);
        verify(jdbc, atLeastOnce()).execute(captor.capture());
        return captor.getAllValues();
    }

    private static boolean tableExists(JdbcTemplate jdbc, String table) {
        Boolean present = jdbc.queryForObject(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = ?)",
                Boolean.class, table);
        return Boolean.TRUE.equals(present);
    }

    private static boolean ledgerContains(JdbcTemplate jdbc, String key) {
        return jdbc.queryForList("SELECT version FROM schema_migrations", String.class).contains(key);
    }

    private static int rowCount(JdbcTemplate jdbc, String table) {
        Integer n = jdbc.queryForObject("SELECT COUNT(*) FROM " + table, Integer.class);
        return n == null ? -1 : n;
    }
}