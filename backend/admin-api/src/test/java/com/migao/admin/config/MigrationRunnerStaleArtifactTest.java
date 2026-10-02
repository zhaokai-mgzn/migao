package com.migao.admin.config;

// case_ids: API-013, MC-012

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.ResourcePatternResolver;
import org.springframework.jdbc.BadSqlGrammarException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.sql.SQLException;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 陈旧构建产物（classpath 有、源码树没有）**不得被静默重跑**（issue #5981）。
 *
 * ## 病灶（实测，issue #5981）
 *
 * `target/classes/db/migration/` 里的陈旧产物被 classpath 扫到 ⇒ 已**退休**（迁到
 * `backend/admin-api/src/main/resources/db/migration-archive/`）的迁移被**重新执行**，启动日志报
 * 5 条失败（`V108/V111/V112` 的 `column "selling_method" does not exist`、`V72` 的
 * `relation "production_option_factors" does not exist`、`V79` 唯一键冲突），
 * 而同一 JVM 的后续请求被半迁移状态污染。
 *
 * 现有语义下这些失败**只打 ERROR 然后继续启动**（#3615/#3270 的刻意权衡：一条坏迁移不得冻结整个
 * schema）⇒ 「陈旧产物」这种**部署事故**与「一条真坏迁移」在日志上同形，用户读到的是"产品故障"。
 *
 * ## 本测试锁什么（五条；与 #3615 / #3714 / #4991 的既有裁定**不冲突**）
 *
 * 1. **陈旧产物 ⇒ fail-fast**（抛 {@link MigrationRunner.MigrationStaleArtifactException}）：文件名
 *    **不在源码树** ∧ **不在台账** ∧ **不在 KNOWN_BENIGN_LEGACY** —— 且**该文件根本不被执行**
 *    —— 陈旧产物不是"一条坏迁移"，是"构建产物与源码不一致"的部署事故，跳过它不会自愈；
 * 2. **台账已有该键 ⇒ 不拒启动**（后面本来就会按台账跳过它，与"陈旧"无关）；
 * 3. **在 KNOWN_BENIGN_LEGACY 登记册里 ⇒ 不拒启动**，仍走 #3714/#4991 的 INFO 降级通道
 *    （否则等于新造一个「例外清单以外一律拒启动」的机制，把已裁定的发行语义改了）；
 * 4. **源码树里真实存在的一条迁移内容失败 ⇒ 语义逐字不变**（#3615：跳过该条 + ERROR + 继续，
 *    不拒启动）—— 这是**防改过头**的负控臂，与
 *    `backend/admin-api/src/test/java/com/migao/admin/config/MigrationRunnerConnectionFailClosedTest.java`
 *    的判据 3 同口径；
 * 5. **源码树解析不到**（容器里只有打包好的 jar：`Dockerfile` 只 `COPY src` 构建后
 *    `COPY --from=builder /app/target/*.jar`）⇒ 检测**整段跳过**、不误判（历史行为逐字不变）。
 *    ⚠️ 这条是**射程声明**，不是"检测在镜像里也有效"。
 *
 * ⚠️ 判据 1 的失败必须**可归因**：点名**哪个文件** stale（否则又回到「真失败与噪音同形」）。
 * ⚠️ 参照面**从 `migrationPattern` 推**（生产那条路径），不靠 `live-dir` 配置口 —— 判据改
 * `migrationPattern` 时参照面跟着走，不会各说各话。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("MigrationRunner 陈旧构建产物不得被静默重跑（issue #5981）")
class MigrationRunnerStaleArtifactTest {

    private static final String STALE = "V108__restore_route_rule_positions.sql";
    private static final String LIVE = "V999__injected_live_probe.sql";

    /** 历史退休迁移的失败形态（issue #5981 的启动日志原文），夹具与真实病灶同形。 */
    private static final String STALE_ERROR = "42703|column \"selling_method\" does not exist";

    @Mock
    private ObjectProvider<JdbcTemplate> jdbcProvider;
    @Mock
    private JdbcTemplate jdbc;
    @Mock
    private ResourcePatternResolver resolver;
    @TempDir
    Path liveDir;

    private Logger runnerLogger;
    private ListAppender<ILoggingEvent> appender;

    @BeforeEach
    void attachAppender() {
        runnerLogger = (Logger) LoggerFactory.getLogger(MigrationRunner.class);
        appender = new ListAppender<>();
        appender.start();
        runnerLogger.addAppender(appender);
        when(jdbcProvider.getIfAvailable()).thenReturn(jdbc);
    }

    @AfterEach
    void detachAppender() {
        if (runnerLogger != null && appender != null) {
            runnerLogger.detachAppender(appender);
        }
    }

    // ── 判据 1：classpath 有 / 源码树没有（陈旧产物）⇒ fail-fast 且不执行 ──

