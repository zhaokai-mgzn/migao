// case_ids: PR-007, PR-010
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.config.MybatisPlusConfig;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ProductResponse;
import com.migao.admin.dto.agent.AgentBatchCreateRequest;
import com.migao.admin.dto.agent.AgentBatchViews;
import com.migao.admin.entity.AgentBatch;
import com.migao.admin.entity.AgentBatchItem;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.AgentBatchItemMapper;
import com.migao.admin.mapper.AgentBatchMapper;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import javax.sql.DataSource;
import java.io.IOException;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowable;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.clearInvocations;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

/**
 * 🔴 <b>#5327 真库判据：{@code agent_batches} / {@code agent_batch_items} 的跨租户隔离。</b>
 *
 * <h2>为什么非真库不可（本类的存在理由）</h2>
 * <p>{@code AgentBatchServiceTest} 里那三条跨租户判据（execute / revert / get 各一条
 * 「{@code selectById} 查不到 ⇒ NOT_FOUND 且零写」）用的是 <b>mocked mapper</b> ——
 * mock 返回什么就是什么，<b>SQL 根本没被执行</b>。于是它要防的三类真问题在 mock 面
 * <b>结构上不可见</b>：</p>
 * <ol>
 *   <li><b>SQL 层 {@code tenant_id} 谓词写错 / 漏写</b>（拦截器没接上、被 {@code @InterceptorIgnore} 摘掉）；</li>
 *   <li>🔴 <b>列不存在</b> —— 明细表必须带 {@code tenant_id} 列，否则拦截器注入的谓词会打到不存在的列；</li>
 *   <li><b>{@code TenantLineInnerInterceptor} 的表纳管遗漏</b>（新表被塞进豁免清单 ⇒ 静默脱离隔离）。</li>
 * </ol>
 * <p>本类<b>不 mock 任何 Mapper</b>：{@code AgentBatchMapper} / {@code AgentBatchItemMapper} 都是真 MyBatis
 * 代理，SQL 真发到真 PG，租户谓词由 <b>生产那一个</b>拦截器 bean（{@link MybatisPlusConfig} 的
 * {@code mybatisPlusInterceptor()}）注入 —— 连豁免清单也是从生产对象上读的（见判据 4、5）。</p>
 *
 * <h2>判据（五条）</h2>
 * <ol>
 *   <li><b>跨租户读</b>：A 建批次 ⇒ B 读 ⇒ SQL 层看不见 A 的行 + 服务层 NOT_FOUND + 真库零写；</li>
 *   <li><b>跨租户执行</b>：同上（+ 正控：B 的尝试之后 A **仍能执行成功** ⇒ B 那次被挡是租户造成的）；</li>
 *   <li><b>跨租户撤销</b>：同 A 执行过的批次，B 撤销 ⇒ NOT_FOUND + 零写（+ A 仍能撤销成功）；</li>
 *   <li><b>明细表纳管</b>（机械）：生产 handler 对本表 {@code ignoreTable=false}、真库本表有
 *       {@code tenant_id} 列、且 B 身份下真读不到 A 的明细行 —— 三条都判；</li>
 *   <li><b>类级元守卫</b>（§23 G1/G2）：豁免台账<b>未登记即红</b>；「拦截面内却没有 {@code tenant_id} 列」
 *       的表进<b>燃尽台账</b>（只许缩短，涨跌都红）—— 现取真库 {@code information_schema}，不读文本。</li>
 * </ol>
 *
 * <h2>两层闸（实测结论，不是设计推断）</h2>
 * <p>跨租户被挡是<b>两层独立</b>的闸共同作用：① SQL 层（租户拦截器注入 {@code tenant_id} 谓词）；
 * ② 服务层（{@code AgentBatchService.requireBatch} 的显式租户比对）。<b>任一层单独成立即可挡住</b>
 * ⇒ 只摘一层时服务层判据（NOT_FOUND）仍绿 —— 这不是判据无判别力，而是<b>纵深防御</b>的语义。
 * 故本类把两层<b>分别</b>写成可观测断言，并由注入式红证逐层证明其判别力：
 * 摘表纳管 / 抹谓词 ⇒ <b>SQL 层断言</b>变红；两闸同时失效 ⇒ <b>服务层断言</b>变红。
 * 红证机具：{@code scripts/agent-batch-tenant-red-proof.py}（登记见 {@code scripts/redproof_registry.json}）。</p>
 *
 * <h2>环境与边界（如实登记）</h2>
 * <ul>
 *   <li>一次性真 PG 集群（{@code initdb} + {@code pg_ctl}，随机端口、跑完即停；共用 {@link PgCluster}），
 *       schema 取自 {@code backend/admin-api/src/main/resources/db/init/schema.sql}
 *       （bootstrap 终态，<b>不手抄列清单</b>）。缺 PG 二进制 ⇒ {@link PgCluster#startOrAbort()}：
 *       CI（{@code MIGAO_REQUIRE_REALDB=1}）⇒ 判红；本机未设该标记 ⇒ 显式 skip
 *       （「没跑」长得像「没跑」，不是通过）。</li>
 *   <li><b>被 stub 的一处</b>（在被判定的事实<b>之外</b>）：{@code ProductService}（商品侧读/写）。
 *       被判定的事实（{@code agent_batches} / {@code agent_batch_items} 的行与**拦截器重写后的 SQL**）
 *       全是真库读数；商品写路径另以 {@code verify(never())} 判「根本没被触达」。</li>
 *   <li><b>未覆盖</b>：{@code agent_batch_items} 的软删 / 并发（本单不引入并发腿）；豁免台账里
 *       {@code session_states} 的**归因**（只经 ai-agent-service 原生 SQL 读写、不经 MyBatis）
 *       是 javadoc 里的说明，未做成机械判据 —— 台账只钉「事实」，不钉「理由」。</li>
 * </ul>
 */
