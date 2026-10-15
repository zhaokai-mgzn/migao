// case_ids: PG-076

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.ProcessingOrderResponse;
import com.migao.admin.dto.ProcessingOrderUpdateRequest;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingFeeCombinationMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import com.migao.admin.mapper.StockLedgerMapper;
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
import java.lang.reflect.Field;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.List;
import java.util.Set;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

/**
 * 🔴 真库并发判据（issue #6955）：<b>加工单状态迁移「读判 × 写」无谓词 ⇒ 相反迁移双双成功 / 订单与加工单终态自相矛盾</b>。
 *
 * <h2>核验的是哪一条主张</h2>
 * 修前 {@link ProcessingOrderService#updateStatus} 先读内存旧值过状态机
 * （{@code STATUS_TRANSITIONS}），再 {@code processingOrderMapper.updateById(upd)}（WHERE 仅主键 ⇒
 * <b>无谓词</b>）⇒ 读判与写之间没有任何互斥。同一份迁移权上有两个写面
 * （手工入口 {@code updateStatus} 的 issue/cancel、订单联动腿 {@code OrderService#cancelOrder} 自动作废），
 * 而 {@code issued} 与 {@code cancelled} 在状态机里<b>互不可达</b> ⇒ 并发下终态<b>必然</b>自相矛盾：
 * <ul>
 *   <li><b>形态 ①</b> 同一张加工单并发 {@code issue} + {@code cancel} ⇒ <b>两个请求都 200</b>，
 *       落库态由后写者决定（{@code issued} 或 {@code cancelled}，另一个请求的 200 是谎话）；</li>
 *   <li><b>形态 ②</b> 订单作废 × 加工单开工 ⇒ 出现「<b>订单 cancelled + 加工单 issued</b>」
 *       —— 订单已废、单还在产（订单联动的对称性被破坏）。</li>
 * </ul>
 * 修后两处都走 {@link ProcessingOrderMapper#markStatusIfFrom}（{@code WHERE id=? AND tenant_id=?
 * AND deleted=0 AND status=<状态机授权的前驱>}），按<b>影响行数</b>判谁抢到迁移权：0 行 ⇒ 409 +
 * 实际当前态的可行动文案。
 *
 * <h2>为什么必须真库 + 窗口注入</h2>
 * CAS 的全部效力来自只有真 PG 才有的两件事：<b>① 行锁</b>（条件更新的判断与写入是同一条语句，
 * 命中行的锁持有到事务结束）、<b>② 条件重估</b>（后到者阻塞到前者提交后按新版本行重估谓词 ⇒
 * 影响行数 0）。mock 面结构上判不了：mock 的 {@code updateById} 恒返回 1、也不会因 WHERE 不满足
 * 而返回 0 ⇒ 修前形态在 mock 上恒绿（假绿）。而窗口只有微秒级（#6928 实测 HTTP 20 轮只命中 3 轮）
 * ⇒ 用 {@link ProcessingOrderService#setStatusUpdateProbePauseMillisForTest} 与
 * {@link OrderService#setCancelOrderPoProbePauseMillisForTest}（生产恒为 0）把窗口放大，
 * 判据才是<b>确定性</b>的，而不是 flake。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>至多一个赢家</b>：同一加工单并发 {@code issue} × {@code cancel} ⇒ 成功数 <b>恰 == 1</b>，
 *       落败方必须是 <b>409 CONFLICT</b>（修前实测两个都 200 ⇒ 判红）；</li>
 *   <li><b>终态属合法集且与赢家一致</b>：终态 ∈ {@code STATUS_TRANSITIONS} 的合法态集合
 *       （夹具常量，<b>不读被测读面</b>），且 == 赢家目标态；</li>
 *   <li><b>订单 × 加工单不出现自相矛盾终态</b>：订单 cancel × 加工单 issue 并发 ⇒
 *       <b>不得</b>出现「订单 cancelled + 加工单 issued」（修前实测该形态 ⇒ 判红），
 *       且只要订单取消失败（非 200），订单终态就<b>不得</b>是 cancelled（「请求失败却落了终态」）。</li>
 * </ol>
 *
 * <h2>判别力（红证，注入式 · 双向）</h2>
 * 把两处写退回修前的无谓词 {@code updateById}：<b>探针开</b> ⇒ 判据 1/3 必红（逐字读数见 PR body）；
 * <b>探针关</b>（{@code pauseMillis=0}）⇒ 不红（窗口收窄回微秒级，碰不到）。修后两处走 CAS ⇒ 探针开也全绿。
 * 正对照：串行单请求 issue / cancel 必须照旧成功（谓词非空 ⇒ 不误杀正常请求）。
 *
 * <p><b>边界（如实登记，不粉饰）</b>：① 本判据跑的是<b>服务层真库并发</b>而非 HTTP 栈
 * （{@code PATCH /api/admin/processing-orders/{id}} 与 {@code POST /api/admin/orders/{id}/cancel}
 * 只是薄转发，状态机与联动写入全在服务层）；② 探针对象全部自建
 * （tenant {@value #TENANT_ID} / 单号前缀 {@code po-6955}），随一次性临时集群销毁，
 * <b>不碰任何存量数据</b>；③ 本判据<b>不</b>覆盖 {@code ProductionService#ensureQrToken} 那条
 * {@code updateById}（它不写 status，形态相邻但不在本单射程 —— 由类级元守卫的
 * {@code coverage_boundary} 逐条登记）。</p>
 */