    @Test
    @DisplayName("陈旧产物（classpath 有、源码树没有、台账无）⇒ 拒启动 + 点名文件 + 该文件根本不执行")
    void classpathOnlyMigrationFailsFastAndIsNotExecuted() throws Exception {
        // 源码树为空 ⇒ classpath 上的 STALE 是陈旧产物（#5981 的形态）
        givenClasspathMigrations(STALE);
        stubBaselineApplied();

        MigrationRunner runner = newRunner();
        ReflectionTestUtils.setField(runner, "liveMigrationDir", liveDir.toString());

        assertThatThrownBy(runner::run)
                .as("构建产物与源码不一致是**部署事故**：「跳过这一条 + 继续」会让它每次起栈重演（#5981）")
                .isInstanceOf(MigrationRunner.MigrationStaleArtifactException.class)
                .hasMessageContaining(STALE)
                .hasMessageContaining("源码树");

        // 失败必须可归因：日志也要点名（不是只把异常甩给调用方）
        assertThat(appender.list)
                .as("拒启动必须点名**是哪个文件** stale（陈旧产物的失败原文不具备这个信息）")
                .anyMatch(e -> e.getLevel() == Level.ERROR && formatted(e).contains(STALE));

        // 关键：陈旧产物**根本不被执行** —— 这正是「不污染同一 JVM 后续请求」的那一半
        verify(jdbc, never()).execute(contains("-- " + STALE));
        verify(jdbc, never()).update(anyString(), anyString());
    }

    // ── 判据 2：负控 —— 真·源码迁移的内容类失败语义逐字不变（#3615）──

    @Test
    @DisplayName("负控：该迁移确实在源码树里 ⇒ 内容类失败仍按 #3615（跳过 + ERROR + 继续，不拒启动）")
    void liveMigrationContentFailureKeepsLegacySemantics() throws Exception {
        writeLiveSourceFile(LIVE);
        givenClasspathMigrations(LIVE);
        stubBaselineApplied();

        assertThatCode(() -> {
            MigrationRunner runner = newRunner();
            ReflectionTestUtils.setField(runner, "liveMigrationDir", liveDir.toString());
            runner.run();
        })
                .as("源码树里的迁移失败维持 #3615 裁定（一条坏迁移不得冻结整个 schema）—— 本修法不许改过头")
                .doesNotThrowAnyException();

        assertThat(appender.list)
                .as("#3615 的逐字日志必须保留")
                .anyMatch(e -> e.getLevel() == Level.ERROR
                        && formatted(e).contains("❌ 迁移失败（已跳过，继续执行其余迁移）"));
    }

    // ── 判据 3：源码树不在（容器里只有 jar）⇒ 检测整段跳过，历史行为逐字不变 ──

    @Test
    @DisplayName("射程：源码树解析不到（容器里只有 jar）⇒ 检测整段跳过，不误判成 stale")
    void absentSourceTreeDisablesTheCheckWithoutFailing() throws Exception {
        givenClasspathMigrations(STALE);
        stubBaselineApplied();

        // `classpath:` 前缀在磁盘上找不到对应源码目录（= 只有打包好的 jar 的容器）⇒ 参照面为 null
        assertThatCode(() -> newRunnerIn("classpath:db/migration-not-in-repo/*.sql").run())
                .as("检测依赖源码树；没有源码树时不许误判成 stale（否则线上会起不来）")
                .doesNotThrowAnyException();
    }

    // ── 判据 4：已在台账里 / 已登记为存量非幂等 ⇒ 不拒启动（不新建第二套发行语义）──

    @Test
    @DisplayName("台账已有该键 ⇒ 陈旧产物按台账跳过（不拒启动）：已退休迁移不该二次变成启动故障")
    void ledgerKnownNameIsNotRejected() throws Exception {
        givenClasspathMigrations(STALE);
        // 台账**已有**该键（该库历史上跑过它）⇒ `applied.contains` 会跳过它，与"陈旧"无关
        Resource baseline = stubBaselineApplied();
        when(jdbc.queryForList("SELECT version FROM schema_migrations", String.class))
                .thenReturn(List.of("schema.sql", STALE));
        assertThat(baseline).isNotNull();

        assertThatCode(() -> newRunnerIn(liveDir.toString()).run())
                .as("台账已有 ⇒ 陈旧与否都不该拒启动（否则等于把「已记账」这条既有一致性判据也改了）")
                .doesNotThrowAnyException();
        verify(jdbc, never()).execute(contains("-- " + STALE));
    }

