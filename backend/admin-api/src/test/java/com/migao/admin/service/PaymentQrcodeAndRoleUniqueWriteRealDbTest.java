// case_ids: MC-161
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Role;
import com.migao.admin.entity.TenantPaymentQrcode;
import com.migao.admin.mapper.RoleMapper;
import com.migao.admin.mapper.TenantPaymentQrcodeMapper;
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

import javax.sql.DataSource;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * issue #7255 真库判据：收款码 / 角色两处「读改写（selectOne 判空 → insert）」写面的
 * **唯一键兜底 + 幂等收敛**。
 *
 * <h2>病（真库才证得出来）</h2>
 * 两处写面都是「先查判空、再写」——这是个**非原子**的读（TOCTOU）：并发下两个请求都判「不存在」⇒ 都写。
 * 表上有唯一键 ⇒ 第二个撞键、异常冒泡成 <b>500</b>；没有唯一键 ⇒ **静默写出第二行**，而读侧
 * {@code selectOne} 直接 {@code TooManyResultsException}（同样是 500）。mock 面上没有约束，
 * {@code selectOne} 判空永远「成功」⇒ 这个病只能在真库里观测。
 *
 * <h2>五条判据（对应施工单 ①②③④⑤）</h2>
 * <ol>
 *   <li><b>① 唯一键真的存在</b>：建库脚本 + V206 之后，两表的唯一键都在 {@code pg_indexes} 里；
 *       且**迁移能修好漂移库**（先摘掉索引 ⇒ 跑 V206 ⇒ 索引回来）、**可重复执行**（再跑一次不报错）；</li>
 *   <li><b>② 并发两次写 ⇒ 只有一行</b>（两线程同起跑线；两次都不抛错）；</li>
 *   <li><b>③ 已存在时再写 ⇒ 幂等</b>（不报错、不产生第二行、upsert 返回既有那一行）；</li>
 *   <li><b>④ 负控</b>：不同 tenant / 不同 payment_type / 不同 code **各自都能插**（唯一键没做太宽）；</li>
 *   <li><b>⑤ 红证（判别力自证）</b>：摘掉唯一键 ⇒ 裸 insert 两次**真的**写进两行（②③ 会红）；
 *       唯一键在时裸 insert ⇒ **23505**（说明幂等收敛不是白写的）。</li>
 * </ol>
 *
 * <p>夹具说明：{@code schema.sql} 是**冻结基线**（issue #5243），它在测试库里已带两处唯一键；
 * 判据 ①/⑤ 会在**同一套夹具**上临时摘掉 / 还原它们（每步都在 {@code finally} 里还原），
 * 所以「摘掉就红」不是靠另造一张表证明的。</p>
 */
@DisplayName("7255 真库：收款码 / 角色的唯一键兜底 + 并发幂等（摘掉唯一键必红）")
class PaymentQrcodeAndRoleUniqueWriteRealDbTest {

    private static final Long TENANT = 7255L;
    private static final Long OTHER_TENANT = 9255L;
    private static final String TYPE = "wechat";
    private static final String OTHER_TYPE = "alipay";
    private static final String ROLE_CODE = "r-7255";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;

