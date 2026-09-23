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
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.ResourcePatternResolver;
import org.springframework.jdbc.BadSqlGrammarException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.sql.SQLException;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.when;

/**
 * {@link MigrationRunner} 失败汇总的**日志形状**契约（issue #3714）。
 *
 * ## 为什么是本测试（病灶与不变量）
 *
 * bootstrap-first 评测栈（`docker-entrypoint-initdb.d/001_schema.sql` = `backend/admin-api/src/main/resources/db/init/schema.sql`
 * 先建终态，随后 admin-api 再跑迁移链）上，3 条**已发布**的历史非幂等迁移每次起栈必失败：
 * `V37`/`V42`（`ALTER ... IF EXISTS` 只守卫**源**对象、不守卫目标）、`V44`（裸 `CREATE POLICY`，
 * PG 不支持 `CREATE POLICY IF NOT EXISTS`）。旧实现一律打 ERROR + 「请立即修复并在修复后重跑」
 * —— 那是一条**必然为假**的行动指令（无物可修、重跑必复现），实证：run 34846098440（SHA
 * `4c466d4d`）在 #3615 关单 6.5 小时后仍逐字包含该行。
 *
 * ⇒ 危害不是"红字难看"，而是**真失败与永久噪音同形** → 归因层失效（本仓库自认的最大失败模式）。
 *
 * ## 本测试锁什么（两条，缺一即本修法失效）
 *
 * 1. **命中已知良性集合 → INFO 且汇总分开计数**（不再出现"请立即修复并在修复后重跑"）；
 * 2. **未命中（未知真失败）→ 仍 ERROR + 失败计数** —— 防"顺手把噪音改成静默"，
 *    把所有失败一并降级（那会把真信号一起吞掉，比噪音更糟）。
 *
 * ⚠️ 这里断言的是**真实日志事件**（logback `ListAppender`），不是"某方法被调用"——
 * 本 bug 的病灶就在日志形态上，断言实现细节会走空（migao-acceptance「禁止停留在函数被调用」）。
 *
 * ⚠️ 射程：本测试用 mock JdbcTemplate 覆盖 {@code run()} 的**真实分支与真实日志调用**，
 * **不等于**"运行期已验证"——真库起栈需 docker/独立栈（见 PR body 的未验证项）。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("MigrationRunner 失败汇总日志形状契约（issue #3714）")
class MigrationRunnerLegacyNoiseTest {

    private static final String V37 = "V37__rename_knowledge_entries_to_cards.sql";
    private static final String V42 = "V42__reconcile_knowledge_table_name.sql";
    private static final String V44 = "V44__create_daily_briefings.sql";
    private static final String V40 = "V40__seed_default_tenant_and_roles.sql";
    private static final String V72 = "V72__switch_routing_model_consumers.sql";
    private static final String V74 = "V74__backfill_legacy_special_option_names.sql";
    private static final String V79 = "V79__seed_fabric_route_and_packing_operation.sql";
    private static final String V99 = "V99__injected_unknown_failure.sql";

    /**
     * 真库实测的失败形态（`SQLSTATE|message`）—— 取自本地真 PG（`scripts/migration_chain_repro.py`
     * 同一路径）与云 dev 部署日志。**消息里的标识符不随 `lc_messages` 变**（中文/英文两种文案都含它），
     * 故 `KNOWN_BENIGN_LEGACY` 的签名一律锚在标识符上。
     */
    private static final Map<String, String> REAL_ERRORS = Map.ofEntries(
            Map.entry(V37, "42P07|关系 \"knowledge_cards\" 已经存在"),
            Map.entry(V42, "42P07|关系 \"idx_knowledge_cards_tenant\" 已经存在"),
            Map.entry(V44, "42710|用于表\"daily_briefings\"的策略\"tenant_isolation_daily_briefings\"已经存在"),
            Map.entry(V40, "23505|duplicate key value violates unique constraint \"roles_tenant_id_code_key\""),
            Map.entry(V72, "42703|字段 f.sort_order 不存在"),
            Map.entry(V74, "42703|字段 \"processing_info\" 不存在"),
            Map.entry(V79, "23505|重复键违反唯一约束\"production_operations_pkey\""),
            Map.entry(V99, "42601|syntax error at or near \"boom\""));

    /** 旧实现的汇总行（必然为假的行动指令）——出现在真失败里才对，出现在已知存量里就是回归。 */
    private static final String FALSE_INSTRUCTION = "请立即修复并在修复后重跑";

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

    // ── 用例 1：只有已登记的历史非幂等迁移失败 → INFO，且不含必然为假的行动指令 ──

    @Test
    @DisplayName("已知存量非幂等（V37+V44）失败 → INFO 降级 + 汇总分开计数，不出现「请立即修复并重跑」")
    void knownBenignLegacyFailuresAreLoggedAsInfoAndCountedSeparately() throws Exception {
        givenMigrationsFailing(V37, V44);

        newRunner().run();

        List<ILoggingEvent> events = appender.list;

        // ① 目标态已达成：不打 ERROR（这是本 issue 的原始症状）
        assertThat(events)
                .as("已知存量失败不得再打 ERROR —— 这正是 #3714 的病灶（每次起栈必现的假行动指令）")
                .noneMatch(e -> e.getLevel() == Level.ERROR);

        // ② 必然为假的行动指令必须消失
        assertThat(events)
                .as("「%s」对已知存量必然为假（无物可修、重跑必复现）——不得出现", FALSE_INSTRUCTION)
                .noneMatch(e -> formatted(e).contains(FALSE_INSTRUCTION));

        // ③ 降级为 INFO，且理由与文件名可见（可归因：不是"静默"）
        assertThat(events)
                .as("应有一条 INFO 明示「已知存量非幂等、无需修复」并带上文件名")
                .anyMatch(e -> e.getLevel() == Level.INFO
                        && formatted(e).contains("已知存量非幂等")
                        && formatted(e).contains(V37)
                        && formatted(e).contains(V44));

        // ④ 汇总行**分开计数**：已知存量 2 条；不得落到真失败计数里
        assertThat(events)
                .as("汇总行应报「本次有 2 条迁移失败属已知存量非幂等」")
                .anyMatch(e -> formatted(e).contains("本次有 2 条迁移失败属")
                        && formatted(e).contains("已知存量非幂等"));
        assertThat(events)
                .as("汇总行不得把已知存量计成真失败（0 条真失败）")
                .noneMatch(e -> formatted(e).contains("本次有 1 条迁移失败")
                        || formatted(e).contains("本次有 2 条迁移失败，schema"));
    }

    // ── 用例 2：注入第 4 个（未登记、真会报错）迁移 → 仍 ERROR + 失败计数 ──

    @Test
    @DisplayName("注入第 4 个未知失败迁移 → 仍 ERROR + 失败计数（良性集合不得把所有失败都降级）")
    void unknownFailureIsStillLoggedAsErrorWithFailureCount() throws Exception {
        givenMigrationsFailing(V37, V44, V99);

        newRunner().run();

        List<ILoggingEvent> events = appender.list;

        // ① 未知失败必须醒目：ERROR + 文件名 + 行动指令（对真失败，这句是**真**的）
        assertThat(events)
                .as("未登记的失败迁移必须仍打 ERROR（防「把这条永久噪音改成静默」把真失败一起吞掉）")
                .anyMatch(e -> e.getLevel() == Level.ERROR
                        && formatted(e).contains(V99)
                        && formatted(e).contains(FALSE_INSTRUCTION));

        // ② 汇总行分开计数：真失败 1 条、已知存量 2 条（形状不同 → 归因可分辨）
        assertThat(events)
                .as("汇总行应报「本次有 1 条迁移失败 … 请立即修复并在修复后重跑」")
                .anyMatch(e -> e.getLevel() == Level.ERROR
                        && formatted(e).contains("本次有 1 条迁移失败")
                        && formatted(e).contains(V99));
        assertThat(events)
                .as("已知存量仍应单独计数为 2 条（与真失败分开）")
                .anyMatch(e -> formatted(e).contains("本次有 2 条迁移失败属")
                        && formatted(e).contains("已知存量非幂等"));

        // ③ 已知存量不得被真失败计数吞掉（V37/V44 只出现在 INFO 桶）
        assertThat(events)
                .as("已知存量不得出现在 ERROR 的汇总计数里（多降级/少降级都会在这里露馅）")
                .noneMatch(e -> e.getLevel() == Level.ERROR
                        && formatted(e).contains("本次有 3 条迁移失败"));
    }

    // ── 用例 3：3 条已登记存量全失败（真实 bootstrap-first 情形）→ 无非真失败汇总行 ──

    @Test
    @DisplayName("V37+V42+V44 全失败 → 无 ERROR 汇总行（真失败计数为 0）")
    void allThreeLegacyFailuresProduceNoErrorSummary() throws Exception {
        givenMigrationsFailing(V37, V42, V44);

        newRunner().run();

        assertThat(appender.list)
                .as("3 条已登记存量全失败时，真失败计数应为 0 —— 不得出现 ERROR 汇总行")
                .noneMatch(e -> e.getLevel() == Level.ERROR);
        assertThat(appender.list)
                .as("汇总行应报已知存量 3 条")
                .anyMatch(e -> formatted(e).contains("本次有 3 条迁移失败属")
                        && formatted(e).contains("已知存量非幂等"));
    }

    // ── 用例 4：已补偿的 4 条存量全失败 → 一并降级（issue #4991）──

    @Test
    @DisplayName("已补偿的 4 条存量（V40/V72/V74/V79）失败 → INFO 降级 + benign 4 / 真失败 0（#4991）")
    void compensatedLegacyFailuresAreDowngradedToo() throws Exception {
        givenMigrationsFailing(V40, V72, V74, V79);

        MigrationRunner runner = newRunner();
        runner.run();

        assertThat(appender.list)
                .as("4 条目标态均已达成（V75/V76/V89 补偿 + schema.sql 种子）⇒ 不得打 ERROR")
                .noneMatch(e -> e.getLevel() == Level.ERROR);
        assertThat(appender.list)
                .as("汇总行应报已知存量 4 条")
                .anyMatch(e -> formatted(e).contains("本次有 4 条迁移失败属")
                        && formatted(e).contains("已知存量非幂等"));
        assertThat(runner.getLastFailedBenignCount()).as("4 条全部计入 benign").isEqualTo(4);
        assertThat(runner.getLastFailedRealCount()).as("真失败 0 条").isZero();
        assertThat(runner.getLastFailedMigrations()).containsExactlyInAnyOrder(V40, V72, V74, V79);
    }

    // ── 用例 5：V79 的**两种**真库形态都命中（一条目多签名）──

    @Test
    @DisplayName("V79 云 dev 形态（numeric/text 不匹配，42804）也命中登记签名（#4991）")
    void v79MatchesCloudDevSignatureToo() throws Exception {
        givenMigrationsFailingWith(Map.of(V79,
                "42804|column \"unit_price\" is of type numeric but expression is of type text"), V79);

        MigrationRunner runner = newRunner();
        runner.run();

        assertThat(appender.list)
                .as("V79 在 bootstrap 上是 23505、在云 dev 上是 42804 —— 两种形态都属已诊断存量")
                .noneMatch(e -> e.getLevel() == Level.ERROR);
        assertThat(runner.getLastFailedBenignCount()).isEqualTo(1);
    }

    // ── 用例 6：护栏②红证 —— 在册文件换了错因 ⇒ 不降级 ──

    @Test
    @DisplayName("护栏②红证：在册文件换错因 ⇒ 不降级、仍 ERROR + 计入真失败（#4991）")
    void registeredFileWithUnexpectedCauseIsNotDowngraded() throws Exception {
        // V72 在册签名 = `42703:f.sort_order`；注入**同 SQLSTATE、不同列名**的错因 ⇒ 必须按真失败处理
        givenMigrationsFailingWith(Map.of(V72, "42703|字段 some_other_column 不存在"), V72);

        MigrationRunner runner = newRunner();
        runner.run();

        assertThat(appender.list)
                .as("错因与登记签名不符 ⇒ 必须按真失败处理（否则同一文件的新病灶会被静默吞掉）")
                .anyMatch(e -> e.getLevel() == Level.ERROR
                        && formatted(e).contains(V72)
                        && formatted(e).contains("错因与登记的签名"));
        assertThat(runner.getLastFailedRealCount()).as("真失败 1 条").isEqualTo(1);
        assertThat(runner.getLastFailedBenignCount()).as("不得计入 benign").isZero();
    }

    @Test
    @DisplayName("护栏②红证：SQLSTATE 不符（子串相同）也不得降级（#4991）")
    void registeredFileWithWrongSqlstateIsNotDowngraded() throws Exception {
        // 子串 `f.sort_order` 仍在，但 SQLSTATE 换成 42P01 ⇒ 判据必须按 **state + 子串** 双条件
        givenMigrationsFailingWith(Map.of(V72, "42P01|字段 f.sort_order 不存在"), V72);

        MigrationRunner runner = newRunner();
        runner.run();

        assertThat(runner.getLastFailedRealCount())
                .as("只比子串不比 SQLSTATE ⇒ 这条会假绿（判据被自己的文案喂绿）")
                .isEqualTo(1);
    }

    // ── 夹具 ──

    private MigrationRunner newRunner() {
        MigrationRunner runner = new MigrationRunner(jdbcProvider, resolver);
        // ⚠️ 纯单测不走 Spring，`@Value` 注入的 migrationPattern 为 null → resolver 收到 null
        // 会抛错并被 run() 的外层 catch 打成「❌ 迁移失败」，测试就测不到被测分支了。
        // 显式钉上与生产一致的默认 pattern（MigrationRunner 的 @Value 默认值）。
        ReflectionTestUtils.setField(runner, "migrationPattern", "classpath:db/migration/*.sql");
        // 基线（issue #5243）：`@Value` 字段在纯单测里不会被注入 ⇒ 显式钉上与生产一致的
        // 默认值（与本行的 migrationPattern 同理），否则 applyBaseline 会拿到 null 位置。
        ReflectionTestUtils.setField(runner, "initScriptLocation", "classpath:db/init/schema.sql");
        return runner;
    }

    private static String formatted(ILoggingEvent e) {
        String formatted = e.getFormattedMessage();
        return formatted == null ? "" : formatted;
    }

    /**
     * 造 N 条迁移资源，并让 `jdbc.execute` 对其中列出的文件名抛出**真库形态**的失败。
     *
     * 设计：SQL 文本里带 `-- <文件名>` 注记 ⇒ mock 的 Answer 能按文件名分辨该抛谁；
     * 已登记为存量（{@code KNOWN_BENIGN_LEGACY}）与非存量用**同一**抛错逻辑 ——
     * 两者差别**只在「文件名在册 ∧ 错因签名相符」**（正是被测行为），不由夹具预先决定。
     * `schema_migrations` 查询返回空 ⇒ 所有迁移都进入执行分支。
     *
     * ⚠️ 抛的是**真库形态**：`BadSqlGrammarException` 包 `SQLException(message, sqlstate)` ——
     * 因为 #4991 的护栏②按 **SQLSTATE + 标识符**判签名，抛裸 `RuntimeException` 会让该分支
     * 测不到（夹具与被测行为脱节 = 空跑）。SQLSTATE 与消息取自真库实测（见 {@link #REAL_ERRORS}）。
     */
    private void givenMigrationsFailing(String... failingNames) throws Exception {
        givenMigrationsFailingWith(Map.of(), failingNames);
    }

    /** 同上，但允许**逐条覆写**错因（护栏②红证要注入「同文件名 + 不同错因」）。 */
    private void givenMigrationsFailingWith(Map<String, String> causeOverrides, String... failingNames)
            throws Exception {
        List<String> failing = List.of(failingNames);
        Resource[] resources = new Resource[failing.size()];
        for (int i = 0; i < failing.size(); i++) {
            String name = failing.get(i);
            Resource resource = org.mockito.Mockito.mock(Resource.class);
            when(resource.getFilename()).thenReturn(name);
            String sql = "-- " + name + "\nSELECT 1;\n";
            when(resource.getInputStream())
                    .thenAnswer(inv -> new ByteArrayInputStream(sql.getBytes(StandardCharsets.UTF_8)));
            resources[i] = resource;
        }
        when(resolver.getResources(anyString())).thenReturn(resources);
        // 基线（issue #5243）：本类测的是**迁移链**的失败汇总形状，与建库脚本无关。
        // ⇒ 把基线显式钉成「台账已记账 ⇒ 整段跳过」：既不引入新的日志/失败计数（判据面不变），
        //    也不让基线走到 `jdbc.execute` 去和下面的注入式 Answer 打架。
        Resource baseline = org.mockito.Mockito.mock(Resource.class);
        when(baseline.getFilename()).thenReturn("schema.sql");
        when(baseline.exists()).thenReturn(true);
        when(resolver.getResource(anyString())).thenReturn(baseline);
        when(jdbc.queryForList("SELECT version FROM schema_migrations", String.class))
                .thenReturn(List.of("schema.sql"));

        doAnswer(invocation -> {
            String sql = invocation.getArgument(0, String.class);
            // 只对**注入的迁移**失败：`ensureHistoryTable` 等内置 SQL 照常放行
            // （若对全部 execute 抛错，夹具会连建表一起打挂 → 测的就不是被测行为了）。
            // 注：无选中项时 `findFirst()` 返回空 Optional（不是 orElse 的兜底值）——
            // 必须显式判空，否则内置 SQL 也会被当迁移抛错。
            String offending = failing.stream().filter(sql::contains).findFirst().orElse(null);
            if (offending != null) {
                String raw = causeOverrides.getOrDefault(offending,
                        REAL_ERRORS.getOrDefault(offending, "42601|syntax error at or near \"boom\""));
                String[] parts = raw.split("\\|", 2);
                throw new BadSqlGrammarException("迁移", sql, new SQLException(parts[1], parts[0]));
            }
            return null;
        }).when(jdbc).execute(anyString());
    }
}