@DisplayName("#5327 真库：批量批次跨租户隔离（读/执行/撤销 ⇒ NOT_FOUND 且零写）+ 租户拦截纳管台账")
class AgentBatchCrossTenantRealDbTest {

    /** 租户 A（批次的属主）/ 租户 B（越权方）：本类**自造**的实体，内存库外一次性集群 ⇒ 用完即弃。 */
    private static final long TENANT_A = 531401L;
    private static final long TENANT_B = 531402L;

    private static final String PRODUCT_A = "prod-5327-a";
    private static final String CREATED_BY = "user-5327-a";
    private static final String BASE_PRICE_BEFORE = "100.00";
    private static final String BASE_PRICE_AFTER = "120.00";

    /**
     * 生产豁免清单的**冻结台账**（§23 G1「未登记即红」）：{@code ignoreTable(t)==true} 的表必须逐条在册。
     * 新增一张豁免 = 该表**静默脱离**租户隔离（不报错、只是不再过滤）⇒ 必须在这一行留痕并被评审看见。
     */
    private static final List<String> EXEMPT_TABLES_LEDGER = List.of(
            "notification_rules", "notification_templates", "platform_admins",
            "tenant_applications", "tenants");

    /**
     * 冻结台账的**风险子集**：既有 {@code tenant_id} 列、又不在拦截面内 ⇒ 只能靠业务层手写
     * {@code tenant_id} 条件兜（静默泄露面）。本仓现状恰两条（通知模板 / 规则，见
     * {@link MybatisPlusConfig} 里那段裁定注释）。
     */
    private static final List<String> EXEMPT_WITH_TENANT_ID_LEDGER = List.of(
            "notification_rules", "notification_templates");

    /**
     * 🔴 **燃尽台账（只许缩短）**：在租户拦截面内（未被豁免）、却**没有** {@code tenant_id} 列的表 ——
     * 拦截器一旦为本表改写 SQL，谓词就会打到不存在的列（issue #5327 三类真问题之二）。
     * 现状一条：{@code session_states}（只经 ai-agent-service 的原生 SQL 读写、**不经 MyBatis**
     * ⇒ 当下不是活缺陷，但「列缺失」这一事实必须显式在册）。
     * <b>只许缩短</b>：补列 / 登记豁免 / 删表之后，本行必须同 PR 缩短 —— 涨跌都红是**有意**的
     * （否则台账会悄悄腐烂成没人看的注释）。
     */
    private static final List<String> NONEXEMPT_WITHOUT_TENANT_ID_LEDGER = List.of("session_states");

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSession session;
    private static MybatisPlusInterceptor productionInterceptor;
    private static AgentBatchMapper batchMapper;
    private static AgentBatchItemMapper itemMapper;
    private static ProductService productService;
    private static AgentBatchService service;

