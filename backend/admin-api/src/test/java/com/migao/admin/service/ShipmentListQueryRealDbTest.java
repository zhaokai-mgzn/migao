// case_ids: OR-056
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.migao.admin.dto.ShipmentListRow;
import com.migao.admin.mapper.OrderShipmentQueryMapper;
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
 * 发货单**列表**读面的**真库**判据（issue #5939）。
 *
 * <h2>为什么必须真库（mock 面结构上看不见）</h2>
 * <ol>
 *   <li><b>明细行数是聚合</b>：{@code COUNT(*)} 与 {@code deleted = 0} 同处一个子查询 ⇒
 *       「软删行混进行数」这种「单子对、数字错」的读数只有真库才现形；</li>
 *   <li><b>客户名来自连接</b>：{@code LEFT JOIN orders ... AND o.tenant_id = s.tenant_id}
 *       写错成内连接 / 漏租户维，在 mock 掉的 mapper 上都是「调了一次 mapper」；</li>
 *   <li><b>排序是 SQL 语义</b>：{@code COALESCE(shipped_at, packed_at, created_at)} 的 NULL 回退、
 *       以及同刻的稳定次序，前端读到的顺序就是它；</li>
 *   <li><b>列表是租户内读面</b>：跨租户泄漏是数据问题，不是过滤问题。</li>
 * </ol>
 *
 * <h2>红证（把实现改坏 ⇒ 本类必红）</h2>
 * <ul>
 *   <li>去掉 {@code s.tenant_id = #{tenantId}} ⇒ {@code otherTenantsShipmentsAreNotVisible} 红；</li>
 *   <li>聚合子查询去掉 {@code deleted = 0} ⇒ {@code softDeletedItemDoesNotCountIntoItemCount} 红；</li>
 *   <li>去掉 {@code LEFT JOIN orders}（或改成不取客户名）⇒ {@code customerNameComesFromTheOrder} 红；</li>
 *   <li>去掉 {@code COALESCE(...)} 的 packed_at 回退 ⇒ {@code notYetShippedRowsFallBackToPackTime} 红；</li>
 *   <li>去掉 {@code LIMIT} ⇒ {@code limitIsHonored} 红。</li>
 * </ul>
 *
 * <h2>环境</h2>
 * 一次性真 PG（{@link PgCluster}，与本包其它真库判据**共用同一装配**），schema 取
 * {@code db/init/schema.sql} 终态（**不手抄列清单**）。缺 PG 二进制 ⇒ {@code startOrAbort()}：
 * CI（{@code MIGAO_REQUIRE_REALDB=1}）判红、本机显式 skip（「没跑」长得像「没跑」）。
 */
@DisplayName("#5939 真库：发货单列表（租户隔离 / 软删不计行数 / 客户名连接 / 排序 / 上限）")
class ShipmentListQueryRealDbTest {

    private static final Long TENANT_ID = 5939L;
    private static final Long OTHER_TENANT_ID = 59390L;

    private static PgCluster cluster;
    private static SqlSessionFactory factory;

    @BeforeAll
    static void startRealPostgres() throws Exception {
        cluster = PgCluster.startOrAbort();
        DataSource dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(read("backend/admin-api/src/main/resources/db/init/schema.sql"));
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-5939', 'acc-5939'), ("
                    + OTHER_TENANT_ID + ", 'acc-5939-other', 'acc-5939-other')");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("acc-5939", new JdbcTransactionFactory(), dataSource));
        configuration.addMapper(OrderShipmentQueryMapper.class);
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
    }

    @AfterAll
    static void stopRealPostgres() {
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ══════════════════════════════════════════════════════════════ 判据 1：租户隔离

    @Test
    @DisplayName("🔴 跨租户读 = 数据泄漏：别人家的发货单不出现（同一关键词也读不到）")
    void otherTenantsShipmentsAreNotVisible() throws Exception {
        seedShipment("s-iso-mine", TENANT_ID, "o-iso-mine", "CSO5939-ISO-1",
                "FH-5939-ISO-MINE", "张女士", "2026-10-01 10:00:00+08", null);
        seedShipment("s-iso-other", OTHER_TENANT_ID, "o-iso-other", "CSO5939-ISO-2",
                "FH-5939-ISO-OTHER", "别人家", "2026-10-01 10:00:00+08", null);

        List<ShipmentListRow> mine = list(TENANT_ID, "FH-5939-ISO-", 50);
        assertThat(mine).extracting(ShipmentListRow::getShipmentNo).containsExactly("FH-5939-ISO-MINE");
        // 反向自证：对方租户自己读得到（否则「只有我这条」可能是别的原因，不是隔离）
        assertThat(list(OTHER_TENANT_ID, "FH-5939-ISO-", 50))
                .extracting(ShipmentListRow::getShipmentNo).containsExactly("FH-5939-ISO-OTHER");
    }

    // ══════════════════════════════════════════════════════════════ 判据 2：软删不计

    @Test
    @DisplayName("🔴 软删明细不计进「明细行数」（行数与批次聚合同源：都在 deleted = 0 之下）")
    void softDeletedItemDoesNotCountIntoItemCount() throws Exception {
        seedShipment("s-del", TENANT_ID, "o-del", "CSO5939-DEL", "FH-5939-DEL",
                "李女士", "2026-10-01 11:00:00+08", null);
        seedItem("s-del", TENANT_ID, "1", "10.00", 0);
        seedItem("s-del", TENANT_ID, "2", "99.00", 1); // 软删行：不该被数进行数

        assertThat(rowOf("s-del").getItemCount()).isEqualTo(1);
    }

    // ══════════════════════════════════════════════════════════════ 判据 3：客户名连接

    @Test
    @DisplayName("🔴 客户名取自 orders 行（连接不是白连：页面「客户」列有真值）")
    void customerNameComesFromTheOrder() throws Exception {
        seedShipment("s-cust", TENANT_ID, "o-cust", "CSO5939-CUST", "FH-5939-CUST",
                "王先生", "2026-10-01 12:00:00+08", null);

        assertThat(rowOf("s-cust").getCustomerName()).isEqualTo("王先生");
        assertThat(rowOf("s-cust").getOrderNo()).isEqualTo("CSO5939-CUST");
    }

    // ══════════════════════════════════════════════════════════════ 判据 4：关键词三列

    @Test
    @DisplayName("关键词三列都命中：发货单号 / 订单号 / 客户名；不匹配 ⇒ 空（不是全量）")
    void keywordMatchesShipmentNoOrderNoAndCustomer() throws Exception {
        seedShipment("s-kw", TENANT_ID, "o-kw", "CSO5939-KW", "FH-5939-KW",
                "关键词客户", "2026-10-01 13:00:00+08", null);

        assertThat(list(TENANT_ID, "FH-5939-KW", 50)).hasSize(1);
        assertThat(list(TENANT_ID, "CSO5939-KW", 50)).hasSize(1);
        assertThat(list(TENANT_ID, "关键词客户", 50)).hasSize(1);
        assertThat(list(TENANT_ID, "绝不存在的串-5939", 50)).isEmpty();
    }

    // ══════════════════════════════════════════════════════════════ 判据 5：排序

    @Test
    @DisplayName("🔴 近的在前；未发货（shipped_at 为空）按打包时间参与排序（不是永远沉底）")
    void notYetShippedRowsFallBackToPackTime() throws Exception {
        // 早发货的
        seedShipment("s-ord-old", TENANT_ID, "o-ord-old", "CSO5939-ORD-A", "FH-5939-ORD-OLD",
                "甲", "2026-10-01 09:00:00+08", "2026-10-01 09:30:00+08");
        // 还没发货，但今天打包 ⇒ 应排在最前
        seedShipment("s-ord-pack", TENANT_ID, "o-ord-pack", "CSO5939-ORD-B", "FH-5939-ORD-PACK",
                "乙", null, "2026-10-02 09:00:00+08");

        assertThat(list(TENANT_ID, "FH-5939-ORD-", 50))
                .extracting(ShipmentListRow::getShipmentNo)
                .containsExactly("FH-5939-ORD-PACK", "FH-5939-ORD-OLD");
    }

    // ══════════════════════════════════════════════════════════════ 判据 6：上限

    @Test
    @DisplayName("LIMIT 生效（流水型单据不许无界返回）")
    void limitIsHonored() throws Exception {
        for (int i = 1; i <= 3; i++) {
            seedShipment("s-lim-" + i, TENANT_ID, "o-lim-" + i, "CSO5939-LIM-" + i,
                    "FH-5939-LIM-" + i, "客户" + i, "2026-10-01 1" + i + ":00:00+08", null);
        }
        assertThat(list(TENANT_ID, "FH-5939-LIM-", 2)).hasSize(2);
        assertThat(list(TENANT_ID, "FH-5939-LIM-", 50)).hasSize(3);
    }

    // ══════════════════════════════════════════════════════════════ helpers

    private static List<ShipmentListRow> list(Long tenantId, String keyword, int limit) {
        try (SqlSession session = factory.openSession(true)) {
            return session.getMapper(OrderShipmentQueryMapper.class)
                    .selectListRows(tenantId, keyword, limit);
        }
    }

    private static ShipmentListRow rowOf(String shipmentId) {
        return list(TENANT_ID, null, 500).stream()
                .filter(r -> shipmentId.equals(r.getId()))
                .findFirst()
                .orElseThrow(() -> new AssertionError("列表里没有这张发货单：" + shipmentId));
    }

    private static void seedShipment(String id, Long tenantId, String orderId, String orderNo,
                                     String shipmentNo, String customerName,
                                     String shippedAt, String packedAt) throws Exception {
        exec("INSERT INTO orders (id, tenant_id, order_no, customer_name, status) VALUES ('"
                + orderId + "', " + tenantId + ", '" + orderNo + "', '"
                + customerName + "', 'shipped')");
        exec("INSERT INTO order_shipments (id, tenant_id, order_id, order_no, shipment_no, source,"
                + " shipped_at, packed_at, shipped_by_worker_name, tracking_no)"
                + " VALUES ('" + id + "', " + tenantId + ", '" + orderId + "', '" + orderNo + "', '"
                + shipmentNo + "', 'worker_photo', "
                + (shippedAt == null ? "NULL" : "TIMESTAMPTZ '" + shippedAt + "'") + ", "
                + (packedAt == null ? "NULL" : "TIMESTAMPTZ '" + packedAt + "'")
                + ", '小王', 'SF1234567890')");
    }

    /** 一行明细；`id` 显式给（主键无默认值 —— 省略会撞 NOT NULL 约束）。 */
    private static void seedItem(String shipmentId, Long tenantId, String itemNo, String qty,
                                 int deleted) throws Exception {
        exec("INSERT INTO order_shipment_items (id, tenant_id, shipment_id, order_id, product_name,"
                + " shipped_quantity, unit, deleted) VALUES ('item-" + shipmentId + "-" + itemNo
                + "', " + tenantId + ", '" + shipmentId
                + "', 'o-del', '遮光窗帘布', " + qty + ", '米', " + deleted + ")");
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
