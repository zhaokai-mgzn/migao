// case_ids: PR-079, PR-082
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.ProcessingOrderResponse;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.mapper.ProcessingOrderMapper;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
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
import java.sql.Statement;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.catchThrowable;

/**
 * 🔴 <b>订单级加急 / 客户要求到货日（V120，issue #5177）的**真库**判据</b>。
 *
 * <h2>为什么必须真库（Mockito 测不出来）</h2>
 * 本单的四个判据的对象全是**库层事实**，mock 面结构上不可见：
 * <ol>
 *   <li><b>V120 幂等可重复执行</b>（判据 7）：靠的是
 *       {@code ADD COLUMN IF NOT EXISTS} / {@code SET NOT NULL} / 终态对账 {@code DO} 块
 *       在**第二遍**仍然成立 —— mock 里没有 SQL 引擎，这条判据在 mock 面**不存在**。</li>
 *   <li><b>列类型正确</b>（判据 7）：{@code boolean} vs {@code date} 由
 *       {@code information_schema} 读，不是由 Java 类型推断（V118 已登记过「列精度不是闸门」
 *       这类「DB 静默按四舍五入落库」的陷阱 ⇒ 只能读真库）。</li>
 *   <li><b>零联动</b>（判据 1）：要让 {@code after_sales_tickets.priority} **真的**存在一行，
 *       再改订单加急，才能证明「改这边不动那边」。纯 Java 断言只能证明「没调用某个方法」。</li>
 *   <li><b>透传进快照</b>（范围 5）：两个键要真的经过 **JSONB 编解码**回到 Java，
 *       并且能被 {@code ProcessingOrderItemBrief} 解析 —— 后者是本仓既有的一处
 *       **静默退化**：快照里出现 DTO 没声明的键 ⇒ {@code convertValue} 抛错被 catch ⇒
 *       {@code items} 整段变 null，接口照样 200。⇒ 本类把它做成**可证伪**的判据
 *       （见 {@link #undeclaredSnapshotKeySilentlyDegradesItems()} 红的对照）。</li>
 * </ol>
 *
 * <h2>环境</h2>
 * 一次性真 PG 集群（{@code initdb} + {@code pg_ctl}，随机端口、跑完即停；共用 {@link PgCluster}，
 * 同 #5167/#5169 的收口），schema 取自 {@code docs/sql/schema.sql}（bootstrap 终态，
 * **不手抄列清单**）。缺 PG 二进制 ⇒ {@link PgCluster#startOrAbort()}：
 * CI（{@code MIGAO_REQUIRE_REALDB=1}）⇒ 判红；本机未设该标记 ⇒ 显式 skip（「没跑」长得像「没跑」，不是通过）。
 */
@DisplayName("#5177 真库守卫：V120 两遍幂等 + 列类型 + 零联动 + 不损失客户 + 加急透传进快照")
class OrderUrgencyRealDbTest {

    private static final Long TENANT_ID = 5177L;
    private static final String ORDER_ID = "acc-5177-order";
    private static final String ORDER_NO = "ORD-5177-0001";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSession session;
    private static ProcessingOrderMapper processingOrderMapper;

