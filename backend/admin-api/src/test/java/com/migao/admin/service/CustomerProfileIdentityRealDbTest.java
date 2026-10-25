// case_ids: CU-009, OR-045

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.mapper.CustomerProfileMapper;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import javax.sql.DataSource;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * issue #7711 真库判据：**同一人只留一条档案**（自动识别 + 合并）+ **补空不覆盖**。
 *
 * <h2>为什么必须真 PG</h2>
 * 两条修法的正确性都在 SQL 语义里，mock 上不可证：
 * <ol>
 *   <li>「已有值不被订单覆盖」靠 {@code COALESCE(NULLIF(BTRIM(列), ''), 新值)} —— mock 里只有字符串；</li>
 *   <li>「合并」要按 {@code REFERENCES customer_profiles(id)} 的真实外键顺序迁引用 ——
 *       顺序错了是**外键/唯一键异常**，不是断言失败；</li>
 *   <li>「先删 loser 再补身份键」的顺序靠 V167 的部分唯一索引才咬得动。</li>
 * </ol>
 *
 * <h2>判据</h2>
 * <ol>
 *   <li><b>收敛</b>：手机号一条（早）+ openid 一条（晚）⇒ 合并成 1 条，keeper = 最早那条，
 *       会话/售后/分群/客户价全部改挂到 keeper，keeper 空列从 loser 补空；</li>
 *   <li><b>补空不覆盖</b>：客服维护过的收货地址/承运商不被订单值覆盖，空列被补；</li>
 *   <li><b>先登录后下单</b>（最常见时序）⇒ 最终只有 1 条且两个身份键齐全；</li>
 *   <li><b>判别力自证</b>：进入收敛前库里确实是 2 条（证明修的是真存在的病）。</li>
 * </ol>
 */
@DisplayName("7711 真库：同一人双档案自动收敛 + 订单信息补空不覆盖")
class CustomerProfileIdentityRealDbTest {

    private static final Long TENANT = 7711L;
    private static final String PHONE = "13900007711";
    private static final String OPENID = "openid-7711";
    private static final String SEGMENT_1 = "seg-7711-1";
    private static final String SEGMENT_2 = "seg-7711-2";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static JdbcTemplate jdbcTemplate;
    private static SqlSessionFactory factory;

