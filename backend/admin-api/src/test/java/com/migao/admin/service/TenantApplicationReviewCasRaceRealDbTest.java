// case_ids: MC-101

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.config.TenantContext;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CategoryMapper;
import com.migao.admin.mapper.ProcessingCategoryMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.PermissionMapper;
import com.migao.admin.mapper.RoleMapper;
import com.migao.admin.mapper.RolePermissionMapper;
import com.migao.admin.mapper.TenantApplicationMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.mapper.UserRoleMapper;
import com.migao.admin.mapper.WarehouseMapper;
import com.migao.admin.security.PermissionInterceptor;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.LocalCacheScope;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import javax.sql.DataSource;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 🔴 真库并发判据（issue #6954）：<b>入驻审批的「并发双 approve」⇒ 租户数恰好 +1、恰好 1 次成功</b>。
 *
 * <h2>核验的是哪一条主张</h2>
 * 改前 {@link RegistrationService#approveApplication} 是 <b>check-then-act</b>：
 * 读判 {@code pending} → **先建租户 + 管理员 + 初始数据** → 最后 {@code applicationMapper.updateById(application)}
 * （WHERE 仅主键 ⇒ 无谓词）。并发的第二个请求会读到同一个 {@code pending} 并通过判断 ⇒
 * <b>两个租户都真的建出来</b>，后写覆盖前写 ⇒ 一个租户成为<b>无主租户</b>（不可逆：租户已落库、
 * 管理员已建、无人知道该删谁）。改后 = 审批权落在 {@code TenantApplicationMapper#approveIfPending}
 * 的<b>条件更新</b>上（{@code WHERE id=? AND status='pending'}），且该 CAS 位于<b>任何副作用之前</b>。
 *
 * <h2>为什么必须真库</h2>
 * CAS 的全部效力来自只有真 PG 才有的两件事：<b>① 行锁</b>（条件更新的判断与写入是同一条语句，
 * 命中行的锁持有到事务结束）、<b>② 条件重估</b>（后到者阻塞到前者提交后按新版本行重估
 * {@code status='pending'} ⇒ 影响行数 0）。mock 面结构上判不了：mock 的 {@code updateById}
 * 恒返回 1、也不会因 WHERE 不满足而返回 0 ⇒ 修前形态在 mock 上恒绿（假绿）。
 * 既有 {@code RegistrationServiceTest} 正是 mock 面（这也是它此前对此缺陷零反应的原因）。
 *
 * <h2>为什么不需要窗口探针（与 #6928 的差别）</h2>
 * #6928 的窗口只有微秒级（HTTP 层 20 轮只命中 3 轮）⇒ 必须注入 {@code CANCEL_PROBE}。
 * 本单的窗口在 {@code updateById} <b>之前</b>，而中间要跑完整条开租链路（建租户 → 七岗 + 权限目录
 * → 管理员用户 → 默认商品分类 → 生产种子模板 → 后置条件校验）⇒ 窗口是<b>毫秒级</b>且随并发线程数放大。
 * 所以用 {@link CountDownLatch} 对齐起跑即可稳定命中 —— 这是本包最省成本的原因。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>恰好 1 次成功</b>：并发 N 次 approve 同一申请单 ⇒ 成功数 {@code == 1}（不是 2、不是 0），
 *       其余全部是**显式 4xx**（CAS 落空 409 CONFLICT / 读判 400），<b>不许有 500</b>；</li>
 *   <li><b>租户数恰好 +1（不可逆副作用的独立算式）</b>：以该企业名建出的 {@code tenants} 行
 *       <b>恰好 1 行</b>（改前实测 2 行 ⇒ 本条红）、该租户下的管理员用户<b>恰好 1 个</b>；</li>
 *   <li><b>终态与赢家一致</b>：申请单终态 {@code approved} 且 {@code reviewed_by} 非空（审结事实落库）；</li>
 *   <li><b>串行正对照（护栏不误杀）</b>：无并发时串行 approve 必须成功 —— 谓词非空 ⇒
 *       正常请求不被 409 误杀。</li>
 * </ol>
 *
 * <h2>判别力（红证，双向）</h2>
 * ① 临时把 {@code approveIfPending} 的 {@code AND status = 'pending'} 摘掉 ⇒ 本判据
 * {@code concurrentApprovalsCreateExactlyOneTenant} 当场红，逐字读数
 * {@code 成功数=2 租户行=2 管理员行=2}（受控注入的唯一变量 = 谓词，别的都不动）；
 * ② 撤回注入 ⇒ 全绿。② 的反向对照（串行正对照）在两次都能通过 ⇒ 证明红的不是「装置坏了」。
 *
 * <p><b>边界（如实登记）</b>：① 本判据跑的是<b>服务层真库并发</b>而非 HTTP 栈（controller 只是薄转发，
 * 状态机与副作用全在服务层）；② 判定「两个请求都成功」用的不是响应体而是<b>落库事实</b>
 * （租户行数 / 管理员行数）—— 两个请求都成功时租户一定已提交，无需额外埋点；
 * ③ 探针对象全部自建（企业名前缀 {@code ta-6954}，随一次性临时集群销毁），<b>不碰任何存量数据</b>；
 * ④ 本判据的装配走裸 MyBatis（{@code autocommit}）而非 Spring 事务代理 ⇒ 它证的是
 * <b>CAS 语句本身</b>的互斥性（事务内的锁语义由 PG 保证，见 mapper 的 javadoc）。</p>
 */
@DisplayName("🔴 真库并发判据（#6954）：入驻审批并发双 approve ⇒ 租户数恰好 +1 + 恰好 1 次成功")
class TenantApplicationReviewCasRaceRealDbTest {

    /** 并发线程数（判据口径 N=5~10；取中位 6：足够稳定命中，又不把开租链路压成长尾）。 */
    private static final int CONCURRENCY = 6;

    private static final String COMPANY = "ta-6954-观星台布艺有限公司";

    /**
     * 审阅人（= 真实链路里 {@code RegistrationController} 的 {@code currentUser.getUserId()}）。
     *
     * <p>必须是 {@code users} 表里的**真行**：{@code tenant_applications.reviewed_by} 有外键
     * （{@code REFERENCES users(id)}）。这也顺带保证本判据覆盖的 CAS 语句形状**与生产逐字一致**
     * （生产里 reviewerId 是超管 userId，不是任意字符串）。</p>
     */
    private static final String REVIEWER_ID = "ta-6954-reviewer";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;

    @BeforeAll
    static void startRealPostgresAndSchema() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            // bootstrap 用 `OVERRIDING SYSTEM VALUE` 显式种了租户 ⇒ identity 序列还停在起点
            // ⇒ 走 mapper 建新租户会撞 tenants_pkey。把序列推到 MAX(id)（仅夹具前置，不改生产语义）。
            st.execute("SELECT setval(pg_get_serial_sequence('tenants', 'id'),"
                    + " (SELECT COALESCE(MAX(id), 1) FROM tenants))");
            // 审阅人必须是 users 表里的真行（tenant_applications.reviewed_by 有 FK）。
            // 挂在 bootstrap 已有的租户 1 上（= 真实链路里超管所属的租户形态）。
            st.execute("INSERT INTO users (id, tenant_id, phone, nickname, role, status) VALUES ('"
                    + REVIEWER_ID + "', 1, '13900006950', 'ta-6954 审阅人', 'admin', 'active')");
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        // 读写要「写完再查」拿到新值（一级缓存必须 STATEMENT 级）
        configuration.setLocalCacheScope(LocalCacheScope.STATEMENT);
        configuration.setEnvironment(new Environment("ta-6954", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器**必须在场**：生产 SQL 会经它重写（追加 tenant_id）⇒ 少了它就只测了 mapper 原文
        MybatisPlusInterceptor tenantLine = new MybatisPlusInterceptor();
        tenantLine.addInnerInterceptor(new TenantLineInnerInterceptor(new TenantLineHandler() {
            @Override
            public Expression getTenantId() {
                Long tid = TenantContext.getTenantId();
                // 无租户上下文（= 建租户前插角色/权限那一段）取 0：没有任何租户是 0
                // ⇒ 该类读一律空集（fail-closed），INSERT 侧因实体显式带 tenant_id 走 ignoreInsert。
                return new LongValue(tid == null ? 0L : tid);
            }

            @Override
            public String getTenantIdColumn() {
                return "tenant_id";
            }

            @Override
            public boolean ignoreTable(String tableName) {
                // 与生产 MybatisPlusConfig.IGNORE_TENANT_TABLES 同口径
                return List.of("tenants", "tenant_applications", "platform_admins").contains(tableName.toLowerCase());
            }
        }));
        configuration.addInterceptor(tenantLine);
        for (Class<?> mapper : List.of(TenantApplicationMapper.class, TenantMapper.class, UserMapper.class,
                UserRoleMapper.class, RoleMapper.class, PermissionMapper.class, RolePermissionMapper.class,
                CategoryMapper.class, ProcessingCategoryMapper.class, ProcessingItemMapper.class,
                WarehouseMapper.class)) {
            configuration.addMapper(mapper);
        }
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
    }

    @AfterAll
    static void stopRealPostgres() {
        TenantContext.clear();
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ────────────────────────────────────────────── 判据 1~3：并发双 approve

    @Test
    @DisplayName("并发 N 次 approve 同一申请单 ⇒ 成功数恰 1 + 租户恰 1 行 + 管理员恰 1 个 + 终态 approved")
    void concurrentApprovalsCreateExactlyOneTenant() throws Exception {
        long appId = insertPendingApplication(COMPANY, "13900006954");

        List<Verdict> outcomes = runConcurrently(appId, CONCURRENCY);
        long successes = outcomes.stream().filter(v -> v.status() == 200).count();
        List<Integer> failures = outcomes.stream().filter(v -> v.status() != 200).map(Verdict::status).sorted().toList();
        long tenantRows = count("SELECT count(*) FROM tenants WHERE name = '" + COMPANY + "'");
        long adminRows = count("SELECT count(*) FROM users u JOIN tenants t ON u.tenant_id = t.id"
                + " WHERE t.name = '" + COMPANY + "' AND u.role = 'admin'");
        String finalStatus = string("SELECT status FROM tenant_applications WHERE id = " + appId);
        String reviewedBy = string("SELECT reviewed_by FROM tenant_applications WHERE id = " + appId);

        System.out.println("[READING #6954 并发] appId=" + appId
                + " 线程数=" + CONCURRENCY
                + " 各状态码=" + outcomes.stream().map(Verdict::status).sorted().toList()
                + " 成功数=" + successes
                + " 失败状态码=" + failures
                + " 租户行=" + tenantRows
                + " 管理员行=" + adminRows
                + " 单据终态=" + finalStatus
                + " reviewed_by=" + reviewedBy
                + " 失败文案=" + outcomes.stream().filter(v -> v.status() != 200).map(Verdict::detail).toList());

        assertThat(successes)
                .as("并发审批同一申请单 ⇒ 恰 1 次成功（修前实测 2 次 —— 两个租户都建出来了）")
                .isEqualTo(1L);
        assertThat(tenantRows)
                .as("🔴 不可逆副作用的独立算式：以该企业名建出的租户数必须恰好 1（修前实测 2）")
                .isEqualTo(1L);
        assertThat(adminRows)
                .as("该租户下的管理员恰好 1 个（修前实测 2 —— 第二个管理员挂在无主租户上）")
                .isEqualTo(1L);
        assertThat(finalStatus).as("申请单终态必须与赢家一致").isEqualTo("approved");
        assertThat(reviewedBy).as("审结事实（reviewed_by）必须落库").isNotBlank();
        assertThat(failures).as("落败方必须全部是显式 4xx（CAS 落空 409 / 读判 400），不许出现 500").isNotEmpty();
        assertThat(failures).as("落败方不得有 5xx").allMatch(s -> s >= 400 && s < 500);
        assertThat(failures).as("至少一条必须是 CAS 落空的 409 CONFLICT（= 闸真的拦住了，而不是全都撞在快速路径上）")
                .contains(409);
    }

    // ────────────────────────────────────────────── 判据 4：串行正对照（护栏不误杀）

    @Test
    @DisplayName("串行正对照（护栏不误杀）：无并发时 approve 必须成功、租户恰 1 行")
    void serialApprovalStillSucceeds() {
        String company = "ta-6954-串行对照布艺有限公司";
        long appId = insertPendingApplication(company, "13900006955");

        Verdict outcome = approveOnce(appId);
        long tenantRows = count("SELECT count(*) FROM tenants WHERE name = '" + company + "'");
        String finalStatus = string("SELECT status FROM tenant_applications WHERE id = " + appId);

        System.out.println("[READING #6954 串行正对照] appId=" + appId
                + " 状态码=" + outcome.status()
                + " 租户行=" + tenantRows
                + " 单据终态=" + finalStatus
                + " detail=" + outcome.detail());

        assertThat(outcome.status()).as("串行 approve 必须成功（这条红了 = 谓词写错、把正常请求 409 误杀）")
                .isEqualTo(200);
        assertThat(tenantRows).as("串行开租：租户恰 1 行").isEqualTo(1L);
        assertThat(finalStatus).as("单据终态").isEqualTo("approved");
    }

    // ────────────────────────────────────────────── 并发装置

    /** 一次审批的结果（业务码 + 文本锚；服务层用异常的业务码等价表达 HTTP 码）。 */
    private record Verdict(int status, String detail) {
    }

    /**
     * N 个线程用 {@link CountDownLatch} 对齐起跑、各用**自己的 session**（= 各自的连接 + 事务）
     * 并发审批同一张申请单。
     *
     * <p>⚠️ 只收集结果（不在此处断言）：修前形态下 {@code approveApplication} 会<b>正常返回</b>，
     * 判红必须来自下面的落库读数（租户行数），而不是「抛没抛异常」—— 否则红证不可归因。</p>
     */
    private static List<Verdict> runConcurrently(long appId, int n) throws Exception {
        CountDownLatch start = new CountDownLatch(1);
        List<Verdict> results = new CopyOnWriteArrayList<>();
        ExecutorService pool = Executors.newFixedThreadPool(n);
        try {
            List<Future<?>> futures = new ArrayList<>();
            for (int i = 0; i < n; i++) {
                final int idx = i;
                futures.add(pool.submit(() -> {
                    try {
                        start.await(30, TimeUnit.SECONDS);
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                        return;
                    }
                    results.add(approveOnce(appId, REVIEWER_ID));
                }));
            }
            start.countDown();
            for (Future<?> f : futures) {
                f.get(120, TimeUnit.SECONDS);
            }
        } finally {
            pool.shutdownNow();
        }
        return results;
    }

    private static Verdict approveOnce(long appId) {
        return approveOnce(appId, REVIEWER_ID);
    }

    private static Verdict approveOnce(long appId, String reviewerId) {
        try (SqlSession s = factory.openSession(true)) {
            registrationServiceOn(s).approveApplication(appId, reviewerId, null);
            return new Verdict(200, "ok");
        } catch (BusinessException e) {
            return new Verdict(e.getHttpStatus(), e.getCode() + ": " + e.getMessage());
        } catch (RuntimeException e) {
            // 非业务异常 = 500 形态：本判据把它当 5xx 判红（修前不该出现，出现即装置或实现坏了）
            e.printStackTrace(System.out);
            Throwable root = e;
            while (root.getCause() != null) {
                root = root.getCause();
            }
            return new Verdict(500, e.getClass().getSimpleName() + ": " + e.getMessage()
                    + " | root=" + root.getClass().getName() + ": " + root.getMessage());
        }
    }

    // ────────────────────────────────────────────── 真值读取（裸 JDBC，不经被测读面）

    private static long count(String sql) {
        Object v = scalar(sql);
        return v == null ? 0L : ((Number) v).longValue();
    }

    private static String string(String sql) {
        Object v = scalar(sql);
        return v == null ? null : v.toString();
    }

    private static Object scalar(String sql) {
        try (Connection c = dataSource.getConnection();
             Statement st = c.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            return rs.next() ? rs.getObject(1) : null;
        } catch (SQLException e) {
            throw new IllegalStateException("真值读取失败: " + sql, e);
        }
    }

    // ────────────────────────────────────────────── 夹具

    /** 入驻链路（真 mappers + 真 UserService/RoleService/分类播种；只把与本判据无关的协作者置为 mock）。 */
    private static RegistrationService registrationServiceOn(SqlSession session) {
        UserMapper userMapper = session.getMapper(UserMapper.class);
        RoleMapper roleMapper = session.getMapper(RoleMapper.class);
        UserRoleMapper userRoleMapper = session.getMapper(UserRoleMapper.class);
        RoleService roleService = new RoleService(roleMapper, session.getMapper(PermissionMapper.class),
                userRoleMapper, userMapper, session.getMapper(RolePermissionMapper.class));
        UserService userService = new UserService(userMapper, roleMapper, userRoleMapper,
                new PermissionInterceptor(roleService));

        // 以下三个协作者不在本判据射程内（各自的链路由其它判据守着）：
        //  · ProductionSeedTemplateService：行业模板套用（#4361），有合法「本行业无模板」分支
        //  · SmsService / RegistrationReviewClient / Redis：提交链路才用，审批链路不碰
        ProductionSeedTemplateService productionSeedTemplateService = mock(ProductionSeedTemplateService.class);
        when(productionSeedTemplateService.applyTemplate(anyLong(), any())).thenReturn(java.util.Map.of("applied", true));

        return new RegistrationService(
                session.getMapper(TenantApplicationMapper.class),
                session.getMapper(TenantMapper.class),
                userService,
                mock(SmsService.class),
                userMapper,
                roleMapper,
                session.getMapper(PermissionMapper.class),
                session.getMapper(RolePermissionMapper.class),
                mock(RegistrationReviewClient.class),
                mock(StringRedisTemplate.class),
                productionSeedTemplateService,
                new ProductCategorySeedService(session.getMapper(CategoryMapper.class)),
                new ProcessingItemSeedService(session.getMapper(ProcessingCategoryMapper.class),
                        session.getMapper(ProcessingItemMapper.class)),
                // #7592：开租默认主仓（本判据只关心审批权 CAS，仓播种走真实现即可）
                new WarehouseSeedService(session.getMapper(WarehouseMapper.class)));
    }

    /** 落一条 pending 入驻申请（= 真实链路里 AI 放行前的那一行）。 */
    private static long insertPendingApplication(String companyName, String phone) {
        try (Connection conn = dataSource.getConnection();
             PreparedStatement ps = conn.prepareStatement(
                     "INSERT INTO tenant_applications (company_name, company_name_norm, contact_name, phone,"
                             + " industry, status) VALUES (?, ?, ?, ?, '布艺', 'pending') RETURNING id")) {
            ps.setString(1, companyName);
            ps.setString(2, companyName);
            ps.setString(3, "测试联系人");
            ps.setString(4, phone);
            try (ResultSet rs = ps.executeQuery()) {
                assertThat(rs.next()).as("入驻申请必须落库成功").isTrue();
                return rs.getLong(1);
            }
        } catch (SQLException e) {
            throw new IllegalStateException("夹具插入失败: " + companyName, e);
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