    @BeforeAll
    static void startRealPostgres() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT + ", 'uq-7255', 'uq-7255')");
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + OTHER_TENANT + ", 'uq-9255', 'uq-9255')");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("uq-7255", new JdbcTransactionFactory(), dataSource));
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
        // 生产装配（MybatisPlusConfig）对这两张表都**不**忽略租户过滤 ⇒ 夹具必须一致，
        // 否则拦截器改写 ON CONFLICT 语句的问题在测试里看不见（假绿）。
        configuration.addMapper(TenantPaymentQrcodeMapper.class);
        configuration.addMapper(RoleMapper.class);
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        TenantContext.setTenantId(TENANT);
    }

    @AfterAll
    static void stopRealPostgres() {
        TenantContext.clear();
        if (cluster != null) {
            cluster.stop();
        }
    }

    /**
     * 每条判据都从**修后的形状**起步：清行 + 跑一次 V206。
     *
     * <p>为什么需要这一步（实测踩到）：①/⑤ 会临时摘掉唯一键；JUnit 的方法执行顺序**不是**
     * 声明顺序 ⇒ 若那条判据先跑又没还原，后面的判据会看到「漂移库」并假红一片。
     * ⇒ 把「生产形状」在每条判据前重新钉住（V206 幂等，这也顺带反复验证了它可重复执行）。</p>
     */
    @BeforeEach
    void resetToTheFixedShape() throws Exception {
        execute("DELETE FROM tenant_payment_qrcodes WHERE tenant_id IN (" + TENANT + ", " + OTHER_TENANT + ")");
        execute("DELETE FROM roles WHERE tenant_id IN (" + TENANT + ", " + OTHER_TENANT + ")");
        applyV206();
    }

    // ────────────────────────────────────────── 判据 ①：唯一键真的存在（含迁移能修漂移库 + 可重复执行）

    @Test
    @DisplayName("🔴 判据 ①：两处唯一键都在 pg_indexes 里；V206 能修好漂移库且可重复执行")
    void uniqueKeysExistAndTheMigrationHealsADriftedDatabase() throws Exception {
        assertThat(qrcodeUniqueIndexDefs())
                .as("tenant_payment_qrcodes 必须有 (tenant_id, payment_type) WHERE deleted = 0 的唯一索引")
                .anySatisfy(def -> assertThat(def)
                        .contains("tenant_id, payment_type").contains("deleted = 0"));
        assertThat(roleUniqueIndexDefs())
                .as("roles 必须有 (tenant_id, code) 的唯一索引 —— 并发建角色的守门人")
                .anySatisfy(def -> assertThat(def).contains("tenant_id, code"));

        // 迁移必须能修好「漂移库」：把两处唯一键都摘掉（复刻 #7255 台账记的形态）⇒ 跑 V206 ⇒ 回来
        dropRoleUniqueKey();
        execute("DROP INDEX IF EXISTS uk_payment_qrcode_tenant_type");
        assertThat(qrcodeUniqueIndexDefs()).as("摘掉之后 qrcode 唯一索引确实不在了（否则本判据是空转）").noneSatisfy(
                def -> assertThat(def).contains("tenant_id, payment_type"));
        assertThat(roleUniqueIndexDefs()).as("摘掉之后 roles 唯一索引确实不在了").isEmpty();

        applyV206();

        assertThat(qrcodeUniqueIndexDefs())
                .as("V206 必须把 qrcode 唯一索引建回来（依赖归档链之外的独立保证）")
                .anySatisfy(def -> assertThat(def)
                        .contains("tenant_id, payment_type").contains("deleted = 0"));
        assertThat(roleUniqueIndexDefs())
                .as("V206 必须把 roles 唯一索引建回来 —— 这是「存量库到底有没有它」的唯一 durable 保证")
                .anySatisfy(def -> assertThat(def).contains("tenant_id, code"));

        // 可重复执行：连跑第二次不许报错（幂等；两支都是 RAISE NOTICE 跳过）
        applyV206();
        assertThat(roleUniqueIndexDefs()).as("重复执行不许建出第二条同名索引").hasSize(1);
    }

    // ────────────────────────────────────────── 判据 ②：并发两次写 ⇒ 只有一行

    @Test
    @DisplayName("🔴 判据 ②：并发两次 upsert 同一 (tenant, type) ⇒ 恰 1 行，两次都不抛错")
    void concurrentQrcodeUpsertsLeaveExactlyOneRow() throws Exception {
        List<Throwable> failures = runConcurrently(
                () -> { upsertQrcode(TENANT, TYPE, "https://img/1.png"); return null; },
                () -> { upsertQrcode(TENANT, TYPE, "https://img/2.png"); return null; });

        assertThat(failures).as("并发保存同一收款类型不许抛错（撞唯一键要幂等收敛，不是 500）").isEmpty();
        assertThat(qrcodeRowCount(TENANT, TYPE)).as("(tenant, type) 必须恰好 1 行").isEqualTo(1);
    }

    @Test
    @DisplayName("🔴 判据 ②（角色）：并发两次建同 code ⇒ 恰 1 行，两次都不抛错")
    void concurrentRoleCreatesLeaveExactlyOneRow() throws Exception {
        List<Throwable> failures = runConcurrently(
                () -> insertRole(TENANT, ROLE_CODE, "角色A"),
                () -> insertRole(TENANT, ROLE_CODE, "角色B"));

        assertThat(failures).as("并发建同一 code 的角色不许抛错").isEmpty();
        assertThat(roleRowCount(TENANT, ROLE_CODE)).as("(tenant, code) 必须恰好 1 行").isEqualTo(1);
        assertThat(lastConcurrentReturns).as("两次条件插入里必须有一次是 0 行（幂等收敛）")
                .containsExactlyInAnyOrder(1, 0);
    }

    // ────────────────────────────────────────── 判据 ③：已存在时再写 ⇒ 幂等

    @Test
    @DisplayName("🔴 判据 ③：已存在时再 upsert ⇒ 不报错、不产生第二行、返回既有行且字段被更新")
    void upsertIsIdempotentAndReturnsTheExistingRow() throws Exception {
        upsertQrcode(TENANT, TYPE, "https://img/first.png");
        String firstId = onlyQrcodeId(TENANT, TYPE);

        upsertQrcode(TENANT, TYPE, "https://img/second.png");   // 不报错

        assertThat(qrcodeRowCount(TENANT, TYPE)).as("第二次写入不许产生第二行").isEqualTo(1);
        assertThat(onlyQrcodeId(TENANT, TYPE)).as("行身份不变（是更新，不是换了一行）").isEqualTo(firstId);
        assertThat(onlyQrcodeImageUrl(TENANT, TYPE))
                .as("返回/落库的都是既有那一行，且 image_url 已更新")
                .isEqualTo("https://img/second.png");
    }

    @Test
    @DisplayName("🔴 判据 ③（角色）：已存在时再建 ⇒ 0 行、不报错、不产生第二行")
    void roleInsertIfAbsentIsIdempotent() throws Exception {
        assertThat(insertRole(TENANT, ROLE_CODE, "角色A")).as("首次建行 = 1").isEqualTo(1);
        assertThat(insertRole(TENANT, ROLE_CODE, "角色B")).as("已存在 ⇒ 0 行（幂等，不抛）").isZero();
        assertThat(roleRowCount(TENANT, ROLE_CODE)).isEqualTo(1);
        assertThat(onlyRoleName(TENANT, ROLE_CODE)).as("不会把既有行的 name 改成第二次请求的值").isEqualTo("角色A");
    }

    // ────────────────────────────────────────── 判据 ④：负控（唯一键没做太宽）

    @Test
    @DisplayName("🔴 判据 ④（负控）：不同 tenant / 不同 payment_type / 不同 code 各自都能插")
    void theUniqueKeysDoNotBlockLegitimateRows() throws Exception {
        upsertQrcode(TENANT, TYPE, "https://img/a.png");
        upsertQrcode(TENANT, OTHER_TYPE, "https://img/b.png");     // 同租户、不同类型
        upsertQrcode(OTHER_TENANT, TYPE, "https://img/c.png");     // 不同类型、不同租户

        assertThat(qrcodeRowCount(TENANT, TYPE)).isEqualTo(1);
        assertThat(qrcodeRowCount(TENANT, OTHER_TYPE)).isEqualTo(1);
        assertThat(qrcodeRowCount(OTHER_TENANT, TYPE)).isEqualTo(1);

        assertThat(insertRole(TENANT, ROLE_CODE, "角色A")).isEqualTo(1);
        assertThat(insertRole(TENANT, ROLE_CODE + "-b", "角色B")).as("同租户不同 code ⇒ 可插").isEqualTo(1);
        assertThat(insertRole(OTHER_TENANT, ROLE_CODE, "角色C")).as("不同租户同 code ⇒ 可插").isEqualTo(1);
        assertThat(roleRowCount(TENANT, ROLE_CODE)).isEqualTo(1);
        assertThat(roleRowCount(OTHER_TENANT, ROLE_CODE)).isEqualTo(1);
    }

    // ────────────────────────────────────────── 判据 ⑤：红证（摘掉唯一键 / 退回裸 insert 都必须红）

    @Test
    @DisplayName("🔴 判据 ⑤-a：摘掉唯一键 ⇒ 裸 insert 两次真的写进两行（②「只有一行」必红）")
    void withoutTheUniqueKeyTheNaiveWriteSilentlyDuplicates() throws Exception {
        dropRoleUniqueKey();
        execute("DROP INDEX IF EXISTS uk_payment_qrcode_tenant_type");

        naiveInsertQrcode(TENANT, TYPE, "https://img/naive-1.png");
        naiveInsertQrcode(TENANT, TYPE, "https://img/naive-2.png");   // 无唯一键 ⇒ 静默第二行

        assertThat(qrcodeRowCount(TENANT, TYPE))
                .as("没有唯一键时「先查后插」的并发结果就是静默两行 —— 这正是 ② 要挡的形态")
                .isEqualTo(2);

        naiveInsertRole(TENANT, ROLE_CODE);
        naiveInsertRole(TENANT, ROLE_CODE);
        assertThat(roleRowCount(TENANT, ROLE_CODE)).as("roles 同理").isEqualTo(2);

        // 存量已重复时 V206 **不阻断部署**（RAISE WARNING + 跳过建索引）—— 这就是 PR body 写的处置口径，
        // 在这里**行为级**验证一次（「部署会不会被存量脏数据卡死」是运维最关心的一件事）。
        applyV206();
        assertThat(qrcodeUniqueIndexDefs()).as("有活跃重复行 ⇒ 迁移必须跳过建索引（不阻断部署）").isEmpty();
        assertThat(roleUniqueIndexDefs()).as("roles 有重复 code ⇒ 迁移同样跳过").isEmpty();

        // 运维清理（每组保留一行）后**重跑**迁移 ⇒ 索引建起来（幂等 + 「清完再跑一次」这条出口真可行动）
        execute("DELETE FROM tenant_payment_qrcodes WHERE tenant_id = " + TENANT
                + " AND payment_type = '" + TYPE + "' AND id NOT IN (SELECT id FROM tenant_payment_qrcodes"
                + " WHERE tenant_id = " + TENANT + " AND payment_type = '" + TYPE + "' ORDER BY id LIMIT 1)");
        execute("DELETE FROM roles WHERE tenant_id = " + TENANT + " AND code = '" + ROLE_CODE
                + "' AND id NOT IN (SELECT id FROM roles"
                + " WHERE tenant_id = " + TENANT + " AND code = '" + ROLE_CODE + "' ORDER BY id LIMIT 1)");
        applyV206();
        assertThat(qrcodeUniqueIndexDefs()).as("清理后重跑必须把 qrcode 唯一索引建起来").isNotEmpty();
        assertThat(roleUniqueIndexDefs()).as("清理后重跑必须把 roles 唯一索引建起来").isNotEmpty();
    }

    @Test
    @DisplayName("🔴 判据 ⑤-b：唯一键在时裸 insert ⇒ 23505（幂等收敛不是白写的）")
    void theNaiveWriteHitsTheUniqueKeyWhenItExists() throws Exception {
        // 先确认唯一键在（本判据的前提，不许静默跳过）
        assertThat(qrcodeUniqueIndexDefs()).isNotEmpty();
        assertThat(roleUniqueIndexDefs()).isNotEmpty();

        naiveInsertQrcode(TENANT, TYPE, "https://img/naive.png");
        SQLException qrcodeConflict = expectUniqueViolation(
                () -> naiveInsertQrcode(TENANT, TYPE, "https://img/naive-2.png"));
        assertThat(qrcodeConflict.getSQLState())
                .as("第二条同 (tenant, type) 的裸 insert 必须撞唯一键（23505）"
                        + " —— 退回裸 insert 就是把 500 还回来")
                .isEqualTo("23505");

        naiveInsertRole(TENANT, ROLE_CODE);
        SQLException roleConflict = expectUniqueViolation(() -> naiveInsertRole(TENANT, ROLE_CODE));
        assertThat(roleConflict.getSQLState()).as("roles 同理").isEqualTo("23505");
    }

    // ══════════════════════════════════════════ 工具

    private static void applyV206() throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(v206Sql());
        }
    }

    /** V206 的正文（**读真文件**，不复制第二份 SQL：迁移改了而这里不知道 ⇒ 判据会静默乐观）。 */
    private static String v206Sql() throws Exception {
        Path dir = Paths.get("src", "main", "resources", "db", "migration");
        assertThat(Files.isDirectory(dir)).as("迁移目录必须存在（路径漂移 ⇒ 判红，不是空跑通过）").isTrue();
        List<Path> found;
        try (Stream<Path> files = Files.list(dir)) {
            found = files.filter(p -> p.getFileName().toString().startsWith("V206__")).collect(Collectors.toList());
        }
        assertThat(found).as("V206 迁移文件必须恰好一个（issue #7255 的承载体）").hasSize(1);
        return Files.readString(found.get(0), StandardCharsets.UTF_8);
    }

    private static String schemaSql() throws Exception {
        Path schema = Paths.get("src", "main", "resources", "db", "init", "schema.sql");
        assertThat(Files.exists(schema)).as("schema.sql 必须存在（路径漂移 ⇒ 判红，不是空跑通过）").isTrue();
        return Files.readString(schema, StandardCharsets.UTF_8);
    }

    private void upsertQrcode(Long tenantId, String type, String imageUrl) {
        TenantContext.setTenantId(tenantId);
        try (SqlSession s = factory.openSession(true)) {
            s.getMapper(TenantPaymentQrcodeMapper.class).upsertActive(TenantPaymentQrcode.builder()
                    .id(UUID.randomUUID().toString().replace("-", ""))
                    .tenantId(tenantId)
                    .paymentType(type)
                    .imageUrl(imageUrl)
                    .status("active")
                    .deleted(0)
                    .build());
        }
    }

    private int insertRole(Long tenantId, String code, String name) {
        TenantContext.setTenantId(tenantId);
        try (SqlSession s = factory.openSession(true)) {
            return s.getMapper(RoleMapper.class).insertIfAbsent(Role.builder()
                    .id(UUID.randomUUID().toString().replace("-", ""))
                    .tenantId(tenantId)
                    .name(name)
                    .code(code)
                    .status("active")
                    .build());
        }
    }

    /** 修法前的写法（裸 insert，不经 ON CONFLICT）—— 红证专用。 */
    private void naiveInsertQrcode(Long tenantId, String type, String imageUrl) throws Exception {
        execute("INSERT INTO tenant_payment_qrcodes (id, tenant_id, payment_type, image_url, status, deleted) "
                + "VALUES ('" + UUID.randomUUID().toString().replace("-", "") + "', " + tenantId + ", '"
                + type + "', '" + imageUrl + "', 'active', 0)");
    }

    private void naiveInsertRole(Long tenantId, String code) throws Exception {
        execute("INSERT INTO roles (id, tenant_id, name, code, status, deleted) VALUES ('"
                + UUID.randomUUID().toString().replace("-", "") + "', " + tenantId + ", 'naive', '"
                + code + "', 'active', 0)");
    }

    /** 收款码**业务键**（tenant_id, payment_type）上的唯一索引定义（PK 不在面内）。 */
    private List<String> qrcodeUniqueIndexDefs() throws Exception {
        return uniqueIndexDefs("tenant_payment_qrcodes", "tenant_id, payment_type");
    }

    /** 角色**业务键**（tenant_id, code）上的唯一索引定义（PK 不在面内）。 */
    private List<String> roleUniqueIndexDefs() throws Exception {
        return uniqueIndexDefs("roles", "tenant_id, code");
    }

    /**
     * 该表的唯一索引定义（`pg_indexes.indexdef` 原文；**现取**，不猜索引名）。
     *
     * @param columns 只取**列集合逐字命中**业务键的那些（`(id)` 的主键索引不算 —— 它也在
     *                {@code pg_indexes} 里，按「表的唯一索引」判会把它算进来 ⇒ 判据假绿）
     */
    private List<String> uniqueIndexDefs(String table, String columns) throws Exception {
        List<String> out = new ArrayList<>();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(
                     "SELECT indexdef FROM pg_indexes WHERE tablename = '" + table + "'")) {
            while (rs.next()) {
                String def = rs.getString(1);
                if (def != null && def.toUpperCase().contains("UNIQUE") && def.contains(columns)) {
                    out.add(def);
                }
            }
        }
        return out;
    }

    /**
     * 摘掉 roles 上覆盖 (tenant_id, code) 的唯一键（复刻 #7255 台账记的「无 uk」形态）。
     *
     * <p>表内 {@code UNIQUE(...)} 在 PG 里是**约束**，索引是它的从属对象 ⇒ 必须先
     * {@code DROP CONSTRAINT}（直接 {@code DROP INDEX} 会报依赖）。名字从 {@code pg_indexes.indexdef}
     * **现取**，不猜（PG 自动生成的名字与索引名相同，但不是我们起的，故不许写死）。</p>
     */
    private void dropRoleUniqueKey() throws Exception {
        for (String def : roleUniqueIndexDefs()) {
            String name = def.replaceAll("(?s).*INDEX\\s+(\\S+)\\s+ON.*", "$1").trim();
            // 两种载体都要试：表内 UNIQUE 是**约束**（要先 DROP CONSTRAINT），而 V206 建的是**普通唯一索引**。
            // 逐句容忍「这一种载体不存在」是必要的 —— 但**不容忍最后还剩**（下面那条断言兜底）。
            try {
                execute("ALTER TABLE roles DROP CONSTRAINT IF EXISTS " + name);
            } catch (SQLException notAConstraint) {
                // 普通索引形态下的 DROP CONSTRAINT 报错（或反之）⇒ 交给下一句
            }
            execute("DROP INDEX IF EXISTS " + name);
        }
        assertThat(roleUniqueIndexDefs()).as("roles 业务键上的唯一键必须已被摘掉（否则本判据是空转）").isEmpty();
    }

    private SQLException expectUniqueViolation(ThrowingRunnable action) throws Exception {
        try {
            action.run();
        } catch (SQLException e) {
            return e;
        }
        throw new AssertionError("期望撞唯一键（23505），但语句成功了 ⇒ 红证失效（本判据是空断言）");
    }

    private int qrcodeRowCount(Long tenantId, String type) throws Exception {
        return count("SELECT COUNT(*) FROM tenant_payment_qrcodes WHERE tenant_id = " + tenantId
                + " AND payment_type = '" + type + "' AND deleted = 0");
    }

    private int roleRowCount(Long tenantId, String code) throws Exception {
        return count("SELECT COUNT(*) FROM roles WHERE tenant_id = " + tenantId
                + " AND code = '" + code + "'");
    }

    private String onlyQrcodeId(Long tenantId, String type) throws Exception {
        return single("SELECT id FROM tenant_payment_qrcodes WHERE tenant_id = " + tenantId
                + " AND payment_type = '" + type + "' AND deleted = 0");
    }

    private String onlyQrcodeImageUrl(Long tenantId, String type) throws Exception {
        return single("SELECT image_url FROM tenant_payment_qrcodes WHERE tenant_id = " + tenantId
                + " AND payment_type = '" + type + "' AND deleted = 0");
    }

    private String onlyRoleName(Long tenantId, String code) throws Exception {
        return single("SELECT name FROM roles WHERE tenant_id = " + tenantId + " AND code = '" + code + "'");
    }

    /** 最近一次 {@link #runConcurrently} 里两个任务各自的返回值（并发判据用它证明「有一次真的收敛成 0 行」）。 */
    private final List<Integer> lastConcurrentReturns = new ArrayList<>();

    private void execute(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(sql);
        }
    }

    private String single(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).as("期望恰好一行：" + sql).isTrue();
            return rs.getString(1);
        }
    }

    private int count(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).isTrue();
            return rs.getInt(1);
        }
    }

    private List<Throwable> runConcurrently(Callable<Integer> a, Callable<Integer> b) throws Exception {
        CountDownLatch start = new CountDownLatch(1);
        ExecutorService pool = Executors.newFixedThreadPool(2);
        List<Throwable> errors = new ArrayList<>();
        List<Integer> returns = new ArrayList<>();
        try {
            List<Future<Integer>> futures = new ArrayList<>();
            for (Callable<Integer> task : List.of(a, b)) {
                futures.add(pool.submit(() -> {
                    TenantContext.setTenantId(TENANT);
                    start.await(10, TimeUnit.SECONDS);
                    return task.call();
                }));
            }
            start.countDown();
            for (Future<Integer> f : futures) {
                try {
                    returns.add(f.get(60, TimeUnit.SECONDS));
                } catch (java.util.concurrent.ExecutionException e) {
                    errors.add(e.getCause() == null ? e : e.getCause());
                }
            }
        } finally {
            pool.shutdownNow();
            start.countDown();
        }
        lastConcurrentReturns.clear();
        lastConcurrentReturns.addAll(returns);
        return errors;
    }

    @FunctionalInterface
    private interface ThrowingRunnable {
        void run() throws Exception;
    }
}