    @BeforeAll
    static void startRealPostgresAndSchema() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-5177', 'acc-5177')");
            // 订单夹具：**不传 is_urgent / required_delivery_date** ⇒ 走列默认（判据 2 的缺省形态）
            st.execute("INSERT INTO orders (id, tenant_id, order_no, customer_name, customer_phone,"
                    + " status, total_amount, actual_amount, discount_amount) VALUES ('" + ORDER_ID + "', "
                    + TENANT_ID + ", '" + ORDER_NO + "', '张三', '13800138000', 'confirmed',"
                    + " 1234.56, 1200.00, 34.56)");
            // 售后工单夹具：**独立的一张表、独立的一行** ⇒ 判据 1 的对照物
            st.execute("INSERT INTO after_sales_tickets (id, tenant_id, ticket_no, order_id,"
                    + " ticket_type, priority) VALUES ('acc-5177-ticket', " + TENANT_ID
                    + ", 'AS-5177-0001', '" + ORDER_ID + "', 'return', 'critical')");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("acc-5177", new JdbcTransactionFactory(), dataSource));
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
        configuration.addMapper(ProcessingOrderMapper.class);
        SqlSessionFactory factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        session = factory.openSession(true);
        processingOrderMapper = session.getMapper(ProcessingOrderMapper.class);
    }

    @AfterAll
    static void stopRealPostgres() {
        if (session != null) {
            session.close();
        }
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ─────────────────────────────────────────── 判据 7：迁移质量

    @Test
    @DisplayName("🔴 判据7 V120 **两遍都成功**（幂等可重复执行）+ 列类型/默认/NOT NULL 逐字对账")
    void v120AppliesTwiceAndColumnShapeIsExact() throws Exception {
        String migration = migrationSql("V120__order_urgency_and_required_delivery_date.sql");
        // 第一遍：schema.sql（bootstrap 终态）里已有这两列 ⇒ ADD COLUMN IF NOT EXISTS 必须容忍；
        // 第二遍：全部语句（含 NOT NULL / 默认值 / 终态对账 DO 块）必须再次成立。
        // ⚠️ 两遍都跑在**同一个库**上 —— 迁移链以外的真实形态正是「重复执行」。
        execute(migration);
        execute(migration);
        System.out.println("[#5177 判别性实验] V120 在同一库上连续执行两遍均成功（幂等自证）");

        assertThat(text("SELECT data_type FROM information_schema.columns WHERE table_schema='public'"
                + " AND table_name='orders' AND column_name='is_urgent'"))
                .as("is_urgent 必须是 boolean").isEqualTo("boolean");
        assertThat(text("SELECT is_nullable FROM information_schema.columns WHERE table_schema='public'"
                + " AND table_name='orders' AND column_name='is_urgent'"))
                .as("🔴 NOT NULL ⇒ 没有第三态：「未标加急」与「明确不加急」必须同值")
                .isEqualTo("NO");
        assertThat(text("SELECT column_default FROM information_schema.columns WHERE table_schema='public'"
                + " AND table_name='orders' AND column_name='is_urgent'"))
                .as("列默认必须存在且为 false（缺省一变，行为就不再与今天逐值相同）")
                .isNotNull().containsIgnoringCase("false");
        assertThat(text("SELECT data_type FROM information_schema.columns WHERE table_schema='public'"
                + " AND table_name='orders' AND column_name='required_delivery_date'"))
                .as("🔴 required_delivery_date 必须是 **date**（不是 timestamp —— 只有日期精度的"
                        + "事实带时刻会让「10 月 1 日」在别的时区读成 9 月 30 日）")
                .isEqualTo("date");
        assertThat(text("SELECT is_nullable FROM information_schema.columns WHERE table_schema='public'"
                + " AND table_name='orders' AND column_name='required_delivery_date'"))
                .as("可空 = 「未指定」有独立真值（不回填、不猜）").isEqualTo("YES");
    }

    @Test
    @DisplayName("🔴 判据7 前置 fail-closed：库里**没有 orders 表**时 V120 必须停下（不兜底建表）")
    void v120RefusesToRunWithoutTheOrdersTable() throws Exception {
        // 前置检查这一半在「schema.sql 已建表」的夹具下**结构上不可达**（如实登记过）⇒
        // 另开一个**空库**来触发它：迁移必须抛错并点名缺哪张表，而**不是** CREATE TABLE 兜底
        // （兜底会造出没有租户列/外键/索引的影子表，比失败坏得多）。
        String url = ((DriverManagerDataSource) dataSource).getUrl();
        String emptyDb = "acc5177_empty";
        execute("DROP DATABASE IF EXISTS " + emptyDb);
        execute("CREATE DATABASE " + emptyDb);
        String migration = migrationSql("V120__order_urgency_and_required_delivery_date.sql");
        String emptyUrl = url.replace("/postgres?", "/" + emptyDb + "?");
        // ⚠️ 失败会**中止该连接的事务**（V120 显式 `BEGIN; … COMMIT;` ⇒ 报错后事务被 abort）：
        // 所以「读影子表」必须换**新连接**，不能在报错那条连接上继续查
        //（实测：同连接续查会得到 `当前事务被终止` 而不是我们要判的事实）。
        try (Connection conn = java.sql.DriverManager.getConnection(emptyUrl, "postgres", "");
             Statement st = conn.createStatement()) {
            Throwable thrown = catchThrowable(() -> st.execute(migration));
            assertThat(thrown).as("🔴 缺前置表 ⇒ V120 必须失败并停下（fail-closed）").isNotNull();
            assertThat(causeChainMessages(thrown))
                    .as("错误必须**点名缺哪张表**（可行动的失败，不是一个笼统的 SQL 错误）")
                    .contains("V120 前置表缺失").contains("orders");
        }
        try (Connection conn = java.sql.DriverManager.getConnection(emptyUrl, "postgres", "");
             Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT COUNT(*) FROM information_schema.tables"
                     + " WHERE table_schema='public' AND table_name='orders'")) {
            assertThat(rs.next()).isTrue();
            assertThat(rs.getInt(1))
                    .as("失败路径**不得** CREATE TABLE 兜底 —— 影子表没有租户列/外键/索引，比失败坏得多")
                    .isZero();
        } finally {
            execute("DROP DATABASE IF EXISTS " + emptyDb);
        }
    }

    // ─────────────────────────────────────────── 判据 2：缺省不变

    @Test
    @DisplayName("判据2 缺省不变：建单未传两列 ⇒ is_urgent 落 FALSE、到货日落 NULL（与今天逐值相同）")
    void absentValuesFallBackToColumnDefaults() throws Exception {
        assertThat(text("SELECT is_urgent::text FROM orders WHERE id = '" + ORDER_ID + "'"))
                .as("🔴 未传 ⇒ false（= 今天的行为：所有单都不加急、都进池）").isEqualTo("false");
        assertThat(text("SELECT required_delivery_date FROM orders WHERE id = '" + ORDER_ID + "'"))
                .as("未指定 ⇒ NULL（**不猜**：不用今天/承诺交期顶替）").isNull();

        // 显式设值 ⇒ 逐值可读（改单三态里的「设置」那一态）
        execute("UPDATE orders SET is_urgent = TRUE, required_delivery_date = DATE '2026-10-01'"
                + " WHERE id = '" + ORDER_ID + "'");
        assertThat(text("SELECT is_urgent::text FROM orders WHERE id = '" + ORDER_ID + "'"))
                .isEqualTo("true");
        assertThat(text("SELECT required_delivery_date FROM orders WHERE id = '" + ORDER_ID + "'"))
                .as("DATE 列读回的就是那一天（不带时刻、不跨时区漂移）").isEqualTo("2026-10-01");

        // 「清空」必须真的能落 NULL（改单三态的第三态；MyBatis-Plus 的 NOT_NULL 策略会跳过 null 字段
        // ⇒ 走 `updateById` 永远清不掉，这正是 OrderService.updateUrgency 用显式 set 的理由）
        execute("UPDATE orders SET is_urgent = FALSE, required_delivery_date = NULL"
                + " WHERE id = '" + ORDER_ID + "'");
        assertThat(text("SELECT required_delivery_date FROM orders WHERE id = '" + ORDER_ID + "'"))
                .as("清空后回到「未指定」").isNull();
        assertThat(text("SELECT is_urgent::text FROM orders WHERE id = '" + ORDER_ID + "'"))
                .as("取消加急是真值（false），不是「未填」").isEqualTo("false");
    }

    // ─────────────────────────────────────────── 判据 1：零联动

    @Test
    @DisplayName("🔴 判据1 零联动（真库双向）：订单加急 ⇎ 售后 priority 逐值不变")
    void orderUrgencyAndTicketPriorityAreIndependentInBothDirections() throws Exception {
        // ① 订单加急 ⇒ 售后 priority **逐值不变**
        String priorityBefore = text("SELECT priority FROM after_sales_tickets WHERE id = 'acc-5177-ticket'");
        assertThat(priorityBefore).as("夹具前置：售后 priority 有一行真值").isEqualTo("critical");
        execute("UPDATE orders SET is_urgent = TRUE WHERE id = '" + ORDER_ID + "'");
        assertThat(text("SELECT priority FROM after_sales_tickets WHERE id = 'acc-5177-ticket'"))
                .as("🔴 给订单标加急**不得**改售后 priority（用户裁定「加急不能跟售后工单绑定」）")
                .isEqualTo(priorityBefore);
        assertThat(count("SELECT COUNT(*) FROM after_sales_tickets WHERE tenant_id = " + TENANT_ID))
                .as("也不得凭空多出/少掉工单（不是「改了另一行」的假通过）").isEqualTo(1L);

        // ② 售后 priority 变 ⇒ 订单加急 **逐值不变**
        execute("UPDATE after_sales_tickets SET priority = 'normal' WHERE id = 'acc-5177-ticket'");
        assertThat(text("SELECT is_urgent::text FROM orders WHERE id = '" + ORDER_ID + "'"))
                .as("🔴 反过来也成立：改售后优先级**不得**插队生产")
                .isEqualTo("true");
        // 复原（同一测试内自洽，不依赖执行顺序）
        execute("UPDATE after_sales_tickets SET priority = 'critical' WHERE id = 'acc-5177-ticket'");
        execute("UPDATE orders SET is_urgent = FALSE WHERE id = '" + ORDER_ID + "'");
    }

    // ─────────────────────────────────────────── 判据 6：不损失客户

    @Test
    @DisplayName("判据6 不损失客户：加急/到货日**不影响**对客金额（逐值不变）")
    void urgencyNeverTouchesCustomerFacingAmounts() throws Exception {
        List<String> amountsBefore = List.of(
                text("SELECT total_amount::text FROM orders WHERE id = '" + ORDER_ID + "'"),
                text("SELECT actual_amount::text FROM orders WHERE id = '" + ORDER_ID + "'"),
                text("SELECT discount_amount::text FROM orders WHERE id = '" + ORDER_ID + "'"));

        execute("UPDATE orders SET is_urgent = TRUE, required_delivery_date = DATE '2026-10-01'"
                + " WHERE id = '" + ORDER_ID + "'");
        List<String> amountsAfterUrgent = List.of(
                text("SELECT total_amount::text FROM orders WHERE id = '" + ORDER_ID + "'"),
                text("SELECT actual_amount::text FROM orders WHERE id = '" + ORDER_ID + "'"),
                text("SELECT discount_amount::text FROM orders WHERE id = '" + ORDER_ID + "'"));
        assertThat(amountsAfterUrgent)
                .as("🔴 加急/到货日只影响**是否入池/派单时机**，不动对客金额（判据 6）")
                .isEqualTo(amountsBefore);

        execute("UPDATE orders SET is_urgent = FALSE, required_delivery_date = NULL"
                + " WHERE id = '" + ORDER_ID + "'");
        assertThat(List.of(
                text("SELECT total_amount::text FROM orders WHERE id = '" + ORDER_ID + "'"),
                text("SELECT actual_amount::text FROM orders WHERE id = '" + ORDER_ID + "'"),
                text("SELECT discount_amount::text FROM orders WHERE id = '" + ORDER_ID + "'")))
                .as("取消加急/清空到货日同样不动金额（双向都不动）").isEqualTo(amountsBefore);
    }

    // ─────────────────────────────────────────── 范围 5：加急透传进快照

    @Test
    @DisplayName("🔴 范围5 透传：两个订单级键经 **JSONB 真编解码**回来，且能被响应 DTO 解析（items 不为 null）")
    void orderLevelKeysRoundTripThroughJsonbAndParseIntoResponseDto() throws Exception {
        List<Map<String, Object>> snapshot = new ArrayList<>();
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("itemId", "acc-5177-item");
        row.put("productName", "布艺遮光帘A");
        row.put("quantity", 3);
        // 与 ProcessingOrderService.stampOrderUrgency 落的键**逐字同名**
        row.put("isUrgent", true);
        row.put("requiredDeliveryDate", "2026-10-01");
        snapshot.add(row);

        ProcessingOrder po = ProcessingOrder.builder()
                .id("acc-5177-po").tenantId(TENANT_ID).orderId(ORDER_ID)
                .processingOrderNo("JG-5177-0001").status("generated")
                .itemsSnapshot(snapshot).templateVersion(1).printCount(0).deleted(0).build();
        processingOrderMapper.insert(po);

        ProcessingOrder readBack = processingOrderMapper.selectById("acc-5177-po");
        assertThat(readBack).as("加工单必须落库可读").isNotNull();
        List<Map<String, Object>> snapshotReadBack = normalized(readBack.getItemsSnapshot());
        assertThat(snapshotReadBack).as("快照是行数组 ⇒ 订单级事实只能逐行固化").hasSize(1);
        assertThat(snapshotReadBack.get(0))
                .as("🔴 isUrgent 经 JSONB 往返后仍是布尔 true（不是字符串 \"true\"）")
                .containsEntry("isUrgent", true);
        assertThat(snapshotReadBack.get(0))
                .as("requiredDeliveryDate 往返后仍是 YYYY-MM-DD 字符串")
                .containsEntry("requiredDeliveryDate", "2026-10-01");

        // 读面必须能解析：`ProcessingOrderResponse.ProcessingOrderItemBrief` 是本仓的一处**静默退化**点
        // （未声明的键 ⇒ convertValue 抛错被 catch ⇒ items 整段 null，接口照样 200）
        List<ProcessingOrderResponse.ProcessingOrderItemBrief> briefs = new ObjectMapper().convertValue(
                snapshotReadBack,
                new ObjectMapper().getTypeFactory().constructCollectionType(List.class,
                        ProcessingOrderResponse.ProcessingOrderItemBrief.class));
        assertThat(briefs).as("🔴 快照必须能被响应 DTO 解析（否则 items 静默变 null）").hasSize(1);
        assertThat(briefs.get(0).getIsUrgent()).as("行情级加急标记在响应里逐值可读").isEqualTo(true);
        assertThat(briefs.get(0).getRequiredDeliveryDate()).isEqualTo("2026-10-01");
        System.out.println("[#5177 判别性实验] 真库快照读回 = " + snapshotReadBack.get(0));
    }

    @Test
    @DisplayName("红证对照：快照里多一个**DTO 未声明**的键 ⇒ 解析抛错（items 静默变 null 的成因）")
    void undeclaredSnapshotKeySilentlyDegradesItems() {
        List<Map<String, Object>> snapshot = new ArrayList<>();
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("itemId", "acc-5177-item");
        row.put("isUrgent", true);
        // 未在 ProcessingOrderItemBrief 里声明的键 —— 正是「新键不加进 DTO」的形态
        row.put("__undeclared_5177_key__", "x");
        snapshot.add(row);

        assertThatThrownBy(() -> new ObjectMapper().convertValue(snapshot,
                new ObjectMapper().getTypeFactory().constructCollectionType(List.class,
                        ProcessingOrderResponse.ProcessingOrderItemBrief.class)))
                .as("🔴 这条断言给上面那条提供判别力：若 isUrgent/requiredDeliveryDate 没被声明，"
                        + "上面那条会以同样方式抛错 ⇒ 不是「碰巧通过」")
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("__undeclared_5177_key__");
    }

    // ─────────────────────────────────────────── 夹具

    /** 快照读回归一：{@code autoResultMap} 生效时是 List，未生效时是 JSON 字符串（读面两条路都要认）。 */
    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> normalized(Object snapshot) throws Exception {
        if (snapshot instanceof List<?> list) {
            return (List<Map<String, Object>>) list;
        }
        assertThat(snapshot).as("processing_orders.items_snapshot 必须是 List 或 JSON 字符串")
                .isInstanceOf(String.class);
        return new ObjectMapper().readValue((String) snapshot,
                new ObjectMapper().getTypeFactory().constructCollectionType(List.class, Map.class));
    }

    private static String migrationSql(String fileName) throws IOException {
        Path root = repoRoot();
        return Files.readString(root.resolve("backend/admin-api/src/main/resources/db/migration")
                .resolve(fileName));
    }

    private static String schemaSql() throws IOException {
        return Files.readString(repoRoot().resolve("docs/sql/schema.sql"));
    }

    private static Path repoRoot() {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve("docs/sql/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位仓库根（真库建表取 schema.sql 终态，不手抄列清单）").isNotNull();
        return root;
    }

    /** 异常链上所有 message 拼起来（多语句迁移的报错可能包在外层「事务被终止」里）。 */
    private static String causeChainMessages(Throwable thrown) {
        StringBuilder out = new StringBuilder();
        for (Throwable t = thrown; t != null; t = t.getCause()) {
            out.append(t.getMessage()).append('\n');
        }
        return out.toString();
    }

    private static void execute(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(sql);
        }
    }

    /** 取一个标量（TEXT 口径）；无行 ⇒ {@code null}。 */
    private static String text(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            return rs.next() ? rs.getString(1) : null;
        }
    }

    private static long count(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).as("查询必须有结果：" + sql).isTrue();
            return rs.getLong(1);
        }
    }
}
