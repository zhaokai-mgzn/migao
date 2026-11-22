// case_ids: AG-010
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.CreateNotificationRequest;
import com.migao.admin.dto.NotificationDTO;
import com.migao.admin.entity.Notification;
import com.migao.admin.entity.ScheduledTask;
import com.migao.admin.mapper.NotificationMapper;
import com.migao.admin.mapper.NotificationRuleMapper;
import com.migao.admin.mapper.NotificationTemplateMapper;
import com.migao.admin.mapper.ScheduledTaskMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.time.BusinessClock;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.mybatis.spring.SqlSessionTemplate;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DuplicateKeyException;

import javax.sql.DataSource;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 真库并发判据（集群 P0-2 / issue #9019）：<b>「先查后写」的到期待办扫描在多实例下会重复投递</b>。
 *
 * <h2>本单核验的主张</h2>
 * 扫描腿（{@code ScheduledTaskService#scanDue}）改前是一条纯 read-modify-write：
 * <ol>
 *   <li>读：{@code selectDueByTenant(...)} —— 普通 {@code SELECT}，{@code status='pending'} 且
 *       {@code fire_at <= now}，<b>没有任何占位</b>；</li>
 *   <li>写：逐条 {@code notificationService.createNotification(...)}（未带 {@code dedupeKey}）；
 *   </li>
 *   <li>改状态：{@code updateById(status='fired')} —— <b>无状态谓词</b>（后写覆盖先写）。</li>
 * </ol>
 * 两个实例在同一分钟醒来（{@code ScheduledTaskScanScheduler} 的 cron 每个实例都跑）⇒ 各自读到
 * <b>同一批</b> {@code pending} ⇒ <b>各写一条站内通知</b> ⇒ 员工收到重复的到点提醒；
 * 而且两行最后都是 {@code fired}，事后从数据上<b>分辨不出</b>重复发生过。
 *
 * <h2>为什么必须真 PG（mock 上这条证不了）</h2>
 * mock 的 {@code select} 在两个线程里返回同一批对象、{@code insert} 恒成功 ⇒「窗口能不能被利用」
 * <b>结构上不可见</b>。本类装配真 service + 真 mapper + 真租户拦截器 + <b>每线程独立连接</b>
 * （= 两个实例各自的事务），并用 {@link CyclicBarrier} 让两侧同时进入扫描。
 *
 * <h2>四条判据</h2>
 * <ol>
 *   <li><b>① 多实例并发扫描</b>（主读数，改前红 / 改后绿）：两个实例同时扫同一批 {@value #DUE_TASKS}
 *       条到期任务 ⇒ 站内通知恰 {@value #DUE_TASKS} 条。改前实测 <b>12</b> 条（各实例 delivered
 *       = [6, 6]）⇒ 红；改后 6 条 ⇒ 绿。</li>
 *   <li><b>② 领取互斥</b>：两个实例并发调 {@code claimDueByTenant} ⇒ 每行只被一个实例领走
 *       （并集 = 全量、两两交集 = 空）。</li>
 *   <li><b>③ 通知幂等</b>：同一 {@code dedupeKey} 走两次服务层 ⇒ 库内恰 1 条、第二次返回 {@code null}
 *       不抛异常；再绕过服务直插一条同键 ⇒ 被唯一索引拦下（{@link DuplicateKeyException}）。</li>
 *   <li><b>④ 租约回收</b>：领取 {@code claimed_at} 超时 ⇒ 放回 {@code pending}（可被重新领取）；
 *       新鲜的领取不被误回收；重复回收幂等（0 行）。</li>
 * </ol>
 */
@DisplayName("真库并发（P0-2）：多实例同时扫到期待办 ⇒ 每条只投递一次")
class ScheduledTaskMultiInstanceClaimRealDbTest {

    /** 本类独占的租户（夹具隔离：不碰其它判据的行）。 */
    private static final long TENANT_ID = 990001L;

    /** 模拟的实例数（两个实例同秒醒来 —— 生产上就是两个 pod）。 */
    private static final int INSTANCES = 2;

    /** 每轮到期的任务数（窗口越宽，重复越容易观测到；改后必须仍只有 6 条通知）。 */
    private static final int DUE_TASKS = 6;

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    /**
     * 🔴 生产形态的 mapper 入口（不是裸 {@code factory.openSession}）：{@code SqlSessionTemplate}
     * 每次调用一个 SqlSession + Spring 的**异常翻译**。少了翻译这一层，真库原始会话抛的是
     * {@code PersistenceException}（PG 23505 的包装）而不是 {@code DuplicateKeyException}
     * ⇒ 被测的「唯一冲突 ⇒ 当作已发」在测试里根本走不到（实测踩过，issue #6301 同一坑）。
     * 与 {@code ProductCreateIdempotencyRealDbTest} 同款装配。
     */
    private static SqlSessionTemplate template;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'p0-2-multi-instance', 'p0-2-mi')");
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("p0-2", new JdbcTransactionFactory(), dataSource));
        // 真租户拦截器必须在场（生产 SQL 会经它重写）；`tenants` 本身是租户表，prod 也忽略它。
        // 🔴 无上下文时**抛异常**（与 `MybatisPlusConfig#tenantLineInnerInterceptor` 同款）——
        // 否则「租约回收在调度线程上无租户上下文」这条生产形态在测试里永远不会被触发
        // （`reclaimStaleClaims` 上的 @InterceptorIgnore 也就没被判据证明过）。
        MybatisPlusInterceptor tenantLine = new MybatisPlusInterceptor();
        tenantLine.addInnerInterceptor(new TenantLineInnerInterceptor(new TenantLineHandler() {
            @Override
            public Expression getTenantId() {
                Long tenantId = TenantContext.getTenantId();
                if (tenantId == null) {
                    throw new RuntimeException(
                            "Tenant context not initialized - possible unauthenticated access");
                }
                return new LongValue(tenantId);
            }

            @Override
            public String getTenantIdColumn() {
                return "tenant_id";
            }

            @Override
            public boolean ignoreTable(String tableName) {
                return "tenants".equalsIgnoreCase(tableName);
            }
        }));
        configuration.addInterceptor(tenantLine);
        for (Class<?> mapper : List.of(ScheduledTaskMapper.class, TenantMapper.class,
                NotificationMapper.class, NotificationTemplateMapper.class,
                NotificationRuleMapper.class, UserMapper.class)) {
            configuration.addMapper(mapper);
        }
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        template = new SqlSessionTemplate(factory);
    }

    @AfterEach
    void clearTenantContext() {
        TenantContext.clear();
    }

    @AfterAll
    static void stopRealPostgres() {
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ────────────────────────────────────────────────────── 判据 ①：多实例并发扫描（主读数）

    @Test
    @DisplayName("① 两个实例同时扫同一批到期 pending ⇒ 站内通知恰 6 条（改前 12 条 ⇒ 红）")
    void twoInstancesDeliverEachDueTaskExactlyOnce() throws Exception {
        resetFixtures();

        List<Integer> delivered = runConcurrently(INSTANCES);

        long notifications = scalarLong(
                "SELECT count(*) FROM notifications WHERE tenant_id = " + TENANT_ID);
        long firedTasks = scalarLong(
                "SELECT count(*) FROM scheduled_tasks WHERE tenant_id = " + TENANT_ID
                        + " AND status = 'fired' AND deleted = 0");
        long firedWithClaimOwner = scalarLong(
                "SELECT count(*) FROM scheduled_tasks WHERE tenant_id = " + TENANT_ID
                        + " AND status = 'fired' AND claimed_by IS NOT NULL AND deleted = 0");
        long tasksWithMoreThanOneNotification = scalarLong(
                "SELECT count(*) FROM ("
                        + "  SELECT s.id FROM scheduled_tasks s"
                        + "  JOIN notifications n ON n.tenant_id = s.tenant_id"
                        + "    AND n.title = s.action_label AND n.recipient_id = s.subject_id"
                        + "  WHERE s.tenant_id = " + TENANT_ID
                        + "  GROUP BY s.id HAVING count(n.id) > 1) dup");

        System.out.println("[READING P0-2 ① 多实例并发扫描] 实例数=" + INSTANCES
                + " 到期任务=" + DUE_TASKS + " 各实例 delivered 读数=" + delivered
                + " 站内通知=" + notifications + " 已置 fired=" + firedTasks
                + " fired 且带领取者=" + firedWithClaimOwner
                + " 收到重复提醒的任务数=" + tasksWithMoreThanOneNotification);

        assertThat(notifications)
                .as("每条到期任务只应产生 1 条站内通知（多实例同时扫描不得重复提醒；改前实测 12 条）")
                .isEqualTo(DUE_TASKS);
        assertThat(tasksWithMoreThanOneNotification)
                .as("没有任何任务被提醒两次（员工侧可观察判据）")
                .isZero();
        assertThat(firedTasks)
                .as("到期任务全都被推进到 fired（不会因为抢不到而永远 pending）")
                .isEqualTo(DUE_TASKS);
        assertThat(firedWithClaimOwner)
                .as("fired 行都留着领取者痕迹（事后可归因：谁投的）")
                .isEqualTo(DUE_TASKS);
    }

    // ────────────────────────────────────────────────────── 判据 ②：领取互斥

    @Test
    @DisplayName("② 两个实例并发 claim ⇒ 每行只被一个实例领走（并集=全量，交集=空）")
    void claimIsExclusiveAcrossInstances() throws Exception {
        resetFixtures();

        List<List<String>> claims = runConcurrentClaims(INSTANCES, 3);

        List<String> union = claims.stream().flatMap(List::stream).toList();
        long distinct = union.stream().distinct().count();
        long fired = scalarLong("SELECT count(*) FROM scheduled_tasks WHERE tenant_id = " + TENANT_ID
                + " AND status = 'firing' AND deleted = 0");

        System.out.println("[READING P0-2 ② 领取互斥] 每实例领取数="
                + claims.stream().map(List::size).toList()
                + " 领取总次数=" + union.size() + " 不同行=" + distinct + " 库内 firing=" + fired);

        assertThat(union).as("并发领取不得把同一行给两个实例（重复 = 红）").hasSize((int) distinct);
        assertThat(distinct).as("到期 pending 全被领走（不丢）").isEqualTo(DUE_TASKS);
        assertThat(fired).as("库内事实：恰 6 行处于 firing").isEqualTo(DUE_TASKS);
    }

    // ────────────────────────────────────────────────────── 判据 ③：通知幂等

    @Test
    @DisplayName("③ 同一 dedupeKey 插两次 ⇒ 唯一索引拦下、第二次当「已发」不抛异常")
    void duplicateNotificationIsSwallowedAsAlreadySent() throws Exception {
        clearNotifications();
        TenantContext.setTenantId(TENANT_ID);

        NotificationService service = notificationServiceOf();
        CreateNotificationRequest request = notificationRequest();
        NotificationDTO first = service.createNotification(
                TENANT_ID, request, "scheduled_task:st-dedupe");
        NotificationDTO second = service.createNotification(
                TENANT_ID, request, "scheduled_task:st-dedupe");
        long rows = scalarLong("SELECT count(*) FROM notifications WHERE tenant_id = " + TENANT_ID
                + " AND dedupe_key = 'scheduled_task:st-dedupe'");

        // 唯一索引是**最终保证**：绕过服务再直插一条同键 ⇒ 必须被拦下（证明索引真的在生效）
        Throwable rawConflict = null;
        try {
            Notification dup = Notification.builder()
                    .tenantId(TENANT_ID).recipientId("u-dedupe").recipientType("employee")
                    .channel("internal").title("重复").content("重复")
                    .dedupeKey("scheduled_task:st-dedupe").status("sent").retryCount(0)
                    .build();
            template.getMapper(NotificationMapper.class).insert(dup);
        } catch (Throwable e) {
            rawConflict = e;
        }

        System.out.println("[READING P0-2 ③ 通知幂等] 服务层第一次插入了=" + (first != null)
                + " 第二次当作已发(应为 true)=" + (second == null) + " 库内条数=" + rows
                + " 绕过服务直插同键=" + (rawConflict == null ? "未被拦（红）" : rawConflict.getClass().getSimpleName()));

        assertThat(first).as("第一次真的插入").isNotNull();
        assertThat(second).as("同一 dedupeKey 第二次 = 已发（返回 null，不抛 500）").isNull();
        assertThat(rows).as("同一 dedupeKey 只落 1 条（V187 唯一索引 + 冲突映射）").isEqualTo(1);
        assertThat(rawConflict).as("唯一索引真的在生效（绕过服务直插同键必须被拦）")
                .isInstanceOf(DuplicateKeyException.class);
    }

    // ────────────────────────────────────────────────────── 判据 ④：租约回收

    @Test
    @DisplayName("④ 领取超时 ⇒ 回收成 pending；新鲜领取不被误回收；重复回收幂等")
    void staleClaimIsReclaimed() throws Exception {
        resetFixtures();
        ScheduledTaskMapper mapper = template.getMapper(ScheduledTaskMapper.class);
        List<ScheduledTask> stale = mapper.claimDueByTenant(
                TENANT_ID, OffsetDateTime.now(), 1, "dead-instance");
        List<ScheduledTask> fresh = mapper.claimDueByTenant(
                TENANT_ID, OffsetDateTime.now(), 1, "alive-instance");
        assertThat(stale).as("LIMIT 1 必须只领 1 条（PG 会压平带 FOR UPDATE 的 IN 子查询 ⇒ 用 CTE picked）")
                .hasSize(1);
        assertThat(fresh).hasSize(1);
        String staleId = stale.get(0).getId();
        String freshId = fresh.get(0).getId();
        // 「实例已死」= 客观事实：领取时刻被拨到 10 分钟前（租约 5 分钟）；另一条保持新鲜
        execute("UPDATE scheduled_tasks SET claimed_at = NOW() - INTERVAL '10 minutes' WHERE id = '"
                + staleId + "'");

        ScheduledTaskService service = newService();
        int reclaimed = service.reclaimStaleClaims(OffsetDateTime.now());
        int reclaimedAgain = service.reclaimStaleClaims(OffsetDateTime.now());
        String staleStatus = scalarString("SELECT status FROM scheduled_tasks WHERE id = '" + staleId + "'");
        String staleOwner = scalarString("SELECT claimed_by FROM scheduled_tasks WHERE id = '" + staleId + "'");
        String freshStatus = scalarString("SELECT status FROM scheduled_tasks WHERE id = '" + freshId + "'");
        String freshOwner = scalarString("SELECT claimed_by FROM scheduled_tasks WHERE id = '" + freshId + "'");

        System.out.println("[READING P0-2 ④ 租约回收] 首轮回收=" + reclaimed
                + " 再次回收(应为 0)=" + reclaimedAgain + " 超时行 status=" + staleStatus
                + " claimed_by=" + staleOwner + " 新鲜行 status=" + freshStatus
                + " claimed_by=" + freshOwner);

        assertThat(reclaimed).as("超时领取被回收（1 行）").isEqualTo(1);
        assertThat(staleStatus).as("回收后回到 pending（下一轮可重新领取，不永久卡 firing）")
                .isEqualTo("pending");
        assertThat(staleOwner).as("领取标记被清空（僵尸 token 不再生效）").isNull();
        assertThat(freshStatus).as("新鲜领取不被误回收").isEqualTo("firing");
        assertThat(freshOwner).as("新鲜领取者保持不变").isEqualTo("alive-instance");
        assertThat(reclaimedAgain).as("重复回收幂等（0 行）").isZero();
    }

    // ────────────────────────────────────────────────────── 夹具与工具

    /** 清掉本租户的通知 + 重造 {@value #DUE_TASKS} 条「已到期仍 pending」的任务。 */
    private static void resetFixtures() throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("DELETE FROM notifications WHERE tenant_id = " + TENANT_ID);
            st.execute("DELETE FROM scheduled_tasks WHERE tenant_id = " + TENANT_ID);
            for (int i = 1; i <= DUE_TASKS; i++) {
                st.execute("INSERT INTO scheduled_tasks (id, tenant_id, task_type, subject_type, subject_id,"
                        + " fire_at, criterion, action_label, action_url, source, status, dedup_key, deleted)"
                        + " VALUES ('p0-2-st-" + i + "', " + TENANT_ID + ", 'follow_up', 'employee', 'u-" + i
                        + "', NOW() - INTERVAL '2 minutes', '判据：' || " + i + ", '去跟进 " + i
                        + "', '/customers?keyword=x" + i + "', 'user', 'pending', 'p0-2-dedup-" + i + "', 0)");
            }
        }
    }

    private static void clearNotifications() throws Exception {
        execute("DELETE FROM notifications WHERE tenant_id = " + TENANT_ID);
    }

    /**
     * 同时启动 {@code instances} 个「实例」，各用<b>独立 SqlSession（= 独立连接）</b>跑一轮
     * {@link ScheduledTaskService#scanDue()}；返回各自的 delivered 读数。
     */
    private static List<Integer> runConcurrently(int instances) throws Exception {
        return runWithBarrier(instances, i -> newService().scanDue());
    }

    /**
     * 同时启动 {@code instances} 个「实例」，各自循环领取直到空；返回每实例领到的 id 清单。
     * （= 两个实例同时抢同一批 pending 的**直接**判据，不经扫描 + 投递那层。）
     */
    private static List<List<String>> runConcurrentClaims(int instances, int batchSize) throws Exception {
        return runWithBarrier(instances, i -> {
            ScheduledTaskMapper mapper = template.getMapper(ScheduledTaskMapper.class);
            List<String> mine = new ArrayList<>();
            while (true) {
                List<ScheduledTask> batch = mapper.claimDueByTenant(
                        TENANT_ID, OffsetDateTime.now(), batchSize, "inst-" + i);
                if (batch.isEmpty()) {
                    return mine;
                }
                batch.forEach(t -> mine.add(t.getId()));
            }
        });
    }

    private interface InstanceBody<T> {
        T run(int index) throws Exception;
    }

    private static <T> List<T> runWithBarrier(int instances, InstanceBody<T> body) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(instances);
        CyclicBarrier barrier = new CyclicBarrier(instances);
        List<Future<T>> futures = new ArrayList<>();
        try {
            for (int i = 0; i < instances; i++) {
                final int index = i;
                futures.add(pool.submit(() -> {
                    // 生产形态：每个实例的每次 mapper 调用各自一个 SqlSession（独立连接）。
                    barrier.await(10, TimeUnit.SECONDS);
                    return body.run(index);
                }));
            }
            List<T> readings = new ArrayList<>();
            for (Future<T> f : futures) {
                readings.add(f.get(60, TimeUnit.SECONDS));
            }
            return readings;
        } finally {
            pool.shutdownNow();
        }
    }

    /** 一个「实例」= 它自己的 mapper / 通知服务 / 业务时钟（共享的只有 DB）。 */
    private static ScheduledTaskService newService() {
        return new ScheduledTaskService(
                template.getMapper(ScheduledTaskMapper.class),
                template.getMapper(TenantMapper.class),
                notificationServiceOf(),
                new BusinessClock());
    }

    private static NotificationService notificationServiceOf() {
        return new NotificationService(
                template.getMapper(NotificationMapper.class),
                template.getMapper(NotificationTemplateMapper.class),
                template.getMapper(NotificationRuleMapper.class),
                template.getMapper(UserMapper.class),
                template.getMapper(TenantMapper.class));
    }

    private static CreateNotificationRequest notificationRequest() {
        CreateNotificationRequest request = new CreateNotificationRequest();
        request.setRecipientId("u-dedupe");
        request.setRecipientType("employee");
        request.setTitle("去跟进张先生");
        request.setContent("你说过：3 天后跟进张先生");
        request.setChannel("internal");
        return request;
    }

    private static void execute(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(sql);
        }
    }

    private static long scalarLong(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection();
             Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).isTrue();
            return rs.getLong(1);
        }
    }

    private static String scalarString(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection();
             Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).isTrue();
            return rs.getString(1);
        }
    }

    private static String schemaSql() throws IOException {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null
                && !Files.exists(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 backend/admin-api/src/main/resources/db/init/schema.sql").isNotNull();
        return Files.readString(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"));
    }
}