    @Test
    @DisplayName("在 KNOWN_BENIGN_LEGACY 登记册里 ⇒ 归既有降级通道（INFO + 继续），不拒启动（#3714/#4991 语义不变）")
    void registeredBenignLegacyIsNotRejected() throws Exception {
        String benign = "V37__rename_knowledge_entries_to_cards.sql";
        givenClasspathMigrationsWith(Map.of(benign, "42P07|关系 \"knowledge_cards\" 已经存在"), benign);
        stubBaselineApplied();

        MigrationRunner runner = newRunnerIn(liveDir.toString());
        assertThatCode(runner::run)
                .as("存量登记册里的名字走既有降级通道 —— 否则等于新建「例外清单以外一律拒启动」的机制")
                .doesNotThrowAnyException();
        assertThat(runner.getLastFailedBenignCount()).as("仍按良性计数").isEqualTo(1);
        assertThat(runner.getLastFailedRealCount()).as("真失败 0 条").isZero();
    }

    // ── 夹具 ──

    private MigrationRunner newRunner() {
        return newRunnerIn(liveDir.toString());
    }

    /**
     * 造一个 runner，并把「源码树参照面」钉在给定位置。
     *
     * <p>⚠️ 判据不靠 `live-dir` 配置（那是运维覆盖口）：这里把 {@code migrationPattern} 指向
     * {@link #liveDir}，走的正是生产那条「参照面从 migrationPattern 推」的路径。</p>
     */
    private MigrationRunner newRunnerIn(String referenceDir) {
        MigrationRunner runner = new MigrationRunner(jdbcProvider, resolver);
        // 纯单测不走 Spring，@Value 字段不会被注入 ⇒ 显式钉上与生产一致的默认值
        ReflectionTestUtils.setField(runner, "migrationPattern",
                referenceDir.startsWith("classpath:") ? referenceDir : referenceDir + "/*.sql");
        ReflectionTestUtils.setField(runner, "initScriptLocation", "classpath:db/init/schema.sql");
        return runner;
    }

    /** 造一个「源码树里真的存在」的迁移文件（内容无关，只判存在性）。 */
    private void writeLiveSourceFile(String filename) throws Exception {
        java.nio.file.Files.writeString(liveDir.resolve(filename), "-- " + filename + "\nSELECT 1;\n");
    }

    /**
     * classpath 上放 N 条迁移，`jdbc.execute` 对它们全部抛出**真库形态**的失败
     * （`BadSqlGrammarException` 包 `SQLException(SQLSTATE, message)`）。
     *
     * ⚠️ 夹具口径与 `MigrationRunnerLegacyNoiseTest` 一致：SQL 文本带 `-- <文件名>` 注记 ⇒
     * mock 按文件名分辨该抛谁；基线钉成「台账已记账 ⇒ 整段跳过」，免得基线分支混进被测行为。
     */
    private void givenClasspathMigrations(String... names) throws Exception {
        givenClasspathMigrationsWith(Map.of(), names);
    }

    /**
     * 同上，但允许**逐条覆写**错因（登记册判据要注入「在册文件名 + 该册登记的错因」才能命中降级）。
     *
     * @param causeOverrides 文件名 → `SQLSTATE|message`（真库形态，取自 issue #5981 的启动日志）
     */
    private void givenClasspathMigrationsWith(Map<String, String> causeOverrides, String... names)
            throws Exception {
        Resource[] resources = new Resource[names.length];
        for (int i = 0; i < names.length; i++) {
            String name = names[i];
            Resource resource = org.mockito.Mockito.mock(Resource.class);
            when(resource.getFilename()).thenReturn(name);
            String sql = "-- " + name + "\nSELECT 1;\n";
            when(resource.getInputStream())
                    .thenAnswer(inv -> new ByteArrayInputStream(sql.getBytes(StandardCharsets.UTF_8)));
            resources[i] = resource;
        }
        when(resolver.getResources(anyString())).thenReturn(resources);
        doAnswer(invocation -> {
            String sql = invocation.getArgument(0, String.class);
            String offending = List.of(names).stream().filter(sql::contains).findFirst().orElse(null);
            if (offending != null) {
                String raw = causeOverrides.getOrDefault(offending, STALE_ERROR);
                String[] parts = raw.split("\\|", 2);
                throw new BadSqlGrammarException("迁移", sql, new SQLException(parts[1], parts[0]));
            }
            return null;
        }).when(jdbc).execute(anyString());
    }

    private Resource stubBaselineApplied() throws Exception {
        Resource baseline = org.mockito.Mockito.mock(Resource.class);
        when(baseline.getFilename()).thenReturn("schema.sql");
        when(baseline.exists()).thenReturn(true);
        when(resolver.getResource(anyString())).thenReturn(baseline);
        when(jdbc.queryForList("SELECT version FROM schema_migrations", String.class))
                .thenReturn(List.of("schema.sql"));
        return baseline;
    }

    private static String formatted(ILoggingEvent e) {
        String formatted = e.getFormattedMessage();
        return formatted == null ? "" : formatted;
    }
}