    @BeforeAll
    static void startRealPostgresAndApplySchema() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        jdbcTemplate = new JdbcTemplate(dataSource);
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT + ", 'cp-7711', 'cp-7711')");
            // 合并要迁的两张带外键的表需要夹具父行
            st.execute("INSERT INTO products (id, tenant_id, name) VALUES ('prod-7711', " + TENANT + ", '夹具商品')");
            st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width) VALUES "
                    + "(771101, " + TENANT + ", 'prod-7711', '2.8m'), "
                    + "(771102, " + TENANT + ", 'prod-7711', '3.2m')");
            st.execute("INSERT INTO customer_segments (id, tenant_id, name, segment_type, conditions) VALUES "
                    + "('" + SEGMENT_1 + "', " + TENANT + ", '分群一', 'custom', '{}'::jsonb), "
                    + "('" + SEGMENT_2 + "', " + TENANT + ", '分群二', 'custom', '{}'::jsonb)");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("cp-7711", new JdbcTransactionFactory(), dataSource));
        MybatisPlusInterceptor tenantLine = new MybatisPlusInterceptor();
        tenantLine.addInnerInterceptor(new TenantLineInnerInterceptor(new TenantLineHandler() {
            @Override
            public Expression getTenantId() {
                return new LongValue(TenantContext.getTenantId() == null ? 0L : TenantContext.getTenantId());
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
        configuration.addMapper(CustomerProfileMapper.class);
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        TenantContext.setTenantId(TENANT);
        applyV167();
    }

    @AfterAll
    static void stopRealPostgres() {
        TenantContext.clear();
        if (cluster != null) {
            cluster.stop();
        }
    }

    @BeforeEach
    void clean() throws Exception {
        jdbcTemplate.update("DELETE FROM customer_sku_prices WHERE tenant_id = ?", TENANT);
        jdbcTemplate.update("DELETE FROM customer_segment_members WHERE tenant_id = ?", TENANT);
        jdbcTemplate.update("DELETE FROM after_sales_tickets WHERE tenant_id = ?", TENANT);
        jdbcTemplate.update("DELETE FROM agent_sessions WHERE tenant_id = ?", TENANT);
        jdbcTemplate.update("DELETE FROM sessions WHERE tenant_id = ?", TENANT);
        jdbcTemplate.update("DELETE FROM customer_profiles WHERE tenant_id = ?", TENANT);
        applyV167();
    }

    // ────────────────────────────────────────── 判据 1：两条 ⇒ 一条（引用全迁 + 空列补空）

    @Test
    @DisplayName("🔴 判据 1：手机号一条 + openid 一条 ⇒ 自动并成 1 条，引用全挂到最早的 keeper")
    void twoRowsBecomeOneAndReferencesMove() throws Exception {
        // 更早那条 = 商户代录下单建的（只有手机号、昵称空）
        insertProfile("cp-a", PHONE, null, null, "2 days");
        // 更晚那条 = 小程序登录建的（只有 openid、有昵称）
        insertProfile("cp-b", null, OPENID, "微信昵称", "1 day");
        jdbcTemplate.update("INSERT INTO sessions (id, tenant_id, customer_id) VALUES ('ses-7711', ?, 'cp-b')", TENANT);
        jdbcTemplate.update("INSERT INTO agent_sessions (id, tenant_id, customer_id) VALUES "
                + "('ases-7711', ?, 'cp-b')", TENANT);
        jdbcTemplate.update("INSERT INTO after_sales_tickets (id, tenant_id, customer_id, ticket_type) "
                + "VALUES ('ast-7711', ?, 'cp-b', 'return')", TENANT);
        // 分群一：keeper 与 loser 都在（撞 (segment_id, customer_id) 唯一键 ⇒ 该删 loser 那行）
        jdbcTemplate.update("INSERT INTO customer_segment_members (id, tenant_id, segment_id, customer_id) "
                + "VALUES ('sm-a1', ?, ?, 'cp-a')", TENANT, SEGMENT_1);
        jdbcTemplate.update("INSERT INTO customer_segment_members (id, tenant_id, segment_id, customer_id) "
                + "VALUES ('sm-b1', ?, ?, 'cp-b')", TENANT, SEGMENT_1);
        // 分群二：只有 loser（改挂到 keeper）
        jdbcTemplate.update("INSERT INTO customer_segment_members (id, tenant_id, segment_id, customer_id) "
                + "VALUES ('sm-b2', ?, ?, 'cp-b')", TENANT, SEGMENT_2);
        // 客户价：sku 771101 只有 loser（改挂）；sku 771102 两边都有（撞部分唯一索引 ⇒ 删 loser 那行）
        jdbcTemplate.update("INSERT INTO customer_sku_prices (tenant_id, customer_id, sku_id, price) "
                + "VALUES (?, 'cp-b', 771101, 12.00)", TENANT);
        jdbcTemplate.update("INSERT INTO customer_sku_prices (tenant_id, customer_id, sku_id, price) "
                + "VALUES (?, 'cp-a', 771102, 20.00)", TENANT);
        jdbcTemplate.update("INSERT INTO customer_sku_prices (tenant_id, customer_id, sku_id, price) "
                + "VALUES (?, 'cp-b', 771102, 21.00)", TENANT);

        assertThat(profileCount()).as("判别力自证：修前形态就是两条（不是我在修一个不存在的问题）")
                .isEqualTo(2);

        CustomerProfile keeper = converge(PHONE, OPENID);

        assertThat(profileCount()).as("同一人必须只剩一条档案").isEqualTo(1);
        assertThat(keeper.getId()).as("keeper = 最早注册那条（与 findFirst* 读语义一致）").isEqualTo("cp-a");
        assertThat(keeper.getPhone()).isEqualTo(PHONE);
        assertThat(keeper.getWechatOpenid()).as("缺失的身份键被补上").isEqualTo(OPENID);
        assertThat(keeper.getWechatNickname()).as("keeper 空列从 loser 补空").isEqualTo("微信昵称");
        assertThat(count("SELECT COUNT(*) FROM sessions WHERE customer_id = 'cp-a'")).isEqualTo(1);
        assertThat(count("SELECT COUNT(*) FROM agent_sessions WHERE customer_id = 'cp-a'")).isEqualTo(1);
        assertThat(count("SELECT COUNT(*) FROM after_sales_tickets WHERE customer_id = 'cp-a'")).isEqualTo(1);
        assertThat(count("SELECT COUNT(*) FROM customer_segment_members WHERE customer_id = 'cp-a'"))
                .as("分群：撞键的那行删掉、独有的那行改挂 ⇒ 两个分群各一条").isEqualTo(2);
        assertThat(count("SELECT COUNT(*) FROM customer_segment_members WHERE customer_id = 'cp-b'")).isZero();
        assertThat(count("SELECT COUNT(*) FROM customer_sku_prices WHERE customer_id = 'cp-a'"))
                .as("客户价：撞键的 loser 行删掉、独有的改挂 ⇒ sku-1 与 sku-2 各一条").isEqualTo(2);
        assertThat(count("SELECT COUNT(*) FROM customer_sku_prices WHERE customer_id = 'cp-b'")).isZero();
        assertThat(count("SELECT COUNT(*) FROM customer_sku_prices WHERE customer_id = 'cp-a' "
                + "AND sku_id = 771102 AND price = 20.00"))
                .as("撞键时保留 keeper 自己的价（不拿 loser 的价覆盖）").isEqualTo(1);
    }

    // ────────────────────────────────────────── 判据 2：补空不覆盖

    @Test
    @DisplayName("🔴 判据 2：订单信息只补空列 —— 客服维护过的地址/承运商不被覆盖")
    void orderFillDoesNotOverwriteMaintainedValues() throws Exception {
        insertProfile("cp-fill", PHONE, null, "小张", "0 seconds");
        jdbcTemplate.update("UPDATE customer_profiles SET default_receiver_address = ?, "
                        + "default_logistics_company = ? WHERE id = ?",
                "客服维护的地址", "德邦", "cp-fill");

        fillOrderContactFrom(PHONE, "小张", "订单里的新地址", "express", "顺丰");

        CustomerProfile after = findProfile(PHONE);
        assertThat(after.getDefaultReceiverAddress()).as("已有地址不得被订单值覆盖").isEqualTo("客服维护的地址");
        assertThat(after.getDefaultLogisticsCompany()).as("已有承运商不得被订单值覆盖").isEqualTo("德邦");
        assertThat(after.getDefaultReceiverName()).as("空列被补").isEqualTo("小张");
        assertThat(after.getDefaultReceiverPhone()).as("空列被补").isEqualTo(PHONE);
        assertThat(after.getDefaultLogisticsType()).as("空列被补").isEqualTo("express");
    }

    // ────────────────────────────────────────── 判据 3：先登录后下单 ⇒ 一条

    @Test
    @DisplayName("🔴 判据 3：先小程序登录（只有 openid）再建单（有手机号）⇒ 仍然只 1 条、两键齐全")
    void loginThenOrderStaysSingleRow() {
        // 登录建档：手机号那时还没授权 ⇒ 只有 openid
        ensure(null, OPENID, "微信昵称", "wechat_mini", 0, true);
        assertThat(profileCount()).isEqualTo(1);

        // 建单：手机号 + 同一 openid ⇒ 认出是同一个人（补空键，不再建第二条）
        ensure(PHONE, OPENID, "李四", "order", 1, true);

        assertThat(profileCount()).as("同一人第二次出现不得新建档案").isEqualTo(1);
        CustomerProfile profile = findProfile(PHONE);
        assertThat(profile.getWechatOpenid()).isEqualTo(OPENID);
        assertThat(profile.getPhone()).isEqualTo(PHONE);
    }

    // ────────────────────────────────────────── 工具

    private CustomerProfile converge(String phone, String openid) {
        return ensure(phone, openid, null, null, 0, false);
    }

    private CustomerProfile ensure(String phone, String openid, String nickname, String channel,
                                   int totalOrders, boolean createIfMissing) {
        try (SqlSession session = factory.openSession(true)) {
            CustomerProfileIdentityService service =
                    new CustomerProfileIdentityService(session.getMapper(CustomerProfileMapper.class), jdbcTemplate);
            return service.ensure(TENANT, phone, openid,
                    new CustomerProfileIdentityService.ProfileSeed(nickname, channel, totalOrders), createIfMissing);
        }
    }

    /** 订单补空：先按手机号把档案读出来（服务按实体上的空缺决定写什么），再写。 */
    private void fillOrderContactFrom(String phone, String name, String address, String type, String company) {
        try (SqlSession session = factory.openSession(true)) {
            CustomerProfileMapper mapper = session.getMapper(CustomerProfileMapper.class);
            CustomerProfile profile = mapper.findFirstByPhone(TENANT, phone);
            assertThat(profile).as("夹具档案必须存在").isNotNull();
            new CustomerProfileIdentityService(mapper, jdbcTemplate)
                    .fillOrderContact(profile, TENANT, name, phone, address, type, company);
        }
    }

    private CustomerProfile findProfile(String phone) {
        try (SqlSession session = factory.openSession(true)) {
            return session.getMapper(CustomerProfileMapper.class).findFirstByPhone(TENANT, phone);
        }
    }

    private void insertProfile(String id, String phone, String openid, String nickname, String registeredAgo)
            throws Exception {
        jdbcTemplate.update("INSERT INTO customer_profiles "
                        + "(id, tenant_id, phone, wechat_openid, wechat_nickname, vip_level, customer_status, "
                        + " registered_at) VALUES (?, ?, ?, ?, ?, 'normal', 'active', NOW() - ?::interval)",
                id, TENANT, phone, openid, nickname, registeredAgo);
    }

    private int profileCount() {
        return count("SELECT COUNT(*) FROM customer_profiles WHERE tenant_id = " + TENANT);
    }

    private int count(String sql) {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).isTrue();
            return rs.getInt(1);
        } catch (Exception e) {
            throw new IllegalStateException("查询失败: " + sql, e);
        }
    }

    /** V167 的两条部分唯一索引（schema.sql 是冻结基线 ⇒ 判据自己造出「迁移之后」的形态）。 */
    private static void applyV167() throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("CREATE UNIQUE INDEX IF NOT EXISTS uk_customer_profiles_phone "
                    + "ON customer_profiles (tenant_id, phone)");
            st.execute("CREATE UNIQUE INDEX IF NOT EXISTS uk_customer_profiles_openid "
                    + "ON customer_profiles (tenant_id, wechat_openid)");
        }
    }

    private static String schemaSql() throws Exception {
        Path schema = Paths.get("src", "main", "resources", "db", "init", "schema.sql");
        assertThat(Files.exists(schema)).as("schema.sql 必须存在（路径漂移 ⇒ 判红）").isTrue();
        return Files.readString(schema, StandardCharsets.UTF_8);
    }
}
