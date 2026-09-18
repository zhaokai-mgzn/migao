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
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.Banner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.WebApplicationType;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.ResourcePatternResolver;
import org.springframework.jdbc.BadSqlGrammarException;
import org.springframework.jdbc.CannotGetJdbcConnectionException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.util.ReflectionTestUtils;

import javax.sql.DataSource;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.sql.SQLException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * {@link MigrationRunner} 的「连接类失败」契约：有限退避重试 + 重试耗尽 fail-closed（issue #4241 实测）。
 *
 * ## 病灶（实测三次撞到，第三次直接挡住集成验证）
 *
 * `ensureHistoryTable`（建/查 `schema_migrations`）拿不到连接时抛
 * `CannotGetJdbcConnectionException`，被 {@code run()} 的外层 catch 吞掉 ⇒ **整轮迁移被放弃**、
 * 一条都没跑（日志无 `🔄 执行迁移`），但应用照常启动、`/actuator/health` 返回 UP。
 * 连锁后果：新迁移没落库 ⇒ 商家改工序单价 **500**（`relation "production_operation_price_versions"
 * does not exist`）⇒ **重启一次（DB 恢复后）该迁移即成功、同一请求立刻 200**。
 *
 * ## 本测试锁什么（四条，缺一即本修法失效）
 *
 * 1. **连接类首次失败 → 退避重试后迁移完成**（当前实现：一条都不跑且返回正常）；
 * 2. **持续连不上 → 有限次（有上限）重试后 fail-closed** —— 抛错让启动失败，
 *    而**不是**无限重试把启动挂死、也**不是**静默放行；
 * 3. **内容类失败（SQL 语法/约束）语义逐字不变** —— 仍走 #3615 既有裁定：
 *    跳过该条、继续其余、记账、ERROR + 「请立即修复并在修复后重跑」，**且不重试、不 fail-closed**；
 * 4. **真·启动失败**（子进程级）：连接持续失败时进程**非 0 退出**且日志有
 *    `Application run failed` —— 这是编排/部署层唯一能看见的信号。
 *
 * ⚠️ 判据 3 是「防改过头」的守卫：把内容类失败也当连接类重试/拒启动，等于把 #3615 的既有裁定拆了
 * （一条坏迁移会冻结整个 schema，正是 #3270 的原始病灶）。
 *
 * ⚠️ 射程：判据 1~3 用 mock `JdbcTemplate` 覆盖 {@code run()} 的真实分支与真实日志；
 * 判据 4 走**真实 SpringApplication 启动路径 + 真实 JDBC 驱动**（不可达端口），是端到端证据。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("MigrationRunner 连接类失败重试 + fail-closed 契约（issue #4241）")
class MigrationRunnerConnectionFailClosedTest {

    private static final String V90 = "V90__injected_probe_a.sql";
    private static final String V91 = "V91__injected_probe_b.sql";

    /** #3615 既有裁定的逐字日志（内容类失败必须一字不改地保留）。 */
    private static final String CONTENT_SKIP_LOG = "❌ 迁移失败（已跳过，继续执行其余迁移）";
    private static final String CONTENT_SUMMARY_LOG = "本次有 1 条迁移失败，schema 可能与代码不一致";

    @Mock
    private ObjectProvider<JdbcTemplate> jdbcProvider;
    @Mock
    private JdbcTemplate jdbc;
    @Mock
    private ResourcePatternResolver resolver;

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

    // ── 判据 1：连接类首次失败 → 重试后迁移完成 ──

    @Test
    @DisplayName("首次连接失败（ensureHistoryTable 抛 CannotGetJdbcConnection）→ 退避重试后迁移全部跑完并记账")
    void connectionFailureOnFirstAttemptIsRetriedUntilMigrationsComplete() throws Exception {
        givenMigrations(V90, V91);
        AtomicInteger executeCalls = new AtomicInteger();
        doAnswer(invocation -> {
            if (executeCalls.incrementAndGet() == 1) {
                // 真库实测形态：Spring 把驱动层的「尝试连线已失败」翻成 CannotGetJdbcConnectionException
                throw new CannotGetJdbcConnectionException("Failed to obtain JDBC Connection",
                        new SQLException("尝试连线已失败。"));
            }
            return null;
        }).when(jdbc).execute(anyString());

        MigrationRunner runner = newRunner(3, 1L);

        assertThatCode(runner::run)
                .as("连接类失败是**暂时**的 —— 首次失败不得让整轮迁移被放弃")
                .doesNotThrowAnyException();

        // ① 迁移真的跑了（当前实现：日志里连 `🔄 执行迁移` 都没有）
        verify(jdbc).execute(contains("-- " + V90));
        verify(jdbc).execute(contains("-- " + V91));
        // ② 记账（applied 落库，否则下次启动重跑；真库 500 的直接成因就是没记账/没执行）
        verify(jdbc).update(anyString(), eq(V90));
        verify(jdbc).update(anyString(), eq(V91));
        // ③ 重试是有日志的（可归因，不是静默重试）
        assertThat(appender.list)
                .as("应有一条「连接类失败、即将退避重试」的 WARN —— 重试必须可观测")
                .anyMatch(e -> e.getLevel() == Level.WARN && formatted(e).contains("重试"));
        assertThat(appender.list)
                .as("重试成功后必须打印迁移完成（当前实现此处为空）")
                .anyMatch(e -> formatted(e).contains("✅ 迁移完成: " + V90));
        // ④ 旧行为（吞掉 + 放弃整轮）必须消失
        assertThat(appender.list)
                .as("首次连接失败不得再走「整轮放弃」分支（那是 fail-open 的形态判据）")
                .noneMatch(e -> e.getLevel() == Level.ERROR);
    }

