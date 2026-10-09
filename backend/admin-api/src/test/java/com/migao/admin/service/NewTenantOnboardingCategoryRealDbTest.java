// case_ids: OB-006
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ProductCreateRequest;
import com.migao.admin.dto.ProductResponse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CategoryMapper;
import com.migao.admin.mapper.PermissionMapper;
import com.migao.admin.mapper.ProductAttributeMapper;
import com.migao.admin.mapper.ProductColorMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.RoleMapper;
import com.migao.admin.mapper.RolePermissionMapper;
import com.migao.admin.mapper.StockLedgerMapper;
import com.migao.admin.mapper.TenantApplicationMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.mapper.UserRoleMapper;
import com.migao.admin.security.PermissionInterceptor;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.LocalCacheScope;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.test.util.ReflectionTestUtils;

import javax.sql.DataSource;
import java.io.IOException;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.spy;
import static org.mockito.Mockito.when;

/**
 * 🔴 <b>真库判据：新租户入驻即种默认商品分类 ⇒ 开箱首建商品不再 422（issue #6295）</b>。
 *
 * <h2>病灶（机制链）</h2>
 * 入驻链路（{@link RegistrationService#approveApplication}）此前<b>不碰</b> {@code categories}
 * ⇒ 新租户分类表为空；而 {@code POST /api/admin/products}（非草稿）要求 {@code categoryId} 非空
 * （{@code ProductService.validateRequiredForStatus}）⇒ <b>开箱第一次建商品必撞 422「分类ID不能为空」</b>。
 *
 * <h2>为什么必须真库（mock 面结构上不可见）</h2>
 * <ol>
 *   <li>判据要证的是「<b>真的有一行进了 {@code categories}</b>」以及「那一行的 id 真的能当外键被
 *       {@code products.category_id} 接受（{@code REFERENCES categories(id)}）」——
 *       mock 面只能证明「调了 insert」，看不见落库与外键；</li>
 *   <li>幂等判据（连续两次不种出重复分类）读的是<b>行数</b>；</li>
 *   <li>「种在了本租户名下」（{@code tenant_id}）+「跨租户不可见」是 SQL 谓词 + 租户拦截器的行为。</li>
 * </ol>
 *
 * <h2>判据（4 条，双向）</h2>
 * <ol>
 *   <li><b>判据 1（主判据·绿）</b>：空库上真跑入驻链路 ⇒ 该租户 {@code categories} 恰 <b>1</b> 行、
 *       名字 = 单一来源常量 {@link OnboardingInitialData#DEFAULT_PRODUCT_CATEGORY_NAME}、
 *       {@code tenant_id} = 新租户；随后用该分类 id 走<b>真</b> {@code ProductService.createProduct}
 *       （{@code status=on_sale}）⇒ <b>首建商品成功</b>、{@code products} 落 1 行且
 *       {@code category_id} = 该分类 id；</li>
 *   <li><b>判据 2（判据 1 的判别力·注入红证 A）</b>：把种子那步<b>摘掉</b>（{@code seedDefaultCategory}
 *       被 spy 成 no-op）+ 同时把后置条件探针摘掉 ⇒ 入驻"成功"但分类表 <b>0</b> 行 ⇒
 *       此时界面唯一能提交的 {@code categoryId} 是空 ⇒ 首建商品<b>逐字</b>报
 *       422「分类ID不能为空」。<b>这条读数证明判据 1 的绿来自「种了分类」，不是「本来就没问题」</b>；</li>
 *   <li><b>判据 3（后置条件元守卫的判别力·注入红证 B）</b>：只把种子摘掉、保留后置条件校验 ⇒
 *       入驻<b>当场失败</b>（{@code ONBOARDING_REQUIRED_DATA_MISSING}）—— 「漏种」从静默变成开租当场红；</li>
 *   <li><b>判据 4（幂等·真库）</b>：入驻已种下 1 行后，再对同一租户调播种 ⇒ 返回 0、行数仍为 1
 *       （重复入驻 / 重试不种出重复分类）。</li>
 * </ol>
 *
 * <p>缺 PG 二进制 ⇒ {@link PgCluster#startOrAbort()}：CI（{@code MIGAO_REQUIRE_REALDB=1}）判红；
 * 本机未设该标记 ⇒ 显式 skip（「没跑」长得像「没跑」，不是通过）。</p>
 */