    @BeforeAll
    static void startRealPostgresWithProductionInterceptor() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("agent-batch-5327",
                new JdbcTransactionFactory(), dataSource));
        // 🔴 用**生产 bean** 装配（不是手搓一个 handler）：表纳管范围（豁免清单）、租户列名、
        //    谓词取值时机全部取自生产真值源 ⇒ 「豁免清单被改」这件事本类必然看得见。
        productionInterceptor = new MybatisPlusConfig().mybatisPlusInterceptor();
        configuration.addInterceptor(productionInterceptor);
        configuration.addMapper(AgentBatchMapper.class);
        configuration.addMapper(AgentBatchItemMapper.class);
        SqlSessionFactory factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        session = factory.openSession(true);
        batchMapper = session.getMapper(AgentBatchMapper.class);
        itemMapper = session.getMapper(AgentBatchItemMapper.class);
        // 商品侧 stub（见类注释「边界」）；批量服务本身与两张批次表**全真**
        productService = mock(ProductService.class);
        service = new AgentBatchService(batchMapper, itemMapper, productService);
    }

    /** 每个用例从干净夹具开始：本类共用一个集群，前一个用例的行不得串味。 */
    @BeforeEach
    void resetFixtures() throws Exception {
        TenantContext.clear();
        clearInvocations(productService);
        lenient().when(productService.getProductById(PRODUCT_A, TENANT_A))
                .thenReturn(productView(BASE_PRICE_BEFORE, "on_sale"));
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("DELETE FROM agent_batch_items WHERE tenant_id IN (" + TENANT_A + "," + TENANT_B + ")");
            st.execute("DELETE FROM agent_batches WHERE tenant_id IN (" + TENANT_A + "," + TENANT_B + ")");
            st.execute("DELETE FROM products WHERE tenant_id IN (" + TENANT_A + "," + TENANT_B + ")");
            st.execute("DELETE FROM tenants WHERE id IN (" + TENANT_A + "," + TENANT_B + ")");
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_A + ", 'agent-batch-5327-a', 'agent-batch-5327-a'), ("
                    + TENANT_B + ", 'agent-batch-5327-b', 'agent-batch-5327-b')");
            st.execute("INSERT INTO products (id, tenant_id, name, base_price, status) VALUES ('"
                    + PRODUCT_A + "', " + TENANT_A + ", '布艺遮光帘A', " + BASE_PRICE_BEFORE
                    + ", 'on_sale')");
        }
    }

    @AfterAll
    static void stopRealPostgres() {
        TenantContext.clear();
        if (session != null) {
            session.close();
        }
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ══════════════════ 判据 1~3：跨租户 读 / 执行 / 撤销 ══════════════════

    @Test
    @DisplayName("🔴 跨租户读：B 读 A 的批次 ⇒ 服务层 NOT_FOUND + 真库零写 + SQL 层看不见")
    void crossTenantGetIsNotFoundAndWritesNothing() throws Exception {
        String batchId = createBatchAsTenantA();
        assertVisibleToOwner(batchId);

        String before = batchFingerprint(batchId);
        TenantContext.setTenantId(TENANT_B);
        BusinessException ex = rejection(() -> service.get(TENANT_B, batchId));
        assertThat(ex.getCode()).as("跨租户一律 NOT_FOUND（不泄露「存在但不是你的」）").isEqualTo("NOT_FOUND");
        assertThat(ex.getHttpStatus()).as("跨租户 = 404（不是 403：不泄露「存在，但不是你的」）").isEqualTo(404);
        assertThat(ex.getSuggestion()).as("文案指回创建时返回的 batchId + 说清「不属于当前租户」")
                .contains(batchId).contains("不属于当前租户");
        assertThat(batchFingerprint(batchId))
                .as("🔴 真库零写：agent_batches / agent_batch_items 逐值不变").isEqualTo(before);
        verify(productService, never()).updateProductForAgent(any(), any(), any());

        assertInvisibleToOtherTenant(batchId);

        TenantContext.setTenantId(TENANT_A);
        AgentBatchViews.Batch view = service.get(TENANT_A, batchId);
        assertThat(view.getBatchId()).as("正控：同一 batchId 在属主身份下读得到（⇒ 上面那条 NOT_FOUND 是租户造成的）")
                .isEqualTo(batchId);
        assertThat(view.getItems()).hasSize(1);
        assertThat(view.getItems().get(0).getOldValue()).isEqualTo(BASE_PRICE_BEFORE);
    }

    @Test
    @DisplayName("🔴 跨租户执行：B 执行 A 的批次 ⇒ NOT_FOUND + 零写（随后 A 仍能执行成功）")
    void crossTenantExecuteIsNotFoundAndWritesNothing() throws Exception {
        String batchId = createBatchAsTenantA();

        String before = batchFingerprint(batchId);
        TenantContext.setTenantId(TENANT_B);
        BusinessException ex = rejection(() -> service.execute(TENANT_B, batchId));
        assertThat(ex.getCode()).isEqualTo("NOT_FOUND");
        assertThat(batchFingerprint(batchId))
                .as("🔴 真库零写：没有被置 executing / done，计数与时间戳一字未动").isEqualTo(before);
        verify(productService, never()).updateProductForAgent(any(), any(), any());

        assertInvisibleToOtherTenant(batchId);

        TenantContext.setTenantId(TENANT_A);
        AgentBatchViews.Batch executed = service.execute(TENANT_A, batchId);
        assertThat(executed.getStatus()).as("正控：B 的尝试之后 A 仍能执行成功 ⇒ 该批次当时确实可执行（B 那次是被租户挡的）")
                .isEqualTo(AgentBatchService.STATUS_DONE);
        assertThat(executed.getSuccessCount()).isEqualTo(1);
    }

    @Test
    @DisplayName("🔴 跨租户撤销：B 撤销 A 已执行的批次 ⇒ NOT_FOUND + 零写（随后 A 仍能撤销成功）")
    void crossTenantRevertIsNotFoundAndWritesNothing() throws Exception {
        String batchId = createBatchAsTenantA();
        assertThat(service.execute(TENANT_A, batchId).getStatus()).as("夹具前提：A 执行成功 ⇒ 批次可撤销")
                .isEqualTo(AgentBatchService.STATUS_DONE);
        // 上面那次 A 的**合法**执行会调商品写路径 ⇒ 只判 B 这一次的调用记录
        clearInvocations(productService);

        String before = batchFingerprint(batchId);
        TenantContext.setTenantId(TENANT_B);
        BusinessException ex = rejection(() -> service.revert(TENANT_B, batchId));
        assertThat(ex.getCode()).isEqualTo("NOT_FOUND");
        assertThat(batchFingerprint(batchId))
                .as("🔴 真库零写：batch 未置 reverted、明细未被改成 skipped / reverted")
                .isEqualTo(before);
        verify(productService, never()).updateProductForAgent(any(), any(), any());

        assertInvisibleToOtherTenant(batchId);

        TenantContext.setTenantId(TENANT_A);
        AgentBatchViews.Batch reverted = service.revert(TENANT_A, batchId);
        assertThat(reverted.getStatus()).as("正控：A 自己撤销成功 ⇒ 该批次当时确实可撤销")
                .isEqualTo(AgentBatchService.STATUS_REVERTED);
    }

    // ══════════════════ 判据 4：明细表的纳管状态（机械判据）══════════════════

    @Test
    @DisplayName("🔴 agent_batch_items 在租户拦截面内：handler 不豁免 + 真库有 tenant_id 列 + B 真读不到明细行")
    void agentBatchItemsAreInsideTenantInterception() throws Exception {
        TenantLineHandler handler = tenantLineHandlerOrFail();

        assertThat(handler.ignoreTable("agent_batch_items"))
                .as("表纳管（机械判据 ①）：生产 handler 不得豁免 agent_batch_items —— "
                        + "豁免 = 明细整表静默脱离租户隔离（本仓 issue #5327 三类真问题之三）")
                .isFalse();
        assertThat(handler.ignoreTable("agent_batches"))
                .as("表纳管（机械判据 ①）：agent_batches 同理").isFalse();
        assertThat(handler.getTenantIdColumn())
                .as("谓词列名（机械判据 ②）：拦截器注入的列必须是 tenant_id（两张表都按这个列名建）")
                .isEqualTo("tenant_id");

        assertThat(columnsOf("agent_batches"))
                .as("列存在（机械判据 ③，真库 information_schema）：拦截器会给本表注入 tenant_id 谓词，"
                        + "列不存在 ⇒ 每次查询/插入 SQL 直接报错")
                .contains("tenant_id");
        assertThat(columnsOf("agent_batch_items"))
                .as("列存在（机械判据 ③）：明细表缺 tenant_id 列 ⇒ 拦截器注入的谓词打到不存在的列")
                .contains("tenant_id");

        // 行为面：真 SQL 走真拦截器 —— 明细表可查（列在）且 B 读不到 A 的行（谓词在）
        String batchId = createBatchAsTenantA();
        assertThat(readItemsAs(TENANT_A, batchId)).as("正控：A 身份下明细可读（本表 + 本列真的可用）").hasSize(1);
        assertThat(readItemsAs(TENANT_B, batchId))
                .as("行为面：B 身份下同一个 mapper 读不到 A 的明细行 ⇒ 本表确实在拦截范围内")
                .isEmpty();
    }

    // ══════════════════ 判据 5：类级元守卫（§23 G1/G2）══════════════════

    @Test
    @DisplayName("🔴 类级元守卫：豁免台账未登记即红 + 「拦截面内缺 tenant_id 列」燃尽台账（只许缩短，涨跌都红）")
    void tenantInterceptionCoverageLedgersAreFrozen() throws Exception {
        TenantLineHandler handler = tenantLineHandlerOrFail();
        Map<String, Boolean> tables = liveTablesWithTenantColumn();
        List<String> exempt = new ArrayList<>();
        List<String> exemptWithTenantId = new ArrayList<>();
        List<String> nonexemptWithoutTenantId = new ArrayList<>();
        for (Map.Entry<String, Boolean> table : tables.entrySet()) {
            if (handler.ignoreTable(table.getKey())) {
                exempt.add(table.getKey());
                if (table.getValue()) {
                    exemptWithTenantId.add(table.getKey());
                }
            } else if (!table.getValue()) {
                nonexemptWithoutTenantId.add(table.getKey());
            }
        }

        assertThat(exempt)
                .as(ledgerMessage("租户拦截豁免台账（冻结：未登记即红）", exempt, EXEMPT_TABLES_LEDGER,
                        "新增豁免 = 该表**静默脱离**租户隔离（不报错、只是不再过滤）；"
                                + "确需豁免 ⇒ 在本判据的台账里登记并在 PR 说明理由"))
                .containsExactlyElementsOf(EXEMPT_TABLES_LEDGER);
        assertThat(exemptWithTenantId)
                .as(ledgerMessage("豁免里的风险子集（有 tenant_id 却不自动过滤 = 静默泄露面）",
                        exemptWithTenantId, EXEMPT_WITH_TENANT_ID_LEDGER,
                        "本子集只许缩短：新表**不要**走豁免，走拦截器（有 tenant_id 列就无需豁免）"))
                .containsExactlyElementsOf(EXEMPT_WITH_TENANT_ID_LEDGER);
        assertThat(nonexemptWithoutTenantId)
                .as(ledgerMessage("燃尽台账（只许缩短）：在拦截面内却没有 tenant_id 列的表",
                        nonexemptWithoutTenantId, NONEXEMPT_WITHOUT_TENANT_ID_LEDGER,
                        "修法（任一）：① 补 tenant_id 列 ② 登记豁免（同时改豁免台账）③ 删表；"
                                + "做完必须**同 PR 缩短本台账**（涨跌都红是**有意**的：否则台账会腐烂成没人看的注释）"))
                .containsExactlyElementsOf(NONEXEMPT_WITHOUT_TENANT_ID_LEDGER);
    }

    // ══════════════════ 夹具与工具 ══════════════════

    /** A 租户**真建**一个批次：走真实 {@code create} ⇒ 真 SQL 落 {@code agent_batches} + {@code agent_batch_items}。 */
    private static String createBatchAsTenantA() {
        TenantContext.setTenantId(TENANT_A);
        AgentBatchCreateRequest.Item item = new AgentBatchCreateRequest.Item();
        item.setResourceId(PRODUCT_A);
        item.setField(AgentBatchService.FIELD_BASE_PRICE);
        item.setOldValue(BASE_PRICE_BEFORE);
        item.setNewValue(BASE_PRICE_AFTER);
        AgentBatchCreateRequest request = new AgentBatchCreateRequest();
        request.setBatchType(AgentBatchService.TYPE_PRODUCT_PRICE);
        request.setItems(List.of(item));
        AgentBatchViews.Batch created = service.create(TENANT_A, CREATED_BY, request);
        verify(productService).getProductById(PRODUCT_A, TENANT_A);
        assertThat(created.getStatus()).as("夹具前提：A 的批次落在 preview").isEqualTo(AgentBatchService.STATUS_PREVIEW);
        assertThat(created.getItemCount()).as("夹具前提：明细真的落了库（1 条）").isEqualTo(1);
        return created.getBatchId();
    }

    /** 正控：属主身份下**服务层**读得到（⇒ 后面的 NOT_FOUND 不是「id 不存在 / 夹具空跑」）。 */
    private static void assertVisibleToOwner(String batchId) {
        AgentBatch row = readBatchRowAs(TENANT_A, batchId);
        assertThat(row == null ? "null（拦截器把属主自己的行也过滤掉了）" : row.getTenantId())
                .as("正控：A 身份下 SQL 层读得到自己的批次").isEqualTo(TENANT_A);
    }

    /** 🔴 SQL 层判据：B 身份下同一个 mapper 读不到 A 的行（谓词在 + 列在 + 表已纳管）。 */
    private static void assertInvisibleToOtherTenant(String batchId) {
        assertThat(readBatchRowAs(TENANT_B, batchId))
                .as("SQL 层：租户拦截器必须给 agent_batches 注入 tenant_id 谓词 ⇒ B 读不到 A 的批次行；"
                        + "读到非 null ⇒ 表未纳管 / 谓词被抹掉 / 列不存在（三类真问题之一）")
                .isNull();
        assertThat(readItemsAs(TENANT_B, batchId))
                .as("SQL 层：agent_batch_items 同样纳管 ⇒ B 读不到 A 的明细行").isEmpty();
    }

    private static AgentBatch readBatchRowAs(long tenantId, String batchId) {
        TenantContext.setTenantId(tenantId);
        return batchMapper.selectById(batchId);
    }

    private static List<AgentBatchItem> readItemsAs(long tenantId, String batchId) {
        TenantContext.setTenantId(tenantId);
        return itemMapper.selectList(new LambdaQueryWrapper<AgentBatchItem>()
                .eq(AgentBatchItem::getBatchId, batchId)
                .orderByAsc(AgentBatchItem::getId));
    }

    /**
     * 生产拦截器上的租户 handler（**唯一真值源**：豁免清单 / 列名都从它读）。
     * 取不到 ⇒ 判红（不是跳过）：生产装配里没有租户拦截器时，本类所有「隔离」结论都无从谈起。
     */
    private static TenantLineHandler tenantLineHandlerOrFail() {
        return productionInterceptor.getInterceptors().stream()
                .filter(TenantLineInnerInterceptor.class::isInstance)
                .map(TenantLineInnerInterceptor.class::cast)
                .findFirst()
                .orElseThrow(() -> new AssertionError(
                        "生产 MybatisPlusInterceptor 里没有 TenantLineInnerInterceptor ⇒ 租户隔离整条腿不在场"
                                + "（表纳管范围无从判定）—— 本判据判 FAIL，不是 skip。"
                                + "装配源：backend/admin-api/src/main/java/com/migao/admin/config/MybatisPlusConfig.java"))
                .getTenantLineHandler();
    }

    /** 判红文案（§23 G3）：实测读数 + 台账 + **可复制命令** + 该状态下的真出口。 */
    private static String ledgerMessage(String what, List<String> measured, List<String> ledger,
                                       String exit) {
        return what + "：实测 = " + measured + "；冻结台账 = " + ledger + "。"
                + "处置：" + exit + "。复算（真库现取）：" + recomputeCommand();
    }

    private static String recomputeCommand() {
        return "psql '" + ((DriverManagerDataSource) dataSource).getUrl() + "' -At -F'|' -c \"SELECT t.table_name,"
                + " EXISTS(SELECT 1 FROM information_schema.columns c WHERE c.table_schema='public'"
                + " AND c.table_name=t.table_name AND c.column_name='tenant_id') FROM information_schema.tables t"
                + " WHERE t.table_schema='public' AND t.table_type='BASE TABLE' ORDER BY 1\"";
    }

    /** 真库现取（**不读 schema.sql 文本**）：表 → 是否有 tenant_id 列。 */
    private static Map<String, Boolean> liveTablesWithTenantColumn() throws Exception {
        Map<String, Boolean> out = new TreeMap<>();
        try (Connection conn = dataSource.getConnection();
             Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(
                     "SELECT t.table_name, EXISTS(SELECT 1 FROM information_schema.columns c"
                             + " WHERE c.table_schema = 'public' AND c.table_name = t.table_name"
                             + " AND c.column_name = 'tenant_id')"
                             + " FROM information_schema.tables t"
                             + " WHERE t.table_schema = 'public' AND t.table_type = 'BASE TABLE'")) {
            while (rs.next()) {
                out.put(rs.getString(1), rs.getBoolean(2));
            }
        }
        return out;
    }

    private static List<String> columnsOf(String table) throws Exception {
        List<String> out = new ArrayList<>();
        try (Connection conn = dataSource.getConnection();
             Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT column_name FROM information_schema.columns"
                     + " WHERE table_schema = 'public' AND table_name = '" + table + "'"
                     + " ORDER BY ordinal_position")) {
            while (rs.next()) {
                out.add(rs.getString(1));
            }
        }
        return out;
    }

    /**
     * 两张表的**逐值指纹**（raw JDBC，不经拦截器 ⇒ 无论租户身份如何都读到库里的原样）：
     * 状态 / 计数 / 两个时间戳 + 明细的逐条 status / error / old_value / new_value。
     * 一次越权尝试只要写了任何一个字节，这里必然不等。
     */
    private static String batchFingerprint(String batchId) throws Exception {
        return "batch[" + text("SELECT status || '|' || item_count || '|' || success_count || '|' || fail_count"
                + " || '|' || COALESCE(executed_at::text, '-') || '|' || COALESCE(reverted_at::text, '-')"
                + " FROM agent_batches WHERE id = '" + batchId + "'") + "]"
                + " items[" + text("SELECT COALESCE(string_agg(id || ':' || status || ':' || COALESCE(error, '-')"
                + " || ':' || COALESCE(old_value, '-') || ':' || COALESCE(new_value, '-'), ';' ORDER BY id), '∅')"
                + " FROM agent_batch_items WHERE batch_id = '" + batchId + "'") + "]";
    }

    private static ProductResponse productView(String price, String status) {
        ProductResponse view = new ProductResponse();
        view.setBasePrice(new BigDecimal(price));
        view.setStatus(status);
        return view;
    }

    /** 断言「被拒绝」：拿不到 BusinessException ⇒ 这条判据判红（**不是**静默通过）。 */
    private static BusinessException rejection(ThrowingRunnable call) {
        Throwable thrown = catchThrowable(call::run);
        assertThat(thrown).as("跨租户访问必须被拒绝（BusinessException），实得 " + thrown)
                .isInstanceOf(BusinessException.class);
        return (BusinessException) thrown;
    }

    private static String text(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).as("查询必须有结果：" + sql).isTrue();
            return rs.getString(1);
        }
    }

    private static String schemaSql() throws IOException {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 backend/admin-api/src/main/resources/db/init/schema.sql"
                + "（真库建表取终态 schema，不手抄列清单）").isNotNull();
        return Files.readString(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"));
    }

    /** 只需要「会抛」的可执行体（避免为一次捕获引入 AssertJ 的 ThrowingCallable 语义）。 */
    @FunctionalInterface
    private interface ThrowingRunnable {
        void run() throws Exception;
    }
}