    // ── 判据 2：持续连不上 → 有限次重试后 fail-closed ──

    @Test
    @DisplayName("持续连不上 → 恰好重试到上限即 fail-closed 抛错（不得无限重试挂死启动）")
    void persistentConnectionFailureFailsClosedAfterBoundedRetries() throws Exception {
        givenMigrations(V90);
        doAnswer(invocation -> {
            throw new CannotGetJdbcConnectionException("Failed to obtain JDBC Connection",
                    new SQLException("尝试连线已失败。"));
        }).when(jdbc).execute(anyString());

        MigrationRunner runner = newRunner(3, 1L);

        assertThatThrownBy(runner::run)
                .as("重试耗尽必须 fail-closed（抛错让启动失败）—— 不得以「schema 未知」状态起服务")
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("迁移")
                .hasMessageContaining("启动");

        // ① 重试**有限**：恰好 3 次 ensureHistoryTable（不是无限循环把启动挂死）
        verify(jdbc, times(3)).execute(anyString());
        // ② 连不上时不得假装「没有已应用迁移」继续往下跑
        verify(jdbc, never()).queryForList(anyString(), eq(String.class));
        // ③ 失败必须留痕：ERROR 里能看出「连接类 + 尝试次数 + 拒绝启动」
        assertThat(appender.list)
                .as("fail-closed 的 ERROR 必须写明连接类失败与尝试次数（可归因）")
                .anyMatch(e -> e.getLevel() == Level.ERROR
                        && formatted(e).contains("连接")
                        && formatted(e).contains("3"));
    }

    // ── 判据 3：内容类失败语义逐字不变（防「改过头拆掉 #3615 裁定」）──

    @Test
    @DisplayName("内容类失败（SQL 语法错）→ 逐字维持 #3615：跳过该条 + 继续其余 + 记账 + ERROR 汇总，不重试不拒启动")
    void contentFailureSemanticsAreUnchanged() throws Exception {
        givenMigrations(V90, V91);
        doAnswer(invocation -> {
            String sql = invocation.getArgument(0, String.class);
            if (sql.contains(V90)) {
                throw new BadSqlGrammarException("迁移", sql, new SQLException("语法错误"));
            }
            return null;
        }).when(jdbc).execute(anyString());

        MigrationRunner runner = newRunner(3, 1L);

        assertThatCode(runner::run)
                .as("内容类失败维持既有语义：不抛异常（#3615 裁定「跳过并继续」，应用仍可启动）")
                .doesNotThrowAnyException();

        // ① 该条被跳过并打既有文案（逐字）
        assertThat(appender.list)
                .as("内容类失败必须保留 #3615 的逐字日志：%s", CONTENT_SKIP_LOG)
                .anyMatch(e -> e.getLevel() == Level.ERROR && formatted(e).contains(CONTENT_SKIP_LOG));
        assertThat(appender.list)
                .as("汇总行必须保留「请立即修复并在修复后重跑」口径：%s", CONTENT_SUMMARY_LOG)
                .anyMatch(e -> e.getLevel() == Level.ERROR && formatted(e).contains(CONTENT_SUMMARY_LOG));
        // ② 其余迁移继续跑完并记账（一条坏迁移不得冻结整个 schema —— #3270 病灶）
        verify(jdbc).execute(contains("-- " + V91));
        verify(jdbc).update(anyString(), eq(V91));
        // ③ **不重试**：坏 SQL 重试一万次还是坏的；只有连接类才退避重试
        verify(jdbc, times(1)).execute(contains("-- " + V90));
        assertThat(appender.list)
                .as("内容类失败不得被当成连接类去重试（那会把坏迁移重放 N 次并最终拒启动）")
                .noneMatch(e -> formatted(e).contains("重试"));
    }

    // ── 判据 4：真·启动失败（子进程级，编排层可见信号）──

    @Test
    @DisplayName("连接持续失败 ⇒ 真实 SpringApplication 启动失败、进程非 0 退出（不是「抛个异常给单测看」）")
    void persistentConnectionFailureMakesProcessExitNonZero() throws Exception {
        String javaBin = Path.of(System.getProperty("java.home"), "bin", "java").toString();
        ProcessBuilder pb = new ProcessBuilder(
                javaBin, "-cp", System.getProperty("java.class.path"),
                StartupProbe.class.getName());
        pb.redirectErrorStream(true);
        Process process = pb.start();
        String output = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);

