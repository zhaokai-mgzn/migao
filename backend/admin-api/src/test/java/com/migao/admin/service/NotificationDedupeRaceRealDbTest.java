// case_ids: ST-014
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.migao.admin.dto.NotificationEvent;
import com.migao.admin.entity.Notification;
import com.migao.admin.entity.NotificationRule;
import com.migao.admin.entity.NotificationTemplate;
import com.migao.admin.mapper.NotificationMapper;
import com.migao.admin.mapper.NotificationRuleMapper;
import com.migao.admin.mapper.NotificationTemplateMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserMapper;
import org.apache.ibatis.exceptions.PersistenceException;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mybatis.spring.transaction.SpringManagedTransactionFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import javax.sql.DataSource;
import java.io.IOException;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Proxy;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 🔴 <b>通知去重「多实例并发」的真库判据（issue #9025）。</b>
 *
 * <h2>为什么必须真 PG（mock / 注解文本结构上看不见的那一件事）</h2>
 * 缺陷形态是 {@code NotificationService#triggerByEvent} 的「先查后写」幂等：
 * {@code countByDedupeKey}（先查）→ {@code notificationMapper.insert}（后写、无 catch）。
 * 两个并发事件同时越过检查 ⇒ 后写者撞<b>部分</b>唯一索引 {@code uk_notifications_dedupe}
 * ⇒ {@code triggerByEvent} 的 {@code @Transactional} 方法抛 {@code DuplicateKeyException}
 * ⇒ PG 把整条事务标成 aborted ⇒ <b>调用方业务写（改状态 / 过账）一起回滚</b>。
 *
 * <p>mock 面结构上不可能复现这三件：① 唯一索引在<b>插入那一刻</b>的原子判定；
 * ② 未提交行对并发事务的可见性（B 的 SELECT 看不见 A 未提交的行 ⇒ TOCTOU 窗口真实存在）；
 * ③ 冲突之后<b>事务是否 aborted</b>（外层业务写在同一个事务里能不能继续提交）。
 * 修法是 mapper 上的原子写 {@code INSERT … ON CONFLICT (tenant_id, dedupe_key)
 * WHERE dedupe_key IS NOT NULL DO NOTHING}：冲突在语句内部消解，影响行数 0 = 已发。</p>
 *
 * <p>装配与 {@code KfConcurrencyRealDbTest} 同款：一次性 {@code initdb} + {@code pg_ctl} 集群
 * （{@link PgCluster#startOrAbort()}；CI 注入 {@code MIGAO_REQUIRE_REALDB=1} ⇒ 缺 PG <b>判红不 skip</b>）。
 * 表结构按 {@code backend/admin-api/src/main/resources/db/init/schema.sql} 的 {@code notifications}
 * 表 + {@code uk_notifications_dedupe} <b>逐条抄</b>（省略与并发无关的外键：{@code tenants} /
 * {@code notification_rules} / {@code notification_templates}；同 {@code KfConcurrencyRealDbTest} 口径）；
 * 判据 ④ 把这条「逐条抄」变成<b>会红的</b>判据（schema 漂移 ⇒ 当场红）。</p>
 *
 * <p>事务边界：{@link TransactionTemplate}（{@code DataSourceTransactionManager}）+ 每票一个
 * {@link SpringManagedTransactionFactory} 会话 ⇒ mapper 调用绑在<b>外层业务事务</b>的连接上，
 * 业务探针 {@code notification_biz_probe} 与通知写入同生共死 —— 这正是「业务写被连带回滚」的观测面。</p>
 *
 * <p><b>边界（如实登记，§19.1）</b>：① 规则 / 模板 / 用户 / 租户四个 mapper 是 Mockito 桩
 * （本判据的射程是<b>通知落库那一条语句</b>的并发语义，不是规则匹配）；
 * ② 原始 {@code SqlSession} 不经 MyBatis-Spring 的异常翻译 ⇒ 判据 ② 的具名异常是
 * {@link PersistenceException}（生产经 MyBatis-Spring 是 {@code DuplicateKeyException}）
 * —— 判据对<b>异常族 + 唯一索引名</b>断言，不钉死一个类名；
 * ③ 并发度 2（缺陷的表征就是「两个实例/两个并发事件」；预检查在 N 并发下同样是窗口）；
 * ④ 全部对象自建（租户 {@value #TENANT}），随一次性临时集群销毁，<b>不碰任何存量数据</b>。</p>
 */
@DisplayName("9025 真库：通知去重原子写 —— 并发只落 1 条且业务事务不回滚")
class NotificationDedupeRaceRealDbTest {

    private static final Long TENANT = 9025L;
    private static final String RULE_ID = "rule-9025-inbound-posted";
    private static final String TEMPLATE_ID = "tpl-9025-inbound-posted";
    private static final String EVENT_TYPE = "inbound_posted";
    private static final String BIZ_ID = "inbound-9025-uuid-1";
    private static final String RECIPIENT = "admin-9025";
    private static final String DEDUPE_KEY = EVENT_TYPE + ":" + BIZ_ID + ":" + RECIPIENT;
    private static final int THREADS = 2;

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static TransactionTemplate txTemplate;
    private static JdbcTemplate jdbc;

    private static NotificationTemplateMapper templateMapper;
    private static NotificationRuleMapper ruleMapper;
    private static UserMapper userMapper;
    private static TenantMapper tenantMapper;

    /** 注入面（纯测试侧）：true ⇒ 把原子写换回「朴素 insert」（= 修前形态，判据 ② 的红证）。 */
    private static final AtomicBoolean NAIVE_INSERT = new AtomicBoolean(false);

    @BeforeAll
    static void startRealPostgres() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("notif-9025",
                new SpringManagedTransactionFactory(), dataSource));
        configuration.addMapper(NotificationMapper.class);
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        txTemplate = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
        jdbc = new JdbcTemplate(dataSource);

        NotificationRule rule = new NotificationRule();
        rule.setId(RULE_ID);
        rule.setTemplateId(TEMPLATE_ID);
        rule.setChannels("[\"internal\"]");
        rule.setRecipientType("employee");
        ruleMapper = mock(NotificationRuleMapper.class);
        when(ruleMapper.selectList(any())).thenReturn(List.of(rule));

        NotificationTemplate template = new NotificationTemplate();
        template.setId(TEMPLATE_ID);
        template.setName("入库过账通知");
        template.setTitleTemplate("入库单 {{inboundNo}} 已过账");
        template.setTemplateContent("共 {{lineCount}} 行");
        template.setChannel("internal");
        template.setStatus("active");
        templateMapper = mock(NotificationTemplateMapper.class);
        when(templateMapper.selectById(TEMPLATE_ID)).thenReturn(template);

        userMapper = mock(UserMapper.class);
        tenantMapper = mock(TenantMapper.class);
    }

    @AfterAll
    static void stopRealPostgres() {
        if (cluster != null) {
            cluster.stop();
        }
    }

    @BeforeEach
    void resetFixtures() {
        NAIVE_INSERT.set(false);
        jdbc.update("DELETE FROM notifications");
        jdbc.update("DELETE FROM notification_biz_probe");
    }

    // ────────────────────────────────────────── 判据 ①（主判据）：并发只落 1 条、业务写不回滚

    @Test
    @DisplayName("🔴 判据①：两线程同时 triggerByEvent 同一 (tenant_id, dedupeKey) ⇒ 通知恰 1 条、无异常、两笔业务写都提交")
    void concurrentTriggerByEventInsertsExactlyOneNotification() throws Exception {
        List<String> outcomes = concurrently(this::triggerInBusinessTransaction);

        System.out.println("[#9025 判据①] 并发读数 = 线程 " + THREADS
                + " / 各票结果 " + outcomes
                + " / notifications = " + count("SELECT COUNT(*) FROM notifications")
                + " / 业务探针行 = " + count("SELECT COUNT(*) FROM notification_biz_probe"));

        assertThat(outcomes).as("两票都必须提交成功（唯一冲突已由 ON CONFLICT DO NOTHING 在语句内部消解）")
                .containsOnly("committed");
        assertThat(count("SELECT COUNT(*) FROM notifications"))
                .as("同一 (tenant_id, dedupe_key) 只落 1 条（并发不重复发）").isEqualTo(1);
        assertThat(count("SELECT COUNT(*) FROM notifications WHERE dedupe_key = '" + DEDUPE_KEY + "'"))
                .as("库内真值：该幂等键恰 1 行").isEqualTo(1);
        assertThat(count("SELECT COUNT(*) FROM notification_biz_probe"))
                .as("**业务写不得被连带回滚**（每票的业务探针都要提交成功 = 2 行）").isEqualTo(THREADS);
        assertThat(count("SELECT COUNT(*) FROM notifications WHERE biz_id = '" + BIZ_ID + "'"
                + " AND recipient_id = '" + RECIPIENT + "'"))
                .as("落库的行带得住业务对象（biz_id / recipient_id）").isEqualTo(1);
    }

    // ────────────────────────────────────────── 判据 ②：注入式红证（把原子写换回朴素 insert）

    @Test
    @DisplayName("🔴 判据②（注入式红证）：原子写换回朴素 insert ⇒ 后写者撞 uk_notifications_dedupe、其业务事务回滚")
    void naiveInsertInjectionReproducesTheAbortedBusinessTransaction() throws Exception {
        NAIVE_INSERT.set(true);
        List<String> outcomes = concurrently(this::triggerInBusinessTransaction);
        List<String> failures = outcomes.stream().filter(o -> !"committed".equals(o)).toList();

        System.out.println("[#9025 判据②] 朴素 insert 注入下的读数 = " + outcomes
                + " / notifications = " + count("SELECT COUNT(*) FROM notifications")
                + " / 业务探针行 = " + count("SELECT COUNT(*) FROM notification_biz_probe"));

        assertThat(failures).as("注入必须真的把其中一票打成冲突异常（否则判据①的绿无判别力）")
                .hasSize(THREADS - 1);
        assertThat(failures.get(0)).as("具名异常族 + 唯一索引名（能指认现场）")
                .contains(PersistenceException.class.getSimpleName())
                .contains("uk_notifications_dedupe");
        assertThat(count("SELECT COUNT(*) FROM notifications"))
                .as("即便一票 5xx，防双记仍成立（唯一索引兜底）").isEqualTo(1);
        assertThat(count("SELECT COUNT(*) FROM notification_biz_probe"))
                .as("**缺陷本体**：失败那一票的外层业务写跟着回滚（改前实测 1 行，修后 2 行）")
                .isEqualTo(THREADS - 1);
    }

    // ────────────────────────────────────────── 判据 ③：顺序重放（0 行 = 已发，不是失败）

    @Test
    @DisplayName("🔴 判据③：同一 dedupeKey 顺序触发两次（各自业务事务）⇒ 仍 1 条、第二次不抛异常、两笔业务写都提交")
    void sequentialReplayIsSwallowedAsAlreadySent() throws Exception {
        String first = triggerInBusinessTransaction();
        String second = triggerInBusinessTransaction();

        System.out.println("[#9025 判据③] 顺序重放读数 = " + List.of(first, second)
                + " / notifications = " + count("SELECT COUNT(*) FROM notifications")
                + " / 业务探针行 = " + count("SELECT COUNT(*) FROM notification_biz_probe"));

        assertThat(List.of(first, second)).as("重放不是失败：两次都必须提交成功")
                .containsOnly("committed");
        assertThat(count("SELECT COUNT(*) FROM notifications"))
                .as("同一幂等键只落 1 条（重放不刷屏）").isEqualTo(1);
        assertThat(count("SELECT COUNT(*) FROM notification_biz_probe"))
                .as("重放那一票的业务写照常提交（0 行 = 已发，事务不进 aborted）").isEqualTo(THREADS);
    }

    // ────────────────────────────────────────── 判据 ④：测试内 DDL 与生产 schema 的漂移守卫

    @Test
    @DisplayName("🔴 判据④：测试内 notifications 的列集合 == schema.sql 的列集合，唯一索引谓词逐字一致")
    void copiedDdlStillMatchesProductionSchema() throws IOException {
        String schema = Files.readString(repoRoot().resolve(
                "backend/admin-api/src/main/resources/db/init/schema.sql"));

        assertThat(columnNamesOf(schema)).as("本判据的 DDL 是从 schema.sql **逐条抄**的（漂移即红）")
                .isEqualTo(columnNamesOf(schemaSql()));
        assertThat(schema).as("唯一索引谓词必须与 ON CONFLICT 的冲突目标逐字一致"
                        + "（部分唯一索引作冲突目标的前提）")
                .contains("CREATE UNIQUE INDEX IF NOT EXISTS uk_notifications_dedupe"
                        + " ON notifications(tenant_id, dedupe_key) WHERE dedupe_key IS NOT NULL;");
    }

    // ────────────────────────────────────────── 夹具

    /**
     * 一票 = 一条**业务事务**（{@code notification_biz_probe} 模拟调用方的业务写，
     * 如 {@code AfterSalesTicketService} 改状态）+ 同事务里的 {@code triggerByEvent}。
     *
     * @return {@code "committed"}；异常时返回 {@code "<异常类名>: <消息>"}（不抛出，便于逐票读数）
     */
    private String triggerInBusinessTransaction() throws Exception {
        SqlSession session = factory.openSession(true);
        try {
            return txTemplate.execute(status -> {
                jdbc.update("INSERT INTO notification_biz_probe (id, tenant_id, note) VALUES (?, ?, ?)",
                        "probe-" + System.nanoTime(), TENANT, "业务写-" + Thread.currentThread().getName());
                serviceOn(session).triggerByEvent(TENANT, EVENT_TYPE, contextData(), event());
                return "committed";
            });
        } catch (Exception e) {
            return e.getClass().getSimpleName() + ": " + e.getMessage();
        } finally {
            session.close();
        }
    }

    /** 生产形态的服务实例（事务边界由调用方的 {@link TransactionTemplate} 提供，等价于 {@code @Transactional}）。 */
    private static NotificationService serviceOn(SqlSession session) {
        NotificationMapper real = session.getMapper(NotificationMapper.class);
        NotificationMapper mapper = (NotificationMapper) Proxy.newProxyInstance(
                NotificationMapper.class.getClassLoader(),
                new Class<?>[]{NotificationMapper.class},
                (proxy, method, args) -> {
                    // 注入面：把原子写降级成朴素 insert（修前形态）。其余方法原样转发真 mapper。
                    if (NAIVE_INSERT.get() && "insertIfDedupeAbsent".equals(method.getName())) {
                        return real.insert((Notification) args[0]);
                    }
                    try {
                        return method.invoke(real, args);
                    } catch (InvocationTargetException e) {
                        throw e.getTargetException();
                    }
                });
        return new NotificationService(mapper, templateMapper, ruleMapper, userMapper, tenantMapper);
    }

    private static Map<String, String> contextData() {
        Map<String, String> ctx = new HashMap<>();
        ctx.put("recipientId", RECIPIENT);
        ctx.put("recipientType", "employee");
        ctx.put("inboundNo", "RK-20261127-0001");
        ctx.put("lineCount", "2");
        return ctx;
    }

    private static NotificationEvent event() {
        return NotificationEvent.builder()
                .bizType("inbound_order")
                .bizId(BIZ_ID)
                .bizNo("RK-20261127-0001")
                .severity("info")
                .build();
    }

    /**
     * 表结构 = {@code schema.sql} 的 {@code notifications} 表 + {@code uk_notifications_dedupe}
     * **逐条抄**（列 / 类型 / NOT NULL / DEFAULT 一字不差；省略三个与并发无关的外键）。
     * 判据 ④ 把「逐条抄」变成会红的判据 ⇒ 这里漂移不会被静默放过。
     */
    private static String schemaSql() {
        return """
                CREATE TABLE notifications (
                    id VARCHAR(64) PRIMARY KEY,
                    tenant_id BIGINT NOT NULL,
                    rule_id VARCHAR(64),
                    template_id VARCHAR(64),
                    recipient_id VARCHAR(64) NOT NULL,
                    recipient_type VARCHAR(32) NOT NULL,
                    channel VARCHAR(32) NOT NULL,
                    title VARCHAR(255),
                    content TEXT NOT NULL,
                    biz_type VARCHAR(32),
                    biz_id VARCHAR(64),
                    biz_no VARCHAR(64),
                    target_path VARCHAR(255),
                    severity VARCHAR(16),
                    occurred_at TIMESTAMP WITH TIME ZONE,
                    dedupe_key VARCHAR(160),
                    status VARCHAR(32) DEFAULT 'pending',
                    sent_at TIMESTAMP WITH TIME ZONE,
                    read_at TIMESTAMP WITH TIME ZONE,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uk_notifications_dedupe
                    ON notifications(tenant_id, dedupe_key) WHERE dedupe_key IS NOT NULL;
                CREATE TABLE notification_biz_probe (
                    id VARCHAR(64) PRIMARY KEY,
                    tenant_id BIGINT NOT NULL,
                    note VARCHAR(128)
                );
                """;
    }

    /** 从一段 DDL 里取 {@code CREATE TABLE <name> (…)} 的列名（跳过约束行 / 右括号）。 */
    private static Set<String> columnNamesOf(String ddl) {
        Matcher table = Pattern.compile("CREATE TABLE(?: IF NOT EXISTS)?\\s+notifications\\s*\\(")
                .matcher(ddl);
        if (!table.find()) {
            throw new IllegalStateException("DDL 里没有 notifications 建表语句");
        }
        Set<String> columns = new LinkedHashSet<>();
        for (String line : ddl.substring(table.end()).split("\n")) {
            String trimmed = line.trim();
            if (trimmed.startsWith(")")) {
                break;
            }
            Matcher column = Pattern.compile("^([a-z_]+)\\s+[A-Z]").matcher(trimmed);
            if (column.find()) {
                columns.add(column.group(1));
            }
        }
        return columns;
    }

    private static Path repoRoot() {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null
                && !Files.exists(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 backend/admin-api/src/main/resources/db/init/schema.sql").isNotNull();
        return root;
    }

    private static Long count(String sql) {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            if (!rs.next()) {
                throw new IllegalStateException("查询无行：" + sql);
            }
            return rs.getLong(1);
        } catch (Exception e) {
            throw new IllegalStateException("查询失败：" + sql, e);
        }
    }

    /** 同一时刻起跑（{@link CyclicBarrier}），每票自带会话 —— 共享 session 会把并发测成串行。 */
    private List<String> concurrently(ThrowingSupplier task) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(THREADS);
        CyclicBarrier start = new CyclicBarrier(THREADS);
        List<Future<String>> futures = new ArrayList<>();
        try {
            for (int i = 0; i < THREADS; i++) {
                futures.add(pool.submit(() -> {
                    start.await(30, TimeUnit.SECONDS);
                    return task.get();
                }));
            }
            List<String> results = new ArrayList<>();
            for (Future<String> f : futures) {
                results.add(f.get(30, TimeUnit.SECONDS));
            }
            return results;
        } finally {
            pool.shutdownNow();
        }
    }

    @FunctionalInterface
    private interface ThrowingSupplier {
        String get() throws Exception;
    }
}
