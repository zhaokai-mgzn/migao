// case_ids: UI-074
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.migao.admin.dto.InboundOrderLine;
import com.migao.admin.mapper.InboundOrderQueryMapper;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import javax.sql.DataSource;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.Statement;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 入库单列表「批次号」聚合的**真库**判据（issue #5844 / UI-074）。
 *
 * <h2>为什么必须真库（mock 面结构上看不见）</h2>
 * <ol>
 *   <li>批次号在列表里是 {@code string_agg(batch_no, ',' ORDER BY batch_no)} 的**聚合**结果 ——
 *       聚合、排序、NULL 跳过全是 **SQL 语义**：「聚合写错」与「聚合根本没写」在 mock 掉的
 *       mapper 上都是「调了一次 mapper」（同一个读数）。</li>
 *   <li>{@code deleted = 0} 谓词与 {@code COUNT(*)} 同处一个子查询 ⇒ 「软删行混进批次号」
 *       而「行数仍对」这种**自相矛盾**的读数只有真库才现形。</li>
 *   <li>列表是**租户内**读面：跨租户泄漏是数据问题，不是过滤问题。</li>
 * </ol>
 *
 * <h2>三态与前端 {@code batchCell} 同源</h2>
 * 已过账 ⇒ 逗号分隔的批次号（**按号排序**）；草稿 ⇒ {@code null}（草稿不发号：批次号 =
 * 「真的收货了」的标识）；已作废 ⇒ {@code null}（永远不会过账，不得被读成「过账后生成」）。
 *
 * <h2>红证（把实现改坏 ⇒ 本类必红）</h2>
 * <ul>
 *   <li>去掉 {@code string_agg(...)} ⇒ {@code postedOrderAggregatesEveryBatchNoInOrder} 红；</li>
 *   <li>去掉 {@code ORDER BY batch_no} ⇒ 同一条判据红（插入是**倒序**的，顺序即断言）；</li>
 *   <li>聚合子查询里去掉 {@code deleted = 0} ⇒ {@code softDeletedItemDoesNotLeakIntoBatchNos} 红；</li>
 *   <li>去掉 {@code o.tenant_id = #{tenantId}} ⇒ {@code otherTenantsOrdersAreNotVisible} 红。</li>
 * </ul>
 *
 * <h2>环境</h2>
 * 一次性真 PG（{@link PgCluster}，与其他真库判据**共用同一装配**），schema 取
 * {@code db/init/schema.sql} 终态（**不手抄列清单**）。缺 PG 二进制 ⇒
 * {@code PgCluster.startOrAbort()}：CI（{@code MIGAO_REQUIRE_REALDB=1}）判红、本机显式 skip
 * （「没跑」长得像「没跑」）。
 */
@DisplayName("#5844 真库：入库单列表批次号聚合（string_agg + 草稿/作废不发号 + 租户隔离）")
class InboundOrderListBatchNosRealDbTest {

    private static final Long TENANT_ID = 5844L;
    private static final Long OTHER_TENANT_ID = 58440L;
    private static final String PRODUCT_ID = "prod-5844-1";

    private static PgCluster cluster;
    private static SqlSessionFactory factory;

    @BeforeAll
    static void startRealPostgres() throws Exception {
        cluster = PgCluster.startOrAbort();
        DataSource dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(read("backend/admin-api/src/main/resources/db/init/schema.sql"));
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-5844', 'acc-5844'), ("
                    + OTHER_TENANT_ID + ", 'acc-5844-other', 'acc-5844-other')");
            // product_id 在 inbound_order_items 上是 NOT NULL REFERENCES products(id)
            st.execute("INSERT INTO products (id, tenant_id, name) VALUES ('" + PRODUCT_ID + "', "
                    + TENANT_ID + ", '遮光窗帘布')");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("acc-5844", new JdbcTransactionFactory(), dataSource));
        configuration.addMapper(InboundOrderQueryMapper.class);
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
    }

    @AfterAll
    static void stopRealPostgres() {
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ============================================================ 判据 1：聚合 + 排序

    @Test
    @DisplayName("🔴 已过账多批次 ⇒ 逗号分隔且**按号排序**（故意倒序插入 —— 顺序就是判据）")
    void postedOrderAggregatesEveryBatchNoInOrder() throws Exception {
        seedOrder("o-posted-1", TENANT_ID, "RK-20261001-0001", "posted");
        seedItem("o-posted-1", TENANT_ID, "PC-20261001-0002", 0); // 先插大号
        seedItem("o-posted-1", TENANT_ID, "PC-20261001-0001", 0); // 再插小号

        assertThat(batchNosOf("o-posted-1")).isEqualTo("PC-20261001-0001,PC-20261001-0002");
    }

    // ============================================================ 判据 2/3：不发号的两态

    @Test
    @DisplayName("草稿未过账 ⇒ batchNos 为 null（草稿不发号；不得伪装成空串或「0 个批次」）")
    void draftOrderHasNoBatchNos() throws Exception {
        seedOrder("o-draft-1", TENANT_ID, "RK-20261001-0002", "draft");
        seedItem("o-draft-1", TENANT_ID, null, 0);

        assertThat(batchNosOf("o-draft-1")).isNull();
    }

    @Test
    @DisplayName("已作废 ⇒ batchNos 为 null（永远不会过账，不得被读成「过账后生成」）")
    void cancelledOrderHasNoBatchNos() throws Exception {
        seedOrder("o-cancelled-1", TENANT_ID, "RK-20261001-0003", "cancelled");
        seedItem("o-cancelled-1", TENANT_ID, null, 0);

        assertThat(batchNosOf("o-cancelled-1")).isNull();
    }

    // ============================================================ 判据 4：软删不混入

    @Test
    @DisplayName("🔴 软删明细不混进批次号（同一条 SQL 里的 deleted = 0 谓词 ⇒ 与行数聚合同源）")
    void softDeletedItemDoesNotLeakIntoBatchNos() throws Exception {
        seedOrder("o-posted-2", TENANT_ID, "RK-20261001-0004", "posted");
        seedItem("o-posted-2", TENANT_ID, "PC-20261001-0005", 0);
        seedItem("o-posted-2", TENANT_ID, "PC-20261001-0999", 1); // 软删行：批次号不该被看见

        InboundOrderLine row = rowOf("o-posted-2");
        assertThat(row.getBatchNos()).isEqualTo("PC-20261001-0005");
        // 同一子查询的两个读数必须**自洽**：行数也不含软删行
        assertThat(row.getItemCount()).isEqualTo(1);
    }

    // ============================================================ 判据 5：租户隔离

    @Test
    @DisplayName("🔴 跨租户读 = 数据泄漏：别人家的单不出现（同一 keyword 也读不到）")
    void otherTenantsOrdersAreNotVisible() throws Exception {
        seedOrder("o-other-1", OTHER_TENANT_ID, "RK-20261001-9001", "posted");
        seedItem("o-other-1", OTHER_TENANT_ID, "PC-20261001-9001", 0);

        List<InboundOrderLine> mine = list(TENANT_ID, "RK-20261001-9001");
        assertThat(mine).isEmpty();
        // 反向自证：对方租户自己读得到（否则「为空」可能是别的原因，不是隔离）
        assertThat(list(OTHER_TENANT_ID, "RK-20261001-9001")).hasSize(1);
    }

    // ============================================================ helpers

    private static List<InboundOrderLine> list(Long tenantId, String keyword) {
        try (SqlSession session = factory.openSession(true)) {
            return session.getMapper(InboundOrderQueryMapper.class)
                    .selectOrderLines(tenantId, keyword, null, 50);
        }
    }

    private static InboundOrderLine rowOf(String orderId) {
        return list(TENANT_ID, null).stream()
                .filter(r -> orderId.equals(r.getId()))
                .findFirst()
                .orElseThrow(() -> new AssertionError("列表里没有这张单：" + orderId));
    }

    private static String batchNosOf(String orderId) {
        return rowOf(orderId).getBatchNos();
    }

    private static void seedOrder(String id, Long tenantId, String inboundNo, String status) throws Exception {
        exec("INSERT INTO inbound_orders (id, tenant_id, inbound_no, status) VALUES ('"
                + id + "', " + tenantId + ", '" + inboundNo + "', '" + status + "')");
    }

    private static void seedItem(String orderId, Long tenantId, String batchNo, int deleted) throws Exception {
        exec("INSERT INTO inbound_order_items (tenant_id, inbound_order_id, product_id, sku_code,"
                + " quantity, batch_no, deleted) VALUES (" + tenantId + ", '" + orderId + "', '"
                + PRODUCT_ID + "', 'HUOHAO-01', 30.0, "
                + (batchNo == null ? "NULL" : "'" + batchNo + "'") + ", " + deleted + ")");
    }

    private static void exec(String sql) throws Exception {
        try (Connection conn = cluster.dataSource().getConnection();
             Statement st = conn.createStatement()) {
            st.execute(sql);
        }
    }

    private static String read(String relative) throws Exception {
        Path path = Paths.get(relative);
        if (!Files.exists(path)) {
            path = Paths.get("..", "..").resolve(relative).normalize();
        }
        return Files.readString(path);
    }
}
