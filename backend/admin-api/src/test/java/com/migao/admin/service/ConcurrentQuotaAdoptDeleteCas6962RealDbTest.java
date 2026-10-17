// case_ids: PG-077

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.config.TenantContext;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.AgentEmployeeMapper;
import com.migao.admin.mapper.AgentMessageMapper;
import com.migao.admin.mapper.AgentSessionMapper;
import com.migao.admin.mapper.CustomerProfileMapper;
import com.migao.admin.mapper.KnowledgeCandidateMapper;
import com.migao.admin.mapper.KnowledgeCardMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import com.migao.admin.mapper.ProductionRouteTemplateMapper;
import com.migao.admin.mapper.ProductionRoutingVersionMapper;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import javax.sql.DataSource;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

/**
 * 🔴 真库并发判据（issue #6962 P5 首批 3 处）：<b>「读-判-写」无互斥的三处并发面 ⇒ 改条件更新（CAS）后「恰一个赢家」</b>。
 *
 * <h2>核验的是哪三条主张（一处一个 @Test 组，逐条会红）</h2>
 * <ol>
 *   <li><b>① 会话并发分配</b>（{@link AgentSessionService#assignSession}）：修前是
 *       「{@code selectById} 判 {@code waiting} → {@code selectCount(active)} 判额度 →
 *       {@code updateById}（WHERE 仅主键）」三段无互斥 ⇒ 同一员工 6 个并发分配时 6 个请求各自读到
 *       <b>分配前</b>的计数 ⇒ 上限 {@code max_concurrent_sessions=3} 被突破（6 条全落 active）。
 *       修后 ① {@code markAssignedIfWaiting}（谓词 {@code id + tenant_id + status='waiting' + deleted=0}）
 *       抢分配权、② {@code lockEmployeeForQuota}（{@code FOR UPDATE} 锁员工行）+
 *       {@code countActiveSessions}（锁内现取计数）把「判额度」与「占额度」压进同一个持锁临界区。</li>
 *   <li><b>② 候选双采纳</b>（{@link KnowledgeCandidateService#adopt}）：修前
 *       {@code getOwned} 读出 {@code pending} 判完 → {@code knowledgeCardMapper.insert(card)} →
 *       {@code updateById(candidate)}（无谓词）⇒ 并发双采纳<b>各插一张卡</b>（2 张）。
 *       修后先抢发布权（{@code markReviewedIfPending}，谓词 {@code id + tenant_id + status='pending'}），
 *       <b>抢到才插卡</b> ⇒ 落败方 409、卡片恰 1 张。</li>
 *   <li><b>③ 路线 / 条件工序规则软删</b>（{@link ProductionRoutingCommandService#deleteRouting} /
 *       {@code #deleteRouteRule}）：修前落库语句只有 {@code .eq(id)}（缺 tenant 限定、无
 *       {@code deleted=0}、不判影响行数）⇒ 并发双删<b>两个都回 200</b>（0 行也当成功）。
 *       修后 {@code markDeletedByIdAndTenant}（谓词 {@code id + tenant_id + deleted=0}）+ 影响行数判定
 *       ⇒ 恰一个 200、另一个 409；跨租户被读判 404 挡住。</li>
 * </ol>
 *
 * <h2>为什么必须真库 + 窗口注入</h2>
 * CAS 的全部效力来自只有真 PG 才有的两件事：<b>① 行锁</b>（条件更新的判断与写入是同一条语句）、
 * <b>② 条件重估</b>（后到者阻塞到前者提交后按新版本行重估谓词 ⇒ 影响行数 0）。mock 面结构上判不了：
 * mock 的 {@code updateById} 恒返回 1、也不会因 WHERE 不满足而返回 0 ⇒ 缺陷形态在 mock 上恒绿（假绿）。
 *
 * <p>而真实窗口只有微秒级，靠调度去碰 = flake ⇒ 本判据用两种<b>确定性</b>窗口放大手段
 * （{@code migao-dev-flow} §28.1：不注入的竞态判据会退化成 flake）：</p>
 * <ul>
 *   <li><b>生产探针</b>（{@link AgentSessionService#setAssignProbePauseMillisForTest}，生产恒 0）：
 *       把 6 条请求钉在「读完会话/员工、还没判额度」的同一时刻；</li>
 *   <li><b>行级冻结闸</b>（{@link RowGate}）：测试自己的连接先 {@code SELECT … FOR UPDATE} 锁住靶行，
 *       于是每条请求都<b>必然</b>先跑完读判（普通 SELECT 不受行锁阻塞）、再卡在写谓词上排队
 *       ⇒ 「两个请求都过了读判」这件事是确定的，不是靠碰运气。<b>它不是生产行为的替代品</b>：
 *       并发度、事务隔离、行锁与条件重估全是真的；被钉住的只是「两条请求重叠」这一件事。</li>
 * </ul>
 *
 * <h2>判别力（红证 · 注入式，2026-10-16 实测）</h2>
 * 把三处写退回修前形态（会话：{@code selectCount} + {@code updateById}、去掉员工行锁；
 * 候选：先插卡再 {@code updateById}；删路线/规则：{@code .eq(id)}-only 的 {@code update}）：
 * <b>探针 ON + 冻结闸</b> ⇒ 判据 1/2/3 全红（逐字读数：1a/1b 落库 {@code active=6}、
 * 判据 2 卡片数 = 2、判据 3a/3c 两个请求都 200）。正对照：串行分配必须先占满 {@code max} 个额度
 * （证明谓词/锁不误杀正常请求）。
 *
 * <h2>⚠️ 修后实测（2026-10-16，本判据对 HEAD 的读数 —— 这是**发现**，不是「通过」）</h2>
 * <ul>
 *   <li><b>判据 2 / 3 全绿</b>：候选双采纳 3 轮全绿（恰 1 成功 / 1 个 409 / 卡片恰 1 张 / 终态 adopted）；
 *       路线与规则双删各 1 绿（恰 1 个 200 / 1 个 409 / 落库 {@code deleted=1}）；跨租户 404 +
 *       对方租户的行原封不动。</li>
 *   <li><b>判据 1 红</b>：「并发超发」这条已治好（再也不会落 6 条 active），但 6 并发里
 *       <b>5 条被 PG 死锁检测中止</b>（500，{@code PersistenceException: 检测到死锁}，两档都是
 *       1 成功 + 5 个 500）。成因：{@code agent_sessions.employee_id → agent_employees} 的外键让
 *       {@code markAssignedIfWaiting} 那条 UPDATE 先对员工行取到 {@code FOR KEY SHARE}，随后
 *       {@code lockEmployeeForQuota} 对**同一行**请求 {@code FOR UPDATE}（两者互斥）⇒ 两条请求
 *       彼此成环、谁也不退让。即「判额度与占额度同一临界区」这个目标达到了，代价是把并发分配
 *       变成了会 500 的接口。</li>
 *   <li><b>一行修法的实测读数</b>：把 {@code AgentSessionMapper#lockEmployeeForQuota} 的
 *       {@code FOR UPDATE} 换成 <b>{@code FOR NO KEY UPDATE}</b>（与 {@code FOR KEY SHARE} 相容、
 *       与自身互斥 ⇒ 恰好只串行化「抢额度」这一步）⇒ <b>整类 8/8 全绿</b>（探针 ON 与 OFF 两档
 *       各自 3 轮，轮轮「成功数 = 3 / 落库 active = 3 / 落败全 409」）。</li>
 * </ul>
 * <p>⇒ 判据 1 的落败码断言**刻意保持严格**（只认 409 / 422，不许 500）：本判据现在就是红的，
 * 直到上面那一行修法落进 {@code AgentSessionMapper}。</p>
 *
 * <h2>边界（如实登记，不粉饰）</h2>
 * <p>① 本判据跑的是<b>服务层真库并发</b>而非 HTTP 栈（端点只是薄转发，判断与写入全在服务层）；
 * ② 探针对象全部自建（租户 {@value #TENANT_A} / {@value #TENANT_B}、id 前缀 {@code 6962}），
 * 随一次性临时集群销毁，<b>不碰任何存量数据</b>；
 * ③ {@link KnowledgeCandidateService#reject} 与 {@code adoptEdited} 走同一条
 * {@code markReviewedIfPending} 条件更新，但 <b>PG-077 不覆盖它们</b>（本单射程 = 采纳面）；
 * ④ 跨租户那条断言命中的是<b>既有读判</b>（{@code findRouting} / {@code deleteRouteRule} 的
 * 404），不是本次新增的影响行数判定 —— 它在此处是<b>护栏对照</b>，不是「修前会红」的靶心。</p>
 */
