// case_ids: CU-004
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.mapper.CustomerProfileMapper;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import javax.sql.DataSource;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.Statement;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🔴 真库：改客户手机号的**落库判据**（issue #9224 的 CU-004）。
 *
 * <h2>它钉的是什么（为什么 mock 判不了）</h2>
 * <p>评测 run 45979067843 报的是两条读数：{@code must_succeed(customer_manage) = 0}、
 * 以及 {@code WRITE_NOT_PERSISTED: 客户「13900001111」不在库里而种子号「13800138000」仍在}。
 * 前一条只说明「工具没成功」，后一条才把「写到底有没有落库」变成机器可判的事实 ——
 * 而**库里的样子只能真库看**：mapper 全 mock 时「只下发 data 里的键」这条语义
 * （服务层 {@code updateCustomer} 的非空拷贝白名单）与「新号覆盖、旧号不再存在」
 * 在 mock 上恒真，删掉整段拷贝逻辑它照样绿。</p>
 *
 * <p>本判据与 AI 侧的 {@code backend/ai-agent-service/tests/test_cu004_write_path_params_9224.py}
 * 合成完整链条：那边钉「模型参数里的 {@code data.phone} 一路走到 {@code PUT} 的 body」，
 * 这边钉「body 到了服务层之后，库里确实换成新号、旧号不在」。两侧都红 ⇒ 写路径彻底断；
 * 只有一侧红 ⇒ 归因唯一（丢参 vs 落库）。</p>
 */
@DisplayName("真库：改客户手机号落库（新号在库里、旧号不在）")
class CustomerPhoneUpdateRealDbTest {

    private static final Long TENANT_ID = 92240L;
    /** 独立栈种子客户（CU-004 的靶子） */
    private static final String CUSTOMER_ID = "cust_eval_zhangsan";
    /** 种子号：`pre_clean` 的复位目标 */
    private static final String OLD_PHONE = "13800138000";
    /** 顾客这次要求改成的新号（真值；掩码 `139****1111` 是日志脱敏，不是它） */
    private static final String NEW_PHONE = "13900001111";
    /** 第二位客户的独立号码（`uk_customer_profiles_phone` 唯一约束 ⇒ 不能与上面共用） */
    private static final String PARTIAL_OLD_PHONE = "13700137000";
    private static final String PARTIAL_NEW_PHONE = "13600136000";

    private static PgCluster cluster;
    private static SqlSession session;
    private static JdbcTemplate jdbc;
    private static CustomerService service;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        DataSource dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'cust-9224', 'cust-9224')");
            st.execute("INSERT INTO customer_profiles (id, tenant_id, wechat_nickname, phone)"
                    + " VALUES ('" + CUSTOMER_ID + "', " + TENANT_ID + ", '张三', '" + OLD_PHONE + "')");
            // 第二位客户：证明本判据看的是「**这位**客户的号换了」，不是「库里有这个号」
            // （`customer_profiles` 有 `uk_customer_profiles_phone(tenant_id, phone)` 唯一约束
            //  ⇒ 两个客户不能共用同一个号，故各用一号）
            st.execute("INSERT INTO customer_profiles (id, tenant_id, wechat_nickname, phone,"
                    + " vip_level, customer_status) VALUES ('cust_eval_partial', " + TENANT_ID
                    + ", '王五', '" + PARTIAL_OLD_PHONE + "', 'vip1', 'silent')");
        }

        jdbc = new JdbcTemplate(dataSource);

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(
                new Environment("cust-9224", new JdbcTransactionFactory(), dataSource));
        configuration.addMapper(CustomerProfileMapper.class);
        SqlSessionFactory factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        session = factory.openSession(true);
        // 服务层是**真实例**（不是 mock）：判据要跑的正是它的「非空拷贝」写入语义。
        // 其余依赖与本改动的写路径无关 ⇒ 传 null（同 CustomerDataScopeTest 的既有口径）。
        service = new CustomerService(session.getMapper(CustomerProfileMapper.class),
                null, null, null, null, null, null, null, null);
    }

    @AfterAll
    static void tearDown() {
        if (session != null) {
            session.close();
        }
        if (cluster != null) {
            cluster.stop();
        }
    }

    @Test
    @DisplayName("🔴 改手机号 ⇒ 库里是新号、种子号不再挂在这位客户上")
    void updateCustomerPersistsTheNewPhoneAndDropsTheOldOne() {
        CustomerProfile patch = new CustomerProfile();
        patch.setPhone(NEW_PHONE);

        service.updateCustomer(CUSTOMER_ID, patch);

        // ① 库里的真值（不看返回值：返回值走的是「暴露面」口径，可能与落库不是一回事）
        assertThat(phoneOf(CUSTOMER_ID)).isEqualTo(NEW_PHONE);
        // ② 旧号不再挂在这位客户上（「改号」而不是「多存一个号」）
        assertThat(jdbc.queryForList(
                "SELECT id FROM customer_profiles WHERE tenant_id = ? AND phone = ?",
                String.class, TENANT_ID, OLD_PHONE)).isEmpty();
    }

    @Test
    @DisplayName("只改给出的字段：其余列（姓名/等级/状态）保持原值")
    void updateCustomerKeepsUntouchedColumnsAsTheyWere() {
        CustomerProfile patch = new CustomerProfile();
        patch.setPhone(PARTIAL_NEW_PHONE);

        service.updateCustomer("cust_eval_partial", patch);

        List<java.util.Map<String, Object>> rows = jdbc.queryForList(
                "SELECT phone, wechat_nickname, vip_level, customer_status FROM customer_profiles"
                        + " WHERE id = ?", "cust_eval_partial");
        assertThat(rows).hasSize(1);
        assertThat(rows.get(0).get("phone")).isEqualTo(PARTIAL_NEW_PHONE);
        assertThat(rows.get(0).get("wechat_nickname")).isEqualTo("王五");
        assertThat(rows.get(0).get("vip_level")).isEqualTo("vip1");
        assertThat(rows.get(0).get("customer_status")).isEqualTo("silent");
    }

    private static String phoneOf(String customerId) {
        List<String> phones = jdbc.queryForList(
                "SELECT phone FROM customer_profiles WHERE id = ?", String.class, customerId);
        assertThat(phones).as("客户 %s 必须存在（否则下面的断言在测空气）", customerId).hasSize(1);
        return phones.get(0);
    }

    /** 终态建库脚本（不手抄列清单：库改了这里自动跟上）。 */
    private static String schemaSql() throws Exception {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        Path candidate = root.resolve("src/main/resources/db/init/schema.sql");
        if (!Files.exists(candidate)) {
            candidate = root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql");
        }
        assertThat(candidate).as("建库脚本必须存在（否则本判据在测空气）").exists();
        return Files.readString(candidate);
    }
}