@DisplayName("#6295 新租户入驻即种默认商品分类 ⇒ 首建商品不再 422（真库）")
class NewTenantOnboardingCategoryRealDbTest {

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static SqlSession session;
    private static ProductCategorySeedService realSeedService;
    private static ProductService productService;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            // bootstrap 脚本用 `OVERRIDING SYSTEM VALUE` 显式种了租户 1 ⇒ identity 序列还停在 1
            // ⇒ 走 mapper 建新租户会撞 tenants_pkey。把序列推到 MAX(id)+1（仅夹具前置，不改生产语义）。
            st.execute("SELECT setval(pg_get_serial_sequence('tenants', 'id'),"
                    + " (SELECT COALESCE(MAX(id), 1) FROM tenants))");
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        // 读数要「写完再查」拿到新值（一级缓存必须 STATEMENT 级）
        configuration.setLocalCacheScope(LocalCacheScope.STATEMENT);
        configuration.setEnvironment(new Environment("acc-6295", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器**必须在场**：生产 SQL 会经它重写（追加 tenant_id）⇒ 少了它就只测了 mapper 原文
        MybatisPlusInterceptor tenantLine = new MybatisPlusInterceptor();
        tenantLine.addInnerInterceptor(new TenantLineInnerInterceptor(new TenantLineHandler() {
            @Override
            public Expression getTenantId() {
                Long tid = TenantContext.getTenantId();
                // 无租户上下文（= 开租链路在建租户前插角色/权限那一段）取 0：没有任何租户是 0
                // ⇒ 该类读一律空集（fail-closed），而 INSERT 侧因实体显式带 tenant_id 走 ignoreInsert、不取本值。
                return new LongValue(tid == null ? 0L : tid);
            }

            @Override
            public String getTenantIdColumn() {
                return "tenant_id";
            }

            @Override
            public boolean ignoreTable(String tableName) {
                // 与生产 MybatisPlusConfig.IGNORE_TENANT_TABLES 同口径（租户/申请单不按租户过滤）
                return List.of("tenants", "tenant_applications", "platform_admins",
                        "notification_templates", "notification_rules").contains(tableName.toLowerCase());
            }
        }));
        configuration.addInterceptor(tenantLine);
        for (Class<?> mapper : List.of(TenantApplicationMapper.class, TenantMapper.class, UserMapper.class,
                UserRoleMapper.class, RoleMapper.class, PermissionMapper.class, RolePermissionMapper.class,
                CategoryMapper.class, ProductMapper.class, ProductColorMapper.class, ProductSkuMapper.class,
                ProductAttributeMapper.class, StockLedgerMapper.class)) {
            configuration.addMapper(mapper);
        }
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        session = factory.openSession(true);

        productService = new ProductService(
                session.getMapper(ProductMapper.class),
                session.getMapper(CategoryMapper.class),
                session.getMapper(ProductColorMapper.class),
                session.getMapper(ProductSkuMapper.class),
                session.getMapper(ProductAttributeMapper.class),
                new StockLedgerService(session.getMapper(StockLedgerMapper.class),
                        session.getMapper(ProductSkuMapper.class)),
                // 幂等键（issue #6209）：本类走无键路径（createProduct(req, tenantId) ⇒ claim 不到），
                // 幂等行为由 ProductCreateIdempotencyTest / ProductCreateIdempotencyRealDbTest 承担
                null);
        // ServiceImpl 的 baseMapper（createProduct 末尾按 id 回读会用到）
        ReflectionTestUtils.setField(productService, "baseMapper", session.getMapper(ProductMapper.class));
        realSeedService = new ProductCategorySeedService(session.getMapper(CategoryMapper.class));
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

    // ══════════════════════════════ 判据 1：入驻即种分类 ⇒ 首建商品成功

    @Test
    @DisplayName("判据1·空库真跑入驻链路 ⇒ 分类恰 1 行（具名）⇒ 用它首建商品成功（改前：分类 0 行 ⇒ 422）")
    void onboardingSeedsDefaultCategoryAndFirstProductSucceeds() throws Exception {
        long appId = insertPendingApplication("杭州观星台布艺有限公司", "13800001501");
        long tenantId = approveAndGetTenantId(registrationServiceWith(realSeedService), appId,
                "杭州观星台布艺有限公司");

        TenantContext.setTenantId(tenantId);
        try {
            List<String> rows = categoryRowsOf(tenantId);
            System.out.println("[#6295 判据1] 入驻后 tenantId=" + tenantId + " 的分类行 = " + rows);
            assertThat(rows)
                    .as("新租户入驻后必须有**恰一行**默认分类（改前 = 0 行 ⇒ 开箱首建商品 422）")
                    .hasSize(1);
            assertThat(categoryNamesOf(tenantId))
                    .as("默认分类必须具名，且名字来自单一来源 OnboardingInitialData.DEFAULT_PRODUCT_CATEGORY_NAME")
                    .containsExactly(OnboardingInitialData.DEFAULT_PRODUCT_CATEGORY_NAME);

            String categoryId = categoryIdsOf(tenantId).get(0);

            // When：开箱首建商品 —— 用户唯一能做的动作（分类由种子给出，不是手建的）
            ProductCreateRequest request = firstProductRequest("首个商品-6295", "SG-6295-1", categoryId);
            ProductResponse created = productService.createProduct(request, tenantId);

            // Then：不再 422，且真的落库（外键指向种子种下的那个分类）
            System.out.println("[#6295 判据1] 首建商品成功 id=" + created.getId()
                    + ", categoryId=" + categoryId
                    + ", products 行 = " + productRowsOf(tenantId));
            assertThat(created.getId()).as("首建商品必须成功返回商品 id").isNotBlank();
            assertThat(productRowsOf(tenantId))
                    .as("products 必须真落一行，且 category_id = 种子里那个分类（外键 REFERENCES categories(id)）")
                    .containsExactly("name=首个商品-6295|categoryId=" + categoryId);
        } finally {
            TenantContext.clear();
        }
    }

    // ══════════════════════════════ 判据 2：注入红证 A（摘掉种子 + 摘掉后置条件 ⇒ 复现 422）

    @Test
    @DisplayName("判据2·注入红证A：摘掉种子那步（+摘掉后置条件探针）⇒ 分类 0 行 ⇒ 首建商品逐字 422「分类ID不能为空」")
    void neuteredSeedWithoutPostconditionGuardReproduces422() throws Exception {
        ProductCategorySeedService neutered = spy(realSeedService);
        // 注入 ①：把种子那步摘掉（no-op）
        doReturn(0).when(neutered).seedDefaultCategory(anyLong());
        // 注入 ②：连后置条件探针一起摘掉，让入驻"成功"——模拟**只有种子被摘掉**的旧形态
        doReturn(1L).when(neutered).countCategories(anyLong());

        long appId = insertPendingApplication("杭州无分类布艺有限公司", "13800001502");
        long tenantId = approveAndGetTenantId(registrationServiceWith(neutered), appId,
                "杭州无分类布艺有限公司");

        TenantContext.setTenantId(tenantId);
        try {
            List<String> rows = categoryRowsOf(tenantId);
            System.out.println("[#6295 判据2·注入红证A] 摘掉种子后 tenantId=" + tenantId + " 的分类行 = " + rows);
            assertThat(rows).as("注入生效自证：摘掉种子 ⇒ 该租户分类必须为 0 行").isEmpty();
            assertThat(categoryIdsOf(tenantId)).as("没有分类 ⇒ 界面拿不到任何 categoryId").isEmpty();

            // When：分类树是空的 ⇒ 界面唯一能提交的 categoryId 是空（'' / null）
            ProductCreateRequest request = firstProductRequest("无分类租户的首个商品", "SG-6295-2", null);

            // Then：逐字复现 issue #6295 的失败读数（这就是「判据1 的绿有判别力」的证据）
            BusinessException reproduced = null;
            try {
                productService.createProduct(request, tenantId);
            } catch (BusinessException e) {
                reproduced = e;
            }
            assertThat(reproduced).as("没有种子 ⇒ 开箱首建商品必须被拒（不许静默建成无分类商品）").isNotNull();
            System.out.println("[#6295 判据2·注入红证A] 首建商品读数 = HTTP " + reproduced.getHttpStatus()
                    + " " + reproduced.getCode() + " / " + reproduced.getMessage());
            assertThat(reproduced.getMessage()).isEqualTo("分类ID不能为空");
            assertThat(reproduced.getCode()).isEqualTo("VALIDATION_ERROR");
            assertThat(reproduced.getHttpStatus()).isEqualTo(422);
            assertThat(productRowsOf(tenantId)).as("被拒时不得落账（防「先写商品再报错」）").isEmpty();
        } finally {
            TenantContext.clear();
        }
    }

    // ══════════════════════════════ 判据 3：注入红证 B（只摘种子，保留后置条件 ⇒ 开租当场失败）

    @Test
    @DisplayName("判据3·注入红证B：只摘掉种子（保留后置条件）⇒ 入驻当场 fail-closed（ONBOARDING_REQUIRED_DATA_MISSING）")
    void neuteredSeedWithPostconditionGuardFailsOnboarding() throws Exception {
        ProductCategorySeedService neutered = spy(realSeedService);
        doReturn(0).when(neutered).seedDefaultCategory(anyLong());
        // countCategories 保持真实（现取探针）⇒ 后置条件必须发现「清单里 enforced 的项缺了」

        long appId = insertPendingApplication("杭州后置条件布艺有限公司", "13800001503");

        assertThatThrownBy(() -> registrationServiceWith(neutered).approveApplication(appId, null, null))
                .as("入驻后置条件的元守卫：漏种必需初始数据 ⇒ 开租必须当场失败（不是静默产出不可用租户）")
                .isInstanceOf(BusinessException.class)
                .extracting(e -> ((BusinessException) e).getCode())
                .isEqualTo("ONBOARDING_REQUIRED_DATA_MISSING");
    }

    // ══════════════════════════════ 判据 4：幂等（真库行数）

    @Test
    @DisplayName("判据4·入驻后再调播种 ⇒ 返回 0、分类行数仍为 1（重复入驻/重试不种出重复分类）")
    void seedingIsIdempotentOnRealDatabase() throws Exception {
        long appId = insertPendingApplication("杭州幂等布艺有限公司", "13800001504");
        long tenantId = approveAndGetTenantId(registrationServiceWith(realSeedService), appId,
                "杭州幂等布艺有限公司");
        assertThat(categoryRowsOf(tenantId)).as("夹具前提：入驻已种下 1 行").hasSize(1);

        TenantContext.setTenantId(tenantId);
        try {
            int again = realSeedService.seedDefaultCategory(tenantId);
            String againName = realSeedService.seedDefaultCategory(tenantId) == 0
                    ? OnboardingInitialData.DEFAULT_PRODUCT_CATEGORY_NAME : "unexpected";
            System.out.println("[#6295 判据4] 再调播种 two-more-times ⇒ 返回 " + again + "/0，分类行 = "
                    + categoryRowsOf(tenantId));
            assertThat(again).as("再调播种：该租户已有分类 ⇒ 幂等跳过（返回 0）").isZero();
            assertThat(againName).isEqualTo(OnboardingInitialData.DEFAULT_PRODUCT_CATEGORY_NAME);
            assertThat(categoryRowsOf(tenantId)).as("行数必须仍是 1（没有种出重复分类）").hasSize(1);
        } finally {
            TenantContext.clear();
        }
    }

    // ══════════════════════════════ 夹具

    /** 入驻链路（真 mappers + 真 UserService/RoleService；只把与本判据无关的协作者置为 mock）。 */
    private static RegistrationService registrationServiceWith(ProductCategorySeedService seeder) {
        UserMapper userMapper = session.getMapper(UserMapper.class);
        RoleMapper roleMapper = session.getMapper(RoleMapper.class);
        UserRoleMapper userRoleMapper = session.getMapper(UserRoleMapper.class);
        RoleService roleService = new RoleService(roleMapper, session.getMapper(PermissionMapper.class),
                userRoleMapper, userMapper, session.getMapper(RolePermissionMapper.class));
        UserService userService = new UserService(userMapper, roleMapper, userRoleMapper,
                new PermissionInterceptor(roleService));

        SmsService smsService = mock(SmsService.class);
        RegistrationReviewClient reviewClient = mock(RegistrationReviewClient.class);
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        // 生产种子模板（#4361）不在本判据射程内（它由 ProductionSeedTemplateServiceTest 与本仓的
        // test_onboarding_required_seed_guard.py 的「调用点仍在」判据守着）—— 这里 mock 掉，
        // 让本判据只对「默认商品分类」这一条链负责。
        ProductionSeedTemplateService productionSeedTemplateService = mock(ProductionSeedTemplateService.class);
        when(productionSeedTemplateService.applyTemplate(anyLong(), any()))
                .thenReturn(Map.of("applied", true));

        return new RegistrationService(
                session.getMapper(TenantApplicationMapper.class),
                session.getMapper(TenantMapper.class),
                userService,
                smsService,
                userMapper,
                roleMapper,
                session.getMapper(PermissionMapper.class),
                session.getMapper(RolePermissionMapper.class),
                reviewClient,
                redisTemplate,
                productionSeedTemplateService,
                seeder);
    }

    private static long approveAndGetTenantId(RegistrationService service, long applicationId,
                                             String companyName) throws SQLException {
        service.approveApplication(applicationId, null, null);
        List<String> ids = stringsOf("SELECT id FROM tenants WHERE name = ? ORDER BY id", companyName);
        assertThat(ids).as("入驻必须真的建出这个租户：%s", companyName).hasSize(1);
        return Long.parseLong(ids.get(0));
    }

    /** 落一条 pending 入驻申请（= 真实链路里 AI 放行前的那一行）。 */
    private static long insertPendingApplication(String companyName, String phone) throws SQLException {
        try (Connection conn = dataSource.getConnection();
             PreparedStatement ps = conn.prepareStatement(
                     "INSERT INTO tenant_applications (company_name, company_name_norm, contact_name, phone,"
                             + " industry, status) VALUES (?, ?, ?, ?, '布艺', 'pending') RETURNING id")) {
            ps.setString(1, companyName);
            ps.setString(2, companyName);
            ps.setString(3, "测试联系人");
            ps.setString(4, phone);
            try (ResultSet rs = ps.executeQuery()) {
                assertThat(rs.next()).as("入驻申请必须落库成功").isTrue();
                return rs.getLong(1);
            }
        }
    }

    private static ProductCreateRequest firstProductRequest(String name, String skuCode, String categoryId) {
        ProductCreateRequest request = new ProductCreateRequest();
        request.setName(name);
        request.setSkuCode(skuCode);
        request.setCategoryId(categoryId);
        request.setBasePrice(new BigDecimal("168.00"));
        request.setStatus("on_sale");
        return request;
    }

    private static List<String> categoryIdsOf(long tenantId) throws SQLException {
        return stringsOf("SELECT id FROM categories WHERE tenant_id = ? AND deleted = 0 ORDER BY id", tenantId);
    }

    private static List<String> categoryNamesOf(long tenantId) throws SQLException {
        return stringsOf("SELECT name FROM categories WHERE tenant_id = ? AND deleted = 0 ORDER BY id", tenantId);
    }

    private static List<String> categoryRowsOf(long tenantId) throws SQLException {
        List<String> rows = new ArrayList<>();
        try (Connection conn = dataSource.getConnection();
             PreparedStatement ps = conn.prepareStatement(
                     "SELECT id, name, tenant_id, status FROM categories WHERE tenant_id = ? AND deleted = 0"
                             + " ORDER BY id")) {
            ps.setLong(1, tenantId);
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    rows.add("id=" + rs.getString(1) + "|name=" + rs.getString(2)
                            + "|tenantId=" + rs.getLong(3) + "|status=" + rs.getString(4));
                }
            }
        }
        return rows;
    }

    private static List<String> productRowsOf(long tenantId) throws SQLException {
        List<String> rows = new ArrayList<>();
        try (Connection conn = dataSource.getConnection();
             PreparedStatement ps = conn.prepareStatement(
                     "SELECT name, category_id FROM products WHERE tenant_id = ? AND deleted = 0 ORDER BY id")) {
            ps.setLong(1, tenantId);
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    rows.add("name=" + rs.getString(1) + "|categoryId=" + rs.getString(2));
                }
            }
        }
        return rows;
    }

    private static List<String> stringsOf(String sql, Object... args) throws SQLException {
        List<String> values = new ArrayList<>();
        try (Connection conn = dataSource.getConnection(); PreparedStatement ps = conn.prepareStatement(sql)) {
            for (int i = 0; i < args.length; i++) {
                ps.setObject(i + 1, args[i]);
            }
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    values.add(rs.getString(1));
                }
            }
        }
        return values;
    }

    /** 终态 schema（不手抄列清单）：bootstrap 路径的真值源。 */
    private static String schemaSql() throws IOException {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 backend/admin-api/src/main/resources/db/init/schema.sql").isNotNull();
        return Files.readString(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"));
    }
}
