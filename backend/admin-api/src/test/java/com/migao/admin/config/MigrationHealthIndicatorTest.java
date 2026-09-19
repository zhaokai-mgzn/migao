package com.migao.admin.config;
// case_ids: PG-031

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.Status;
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.ResourcePatternResolver;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.sql.SQLException;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 迁移结果的**可观测性**契约（issue #4517）。
 *
 * <h2>为什么需要</h2>
 * 本仓对**非连接类**迁移失败是「跳过这一条、继续跑后面的」（{@link MigrationRunner}，issue #3270
 * 的刻意权衡）⇒ 「迁移全过」与「有迁移被跳过」在**部署期不可区分**：应用 UP、探活 200、部署 success，
 * 而故障面后移到业务 500。本会话已**三次**因此付出代价（#4501 的 V74 / #4514 的 V72 /
 * 由 V72 引发的「云上生成加工单对所有订单 500」）。
 *
 * <h2>本测试钉的三件事（每条都有红证）</h2>
 * <ol>
 *   <li><b>失败可见</b>：有迁移失败时，{@code failed_migrations} 必须**列出文件名**
 *       （红证：注入一条坏迁移 ⇒ 今天该字段不存在 ⇒ 红）；</li>
 *   <li><b>无失败时为空</b>：不得恒非空（恒非空 = 噪音 ⇒ 没人会看，等于没有）；</li>
 *   <li><b>恒 UP（不熔断）</b>：迁移失败**不得**让健康检查变 DOWN ——
 *       否则 {@code KNOWN_BENIGN_LEGACY} 里那几条「每次起栈必失败」的历史非幂等迁移
 *       会把**整个环境打挂**，那是比原问题更糟的故障。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("迁移结果可观测性：/actuator/health 暴露 failed_migrations（issue #4517）")
class MigrationHealthIndicatorTest {

    private static final String BAD = "V90__injected_broken.sql";
    private static final String GOOD = "V91__injected_ok.sql";

    @Mock
    private ObjectProvider<JdbcTemplate> jdbcProvider;
    @Mock
    private JdbcTemplate jdbc;
    @Mock
    private ResourcePatternResolver resolver;

    @BeforeEach
    void setUp() {
        when(jdbcProvider.getIfAvailable()).thenReturn(jdbc);
    }

    // ── 判据 1：失败可见 ──

    @Test
    @DisplayName("有迁移失败 ⇒ health 的 failed_migrations 列出该文件名（且 failed_real_count = 1）")
    void failedMigrationIsVisibleInHealthDetails() throws Exception {
        givenMigrations(BAD, GOOD);
        // 第一条（V90）失败：内容类失败 ⇒ 被跳过、继续跑后面的（既有语义，不抛异常）
        doAnswer(inv -> {
            String sql = inv.getArgument(0);
            if (sql.contains(BAD)) {
                throw new org.springframework.jdbc.BadSqlGrammarException(
                        "bad", sql, new SQLException("字段 f.sort_order 不存在"));
            }
            return null;
        }).when(jdbc).execute(anyString());

        MigrationRunner runner = newRunner();
        runner.run();

        Health health = new MigrationHealthIndicator(runner).health();

        assertThat(health.getDetails().get("failed_migrations"))
                .as("失败迁移必须**列出文件名** —— 否则部署腿只看到 success，故障面后移到业务 500")
                .isEqualTo(List.of(BAD));
        assertThat(health.getDetails().get("failed_real_count"))
                .as("排除 KNOWN_BENIGN_LEGACY 后，真正需要修的条数")
                .isEqualTo(1);
    }

    // ── 判据 2：无失败时为空（不得恒非空） ──

    @Test
    @DisplayName("无迁移失败 ⇒ failed_migrations 为空列表（不得恒非空 —— 恒非空 = 噪音）")
    void noFailureMeansEmptyList() throws Exception {
        givenMigrations(GOOD);

        MigrationRunner runner = newRunner();
        runner.run();

        Health health = new MigrationHealthIndicator(runner).health();

        assertThat(health.getDetails().get("failed_migrations"))
                .as("全过时必须是空列表；恒非空会让人直接忽略这个字段")
                .isEqualTo(List.of());
        assertThat(health.getDetails().get("failed_real_count")).isEqualTo(0);
    }

    // ── 判据 3：恒 UP（不熔断） ──

    @Test
    @DisplayName("迁移失败**不得**让健康检查变 DOWN（不熔断）—— 历史非幂等迁移会打挂整个环境")
    void failedMigrationDoesNotFlipHealthToDown() throws Exception {
        givenMigrations(BAD, GOOD);
        doAnswer(inv -> {
            String sql = inv.getArgument(0);
            if (sql.contains(BAD)) {
                throw new org.springframework.jdbc.BadSqlGrammarException(
                        "bad", sql, new SQLException("boom"));
            }
            return null;
        }).when(jdbc).execute(anyString());

        MigrationRunner runner = newRunner();
        runner.run();

        Health health = new MigrationHealthIndicator(runner).health();

        assertThat(health.getStatus())
                .as("必须恒 UP：KNOWN_BENIGN_LEGACY 里那几条每次起栈必失败，"
                        + "若据此判 DOWN ⇒ 整个环境打挂（比原问题更糟）")
                .isEqualTo(Status.UP);
    }

    // ── 判据 4：未跑过迁移时（DataSource 不可用）不得谎报 ──

    @Test
    @DisplayName("DataSource 不可用（迁移整轮跳过）⇒ 字段存在且为空，不抛异常")
    void noDataSourceMeansEmptyNotCrash() {
        when(jdbcProvider.getIfAvailable()).thenReturn(null);

        MigrationRunner runner = newRunner();
        runner.run();

        Health health = new MigrationHealthIndicator(runner).health();

        assertThat(health.getStatus()).isEqualTo(Status.UP);
        assertThat(health.getDetails().get("failed_migrations")).isEqualTo(List.of());
    }

    // ── 辅助 ──

    private MigrationRunner newRunner() {
        MigrationRunner runner = new MigrationRunner(jdbcProvider, resolver);
        ReflectionTestUtils.setField(runner, "migrationPattern", "classpath:db/migration/*.sql");
        return runner;
    }

    private void givenMigrations(String... names) throws Exception {
        Resource[] resources = new Resource[names.length];
        for (int i = 0; i < names.length; i++) {
            String name = names[i];
            Resource resource = mock(Resource.class);
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
}
