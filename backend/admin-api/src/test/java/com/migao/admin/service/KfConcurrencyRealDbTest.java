// case_ids: KF-017, KF-018, KF-011
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.migao.admin.entity.KfOutbox;
import com.migao.admin.mapper.KfOutboxMapper;
import com.migao.admin.mapper.KfSendBudgetMapper;
import com.migao.admin.mapper.KfSessionRemoteMapper;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.Statement;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🔴 <b>微信客服「并发安全」的真库判据（issue #9208；设计 §13 的「真 PG」层）。</b>
 *
 * <h2>为什么必须真 PG（mock / 注解文本结构上看不见的三件事）</h2>
 * <ol>
 *   <li><b>「不超发」是 WHERE 谓词 + CHECK 的行为</b>：{@code ON CONFLICT … DO UPDATE … WHERE used < 5}
 *       只有让并发事务真的撞在同一行上，才能证明它**不会**把 used 推到 6。既有
 *       {@code KfSendBudgetMapperTest} 断言的是注解字符串里有没有那几个词 ——
 *       删掉谓词它**仍然是绿的**（本类落地时以红证实测过）。</li>
 *   <li><b>「不重复领」是 {@code SKIP LOCKED} 的运行时语义</b>：把它换成 {@code NOWAIT} 或普通
 *       {@code FOR UPDATE}，SQL 文本几乎不变，但两个 worker 会阻塞或重复领取。</li>
 *   <li><b>「当前段唯一」是<b>部分唯一索引</b>的语义</b>：{@code ON CONFLICT (open_kfid, external_userid)
 *       WHERE closed_at IS NULL} 要求索引谓词逐字匹配；索引漏建时语句直接报错，索引谓词写错时并发会建出两段。</li>
 * </ol>
 *
 * <p>装配与 {@code OrderLogisticsShippedAtBackfillRealDbTest} 同款：一次性 {@code initdb} + {@code pg_ctl}
 * 集群（{@link PgCluster#startOrAbort()}；CI 注入 {@code MIGAO_REQUIRE_REALDB=1} ⇒ 缺 PG 判红、不 skip）。
 * 表结构按 {@code V217__create_wechat_kf_tables.sql} 的列 / 约束**逐条抄**（省略与并发无关的外键）。</p>
 *
 * <p>三条 mapper 都带 {@code @InterceptorIgnore(tenantLine = "true")}（跨租户按显式 tenant_id 取数），
 * 故装配里不挂租户拦截器 —— 那不会改变本类断言的三条 SQL 语义。</p>
 */
@DisplayName("9208 真库：预算 5 条不超发 / outbox 不重复领 / 当前段唯一")
class KfConcurrencyRealDbTest {

    private static final Long TENANT = 9208L;
    private static final String SESSION = "kf-9208-session";
    private static final String OPEN_KFID = "wk-9208";
    private static final String EXTERNAL_USERID = "wm-9208-user";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;

    @BeforeAll
    static void startRealPostgres() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("kf-9208", new JdbcTransactionFactory(), dataSource));
        configuration.addMapper(KfSendBudgetMapper.class);
        configuration.addMapper(KfOutboxMapper.class);
        configuration.addMapper(KfSessionRemoteMapper.class);
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
    }

    @AfterAll
    static void stopRealPostgres() {
        if (cluster != null) {
            cluster.stop();
        }
    }

    @BeforeEach
    void resetFixtures() throws Exception {
        execute("DELETE FROM kf_send_budget");
        execute("DELETE FROM kf_outbox");
        execute("DELETE FROM kf_session_remote");
    }

    // ────────────────────────────────────────────── 判据 1 / 2：预算

    @Test
    @DisplayName("🔴 判据 1：20 线程并发扣减同一会话 ⇒ 成功恰 5 次、used=5、第 6 次返回 0（不超发）")
    void concurrentConsumeNeverExceedsFive() throws Exception {
        List<Integer> results = concurrently(20, () -> {
            try (SqlSession session = factory.openSession(true)) {
                return session.getMapper(KfSendBudgetMapper.class).tryConsume(SESSION, TENANT);
            }
        });

        assertThat(results).as("每一票都是 1（扣到）或 0（预算耗尽），不允许异常/其他读数")
                .allSatisfy(r -> assertThat(r).isIn(0, 1));
        assertThat(results.stream().filter(r -> r == 1).count())
                .as("20 个并发请求里只有 5 个能拿到预算（WHERE used < 5）").isEqualTo(5);

        try (SqlSession session = factory.openSession(true)) {
            Integer used = session.getMapper(KfSendBudgetMapper.class).selectUsedInWindow(SESSION);
            assertThat(used).as("库内真值：used 恰为 5 —— 不是 6、也不是 20").isEqualTo(5);
            assertThat(session.getMapper(KfSendBudgetMapper.class).tryConsume(SESSION, TENANT))
                    .as("第 6 次必须失败（0），调用方据此停发").isZero();
        }
    }

    @Test
    @DisplayName("🔴 判据 2：窗口已过 48h ⇒ used 重置为 1、window_start 刷新（窗口语义是 SQL 里的时间条件）")
    void expiredWindowResetsUsedToOne() throws Exception {
        execute("INSERT INTO kf_send_budget (session_id, tenant_id, window_start, used) VALUES ('"
                + SESSION + "', " + TENANT + ", NOW() - INTERVAL '49 hours', 5)");

        try (SqlSession session = factory.openSession(true)) {
            assertThat(session.getMapper(KfSendBudgetMapper.class).tryConsume(SESSION, TENANT))
                    .as("48h 已过 ⇒ 允许再发一条，不是「永久用尽」").isEqualTo(1);
            assertThat(session.getMapper(KfSendBudgetMapper.class).selectUsedInWindow(SESSION))
                    .as("重置后本窗口 used = 1（旧窗口的 5 条不累计）").isEqualTo(1);
        }
        assertThat(queryInt("SELECT used FROM kf_send_budget WHERE session_id = '" + SESSION + "'"))
                .isEqualTo(1);
    }

    // ────────────────────────────────────────────── 判据 3：outbox claim

    @Test
    @DisplayName("🔴 判据 3：两个 worker 并发 claim ⇒ id 集合不相交、每行 attempts=1（SKIP LOCKED 真的在跳锁）")
    void concurrentClaimNeverHandsOutTheSameRow() throws Exception {
        for (int i = 0; i < 10; i++) {
            enqueue("kf-9208-msg-" + i, "pending");
        }
        OffsetDateTime staleBefore = OffsetDateTime.now().minusMinutes(5);

        List<List<Long>> claims = concurrently(2, () -> {
            try (SqlSession session = factory.openSession(true)) {
                return session.getMapper(KfOutboxMapper.class)
                        .claimDue(staleBefore, 3, "worker-" + Thread.currentThread().getId())
                        .stream().map(KfOutbox::getId).toList();
            }
        });

        assertThat(claims).as("每侧最多领 3 条").allSatisfy(c -> assertThat(c).hasSizeLessThanOrEqualTo(3));
        List<Long> all = new ArrayList<>();
        claims.forEach(all::addAll);
        assertThat(all).as("两侧加起来恰好领走 6 条（10 条里够领）").hasSize(6);

        Set<Long> unique = new HashSet<>(all);
        assertThat(unique).as("同一条消息不得被两个 worker 同时领走（集合不相交）")
                .hasSameSizeAs(all);

        assertThat(queryInt("SELECT MIN(attempts) FROM kf_outbox WHERE status = 'sending'"))
                .as("被领走的行 attempts 都只 +1（重复领取会把某一行的 attempts 推到 2）").isEqualTo(1);
        assertThat(queryInt("SELECT COUNT(*) FROM kf_outbox WHERE status = 'sending'"))
                .as("状态：领走即 sending，剩下的仍是 pending").isEqualTo(6);
    }

    // ────────────────────────────────────────────── 判据 4：当前段唯一

    @Test
    @DisplayName("🔴 判据 4：10 线程并发建同一客户会话 ⇒ 恰 1 行；关闭后新 session 可建（新 epoch）")
    void concurrentInsertKeepsSingleOpenSegment() throws Exception {
        List<Integer> results = concurrently(10, () -> {
            String sessionId = "kf-9208-race-" + System.nanoTime();
            try (SqlSession session = factory.openSession(true)) {
                return session.getMapper(KfSessionRemoteMapper.class)
                        .insertIgnore(sessionId, TENANT, OPEN_KFID, EXTERNAL_USERID);
            }
        });

        assertThat(results.stream().filter(r -> r == 1).count())
                .as("部分唯一索引 ⇒ 并发建会话只有 1 个成功，其余 ON CONFLICT DO NOTHING").isEqualTo(1);
        assertThat(queryInt("SELECT COUNT(*) FROM kf_session_remote WHERE open_kfid = '" + OPEN_KFID
                + "' AND closed_at IS NULL")).as("当前段只有一行").isEqualTo(1);

        String openSessionId;
        try (SqlSession session = factory.openSession(true)) {
            openSessionId = session.getMapper(KfSessionRemoteMapper.class)
                    .selectCurrent(TENANT, OPEN_KFID, EXTERNAL_USERID).getSessionId();
            assertThat(session.getMapper(KfSessionRemoteMapper.class).closeSession(openSessionId, "human_end"))
                    .as("人工结束：关闭当前段").isEqualTo(1);

            String nextSessionId = "kf-9208-epoch-2";
            assertThat(session.getMapper(KfSessionRemoteMapper.class)
                    .insertIgnore(nextSessionId, TENANT, OPEN_KFID, EXTERNAL_USERID))
                    .as("关闭后允许建新段（下条客户消息 → 新 epoch）").isEqualTo(1);
            assertThat(session.getMapper(KfSessionRemoteMapper.class)
                    .selectCurrent(TENANT, OPEN_KFID, EXTERNAL_USERID).getSessionId())
                    .as("当前段换成新会话").isEqualTo(nextSessionId);
        }
        assertThat(openSessionId).isNotEqualTo("kf-9208-epoch-2");
    }

    // ────────────────────────────────────────────── 夹具

    private static String schemaSql() {
        return """
                CREATE TABLE kf_send_budget (
                    session_id VARCHAR(64) PRIMARY KEY,
                    tenant_id BIGINT NOT NULL,
                    window_start TIMESTAMP WITH TIME ZONE NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    CONSTRAINT ck_kf_send_budget_used CHECK (used >= 0 AND used <= 5)
                );
                CREATE TABLE kf_outbox (
                    id BIGSERIAL PRIMARY KEY,
                    tenant_id BIGINT NOT NULL,
                    session_id VARCHAR(64) NOT NULL,
                    msgid VARCHAR(32) NOT NULL,
                    parts JSONB NOT NULL,
                    status VARCHAR(16) NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    sent_msgid VARCHAR(128),
                    fail_type INTEGER,
                    sending_at TIMESTAMP WITH TIME ZONE,
                    lease_owner VARCHAR(64),
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    CONSTRAINT ck_kf_outbox_status CHECK (
                        status IN ('pending', 'sending', 'accepted', 'failed', 'unknown')
                    )
                );
                CREATE UNIQUE INDEX uq_kf_outbox_msgid ON kf_outbox (msgid);
                CREATE TABLE kf_session_remote (
                    session_id VARCHAR(64) PRIMARY KEY,
                    tenant_id BIGINT NOT NULL,
                    open_kfid VARCHAR(128) NOT NULL,
                    external_userid VARCHAR(128) NOT NULL,
                    state SMALLINT NOT NULL DEFAULT 4,
                    version INTEGER NOT NULL DEFAULT 0,
                    epoch INTEGER NOT NULL DEFAULT 1,
                    last_msg_at TIMESTAMP WITH TIME ZONE,
                    last_sync_at TIMESTAMP WITH TIME ZONE,
                    closed_at TIMESTAMP WITH TIME ZONE,
                    close_reason VARCHAR(32),
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                );
                CREATE UNIQUE INDEX uq_kf_session_remote_current
                    ON kf_session_remote (open_kfid, external_userid)
                    WHERE closed_at IS NULL;
                """;
    }

    private static void enqueue(String msgid, String status) {
        execute("INSERT INTO kf_outbox (tenant_id, session_id, msgid, parts, status) VALUES ("
                + TENANT + ", '" + SESSION + "', '" + msgid + "', '[]'::jsonb, '" + status + "')");
    }

    private static void execute(String sql) {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(sql);
        } catch (Exception e) {
            throw new IllegalStateException("fixture 失败：" + sql, e);
        }
    }

    private static int queryInt(String sql) {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             var rs = st.executeQuery(sql)) {
            if (!rs.next()) {
                throw new IllegalStateException("查询无行：" + sql);
            }
            return rs.getInt(1);
        } catch (Exception e) {
            throw new IllegalStateException("查询失败：" + sql, e);
        }
    }

    /** 同一时刻起跑（CountDownLatch），每票自带 SqlSession —— 共享 session 会把并发测成串行。 */
    private static <T> List<T> concurrently(int n, Callable<T> task) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(n);
        CountDownLatch start = new CountDownLatch(1);
        List<Future<T>> futures = new ArrayList<>();
        try {
            for (int i = 0; i < n; i++) {
                futures.add(pool.submit(() -> {
                    start.await();
                    return task.call();
                }));
            }
            start.countDown();
            List<T> results = new ArrayList<>();
            for (Future<T> f : futures) {
                results.add(f.get(30, TimeUnit.SECONDS));
            }
            return results;
        } finally {
            pool.shutdownNow();
        }
    }
}
