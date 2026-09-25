// case_ids: DF-017, PG-018
package com.migao.admin.security;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.User;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.service.ProductionScanCompleteService;
import com.migao.admin.service.ProductionScanService;
import com.migao.admin.service.ProductionService;
import com.migao.admin.worker.WorkerSessionService;
import com.migao.guardfixture.worker.WorkerTenantGuardApp;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.test.web.servlet.MockMvc;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.when;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.authentication;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 🔴 <b>工人端「会话 ⇒ 租户」集成守卫（issue #4864，P0）</b>。
 *
 * <h2>它守的是什么</h2>
 * <p>改前：{@code WorkerSessionFilter} 要先读 {@code worker_sessions} 行才能知道租户，而该表受
 * {@code TenantLineInnerInterceptor} 管、租户又要从那一行里取 ⇒ <b>循环</b> ⇒ 拦截器抛
 * {@code Tenant context not initialized} ⇒ 被 filter 的 catch 吞成「未认证」⇒
 * {@code SecurityConfig} 的 {@code /api/worker/**} → {@code .authenticated()} ⇒
 * <b>除 {@code /login} 外全链路 401</b>（工人扫码后报不了工）。</p>
 *
 * <h2>为什么必须是「集成级」（本类的存在理由）</h2>
 * <p>本缺陷藏了这么久，正是因为它<b>只在真租户拦截器 + 真会话行</b>下才现形：单测把
 * {@code WorkerSessionMapper} mock 掉 ⇒ 拦截器那条路径**从未被行使** ⇒ 全绿。
 * ⇒ 本类**刻意不 mock 任何 Mapper**：{@code WorkerSessionMapper} / {@code UserMapper} 都是
 * 真 MyBatis 代理，SQL 真发到 DB，租户条件由**真的** {@code TenantLineInnerInterceptor}
 * （即 {@link MybatisPlusConfig} 里那个 bean）注入，会话行是**真插进库里的行**，
 * 请求走**真的** {@code SecurityConfig} 过滤链。</p>
 *
 * <h2>库的选择（如实登记）</h2>
 * <p>CI 的 {@code admin-api-test} 只有 {@code ./mvnw test}（无 postgres service），且本机 token
 * 无 {@code workflow} scope ⇒ 不能给 CI 加 DB 服务。故守卫默认跑 <b>H2 的 PostgreSQL 兼容模式</b>
 * （{@code MODE=PostgreSQL}，内存库、随上下文销毁）：<b>被测机制</b>（JSqlParser 改写 SQL 注入
 * {@code tenant_id} + {@code TenantContext} 的取值时机）与库引擎无关，而"确定性、无外部依赖"
 * 正是守卫能在每次 PR 上都真跑的前提。需要对着**真 PostgreSQL** 复核时，
 * 用 {@code -Dworker.guard.jdbc.url=jdbc:postgresql://…} 指向本地 PG 跑同一个类（同一份断言）。</p>
 *
 * <h2>红证（把机制拿掉 ⇒ 本类必须变红）</h2>
 * <ul>
 *   <li>拿掉 {@code WorkerSessionMapper.selectActiveById} 的 {@code @InterceptorIgnore} ⇒
 *       租户上下文未初始化时读行即抛 ⇒ 「有效会话 ⇒ 200」那条**必红**（实测：401）；</li>
 *   <li>拿掉 {@code WorkerSessionService.loadActiveSession} 里的
 *       {@code TenantContext.setTenantId(session.getTenantId())} ⇒ 后续 {@code touch} 抛
 *       ⇒ 同样必红；</li>
 *   <li>拿掉租户一致性判定 ⇒ 「请求已带 B 租户上下文 + A 的会话 ⇒ 401」那条**必红**（变 200，
 *       且返回 A 租户工人的姓名 ⇒ 跨租户读）；</li>
 *   <li>把 filter 的 ERROR 日志改回 {@code log.warn(e.getMessage())} ⇒ 可观测性那条**必红**。</li>
 * </ul>
 */
@SpringBootTest(classes = WorkerTenantGuardApp.class)
@AutoConfigureMockMvc
@DisplayName("🔴 工人端 会话⇒租户 集成守卫（真租户拦截器 + 真会话行，issue #4864）")
class WorkerTenantCycleGuardTest {

    /** 租户 A / B：本类**自造**的实体，用可辨识命名，DB 是内存库 ⇒ 用完即弃，零残留。 */
    private static final long TENANT_A = 486401L;
    private static final long TENANT_B = 486402L;

    private static final String WORKER_NO_A = "acc-fix4864-a";
    private static final String WORKER_NO_B = "acc-fix4864-b";
    private static final String WORKER_ID_A = "acc-fix4864-worker-a";
    private static final String WORKER_NAME_A = "验收工人A";
    private static final String PIN = "486401";

    private static final String SESSION_HEADER = WorkerSessionService.SESSION_HEADER;

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private DataSource dataSource;

    @Autowired
    private UserMapper userMapper;

    /** JWT 链：本类不带 JWT ⇒ 只满足装配（令牌解析器与黑名单 Redis 都不会被调用）。 */
    @MockBean
    private JwtTokenProvider jwtTokenProvider;

    @MockBean
    private StringRedisTemplate redisTemplate;

    @MockBean
    private UserDetailsService userDetailsService;

    /** 生产业务服务：本守卫只测「工人端能不能进来 / 进来的身份是谁」，不测报工记账。 */
    @MockBean
    private ProductionService productionService;

    @MockBean
    private ProductionScanService productionScanService;

    @MockBean
    private ProductionScanCompleteService productionScanCompleteService;

    @BeforeEach
    void resetSchema() {
        TenantContext.clear();
        SecurityContextHolder.clearContext();
        execute("DROP TABLE IF EXISTS worker_sessions");
        execute("DROP TABLE IF EXISTS users");
        execute("CREATE TABLE users ("
                + "id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT, phone VARCHAR(32),"
                + "password_hash VARCHAR(128), nickname VARCHAR(64), avatar VARCHAR(255),"
                + "role VARCHAR(32), position VARCHAR(64), worker_no VARCHAR(64),"
                + "permissions VARCHAR(2048), session_ttl INTEGER, status VARCHAR(16),"
                // V128（issue #5485）：员工登录用户名 + 首登强制改密标记。真 Mapper 的
                // selectActiveUsersByPhoneIgnoreTenant 已把这两列列进投影 ⇒ 夹具 DDL 缺列会
                // 让本守卫在「Column \"username\" not found」上假红（实测踩中）。
                + "username VARCHAR(64), must_change_password BOOLEAN NOT NULL DEFAULT FALSE,"
                + "created_at TIMESTAMP WITH TIME ZONE, updated_at TIMESTAMP WITH TIME ZONE,"
                + "deleted INTEGER NOT NULL DEFAULT 0)");
        // 与 V98 逐列同形（生产 PG 的 DDL；H2 的 PostgreSQL 模式接受同一份类型）
        execute("CREATE TABLE worker_sessions ("
                + "id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL, worker_id VARCHAR(64) NOT NULL,"
                + "worker_no VARCHAR(64), worker_name VARCHAR(64), device_label VARCHAR(64),"
                + "started_at TIMESTAMP WITH TIME ZONE NOT NULL,"
                + "last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,"
                + "idle_expires_at TIMESTAMP WITH TIME ZONE NOT NULL,"
                + "ended_at TIMESTAMP WITH TIME ZONE, end_reason VARCHAR(16),"
                + "created_at TIMESTAMP WITH TIME ZONE, updated_at TIMESTAMP WITH TIME ZONE,"
                + "deleted INTEGER NOT NULL DEFAULT 0)");
    }

    @AfterEach
    void clearThreadState() {
        TenantContext.clear();
        SecurityContextHolder.clearContext();
    }

    // ==================================================== ① 有效会话 ⇒ 工人端端点 200（端点族）

    @Test
    @DisplayName("🔴 工号+PIN 登录拿到的会话 ⇒ auth/session 族 + production 族端点**全部 200**（改前：除 login 外全 401）")
    void validWorkerSessionIsAcceptedOnBothEndpointFamilies() throws Exception {
        String sessionId = loginAsWorkerA();

        // auth/session 族
        mockMvc.perform(post("/api/worker/session/current").header(SESSION_HEADER, sessionId))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.worker_id").value(WORKER_ID_A))
                .andExpect(jsonPath("$.data.worker_name").value(WORKER_NAME_A));

        // production 族 ①：当前工人
        mockMvc.perform(get("/api/worker/production/current-worker").header(SESSION_HEADER, sessionId))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.worker_id").value(WORKER_ID_A));

        // production 族 ②：扫码解析（读面；业务实现由 mock 提供，本守卫只判「进得来 + 租户正确」）
        when(productionScanService.resolve(eq("acc-fix4864-token"), isNull(), eq(TENANT_A)))
                .thenReturn(Map.of("granularity", "order"));
        mockMvc.perform(get("/api/worker/production/scan")
                        .param("token", "acc-fix4864-token")
                        .header(SESSION_HEADER, sessionId))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.granularity").value("order"));
    }

    @Test
    @DisplayName("🔴 共用 PAD 的快速切换（/session/switch）也在这条链上：旧会话立即失效 + 新会话可用（W2 语义不回归）")
    void switchWorkerWorksAndInvalidatesOldSession() throws Exception {
        String oldSession = loginAsWorkerA();

        // ⚠️ /session/switch 与 /login 同款：租户由**域名/网关头**解析（#4733 既有口径，
        //    与本单的 401 循环无关）⇒ 这里带上网关头；缺它 ⇒ 422「无法识别租户」（不是 401）
        String switched = mockMvc.perform(post("/api/worker/session/switch")
                        .header("X-Tenant-Id", String.valueOf(TENANT_A))
                        .header(SESSION_HEADER, oldSession)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"" + WORKER_NO_A + "\",\"pin\":\"" + PIN + "\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.session_id").isNotEmpty())
                .andReturn().getResponse().getContentAsString(java.nio.charset.StandardCharsets.UTF_8);
        String newSession = switched.replaceAll(".*\"session_id\"\\s*:\\s*\"([^\"]+)\".*", "$1");
        assertThat(newSession).as("切换后必须拿到新会话 id").isNotEqualTo(oldSession);

        mockMvc.perform(post("/api/worker/session/current").header(SESSION_HEADER, newSession))
                .andExpect(status().isOk());
        mockMvc.perform(post("/api/worker/session/current").header(SESSION_HEADER, oldSession))
                .andExpect(status().isUnauthorized());
    }

    // ==================================================== ② 无 / 伪会话 ⇒ 401（fail-closed）

    @Test
    @DisplayName("🔴 无会话 / 伪造会话 ⇒ 两个端点族一律 401（认证面**不得**被本次修复削弱）")
    void missingOrForgedSessionIsRejected() throws Exception {
        mockMvc.perform(post("/api/worker/session/current"))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/worker/production/current-worker"))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/worker/production/scan").param("token", "acc-fix4864-token"))
                .andExpect(status().isUnauthorized());

        String forged = UUID.randomUUID().toString().replace("-", "");
        mockMvc.perform(post("/api/worker/session/current").header(SESSION_HEADER, forged))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/worker/production/current-worker").header(SESSION_HEADER, forged))
                .andExpect(status().isUnauthorized());
    }

    @Test
    @DisplayName("🔴 身份**仍由服务端从会话解**：A 的会话 + body 塞 B 的工号 + 伪造 X-Tenant-Id ⇒ 归属仍是 A")
    void identityStillComesFromSessionNotFromRequest() throws Exception {
        String sessionId = loginAsWorkerA();

        mockMvc.perform(post("/api/worker/session/current")
                        .header(SESSION_HEADER, sessionId)
                        .header("X-Tenant-Id", String.valueOf(TENANT_B))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"worker_id\":\"" + WORKER_ID_A.replace("a", "b") + "\","
                                + "\"worker_no\":\"" + WORKER_NO_B + "\",\"worker_name\":\"冒充者\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.worker_id").value(WORKER_ID_A))
                .andExpect(jsonPath("$.data.worker_name").value(WORKER_NAME_A));
    }

    @Test
    @DisplayName("🔴 请求已带别的租户上下文（商家 JWT 形态）⇒ 用 A 的会话**不得**换到 A 租户（跨租户读的红证）")
    void sessionOfAnotherTenantIsRejectedWhenRequestTenantAlreadySet() throws Exception {
        String sessionA = loginAsWorkerA();
        // JwtAuthenticationFilter 在同形态请求里做的事：租户上下文 = 商家自己的租户
        TenantContext.setTenantId(TENANT_B);

        mockMvc.perform(get("/api/worker/production/current-worker")
                        .with(authentication(merchantOfTenantB()))
                        .header(SESSION_HEADER, sessionA))
                .andExpect(status().isUnauthorized());
    }

    // ==================================================== ③ 失败不许静默（真注入）

    @Test
    @DisplayName("🔴 会话读取真失败（表被删）⇒ 401 fail-closed **且** 留 ERROR + 异常栈（改前只记 e.getMessage() ⇒ 静默）")
    void sessionReadFailureIsObservableAndFailsClosed() throws Exception {
        String sessionId = loginAsWorkerA();
        execute("DROP TABLE worker_sessions"); // 真注入：会话行读取必然抛（不是 mock 抛）

        Logger filterLogger = (Logger) LoggerFactory.getLogger(WorkerSessionFilter.class);
        ListAppender<ILoggingEvent> appender = new ListAppender<>();
        appender.start();
        filterLogger.addAppender(appender);
        try {
            mockMvc.perform(get("/api/worker/production/current-worker").header(SESSION_HEADER, sessionId))
                    .andExpect(status().isUnauthorized());
        } finally {
            filterLogger.detachAppender(appender);
            appender.stop();
        }

        assertThat(appender.list)
                .as("认证期异常必须留下可 grep 的 ERROR 且**带异常类型与栈** —— "
                        + "改前是 log.warn(e.getMessage())（类型/栈全丢），这条系统性故障因此没人发现")
                .anyMatch(event -> event.getLevel() == Level.ERROR
                        && event.getThrowableProxy() != null
                        && event.getFormattedMessage().contains("[工人登录态][filter-error]"));
    }

    // ==================================================== ④ 不得过度收紧（放行面不回归）

    @Test
    @DisplayName("🔴 /api/worker/login 仍 permitAll（未认证可达，不是 401）；/s/{短码} 仍 permitAll")
    void loginAndShortLinkStayPermitAll() throws Exception {
        // 无会话、无 JWT 调登录：必须**过授权层**（落业务层 422「无法识别租户」），不能是 401
        mockMvc.perform(post("/api/worker/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isUnprocessableEntity());

        // 短链是印刷品上的公开入口（需求⑤）：未认证必须可达（本上下文没装短链控制器 ⇒ 404，但**不是** 401）
        int shortLinkStatus = mockMvc.perform(get("/s/acc-fix4864"))
                .andReturn().getResponse().getStatus();
        assertThat(shortLinkStatus)
                .as("/s/** 必须保持 permitAll（改 SecurityConfig 时别顺手收紧它）")
                .isNotEqualTo(401);
    }

    // ==================================================== helpers

    /** 真登录（工号 + PIN → 真会话行）；返回 session_id。 */
    private String loginAsWorkerA() throws Exception {
        insertWorkerUser(TENANT_A, WORKER_NO_A, WORKER_ID_A, WORKER_NAME_A);
        String body = mockMvc.perform(post("/api/worker/login")
                        .header("X-Tenant-Id", String.valueOf(TENANT_A))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"" + WORKER_NO_A + "\",\"pin\":\"" + PIN + "\"}"))
                .andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString(java.nio.charset.StandardCharsets.UTF_8);
        String sessionId = body.replaceAll(".*\"session_id\"\\s*:\\s*\"([^\"]+)\".*", "$1");
        assertThat(sessionId).as("登录必须真的签出会话 id（否则后续断言全是空转）").hasSize(32);
        return sessionId;
    }

    /** 真插一行工人档案（走真 Mapper + 真租户拦截器注入 tenant_id）。 */
    private void insertWorkerUser(long tenantId, String workerNo, String workerId, String workerName) {
        TenantContext.setTenantId(tenantId);
        try {
            OffsetDateTime now = OffsetDateTime.now();
            userMapper.insert(User.builder()
                    .id(workerId)
                    .phone("acc-fix4864-" + workerNo)
                    .passwordHash(new BCryptPasswordEncoder().encode(PIN))
                    .nickname(workerName)
                    .role("worker")
                    .workerNo(workerNo)
                    .permissions("[]")
                    .status("active")
                    .createdAt(now)
                    .updatedAt(now)
                    .deleted(0)
                    .build());
        } finally {
            TenantContext.clear();
        }
    }

    private static Authentication merchantOfTenantB() {
        List<SimpleGrantedAuthority> authorities = List.of(
                new SimpleGrantedAuthority("ROLE_operator"), new SimpleGrantedAuthority("operator"));
        SecurityUser user = new SecurityUser("acc-fix4864-merchant", TENANT_B, "acc-fix4864-merchant",
                List.of("operator"), authorities);
        return new UsernamePasswordAuthenticationToken(user, null, authorities);
    }

    private void execute(String sql) {
        try (Connection connection = dataSource.getConnection();
             Statement statement = connection.createStatement()) {
            statement.execute(sql);
        } catch (SQLException e) {
            throw new IllegalStateException("守卫夹具 SQL 失败: " + sql, e);
        }
    }
}