@DisplayName("🔴 真库并发判据（#6962）：会话并发分配额度 / 候选双采纳 / 路线软删 = 条件更新，恰一个赢家")
class ConcurrentQuotaAdoptDeleteCas6962RealDbTest {

    /** 竞态面租户（A）。 */
    private static final Long TENANT_A = 6962L;
    /** 跨租户对照租户（B）：只用来证明「拿别人的 id 删不动别人的行」。 */
    private static final Long TENANT_B = 6963L;

    /** 员工额度上限（夹具常量；缺陷形态 = 落库 active 数 > 本值）。 */
    private static final int MAX_CONCURRENT = 3;
    /** 每轮并发分配条数（> 上限 ⇒ 超发才可观测；修前实测 6 条全落 active）。 */
    private static final int SESSIONS_PER_ROUND = 6;
    /** 并发轮数（缺陷时序敏感：单轮可能因调度恰好串行而侥幸变绿）。 */
    private static final int ROUNDS = 3;
    /** 双采纳轮数（每轮一个独立候选）。 */
    private static final int ADOPT_ROUNDS = 3;

    /** 窗口注入时长（毫秒）：必须显著大于「读判 + 写」的全程（本机实测 ~10~50ms）。 */
    private static final long PAUSE_MILLIS = 800L;
    /** 等「行锁等待者凑齐」/「探针进入窗口」的上限（确定性时序的护栏）。 */
    private static final long GATE_WAIT_MILLIS = 10_000L;

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_A + ", 'cas-6962-a', 'cas-6962-a')");
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_B + ", 'cas-6962-b', 'cas-6962-b')");

            // ── 判据 1 夹具：每轮（每条臂）一个**独立员工** ⇒ 额度互不污染（否则第二轮起前置读判必拒，
            //    判据会以「0 成功 vs 3 落库」自伤）。
            for (int r = 1; r <= ROUNDS; r++) {
                st.execute(employeeSql("on", r));
                st.execute(employeeSql("off", r));
                for (int i = 1; i <= SESSIONS_PER_ROUND; i++) {
                    st.execute(waitingSessionSql("as-6962-on-r" + r + "-" + i));
                    st.execute(waitingSessionSql("as-6962-off-r" + r + "-" + i));
                }
            }
            // ── 正对照夹具：串行占满额度用同一个员工 + (上限 + 1) 条等待会话。
            st.execute(employeeSql("ser", 0));
            for (int i = 1; i <= MAX_CONCURRENT + 1; i++) {
                st.execute(waitingSessionSql("as-6962-ser-" + i));
            }

            // ── 判据 2 夹具：每轮一个 pending 候选。source_ref 逐字 = 候选 id（生产里卡片
            //    source_ref 继承自候选，见 KnowledgeCandidateService#adoptInternal）⇒ 卡片归属无歧义。
            for (int r = 1; r <= ADOPT_ROUNDS; r++) {
                st.execute("INSERT INTO knowledge_candidates (id, tenant_id, source_type, source_ref,"
                        + " suggested_title, suggested_answer, suggested_category, status) VALUES ('"
                        + candidateId(r) + "', " + TENANT_A + ", 'conversation', '" + candidateId(r)
                        + "', '标题-6962-" + r + "', '回答-6962-" + r + "', 'faq', 'pending')");
            }

            // ── 判据 3 夹具：租户 A 两条**非默认**路线（deleteRouting 的「默认 ⇒ 422 / 最后一条 ⇒ 422」
            //    两条护栏都要放行）；租户 B 一条只用于跨租户对照。规则同款。
            st.execute(routeSql("rt-6962-cas-1", TENANT_A));
            st.execute(routeSql("rt-6962-cas-2", TENANT_A));
            st.execute(routeSql("rt-6963-xt", TENANT_B));
            st.execute(routeRuleSql("rr-6962-cas", TENANT_A));
            st.execute(routeRuleSql("rr-6963-xt", TENANT_B));
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("cas-6962", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器**必须在场**：生产 SQL 会经它重写 ⇒ 少了它就只测了 mapper 原文
        // （跨租户那条断言尤其依赖它：deleteRouting 的读判靠 tenant_id 限定才看不到 B 的行）。
        MybatisPlusInterceptor tenantLine = new MybatisPlusInterceptor();
        tenantLine.addInnerInterceptor(new TenantLineInnerInterceptor(new TenantLineHandler() {
            @Override
            public Expression getTenantId() {
                return new LongValue(TENANT_A);
            }

            @Override
            public String getTenantIdColumn() {
                return "tenant_id";
            }

            @Override
            public boolean ignoreTable(String tableName) {
                return false;
            }
        }));
        configuration.addInterceptor(tenantLine);
        for (Class<?> mapper : List.of(AgentSessionMapper.class, AgentMessageMapper.class,
                AgentEmployeeMapper.class, CustomerProfileMapper.class, KnowledgeCandidateMapper.class,
                KnowledgeCardMapper.class, ProductionRouteTemplateMapper.class,
                ProductionRoutingVersionMapper.class, ProductionOperationMapper.class,
                ProductionRouteRuleMapper.class, ProcessingItemMapper.class)) {
            configuration.addMapper(mapper);
        }
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
    }

    @AfterEach
    void clearProbe() {
        AgentSessionService.setAssignProbePauseMillisForTest(0L);
    }

    @AfterAll
    static void stopRealPostgres() {
        AgentSessionService.setAssignProbePauseMillisForTest(0L);
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ────────────────────────────────── 判据 1a：探针 ON + 行级冻结闸（严格档）

    @Test
    @DisplayName("判据 1a（探针 ON + 冻结闸）：同一员工 6 并发分配 ⇒ 落库 active 恰 = 上限 3，落败方全 409")
    void concurrentAssignWithProbeOnRespectsQuota() throws Exception {
        AgentSessionService.setAssignProbePauseMillisForTest(PAUSE_MILLIS);
        for (int round = 1; round <= ROUNDS; round++) {
            final String emp = employeeId("on", round);
            List<Callable<Verdict>> work = new ArrayList<>();
            for (int i = 1; i <= SESSIONS_PER_ROUND; i++) {
                final String sid = "as-6962-on-r" + round + "-" + i;
                work.add(() -> assignOne(sid, emp));
            }
            // 冻结闸锁**员工行**（FOR SHARE：不挡外键校验、只挡「抢额度」那一步的行锁）：
            // 修后每条请求都要过 lockEmployeeForQuota ⇒ 全部先跑完读判再排队；
            // 修前那条路根本不碰员工行 ⇒ 闸不会收敛（读数里会显式打印），此时按真并发读数继续判。
            List<Verdict> verdicts;
            try (RowGate gate = RowGate.lockShared("agent_employees", emp)) {
                verdicts = runConcurrently(work, gate, "agent_employees", "判据1a round" + round);
            }
            long active = activeSessions(emp);
            long successes = verdicts.stream().filter(v -> v.status == 200).count();

            System.out.println("[READING #6962 判据1a round " + round + "] 上限=" + MAX_CONCURRENT
                    + " 并发=" + SESSIONS_PER_ROUND + " 成功数=" + successes + " 落库active=" + active
                    + " 明细=" + render(verdicts));

            assertThat(active)
                    .as("同一员工并发分配后落库 active 数必须 ≤ 上限（修前实测 6 > 3 ⇒ 判红）")
                    .isLessThanOrEqualTo(MAX_CONCURRENT);
            assertThat(successes)
                    .as("库态与回执必须一致（200 的条数 == 落库 active 数），实得 成功=" + successes + " 落库=" + active)
                    .isEqualTo(active);
            assertThat(active)
                    .as("夹具额度必须被用满（3）——少了说明闸/谓词误杀了正常请求，实得 " + active)
                    .isEqualTo(MAX_CONCURRENT);
            for (Verdict v : verdicts) {
                if (v.status != 200) {
                    assertThat(v.status)
                            .as("落败方必须是显式 409 CONFLICT（冻结闸保证它已过读判 ⇒ 落败只可能来自"
                                    + "影响行数 0 / 锁内超额），实得 " + v)
                            .isEqualTo(409);
                }
            }
        }
    }

    // ────────────────────────────────── 判据 1b：探针 OFF（无注入档，真自由竞态）

    @Test
    @DisplayName("判据 1b（探针 OFF）：同一员工 6 并发分配 ⇒ 落库 active 必须 ≤ 上限（不靠窗口注入也不许破）")
    void concurrentAssignWithProbeOffRespectsQuota() throws Exception {
        AgentSessionService.setAssignProbePauseMillisForTest(0L);
        for (int round = 1; round <= ROUNDS; round++) {
            final String emp = employeeId("off", round);
            List<Callable<Verdict>> work = new ArrayList<>();
            for (int i = 1; i <= SESSIONS_PER_ROUND; i++) {
                final String sid = "as-6962-off-r" + round + "-" + i;
                work.add(() -> assignOne(sid, emp));
            }
            // 无闸：这一档要的就是「窗口收窄回微秒级」下的真并发。落败码允许 409（抢额度）或
            // 422（前置读判的快路径）—— 两者都是**显式拒绝**；仍然不许 200、更不许 500。
            List<Verdict> verdicts = runConcurrently(work, null, null, "判据1b round" + round);
            long active = activeSessions(emp);
            long successes = verdicts.stream().filter(v -> v.status == 200).count();
            long conflict = verdicts.stream().filter(v -> v.status == 409).count();

            System.out.println("[READING #6962 判据1b round " + round + "] 上限=" + MAX_CONCURRENT
                    + " 并发=" + SESSIONS_PER_ROUND + " 成功数=" + successes + " 落库active=" + active
                    + " 409数=" + conflict + " 明细=" + render(verdicts));

            assertThat(active)
                    .as("窗口收窄也必须守住上限（修前实测 6 ⇒ 判红）")
                    .isLessThanOrEqualTo(MAX_CONCURRENT);
            assertThat(successes)
                    .as("库态与回执必须一致，实得 成功=" + successes + " 落库=" + active)
                    .isEqualTo(active);
            for (Verdict v : verdicts) {
                if (v.status != 200) {
                    assertThat(v.status)
                            .as("落败方必须是显式业务拒绝（409 抢额度落败 / 422 前置读判兜底），"
                                    + "不许 500 静默炸，实得 " + v)
                            .isIn(409, 422);
                }
            }
        }
    }

    // ────────────────────────────────── 判据 1c：正对照（护栏不误杀）

    @Test
    @DisplayName("正对照：串行分配必须先占满上限（前 max 个 200），第 max+1 个才被拒")
    void serialAssignUsesFullQuotaThenRejects() {
        String emp = employeeId("ser", 0);
        AgentSessionService.setAssignProbePauseMillisForTest(0L);
        List<Verdict> verdicts = new ArrayList<>();
        for (int i = 1; i <= MAX_CONCURRENT + 1; i++) {
            verdicts.add(assignOne("as-6962-ser-" + i, emp));
        }
        long active = activeSessions(emp);
        System.out.println("[READING #6962 正对照] 上限=" + MAX_CONCURRENT + " 落库active=" + active
                + " 明细=" + render(verdicts));

        for (int i = 0; i < MAX_CONCURRENT; i++) {
            assertThat(verdicts.get(i).status)
                    .as("第 " + (i + 1) + " 个串行分配必须成功（红了 = 谓词/锁误杀正常请求），实得 " + verdicts.get(i))
                    .isEqualTo(200);
        }
        assertThat(verdicts.get(MAX_CONCURRENT).status)
                .as("第 " + (MAX_CONCURRENT + 1) + " 个必须被拒（额度已满），实得 " + verdicts.get(MAX_CONCURRENT))
                .isIn(409, 422);
        assertThat(active).as("串行占满后落库 active 恰 = 上限").isEqualTo(MAX_CONCURRENT);
    }

    // ────────────────────────────────── 判据 2：候选双采纳 ⇒ 卡片恰 1 张

    @Test
    @DisplayName("判据 2（冻结闸）：同一 pending 候选 2 并发采纳 ⇒ 恰 1 成功 / 1 个 409 / 卡片恰 1 张 / 终态 adopted")
    void concurrentAdoptYieldsExactlyOneCard() throws Exception {
        for (int round = 1; round <= ADOPT_ROUNDS; round++) {
            final String cand = candidateId(round);
            List<Callable<Verdict>> work = List.of(() -> adoptOne(cand), () -> adoptOne(cand));
            // 冻结闸锁候选行：修后两条都必须先过 getOwned 的读判、再卡在 markReviewedIfPending 的谓词上；
            // 修前那条路是「先插卡、再 updateById」⇒ 同样会卡住（两条都已插了卡）—— 这正是修前 2 张卡的形态。
            List<Verdict> verdicts;
            try (RowGate gate = RowGate.lock("knowledge_candidates", cand)) {
                verdicts = runConcurrently(work, gate, "knowledge_candidates", "判据2 round" + round);
            }
            long cards = cardCount(cand);
            String status = scalarString("SELECT status FROM knowledge_candidates WHERE id = '" + cand + "'");
            long successes = verdicts.stream().filter(v -> v.status == 200).count();

            System.out.println("[READING #6962 判据2 round " + round + "] 候选=" + cand + " 成功数=" + successes
                    + " 卡片数(source_ref=" + cand + ")=" + cards + " 候选终态=" + status
                    + " 明细=" + render(verdicts));

            assertThat(cards)
                    .as("同一候选并发双采纳后卡片必须**恰 1 张**（修前实测 2 张 ⇒ 判红）")
                    .isEqualTo(1L);
            assertThat(successes)
                    .as("恰一个赢家（回 200 的条数必须 = 1；修前两个都 200），实得 " + successes)
                    .isEqualTo(1L);
            assertThat(status)
                    .as("候选终态必须是 adopted（赢家写下的态），实得 " + status)
                    .isEqualTo("adopted");
            for (Verdict v : verdicts) {
                if (v.status != 200) {
                    assertThat(v.status)
                            .as("落败方必须是显式 409（抢发布权落败），实得 " + v)
                            .isEqualTo(409);
                }
            }
        }
    }

    // ────────────────────────────────── 判据 3：软删 CAS + 跨租户

    @Test
    @DisplayName("判据 3a（冻结闸）：同一路线 2 并发删除 ⇒ 恰 1 个 200 / 1 个 409，落库 deleted=1")
    void concurrentDeleteRoutingYieldsExactlyOneWinner() throws Exception {
        String id = "rt-6962-cas-1";
        List<Callable<Verdict>> work = List.of(
                () -> deleteRoutingOne(TENANT_A, id), () -> deleteRoutingOne(TENANT_A, id));
        List<Verdict> verdicts;
        try (RowGate gate = RowGate.lock("production_route_templates", id)) {
            verdicts = runConcurrently(work, gate, "production_route_templates", "判据3a");
        }
        long successes = verdicts.stream().filter(v -> v.status == 200).count();
        long deleted = deletedFlag("production_route_templates", id);

        System.out.println("[READING #6962 判据3a] 路线=" + id + " 成功数=" + successes
                + " 落库deleted=" + deleted + " 明细=" + render(verdicts));

        assertThat(successes)
                .as("同一路线并发双删恰一个赢家（修前实测两个都 200 = 0 行当成功 ⇒ 判红），实得 " + successes)
                .isEqualTo(1L);
        assertThat(deleted).as("软删必须真落库（issue #4608：不是静默 no-op）").isEqualTo(1L);
        for (Verdict v : verdicts) {
            if (v.status != 200) {
                assertThat(v.status)
                        .as("落败方必须是显式 409（影响行数 0），实得 " + v)
                        .isEqualTo(409);
            }
        }
    }

    @Test
    @DisplayName("判据 3b：跨租户删路线必须被拒（404 读判），B 的行必须仍是 deleted=0")
    void crossTenantDeleteRoutingRejected() {
        // 拿 B 的 id、以 A 的租户身份删：修前修后都必须删不动（这里是**既有读判**的护栏对照）
        Verdict v = deleteRoutingOne(TENANT_A, "rt-6963-xt");
        long deleted = deletedFlag("production_route_templates", "rt-6963-xt");
        System.out.println("[READING #6962 判据3b] deleteRouting(B的id, tenant=" + TENANT_A + ")=" + v
                + " B的行deleted=" + deleted);

        assertThat(v.status)
                .as("跨租户删路线必须被拒（404 读判 / 409 CAS；不许 200），实得 " + v)
                .isIn(404, 409);
        assertThat(deleted).as("B 的行必须原封不动（deleted=0）").isZero();
    }

    @Test
    @DisplayName("判据 3c（冻结闸）：同一条件工序规则 2 并发删除 ⇒ 恰 1 个 200 / 1 个 409，落库 deleted=1")
    void concurrentDeleteRouteRuleYieldsExactlyOneWinner() throws Exception {
        String id = "rr-6962-cas";
        List<Callable<Verdict>> work = List.of(
                () -> deleteRouteRuleOne(TENANT_A, id), () -> deleteRouteRuleOne(TENANT_A, id));
        List<Verdict> verdicts;
        try (RowGate gate = RowGate.lock("production_route_rules", id)) {
            verdicts = runConcurrently(work, gate, "production_route_rules", "判据3c");
        }
        long successes = verdicts.stream().filter(v -> v.status == 200).count();
        long deleted = deletedFlag("production_route_rules", id);

        System.out.println("[READING #6962 判据3c] 规则=" + id + " 成功数=" + successes
                + " 落库deleted=" + deleted + " 明细=" + render(verdicts));

        assertThat(successes)
                .as("同一规则并发双删恰一个赢家（修前实测两个都 200 ⇒ 判红），实得 " + successes)
                .isEqualTo(1L);
        assertThat(deleted).as("软删必须真落库").isEqualTo(1L);
        for (Verdict v : verdicts) {
            if (v.status != 200) {
                assertThat(v.status)
                        .as("落败方必须是显式 409（影响行数 0），实得 " + v)
                        .isEqualTo(409);
            }
        }
    }

    @Test
    @DisplayName("判据 3d：跨租户删条件工序规则必须被拒（404 读判），B 的行必须仍是 deleted=0")
    void crossTenantDeleteRouteRuleRejected() {
        Verdict v = deleteRouteRuleOne(TENANT_A, "rr-6963-xt");
        long deleted = deletedFlag("production_route_rules", "rr-6963-xt");
        System.out.println("[READING #6962 判据3d] deleteRouteRule(B的id, tenant=" + TENANT_A + ")=" + v
                + " B的行deleted=" + deleted);

        assertThat(v.status)
                .as("跨租户删规则必须被拒（404 读判 / 409 CAS；不许 200），实得 " + v)
                .isIn(404, 409);
        assertThat(deleted).as("B 的行必须原封不动（deleted=0）").isZero();
    }

    // ────────────────────────────────── 并发装置

    /**
     * 一次请求的结果（业务码 + 文本锚 + 落败判别）。
     *
     * <p>{@code cause} 把落败分开（判别只看业务码，不猜文案）：{@code CAS落败(409)} = 走到条件更新的
     * 影响行数判定 / 锁内超额；{@code 兜底(4xx)} = 提交前的**前置读判**（{@code validationError}=422 之类）；
     * {@code hard-fail} = 非业务异常（一旦出现就该判红 —— 实测 500 的读数会在断言里原样暴露）。</p>
     */
    private record Verdict(int status, String detail, String cause) {
    }

    /**
     * 行级冻结闸：测试自己的连接先锁住靶行，把并发请求钉在「<b>已过读判、卡在写谓词</b>」的确定时序上。
     *
     * <p>为什么这不是「作弊」：并发度、独立连接/事务、行锁与条件重估全部是真的；被钉住的只有
     * 「两条请求重叠」这一件事 —— 而那正是修前/修后行为分叉的那件事（修前：两条都过读判 ⇒ 两条都写；
     * 修后：两条都过读判 ⇒ 只有一条的影响行数非 0）。没有它，判据会退化成 flake（窗口微秒级）。</p>
     */
    private static final class RowGate implements AutoCloseable {

        private final Connection connection;
        private boolean released;

        private RowGate(Connection connection) {
            this.connection = connection;
        }

        /** 锁住 {@code table} 里 {@code id} 那一行（{@code SELECT … FOR UPDATE}，事务保持打开）。 */
        static RowGate lock(String table, String id) throws SQLException {
            return lock(table, id, "FOR UPDATE");
        }

        /**
         * 以 {@code FOR SHARE} 锁住那一行：**只**挡住「更强的行锁请求」，不挡外键校验。
         *
         * <p>员工行必须用这一档（PG 行锁冲突矩阵）：{@code agent_sessions.employee_id → agent_employees}
         * 的外键让 {@code markAssignedIfWaiting} 那条 UPDATE 先取到员工行的 {@code FOR KEY SHARE}
         * ⇒ 用 {@code FOR UPDATE} 当闸会连**外键校验**一起挡（读数里「行锁等待者」恒为 0，且两条请求
         * 彼此就会成环 ⇒ 死锁）。{@code FOR SHARE} 与 {@code FOR KEY SHARE} 相容、与
         * {@code FOR NO KEY UPDATE} / {@code FOR UPDATE} 冲突 ⇒ 恰好钉在「抢额度」那一步。</p>
         */
        static RowGate lockShared(String table, String id) throws SQLException {
            return lock(table, id, "FOR SHARE");
        }

        private static RowGate lock(String table, String id, String mode) throws SQLException {
            Connection c = dataSource.getConnection();
            c.setAutoCommit(false);
            boolean locked = false;
            try {
                try (Statement st = c.createStatement();
                     ResultSet rs = st.executeQuery(
                             "SELECT id FROM " + table + " WHERE id = '" + id + "' " + mode)) {
                    if (!rs.next()) {
                        throw new IllegalStateException("冻结闸锁不到靶行（夹具坏了）: " + table + "#" + id);
                    }
                }
                locked = true;
                return new RowGate(c);
            } finally {
                if (!locked) {
                    try {
                        c.close();
                    } catch (SQLException ignored) {
                        // 尽力而为
                    }
                }
            }
        }

        /** 放行（提交那把行锁）。幂等。 */
        void release() {
            if (!released) {
                released = true;
                try {
                    connection.commit();
                } catch (SQLException e) {
                    throw new IllegalStateException("冻结闸放行失败", e);
                }
            }
        }

        @Override
        public void close() {
            release();
            try {
                connection.close();
            } catch (SQLException ignored) {
                // 尽力而为（临时集群随后销毁）
            }
        }
    }

    /**
     * 同刻起跑 N 条请求；{@code gate} 非空时先等「N 个后端都在等行锁」（或请求已全部返回）再放行。
     *
     * <p>「发了 N 次」不是并发证据；本判据的并发证据 = <b>N 条请求同时卡在同一把行锁上</b>
     * （读数里的「期望锁等待者/已收敛」就是这条证据），或探针把 N 条钉在同一时刻。</p>
     */
    private static List<Verdict> runConcurrently(List<Callable<Verdict>> work, RowGate gate,
                                                 String tableName, String label) throws Exception {
        int n = work.size();
        AtomicInteger seq = new AtomicInteger();
        ExecutorService pool = Executors.newFixedThreadPool(n, r -> {
            Thread t = new Thread(r, "cas-6962-" + seq.incrementAndGet());
            t.setDaemon(true);
            return t;
        });
        CyclicBarrier barrier = new CyclicBarrier(n);
        try {
            List<Future<Verdict>> futures = new ArrayList<>();
            for (Callable<Verdict> action : work) {
                futures.add(pool.submit(() -> {
                    barrier.await(30, TimeUnit.SECONDS);
                    return action.call();
                }));
            }
            if (gate != null) {
                boolean converged = awaitLockWaitersOrDone(n, tableName, futures);
                System.out.println("[READING #6962 闸 " + label + "] 目标表=" + tableName
                        + " 期望行锁等待者=" + n + " 已凑齐=" + converged);
                gate.release();
            }
            List<Verdict> out = new ArrayList<>();
            for (Future<Verdict> f : futures) {
                out.add(f.get(120, TimeUnit.SECONDS));
            }
            return out;
        } finally {
            pool.shutdownNow();
        }
    }

    /**
     * 等「{@code tableName} 上有 {@code expected} 个后端卡在行锁上」或「请求已全部返回」。
     *
     * <p>第二种出口是给<b>修前形态</b>用的：那条路根本不碰被锁的行 ⇒ 永远凑不齐等待者，
     * 若在这里死等就会以「装置坏了」判红，而那不是缺陷读数。返回 {@code false} 表示本档没有卡在写谓词上。</p>
     */
    private static boolean awaitLockWaitersOrDone(int expected, String tableName,
                                                  List<Future<Verdict>> futures) throws SQLException {
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(GATE_WAIT_MILLIS);
        int last = 0;
        while (System.nanoTime() < deadline) {
            last = lockWaiters(tableName);
            if (last >= expected) {
                return true;
            }
            if (futures.stream().allMatch(Future::isDone)) {
                System.out.println("[READING #6962 闸] 请求已全部返回（行锁等待者最多 " + last + "/" + expected
                        + "）⇒ 本档没有卡在写谓词上（修前形态的预期读数）");
                return false;
            }
            try {
                Thread.sleep(2L);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return false;
            }
        }
        System.out.println("[READING #6962 闸] " + GATE_WAIT_MILLIS + "ms 内行锁等待者仅 " + last + "/" + expected
                + " ⇒ 按真并发读数继续判");
        return false;
    }

    /** {@code pg_stat_activity} 里卡在该表语句上的后端数（真库侧读数，不经被测面）。 */
    private static int lockWaiters(String tableName) throws SQLException {
        try (Connection c = dataSource.getConnection();
             Statement st = c.createStatement();
             ResultSet rs = st.executeQuery("SELECT count(*) FROM pg_stat_activity"
                     + " WHERE wait_event_type = 'Lock' AND query ILIKE '%" + tableName + "%'")) {
            return rs.next() ? rs.getInt(1) : 0;
        }
    }

    // ────────────────────────────────── 每次请求：各自独立连接 + 独立事务

    /** 一次 {@code assignSession}（服务层真库调用；异常 → 业务码，非业务异常 → 500 判红）。 */
    private static Verdict assignOne(String sessionId, String employeeId) {
        TenantContext.setTenantId(TENANT_A);
        try (SqlSession s = factory.openSession(false)) {
            agentSessionServiceOn(s).assignSession(sessionId, employeeId);
            s.commit();
            return new Verdict(200, "ok", "-");
        } catch (BusinessException e) {
            return new Verdict(e.getHttpStatus(), "msg=" + e.getMessage(), causeOf(e));
        } catch (RuntimeException e) {
            return hardFail(e);
        } finally {
            TenantContext.clear();
        }
    }

    /** 一次 {@code adopt}（真 knowledge_card insert）。 */
    private static Verdict adoptOne(String candidateId) {
        TenantContext.setTenantId(TENANT_A);
        try (SqlSession s = factory.openSession(false)) {
            var card = knowledgeCandidateServiceOn(s).adopt(candidateId);
            s.commit();
            return new Verdict(200, "card=" + card.getId(), "-");
        } catch (BusinessException e) {
            return new Verdict(e.getHttpStatus(), "msg=" + e.getMessage(), causeOf(e));
        } catch (RuntimeException e) {
            return hardFail(e);
        } finally {
            TenantContext.clear();
        }
    }

    /** 一次 {@code deleteRouting}（真 mapper 条件更新）。 */
    private static Verdict deleteRoutingOne(Long tenantId, String id) {
        TenantContext.setTenantId(TENANT_A);
        try (SqlSession s = factory.openSession(false)) {
            Map<String, Object> result = routingServiceOn(s).deleteRouting(id, tenantId);
            s.commit();
            return new Verdict(200, "resp.deleted=" + result.get("deleted"), "-");
        } catch (BusinessException e) {
            return new Verdict(e.getHttpStatus(), "msg=" + e.getMessage(), causeOf(e));
        } catch (RuntimeException e) {
            return hardFail(e);
        } finally {
            TenantContext.clear();
        }
    }

    /** 一次 {@code deleteRouteRule}（真 mapper 条件更新）。 */
    private static Verdict deleteRouteRuleOne(Long tenantId, String id) {
        TenantContext.setTenantId(TENANT_A);
        try (SqlSession s = factory.openSession(false)) {
            Map<String, Object> result = routingServiceOn(s).deleteRouteRule(id, tenantId);
            s.commit();
            return new Verdict(200, "resp.deleted=" + result.get("deleted"), "-");
        } catch (BusinessException e) {
            return new Verdict(e.getHttpStatus(), "msg=" + e.getMessage(), causeOf(e));
        } catch (RuntimeException e) {
            return hardFail(e);
        } finally {
            TenantContext.clear();
        }
    }

    /** 落败判别：CAS 的 409 / 锁内超额 409 vs 前置读判的 4xx（**只看码**，不猜文案）。 */
    private static String causeOf(BusinessException e) {
        return e.getHttpStatus() == 409 ? "CAS落败(409)" : "兜底(前置读判 " + e.getHttpStatus() + ")";
    }

    /** 非业务异常 = 硬失败（500）：这条一旦出现就必须判红，读数里带上异常类型。 */
    private static Verdict hardFail(RuntimeException e) {
        e.printStackTrace(System.out);
        return new Verdict(500, e.getClass().getName() + ": " + e.getMessage(), "hard-fail");
    }

    private static String render(List<Verdict> verdicts) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < verdicts.size(); i++) {
            if (i > 0) {
                sb.append(", ");
            }
            sb.append(verdicts.get(i).status).append('/').append(verdicts.get(i).cause);
        }
        return sb.append(']').toString();
    }

    // ────────────────────────────────── 真装配（真库 mapper + mock 掉非靶心依赖）

    /**
     * 真装配：{@link AgentSessionService} 的 5 个 final 字段按声明顺序注入（会话/消息/员工 mapper 走真库，
     * 客户档案与事件发布不是本判据的靶心）。{@code businessClock} 是有默认值的字段 ⇒ 不在构造参数里。
     */
    private static AgentSessionService agentSessionServiceOn(SqlSession s) {
        return new AgentSessionService(
                s.getMapper(AgentSessionMapper.class),
                s.getMapper(AgentMessageMapper.class),
                s.getMapper(AgentEmployeeMapper.class),
                s.getMapper(CustomerProfileMapper.class),
                event -> {
                    // 事件发布不是靶心（分配成功与否只看落库）
                });
    }

    /** 真装配：两个 mapper 都走真库（卡片的 insert 正是判据 2 的靶心）。 */
    private static KnowledgeCandidateService knowledgeCandidateServiceOn(SqlSession s) {
        return new KnowledgeCandidateService(
                s.getMapper(KnowledgeCandidateMapper.class),
                s.getMapper(KnowledgeCardMapper.class));
    }

    /** 真装配：路线模板 / 规则 mapper 走真库（条件更新是靶心）；查询服务不是靶心。 */
    private static ProductionRoutingCommandService routingServiceOn(SqlSession s) {
        return new ProductionRoutingCommandService(
                s.getMapper(ProductionRouteTemplateMapper.class),
                s.getMapper(ProductionRoutingVersionMapper.class),
                s.getMapper(ProductionOperationMapper.class),
                mock(ProductionOperationQueryService.class),
                s.getMapper(ProductionRouteRuleMapper.class),
                s.getMapper(ProcessingItemMapper.class));
    }

    // ────────────────────────────────── 真值读取（裸 JDBC，不经被测读面）

    private static long activeSessions(String employeeId) {
        return scalarLong("SELECT COUNT(*) FROM agent_sessions WHERE employee_id = '" + employeeId
                + "' AND status = 'active' AND deleted = 0");
    }

    /** 归属某候选的卡片数（卡片 source_ref 继承自候选 ⇒ 夹具里两者逐字相等）。 */
    private static long cardCount(String sourceRef) {
        return scalarLong("SELECT COUNT(*) FROM knowledge_cards WHERE tenant_id = " + TENANT_A
                + " AND source_ref = '" + sourceRef + "'");
    }

    private static long deletedFlag(String table, String id) {
        return scalarLong("SELECT deleted FROM " + table + " WHERE id = '" + id + "'");
    }

    private static long scalarLong(String sql) {
        try (Connection c = dataSource.getConnection();
             Statement st = c.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            return rs.next() ? rs.getLong(1) : -1L;
        } catch (SQLException e) {
            throw new IllegalStateException("真值读取失败: " + sql, e);
        }
    }

    private static String scalarString(String sql) {
        try (Connection c = dataSource.getConnection();
             Statement st = c.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            return rs.next() ? rs.getString(1) : null;
        } catch (SQLException e) {
            throw new IllegalStateException("真值读取失败: " + sql, e);
        }
    }

    // ────────────────────────────────── 夹具命名 / DDL

    private static String employeeId(String arm, int round) {
        return "emp-6962-" + arm + (round > 0 ? "-r" + round : "");
    }

    private static String candidateId(int round) {
        return "kc-6962-r" + round;
    }

    private static String employeeSql(String arm, int round) {
        String id = employeeId(arm, round);
        return "INSERT INTO agent_employees (id, tenant_id, name, status, max_concurrent_sessions, deleted) VALUES ('"
                + id + "', " + TENANT_A + ", '" + id + "', 'online', " + MAX_CONCURRENT + ", 0)";
    }

    /** 等待中的会话（{@code employee_id = NULL}：还没分配，与生产转人工的形态一致）。 */
    private static String waitingSessionSql(String id) {
        return "INSERT INTO agent_sessions (id, tenant_id, customer_id, employee_id, status, deleted) VALUES ('"
                + id + "', " + TENANT_A + ", NULL, NULL, 'waiting', 0)";
    }

    private static String routeSql(String id, Long tenantId) {
        return "INSERT INTO production_route_templates (id, tenant_id, name, is_default, deleted) VALUES ('"
                + id + "', " + tenantId + ", '" + id + "', FALSE, 0)";
    }

    private static String routeRuleSql(String id, Long tenantId) {
        return "INSERT INTO production_route_rules (id, tenant_id, trigger_kind, trigger_value, action,"
                + " operation, priority, status, deleted) VALUES ('"
                + id + "', " + tenantId + ", 'craft', '" + id + "', 'insert', '工序A', 100, 'active', 0)";
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