        assertThat(process.waitFor(60, TimeUnit.SECONDS))
                .as("子进程必须在 60s 内退出 —— 有限次重试不得把启动挂死")
                .isTrue();
        assertThat(process.exitValue())
                .as("迁移连接失败重试耗尽后，进程必须以非 0 退出（fail-closed）。实际输出：\n%s", output)
                .isNotZero();
        // ⚠️ 实测口径（Spring Boot 3.3.9，勿照抄旧版本的 "Failed to execute CommandLineRunner"）：
        // runner 抛出的异常被**原样重抛**给 main（不包一层），Spring 只先记一行
        // `ERROR o.s.boot.SpringApplication - Application run failed` ⇒ 未捕获 ⇒ 退出码非 0。
        assertThat(output)
                .as("启动失败必须由 CommandLineRunner 抛出并被 Spring 收口（编排层可见）。实际输出：\n%s", output)
                .contains("Application run failed")
                .contains("拒绝启动");
    }

    /**
     * 子进程探针：**不可达的 DB 端点** + 真实 `MigrationRunner` ⇒ 走真实 `SpringApplication` 启动路径。
     *
     * 为什么必须真起：单测里「`run()` 抛异常」只证明我们抛了；本探针证明**抛出去的异常真的让应用起不来**
     * （Spring 收口为 `Failed to execute CommandLineRunner`、进程非 0 退出）—— 这正是 issue 要求的
     * 「让编排/部署层能看见」。
     */
    public static class StartupProbe {

        public static void main(String[] args) {
            SpringApplication app = new SpringApplication(ProbeConfig.class);
            app.setWebApplicationType(WebApplicationType.NONE);
            app.setBannerMode(Banner.Mode.OFF);
            // 重试上限/退避压到最小，避免探针跑 24s（配置项默认值仍是生产口径）
            app.setDefaultProperties(Map.of(
                    "migao.migration.connect-retry.max-attempts", "2",
                    "migao.migration.connect-retry.backoff-ms", "1"));
            // fail-closed ⇒ 这里抛 IllegalStateException；main 不捕获 ⇒ 进程非 0 退出
            app.run(args);
        }
    }

    /** 探针上下文：只装 DataSource/JdbcTemplate/MigrationRunner（不开 auto-config，零外部依赖）。 */
    @Configuration
    public static class ProbeConfig {

        @Bean
        public DataSource dataSource() {
            // 端口 1 必然无人监听 ⇒ 连接立刻被拒（真驱动、真失败，不是 mock）
            return new DriverManagerDataSource("jdbc:postgresql://127.0.0.1:1/absent", "nobody", "nothing");
        }

        @Bean
        public JdbcTemplate jdbcTemplate(DataSource dataSource) {
            return new JdbcTemplate(dataSource);
        }

        @Bean
        public MigrationRunner migrationRunner(ObjectProvider<JdbcTemplate> jdbcProvider,
                                               ResourcePatternResolver resolver) {
            return new MigrationRunner(jdbcProvider, resolver);
        }
    }

    // ── 夹具 ──

    private MigrationRunner newRunner(int maxAttempts, long backoffMs) {
        MigrationRunner runner = new MigrationRunner(jdbcProvider, resolver);
        // 纯单测不走 Spring：`@Value` 注入的字段保留声明处默认值，这里显式压小以缩短测试时长
        ReflectionTestUtils.setField(runner, "migrationPattern", "classpath:db/migration/*.sql");
        tuneIfPresent(runner, "maxConnectAttempts", maxAttempts);
        tuneIfPresent(runner, "connectRetryBackoffMs", backoffMs);
        return runner;
    }

    /**
     * 只在字段存在时压小重试参数（字段缺失 = 实现还没做，见下）。
     *
     * ⚠️ 为什么要容错：TDD 的红灯必须落在**被测行为**上，而不是 `NoSuchFieldException`。
     * 若实现把字段改名/删掉，本测试**不会**因此静默放行：重试参数会退回生产默认值（5 次），
     * `verify(jdbc, times(3)).execute(...)` 立刻因「实际 5 次」报红。
     */
    private static void tuneIfPresent(Object target, String field, Object value) {
        if (org.springframework.util.ReflectionUtils.findField(target.getClass(), field) != null) {
            ReflectionTestUtils.setField(target, field, value);
        }
    }

    /**
     * 造 N 条迁移资源：SQL 文本里带 `-- <文件名>` 注记 ⇒ mock 的 Answer 能按文件名分辨该抛谁；
     * `schema_migrations` 查询返回空 ⇒ 所有迁移都进入执行分支（同 LegacyNoiseTest 的夹具口径）。
     */
    private void givenMigrations(String... names) throws Exception {
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
        when(jdbc.queryForList("SELECT version FROM schema_migrations", String.class))
                .thenReturn(List.of());
    }

    private static String formatted(ILoggingEvent e) {
        String formatted = e.getFormattedMessage();
        return formatted == null ? "" : formatted;
    }
}