@DisplayName("🔴 真库并发判据（#6955）：加工单状态迁移 = CAS，恰一个赢家 + 订单/加工单终态不自相矛盾")
class ProcessingOrderStatusCasRaceRealDbTest {

    private static final Long TENANT_ID = 6955L;
    private static final String PO_PREFIX = "po-6955-";

    /**
     * 状态机合法的状态集合（夹具常量，**独立于被测读面** —— 从 {@code STATUS_TRANSITIONS} 抄成常量会让
     * 「状态机被改坏」也判绿）。真值 = {@code ProcessingOrderService.STATUS_TRANSITIONS} 的键∪值。
     */
    private static final Set<String> LEGAL_STATUSES =
            Set.of("generated", "issued", "in_processing", "completed", "cancelled");

    /** 形态 ① 的轮数（每轮一张独立加工单）。 */
    private static final int ROUNDS = 3;
    /** 形态 ② 的轮数（每轮一对独立订单+加工单）。 */
    private static final int LINK_ROUNDS = 3;
    /** 正对照的独立夹具轮号（**必须与竞态轮分开** —— 否则并发轮的库态被对照测试提前改掉 ⇒ 判据自伤）。 */
    private static final int SERIAL_ROUND = ROUNDS + 1;

    /** 窗口注入时长（毫秒）：必须显著大于另一条路的全程（实测 ~10~30ms）。 */
    private static final long PAUSE_MILLIS = 800L;
    /** 等「探针已进入窗口」的上限（确定性时序的护栏；超时 = 判据装置坏了）。 */
    private static final long PAUSE_WAIT_MILLIS = 10_000L;

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
                    + TENANT_ID + ", 'po-6955', 'po-6955')");
            for (int r = 1; r <= SERIAL_ROUND; r++) {
                // 形态 ①：只要加工单（走 ProcessingOrderService，订单联动因该订单是 cancelled 态而跳过
                // —— 本形态的靶心是加工单自己的迁移权，不是联动）。FK 要求订单行真实存在。
                st.execute("INSERT INTO orders (id, tenant_id, order_no, status) VALUES ('"
                        + orderIdOf(poId(r)) + "', " + TENANT_ID + ", '" + orderNoOfDangling(r) + "', 'cancelled')");
                st.execute("INSERT INTO processing_orders (id, tenant_id, order_id, processing_order_no, status) VALUES ('"
                        + poId(r) + "', " + TENANT_ID + ", '" + orderIdOf(poId(r)) + "', '"
                        + poNo(r) + "', 'generated')");
            }
            for (int r = 1; r <= LINK_ROUNDS; r++) {
                // 形态 ②：真订单（confirmed）+ 真加工单（generated）
                st.execute("INSERT INTO orders (id, tenant_id, order_no, status) VALUES ('"
                        + orderId(r) + "', " + TENANT_ID + ", '" + orderNo(r) + "', 'confirmed')");
                st.execute("INSERT INTO processing_orders (id, tenant_id, order_id, processing_order_no, status) VALUES ('"
                        + poIdOfOrder(r) + "', " + TENANT_ID + ", '" + orderId(r) + "', '"
                        + poNoOfOrder(r) + "', 'generated')");
            }
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("po-6955", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器**必须在场**：生产 SQL 会经它重写 ⇒ 少了它就只测了 mapper 原文
        MybatisPlusInterceptor tenantLine = new MybatisPlusInterceptor();
        tenantLine.addInnerInterceptor(new TenantLineInnerInterceptor(new TenantLineHandler() {
            @Override
            public Expression getTenantId() {
                return new LongValue(TENANT_ID);
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
        for (Class<?> mapper : List.of(ProcessingOrderMapper.class, OrderMapper.class, OrderItemMapper.class,
                ProcessingItemMapper.class, StockLedgerMapper.class, ProductSkuMapper.class, ProductMapper.class,
                FinanceTransactionMapper.class, OrderLogisticsMapper.class)) {
            configuration.addMapper(mapper);
        }
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
    }

    @AfterEach
    void clearProbe() {
        ProcessingOrderService.setStatusUpdateProbePauseMillisForTest(0L);
        OrderService.setCancelOrderPoProbePauseMillisForTest(0L);
    }

    @AfterAll
    static void stopRealPostgres() {
        ProcessingOrderService.setStatusUpdateProbePauseMillisForTest(0L);
        OrderService.setCancelOrderPoProbePauseMillisForTest(0L);
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ────────────────────────────────── 判据 1~2：同一加工单 issue × cancel 交叉竞态

    @Test
    @DisplayName("同一加工单 issue × cancel 交叉竞态（3 轮）：恰一个赢家 + 终态合法且与赢家一致")
    void concurrentIssueAndCancelOnSameProcessingOrder() throws Exception {
        ProcessingOrderService.setStatusUpdateProbePauseMillisForTest(PAUSE_MILLIS);
        for (int round = 1; round <= ROUNDS; round++) {
            final String id = poId(round);

            // 两条请求经 CyclicBarrier **同刻起跑**（各自独立连接 + 独立事务）⇒ 探针关掉时这也是一次
            // 真并发（只是窗口收窄回微秒级），而不是「一条跑完了另一条才开始」的假并发。
            CyclicBarrier barrier = new CyclicBarrier(2);
            ExecutorService pool = Executors.newFixedThreadPool(2);
            // ① cancel（带原因 —— 那条校验在探针之前，不给原因会 422 早退、探针永远进不去）
            Future<Verdict> cancelFuture = pool.submit(() -> {
                barrier.await(30, TimeUnit.SECONDS);
                return runOne("cancel", id, "并发竞态取消原因");
            });
            Future<Verdict> issueFuture = pool.submit(() -> {
                barrier.await(30, TimeUnit.SECONDS);
                // 同形态②：等 cancel 停进窗口再起跑（否则它会抢在探针之前把单推成 issued，
                // 我们只看到「前置读判拒了」而看不到「CAS 只放一个赢家过去」）。
                if (ProcessingOrderService.statusUpdateProbeMillisForTest() > 0) {
                    awaitProbeEntered(ProcessingOrderService::statusUpdateProbePausedForTest);
                }
                return runOne("issue", id, null);
            });
            // ② 探针**开着**时等它真的进入窗口（确定性时序 —— 不是 sleep 猜时间）；
            //    探针是 0（对照档）时窗口本来就进不去，直接取两条并发结果即可。
            if (ProcessingOrderService.statusUpdateProbeMillisForTest() > 0
                    && !awaitProbePausedOrCompleted(
                            ProcessingOrderService::statusUpdateProbePausedForTest, cancelFuture)) {
                System.out.println("[READING #6955 时序] 形态① 探针在窗口开启前就返回 提前结果=" + cancelFuture.get());
            }
            Verdict issue = issueFuture.get(60, TimeUnit.SECONDS);
            Verdict cancel = cancelFuture.get(60, TimeUnit.SECONDS);
            pool.shutdown();

            String dbStatus = scalarString("SELECT status FROM processing_orders WHERE id = '" + id + "'");
            long successes = (issue.status == 200 ? 1 : 0) + (cancel.status == 200 ? 1 : 0);
            String winnerTarget = issue.status == 200 ? "issued" : "cancelled";

            System.out.println("[READING #6955 形态① round " + round + "] issue=" + issue.status + "(" + issue.detail + ")"
                    + " cancel=" + cancel.status + "(" + cancel.detail + ")"
                    + " 落败原因=" + (issue.status == 200 ? cancel.cause : issue.cause)
                    + " 成功数=" + successes + " 加工单终态=" + dbStatus);

            assertThat(successes)
                    .as("issue 与 cancel 争同一份状态迁移权 ⇒ **恰一个**赢家（两个都 200 就是修前的缺陷形态）")
                    .isEqualTo(1L);
            assertThat(issue.status == 200 || issue.status == 409)
                    .as("落败方必须是显式 409 CONFLICT（不是 500 / 不是静默成功），实得 " + issue.status)
                    .isTrue();
            assertThat(cancel.status == 200 || cancel.status == 409)
                    .as("落败方必须是显式 409 CONFLICT（不是 500 / 不是静默成功），实得 " + cancel.status)
                    .isTrue();
            assertThat(LEGAL_STATUSES)
                    .as("加工单终态必须落在状态机的合法态集合里（夹具常量），实得 " + dbStatus)
                    .contains(dbStatus);
            assertThat(dbStatus)
                    .as("终态必须与赢家的目标态一致（issue 赢 ⇒ issued；cancel 赢 ⇒ cancelled）")
                    .isEqualTo(winnerTarget);
            // 🔴 判别力的第三靶心（**最直接**的一条）：谁回了 200，终态就必须**是**它声称的那个态。
            // 修前实测：issue=200(resp=issued) 而加工单终态=cancelled、cancel=200(resp=cancelled) 而
            // 加工单终态=issued ⇒ **200 是谎话**（一个请求报成功、库里却是另一个请求的终态）。
            if (issue.status == 200) {
                assertThat(dbStatus)
                        .as("issue 回了 200(resp=" + issue.detail + ") ⇒ 终态必须就是 issued（回 200 却落到别人的终态 = 谎报成功）")
                        .isEqualTo("issued");
            }
            if (cancel.status == 200) {
                assertThat(dbStatus)
                        .as("cancel 回了 200 ⇒ 终态必须就是 cancelled（回 200 却落到别人的终态 = 谎报成功）")
                        .isEqualTo("cancelled");
            }
        }
    }

    // ────────────────────────────────── 判据 3：订单 cancel × 加工单 issue 不得自相矛盾

    @Test
    @DisplayName("订单 cancel × 加工单 issue 并发（3 轮）：不得出现「订单 cancelled + 加工单 issued」")
    void orderCancelAndProcessingOrderIssueDoNotContradict() throws Exception {
        OrderService.setCancelOrderPoProbePauseMillisForTest(PAUSE_MILLIS);
        for (int round = 1; round <= LINK_ROUNDS; round++) {
            final String orderId = orderId(round);
            final String poId = poIdOfOrder(round);

            // 同刻起跑（同形态① 的口径：探针关掉时这也是一次真并发，不是假并发）
            CyclicBarrier barrier = new CyclicBarrier(2);
            ExecutorService pool = Executors.newFixedThreadPool(2);
            Future<Verdict> cancelFuture = pool.submit(() -> {
                barrier.await(30, TimeUnit.SECONDS);
                return runOne("order-cancel", orderId, null);
            });
            Future<Verdict> issueFuture = pool.submit(() -> {
                barrier.await(30, TimeUnit.SECONDS);
                // 🔴 让 issue 腿**等 cancel 真的停进窗口**再起跑：否则它可能先把加工单推成 issued，
                //    而 cancel 的**前置读判**（比探针更早的那一步）就此看到 issued、走 422 兜底分支
                //    ⇒ 前置读判抢在探针前面 ⇒ CAS 那一跳永远测不到（本判据初版实测就是这种形态）。
                //    探针关掉（对照档）时不设闸：那时要的就是一次真并发。
                if (OrderService.cancelOrderPoProbeMillisForTest() > 0) {
                    awaitProbeEntered(OrderService::cancelOrderPoProbePausedForTest);
                }
                return runOne("issue", poId, null);
            });
            // ② issue 腿**等探针真的进入窗口**再起跑（确定性时序：这段时间里 cancel 已跑完它的
            //    「读判（订单 + 加工单 generated）」并停住 ⇒ 之后 cancel 的 CAS 必然看到 issue 写过的新行）
            if (OrderService.cancelOrderPoProbeMillisForTest() > 0
                    && !awaitProbePausedOrCompleted(OrderService::cancelOrderPoProbePausedForTest, cancelFuture)) {
                System.out.println("[READING #6955 时序] 形态② 探针在窗口开启前就返回 提前结果=" + cancelFuture.get());
            }
            Verdict issue = issueFuture.get(60, TimeUnit.SECONDS);
            Verdict cancel = cancelFuture.get(60, TimeUnit.SECONDS);
            pool.shutdown();

            String orderStatus = scalarString("SELECT status FROM orders WHERE id = '" + orderId + "'");
            String poStatus = scalarString("SELECT status FROM processing_orders WHERE id = '" + poId + "'");

            System.out.println("[READING #6955 形态② round " + round + "] orderCancel=" + cancel.status
                    + "(" + cancel.detail + ") 落败原因=" + cancel.cause
                    + " issue=" + issue.status + "(" + issue.detail + ")"
                    + " 订单终态=" + orderStatus + " 加工单终态=" + poStatus);

            // 🔴 判别力的**主靶心**（修前逐字实测这一条必红）：订单取消回 200 ⇒ 订单终态就必须是
            // cancelled **且**加工单也被它作废；而开工腿回 200(resp=issued) ⇒ 那份「已发加工」的意图
            // 也已被接受。两者同时成立 ⇒ 终态只能是「订单 cancelled + 加工单 cancelled/issued」这种
            // **互相排斥的组合**（修前实测：orderCancel=200 + issue=200(resp=issued) + 订单 cancelled +
            // 加工单 cancelled = 「订单已废、加工单却被另一个请求成功开工过」）。
            if (issue.status == 200) {
                String issueResp = issue.detail.startsWith("resp=") ? issue.detail.substring(5) : issue.detail;
                assertThat(issueResp)
                        .as("开工腿回 200 时它的响应态必须是 issued（否则不是成功迁移）")
                        .isEqualTo("issued");
                assertThat(orderStatus)
                        .as("加工单开工**成功**（200/resp=issued）⇒ 订单不得是 cancelled"
                                + "（订单已废、单还在产 = 两个相反迁移双双成功的形态）")
                        .isNotEqualTo("cancelled");
            }
            assertThat(orderStatus + "+" + poStatus)
                    .as("**不得出现「订单 cancelled + 加工单 issued」** —— 订单已废、单还在产（本单要治的形态）")
                    .isNotEqualTo("cancelled+issued");
            assertThat(poStatus)
                    .as("加工单终态必须落在状态机的合法态集合里")
                    .isIn(LEGAL_STATUSES);
            if (cancel.status != 200) {
                assertThat(orderStatus)
                        .as("订单取消失败（非 200）却把订单落成 cancelled = 「请求失败却落了终态」")
                        .isNotEqualTo("cancelled");
            }
            // 🔴 修前实测的**直接矛盾**（本判据判别力的靶心，逐字读数见 PR body）：开工那条腿明明成功了
            // （issue=200，加工单到 issued），而订单终态同时是 cancelled ⇒ **两个动作都成功**却落在
            // 互相排斥的终态上（订单已废、单还在产）——「订单取消 × 加工单开工」的对称性被破坏。
            // 🔴 两个动作都成功 == 修前的缺陷形态（本判据判别力的第二靶心）：订单取消回 200、加工单开工也回
            // 200 ⇒ 两份互相排斥的意图被**同时**接受 ⇒ 终态必然是「订单 cancelled + 加工单 issued」
            // （订单已废、单还在产）。本单的病就是「两个相反迁移可以双双成功」。
            if (cancel.status == 200 && issue.status == 200) {
                assertThat(orderStatus + "+" + poStatus)
                        .as("订单取消与加工单开工**都成功**时，终态必然是互相排斥的那一对（修前实测形态）")
                        .isNotEqualTo("cancelled+issued");
            }
            if (issue.status == 200 && "issued".equals(poStatus)) {
                assertThat(orderStatus)
                        .as("开工成功（加工单 issued）与订单 cancelled 是互相排斥的终态；两个都成功 = 修前的缺陷形态")
                        .isNotEqualTo("cancelled");
            }
        }
    }

    // ────────────────────────────────── 正对照：护栏不误杀

    @Test
    @DisplayName("正对照（护栏不误杀）：无并发时 issue / cancel 串行各成功一次、终态正确")
    void serialTransitionsStillSucceed() {
        // 谓词带 status=<前驱> ⇒ 若谓词写错（如写成常量 null / 写错前驱），**所有**迁移都会被 409 误杀。
        // 这条与上面的判据合起来才是完整证据：CAS **拦得住并发**且**不误杀正常请求**。
        String id = poId(SERIAL_ROUND);
        ProcessingOrderService.setStatusUpdateProbePauseMillisForTest(0L);
        Verdict issue = runOne("issue", id, null);
        String afterIssue = scalarString("SELECT status FROM processing_orders WHERE id = '" + id + "'");
        Verdict cancelAfterIssue = runOne("cancel", id, "正对照取消原因");
        String afterCancel = scalarString("SELECT status FROM processing_orders WHERE id = '" + id + "'");
        System.out.println("[READING #6955 正对照] issue=" + issue.status + "(" + issue.detail + ") 终态=" + afterIssue
                + " → cancel=" + cancelAfterIssue.status + "(" + cancelAfterIssue.detail + ") 终态=" + afterCancel);

        assertThat(issue.status).as("串行 issue 必须成功（这条红了 = 谓词误杀正常请求）").isEqualTo(200);
        assertThat(afterIssue).as("issue 后终态").isEqualTo("issued");
        // issued → cancelled 是状态机的合法迁移（issued 的前驱不是 generated）⇒ 第二次必须成功
        assertThat(cancelAfterIssue.status).as("issued → cancelled 是合法迁移，必须成功").isEqualTo(200);
        assertThat(afterCancel).as("cancel 后终态").isEqualTo("cancelled");
    }

    // ────────────────────────────────── 并发装置

    /** 一次请求的结果（HTTP 业务码 + 文本锚；服务层用异常的业务码等价表达）。 */
    /**
     * 一次请求的结果（HTTP 业务码 + 文本锚 + **落败原因判别**）。
     *
     * <p>{@code cause} 把两种落败分开（读日志时不必猜，判别只看**业务码**，不猜文案）：
     * ① {@code 兜底} = <b>提交前的前置读判</b>就拒了 —— 加工单那条路是 {@code validationError}（400/422），
     * 订单那条路是 422（与 CAS 的 409 **不同码**，见 {@code ProcessingOrderService} 的
     * {@code BusinessException.conflict} 与订单腿的 {@code validationError}）。它说明并发对手
     * <b>先完成了整条路</b> ⇒ 本次探针没抢在对手之前 → 是时序读数；② {@code CAS落败} = 走到尾部的
     * 条件更新才落败（409）⇒ 探针真的把窗口撑开了，且 CAS 正确地只放一个赢家过去。</p>
     */
    private record Verdict(int status, String detail, String cause) {
    }

    private static Verdict runOne(String action, String id, String reason) {
        try (SqlSession s = factory.openSession(false)) {
            if ("order-cancel".equals(action)) {
                orderServiceOn(s).cancelOrder(id, reason);
                s.commit();
                return new Verdict(200, "ok", "-");
            }
            ProcessingOrderService service = processingOrderServiceOn(s);
            ProcessingOrderUpdateRequest req = new ProcessingOrderUpdateRequest();
            req.setAction(action);
            req.setReason(reason);
            ProcessingOrderResponse resp = service.updateStatus(id, req, TENANT_ID, "admin-6955");
            s.commit();
            return new Verdict(200, "resp=" + resp.getStatus(), "-");
        } catch (BusinessException e) {
            // 业务异常 = 显式 4xx（本判据只认 200 / 409 两种；500 会让上面的断言红）
            return new Verdict(e.getHttpStatus(), "msg=" + e.getMessage(), causeOf(e));
        }
    }

    /** 落败判别：CAS 的 409 vs 前置读判的 400/422（**只看码**，不猜文案）。 */
    private static String causeOf(BusinessException e) {
        return e.getHttpStatus() == 409 ? "CAS落败(409)" : "兜底(前置读判)";
    }

    /**
     * 忙等探针进入窗口（**不带**「或已返回」那一支）：调用方要求「对手必须先进窗口」时用它 ——
     * 探针关掉（对照档）时调用方不会调它。超时 ⇒ 判据装置坏了（fail-closed，不许静默继续）。
     */
    private static void awaitProbeEntered(java.util.function.BooleanSupplier entered) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(PAUSE_WAIT_MILLIS);
        while (System.nanoTime() < deadline) {
            if (entered.getAsBoolean()) {
                return;
            }
            Thread.sleep(2L);
        }
        throw new IllegalStateException("对手探针未在 " + PAUSE_WAIT_MILLIS + "ms 内进入窗口 —— 判据装置坏了");
    }

    /**
     * 等探针进入暂停窗口，或等请求**在窗口开启前**先返回。
     *
     * <p><b>为什么带「或已返回」这一支</b>：探针关掉（对照档）时窗口本来就进不去 ⇒ 若在这里死等，
     * 判据会以「装置坏了」判红，而那不是缺陷读数（对照档要的是「不红」）。返回 {@code false}
     * 表示探针没进窗口 ⇒ 调用方打印提前结果、按真并发读数继续判。</p>
     *
     * @return 探针是否真的进入过窗口
     */
    private static boolean awaitProbePausedOrCompleted(java.util.function.BooleanSupplier entered,
                                                       Future<?> request) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(PAUSE_WAIT_MILLIS);
        while (System.nanoTime() < deadline) {
            if (entered.getAsBoolean()) {
                return true;
            }
            if (request.isDone()) {
                return false;
            }
            Thread.sleep(5L);
        }
        throw new IllegalStateException("探针未在 " + PAUSE_WAIT_MILLIS + "ms 内进入窗口 —— 判据装置坏了");
    }

    /** 真装配：加工单状态迁移走**真库 mapper**；订单联动用 mock（形态① 的靶心不是联动）。 */
    private static ProcessingOrderService processingOrderServiceOn(SqlSession s) {
        ProcessingOrderService service = new ProcessingOrderService(
                s.getMapper(ProcessingOrderMapper.class),
                s.getMapper(OrderMapper.class),
                s.getMapper(OrderItemMapper.class),
                s.getMapper(ProcessingItemMapper.class),
                mock(OrderService.class),
                new ObjectMapper(),
                mock(ProductionService.class),
                mock(ProductionOperationQueryService.class),
                mock(ProductionOperationQtyClient.class));
        injectField(service, "stockBatchConsumptionService", mock(StockBatchConsumptionService.class));
        return service;
    }

    /** 真装配：订单取消联动腿走**真 processingOrderMapper**（靶心），其余依赖 mock。 */
    private static OrderService orderServiceOn(SqlSession s) {
        ProcessingOrderMapper realPoMapper = s.getMapper(ProcessingOrderMapper.class);
        StockLedgerService stockLedgerService = new StockLedgerService(
                s.getMapper(StockLedgerMapper.class), s.getMapper(ProductSkuMapper.class));
        OrderService service = new OrderService(
                s.getMapper(OrderMapper.class),
                s.getMapper(OrderItemMapper.class),
                mock(OrderLogisticsMapper.class),
                mock(CustomerService.class),
                s.getMapper(ProductMapper.class),
                s.getMapper(ProductSkuMapper.class),
                mock(FinanceTransactionMapper.class),
                new ObjectMapper(),
                mock(NotificationService.class),
                realPoMapper,
                mock(UserService.class),
                mock(ClientRequestIdService.class),
                stockLedgerService,
                new ProcessingFeeCalculator(mock(ProcessingFeeCombinationMapper.class),
                        mock(ProductionRouteRuleMapper.class)),
                mock(ProcessingFeeCombinationCommandService.class));
        injectField(service, "stockBatchConsumptionService", mock(StockBatchConsumptionService.class));
        return service;
    }

    /** 字段注入（与生产装配同路：这些依赖刻意不是构造参数，见各自的字段注释）。 */
    private static void injectField(Object target, String field, Object value) {
        try {
            Field f = target.getClass().getDeclaredField(field);
            f.setAccessible(true);
            f.set(target, value);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("装配失败: " + field, e);
        }
    }

    // ────────────────────────────────── 真值读取（裸 JDBC，不经被测读面）

    private static String scalarString(String sql) {
        try (Connection c = dataSource.getConnection();
             Statement st = c.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            return rs.next() ? rs.getString(1) : null;
        } catch (SQLException e) {
            throw new IllegalStateException("真值读取失败: " + sql, e);
        }
    }

    // ────────────────────────────────── 夹具命名

    private static String poId(int round) {
        return PO_PREFIX + "s" + round;
    }

    /** 形态① 的加工单指向一个 **cancelled 订单**（联动分支跳过 ⇒ 只测加工单自己的迁移权）。 */
    private static String orderIdOf(String poId) {
        return poId + "-no-order";
    }

    private static String orderNoOfDangling(int round) {
        return "ORD-6955-D" + round;
    }

    private static String poNo(int round) {
        return "PO-6955-S" + round;
    }

    private static String orderId(int round) {
        return "o-6955-l" + round;
    }

    private static String orderNo(int round) {
        return "ORD-6955-L" + round;
    }

    private static String poIdOfOrder(int round) {
        return PO_PREFIX + "l" + round;
    }

    private static String poNoOfOrder(int round) {
        return "PO-6955-L" + round;
    }

    // ────────────────────────────────── schema

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
