package com.migao.admin.security;
// case_ids: DF-007, DF-017, PG-020, PG-018

import com.aliyun.oss.OSS;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.controller.AuthController;
import com.migao.admin.controller.CustomerAgentSessionController;
import com.migao.admin.controller.ProductController;
import com.migao.admin.controller.SmsController;
import com.migao.admin.dto.AgentSessionDetailResponse;
import com.migao.admin.dto.LoginRequest;
import com.migao.admin.dto.LoginResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.AgentMessage;
import com.migao.admin.service.AuthService;
import com.migao.admin.service.ProductService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import com.baomidou.mybatisplus.autoconfigure.MybatisPlusAutoConfiguration;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;
import org.springframework.boot.autoconfigure.data.redis.RedisAutoConfiguration;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Bean;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.util.AopTestUtils;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;
import java.util.Locale;

import static org.hamcrest.Matchers.containsString;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.authentication;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.user;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * Security 配置集成测试
 * 测试安全过滤链的认证/授权行为
 */
@SpringBootTest
@AutoConfigureMockMvc
@EnableAutoConfiguration(exclude = {
        DataSourceAutoConfiguration.class,
        MybatisPlusAutoConfiguration.class,
        RedisAutoConfiguration.class
})
class SecurityConfigTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private ServiceTokenFilter serviceTokenFilter;

    /**
     * 工人会话链上的三个 bean（issue #4733 / #4770）：**必须是真的**（不得 @MockBean 顶替）。
     *
     * <p>理由见 {@link #contextLoads_workerSessionChainIsReallyWired()} —— 本类是全仓唯一的
     * {@code @SpringBootTest} 全上下文测试，环必须在这里被照出来。</p>
     */
    @Autowired
    private com.migao.admin.worker.WorkerSessionService workerSessionService;

    @Autowired
    private WorkerSessionFilter workerSessionFilter;

    @Autowired
    private PasswordEncoder passwordEncoder;

    /** Service Token 密钥：测试环境用固定值（生产从 SERVICE_TOKEN_SECRET 注入）。 */
    private static final String SERVICE_SECRET = "test-service-token";

    @BeforeEach
    void setUpServiceTokenSecret() {
        ReflectionTestUtils.setField(serviceTokenFilter, "serviceTokenSecret", SERVICE_SECRET);
    }

    @MockBean
    private AuthService authService;

    @MockBean
    private ProductService productService;

    @MockBean
    private com.migao.admin.service.RegistrationService registrationService;

    @MockBean
    private com.migao.admin.service.UserService userService;

    /**
     * 工人档案服务（issue #4869）：新控制器 {@code AdminWorkerController} 的构造依赖
     * ⇒ 本上下文必须能装配它（本类对全部服务一律 {@code @MockBean}，与上面几条同款）。
     */
    @MockBean
    private com.migao.admin.service.WorkerAdminService workerAdminService;

    @MockBean
    private com.migao.admin.service.OrderShipmentService orderShipmentService;
    @MockBean
    private com.migao.admin.service.AfterSalesTicketService afterSalesTicketService;

    @MockBean
    private com.migao.admin.service.AgentEmployeeService agentEmployeeService;

    @MockBean
    private com.migao.admin.service.AgentSessionService agentSessionService;

    @MockBean
    private com.migao.admin.service.AuditLogService auditLogService;

    @MockBean
    private com.migao.admin.service.CategoryService categoryService;

    @MockBean
    private com.migao.admin.service.CustomerService customerService;

    // LLM WIKI 板块（issue #3051）：知识卡片服务（其依赖 Mapper 已在上方 @MockBean）
    @MockBean
    private com.migao.admin.service.KnowledgeCardService knowledgeCardService;

    // LLM WIKI 板块（issue #3051 P3）：行业模板服务
    @MockBean
    private com.migao.admin.service.KnowledgeTemplateService knowledgeTemplateService;

    // LLM WIKI 板块（issue #3051 P5）：提炼候选队列服务
    @MockBean
    private com.migao.admin.service.KnowledgeCandidateService knowledgeCandidateService;

    // LLM WIKI 板块（issue #3051 P5b）：会话提炼服务
    @MockBean
    private com.migao.admin.service.KnowledgeDistillService knowledgeDistillService;

    // 加工单服务（issue #3340）
    @MockBean
    private com.migao.admin.service.ProcessingOrderService processingOrderService;

    // 库存台账 Mapper（issue #4055）：MyBatis-Plus 自动扫描到的 Mapper，本上下文无 sqlSessionFactory
    // （MybatisPlusAutoConfiguration 已排除），按本文件既有口径（UserMemoryMapper 等）用 @MockBean 顶替
    @MockBean
    private com.migao.admin.mapper.StockLedgerMapper stockLedgerMapper;

    // 入库单（issue #5045，V111）：InboundOrderService 依赖的四个 Mapper 必须顶替 ——
    // 本上下文排除了 MybatisPlusAutoConfiguration ⇒ 没有 sqlSessionFactory ⇒ 不顶替会让
    // **整类 42 条断言一起红**，而红的表现是「ApplicationContext failure threshold exceeded」
    // （看不出跟入库单有关，排查会绕远）。同 StockLedgerMapper 的口径。
    @MockBean
    private com.migao.admin.mapper.InboundOrderMapper inboundOrderMapper;
    @MockBean
    private com.migao.admin.mapper.InboundOrderItemMapper inboundOrderItemMapper;
    @MockBean
    private com.migao.admin.mapper.InboundOrderQueryMapper inboundOrderQueryMapper;
    @MockBean
    private com.migao.admin.mapper.StockBatchMapper stockBatchMapper;
    // 批次消耗台账（V116 / issue #5145 阶段 1）：本上下文排除了 MybatisPlusAutoConfiguration
    // ⇒ 新 Mapper 无 sqlSessionFactory，必须与上面几个同款用 @MockBean 顶替（否则整个上下文起不来）
    @MockBean
    private com.migao.admin.mapper.StockBatchConsumptionMapper stockBatchConsumptionMapper;

    /**
     * 余料两表（V122 / issue #5146）：与上面几个 mapper 同款 —— 本上下文排除了
     * {@code MybatisPlusAutoConfiguration} ⇒ 新 Mapper 没有 {@code sqlSessionFactory}，
     * **不顶替就整个上下文起不来**（实测：`Error creating bean with name 'fabricRemnantMapper':
     * Property 'sqlSessionFactory' or 'sqlSessionTemplate' are required`，42 条用例全 ERROR）。
     *
     * <p>⚠️ 只 mock 服务**不够**（实测踩过）：mapper 是**独立**的单例，不因消费者被 mock 而不创建。</p>
     */
    @MockBean
    private com.migao.admin.mapper.FabricRemnantMapper fabricRemnantMapper;
    @MockBean
    private com.migao.admin.mapper.RemnantItemSizeMapper remnantItemSizeMapper;

    /** 批次账服务（#5145）：StockBatchController 的构造依赖 ⇒ 本上下文必须能装配它 */
    @MockBean
    private com.migao.admin.service.StockBatchConsumptionService stockBatchConsumptionService;

    /**
     * 余料回收服务（#5146）：`RemnantController` 与 `StockBatchConsumptionService` 的构造依赖
     * ⇒ 本上下文必须能装配它。
     *
     * <p>⚠️ **不 mock 就会红**（实测）：本类 `@EnableAutoConfiguration(exclude = {…,
     * MybatisPlusAutoConfiguration.class, …})` ⇒ 上下文里**没有** `SqlSessionFactory`，
     * 于是任何一个「真的去造 mapper」的服务都会在启动时炸
     * （`Property 'sqlSessionFactory' or 'sqlSessionTemplate' are required`）。
     * 本类对全部服务一律 `@MockBean`，这条与其余同款 —— 不是放宽，是**保持装配面可启动**。</p>
     */
    @MockBean
    private com.migao.admin.service.RemnantService remnantService;

    @MockBean
    private com.migao.admin.service.NotificationService notificationService;

    // 通知规则 / 模板（issue #4727）：两个 controller 补了类级 system:manage ⇒ 正向对照需要服务桩
    @MockBean
    private com.migao.admin.service.NotificationRuleService notificationRuleService;

    @MockBean
    private com.migao.admin.service.NotificationTemplateService notificationTemplateService;

    @MockBean
    private com.migao.admin.service.OrderService orderService;

    @MockBean
    private com.migao.admin.service.OrderLogisticsService orderLogisticsService;

    // 注意：FileStorageService 是接口，LocalFileStorageService 已默认启用，
    // OSS Client — 防止 OssConfig 尝试创建真实连接（CI 环境无凭证）
    @MockBean
    private OSS ossClient;

    // UserMemoryMapper — MyBatis-Plus 自动扫描到的 Mapper，CI 无 sqlSessionFactory
    @MockBean
    private com.migao.admin.mapper.UserMemoryMapper userMemoryMapper;

    // LLM WIKI 板块（issue #3051）：knowledge_cards / knowledge_candidates 的 Mapper
    @MockBean
    private com.migao.admin.mapper.KnowledgeCardMapper knowledgeCardMapper;

    @MockBean
    private com.migao.admin.mapper.KnowledgeCandidateMapper knowledgeCandidateMapper;

    // OssService 带有 @ConditionalOnBean 在测试环境下不会被加载，
    // 因此不需要 @MockBean FileStorageService / OssService，
    // 避免由于多个实现导致 NoUniqueBeanDefinitionException。

    @MockBean
    private com.migao.admin.service.PermissionService permissionService;

    @MockBean
    private com.migao.admin.service.ProcessingCategoryService processingCategoryService;

    @MockBean
    private com.migao.admin.service.ProcessingItemService processingItemService;

    @MockBean
    private com.migao.admin.service.RoleService roleService;

    @MockBean
    private com.migao.admin.service.SmsService smsService;

    @MockBean
    private com.migao.admin.service.WechatService wechatService;

    @MockBean
    private StringRedisTemplate redisTemplate;

    // 注意：UserService 已实现 UserDetailsService，上面的 @MockBean userService 会同时
    // 满足 UserService 和 UserDetailsService 两种类型的依赖注入需求，
    // 因此不再重复声明 UserDetailsService 的 @MockBean，避免覆盖后导致
    // UserService 类型不可被装配。

    // Mock all mapper beans that @MapperScan might try to create
    @MockBean
    private com.migao.admin.mapper.AfterSalesTicketMapper afterSalesTicketMapper;
    @MockBean
    private com.migao.admin.mapper.AgentEmployeeMapper agentEmployeeMapper;
    @MockBean
    private com.migao.admin.mapper.AgentMessageMapper agentMessageMapper;
    @MockBean
    private com.migao.admin.mapper.AgentSessionMapper agentSessionMapper;
    @MockBean
    private com.migao.admin.mapper.AuditLogMapper auditLogMapper;
    @MockBean
    private com.migao.admin.mapper.CategoryMapper categoryMapper;
    @MockBean
    private com.migao.admin.mapper.CustomerProfileMapper customerProfileMapper;
    @MockBean
    private com.migao.admin.mapper.CustomerSegmentMapper customerSegmentMapper;
    @MockBean
    private com.migao.admin.mapper.CustomerSegmentMemberMapper customerSegmentMemberMapper;
    @MockBean
    private com.migao.admin.mapper.CustomerTagMapper customerTagMapper;
    @MockBean
    private com.migao.admin.mapper.NotificationMapper notificationMapper;
    @MockBean
    private com.migao.admin.mapper.NotificationRuleMapper notificationRuleMapper;
    @MockBean
    private com.migao.admin.mapper.NotificationTemplateMapper notificationTemplateMapper;
    @MockBean
    private com.migao.admin.mapper.OrderItemMapper orderItemMapper;
    @MockBean
    private com.migao.admin.mapper.OrderLogisticsMapper orderLogisticsMapper;
    @MockBean
    private com.migao.admin.mapper.OrderMapper orderMapper;
    @MockBean
    private com.migao.admin.mapper.ProcessingOrderMapper processingOrderMapper;

    // 工人登录态（issue #4733）：WorkerSessionFilter 依赖这两个 bean，
    // 缺任一 ⇒ 本测试的 Spring 上下文起不来（本文件既有口径：Mapper 一律 @MockBean 顶替）
    @MockBean
    private com.migao.admin.mapper.WorkerSessionMapper workerSessionMapper;

    // 报工身份旁路账 Mapper（issue #4733）：MyBatis-Plus 自动扫描到的 Mapper，本上下文无
    // sqlSessionFactory（MybatisPlusAutoConfiguration 已排除），按本文件既有口径 @MockBean 顶替
    @MockBean
    private com.migao.admin.mapper.WorkerReportAuditMapper workerReportAuditMapper;

    // 🔴 issue #4770（P0 启动期环）核清结论：此处**不得**出现 `@MockBean WorkerSessionService`。
    // 它自 #4733 起把环上「workerSessionService → passwordEncoder」那条边切断 ⇒ 本类（全仓唯一的
    // @SpringBootTest 全上下文测试）对
    // `securityConfig → workerSessionFilter → workerSessionService → securityConfig`
    // **完全不敏感** ⇒ 当时 2297 条单测全绿（历史值），而线上 admin-api 每次启动都崩（nginx 502）。
    // 承重判据见 contextLoads_workerSessionChainIsReallyWired()。
    @MockBean
    private com.migao.admin.mapper.PermissionMapper permissionMapper;
    @MockBean
    private com.migao.admin.mapper.ProcessingCategoryMapper processingCategoryMapper;
    @MockBean
    private com.migao.admin.mapper.ProcessingItemMapper processingItemMapper;
    @MockBean
    private com.migao.admin.mapper.ProductMapper productMapper;
    @MockBean
    private com.migao.admin.mapper.ProductColorMapper productColorMapper;
    @MockBean
    private com.migao.admin.mapper.ProductSkuMapper productSkuMapper;
    @MockBean
    private com.migao.admin.mapper.ProductAttributeMapper productAttributeMapper;
    @MockBean
    private com.migao.admin.mapper.RoleMapper roleMapper;
    @MockBean
    private com.migao.admin.mapper.SessionMapper sessionMapper;
    @MockBean
    private com.migao.admin.mapper.SessionMessageMapper sessionMessageMapper;
    @MockBean
    private com.migao.admin.mapper.TenantAiConfigMapper tenantAiConfigMapper;
    @MockBean
    private com.migao.admin.mapper.TenantAppMapper tenantAppMapper;
    @MockBean
    private com.migao.admin.mapper.TenantMapper tenantMapper;
    @MockBean
    private com.migao.admin.mapper.TicketNoteMapper ticketNoteMapper;
    @MockBean
    private com.migao.admin.mapper.TicketTimelineMapper ticketTimelineMapper;
    @MockBean
    private com.migao.admin.mapper.UserIdentityMapper userIdentityMapper;
    @MockBean
    private com.migao.admin.mapper.UserMapper userMapper;
    @MockBean
    private com.migao.admin.mapper.TenantPaymentQrcodeMapper paymentQrcodeMapper;
    @MockBean
    private com.migao.admin.mapper.UserRoleMapper userRoleMapper;
    @MockBean
    private com.migao.admin.mapper.RolePermissionMapper rolePermissionMapper;
    @MockBean
    private com.migao.admin.mapper.TenantApplicationMapper tenantApplicationMapper;

    // 生产报工（issue #3995，V49）：新增的 Mapper / Service 同样没有 sqlSessionFactory，
    // 必须在此 mock，否则整个上下文起不来（安全用例连坐失败）。
    @MockBean
    private com.migao.admin.mapper.ProductionOperationMapper productionOperationMapper;
    @MockBean
    private com.migao.admin.mapper.ProductionRoutingMapper productionRoutingMapper;
    // （原「特殊选项两张表」的 @MockBean 已随到期对象删除：issue #5245 A4 把
    //  `production_option_routings` / `production_option_factors` 连同实体与 Mapper 一起退场，
    //  `@MapperScan` 再也扫不到它们 ⇒ 不必 mock。）
    @MockBean
    private com.migao.admin.mapper.ProcessingPositionOperationMapper processingPositionOperationMapper;
    @MockBean
    private com.migao.admin.mapper.ProductionWorkLogMapper productionWorkLogMapper;
    // 扫码闭环两张新表（issue #4698 切片 ⓪，V92）：一部位一码 token + 套号载体。同族坑再犯一次
    // （实测：漏了前者 ⇒ `productionController` 的 `productionScanService` 建不出来 ⇒
    // 本类 26 条全 error「Property 'sqlSessionFactory' or 'sqlSessionTemplate' are required」）。
    @MockBean
    private com.migao.admin.mapper.ProcessingSetPartTokenMapper processingSetPartTokenMapper;
    @MockBean
    private com.migao.admin.mapper.ProcessingOrderSetMapper processingOrderSetMapper;
    // 单价版本表（issue #4204，V55）：同上——@MapperScan 会尝试创建它，没有 sqlSessionFactory
    // 时上下文整体起不来（26 条安全用例连坐失败，实测）。
    @MockBean
    private com.migao.admin.mapper.ProductionOperationPriceVersionMapper productionOperationPriceVersionMapper;
    // 路线可配（issue #4308，V60）：信号映射表 + 路线版本账。同族坑再犯一次（实测：漏了前者 ⇒
    // ProductionOperationQueryService 的第 5 个构造参数建不出来 ⇒ 本类 26 条全 error
    // 「Property 'sqlSessionTemplate' are required」）⇒ **新增 Mapper/构造依赖必须同步补这里**。
    @MockBean
    private com.migao.admin.mapper.ProductionRouteSignalMapper productionRouteSignalMapper;
    @MockBean
    private com.migao.admin.mapper.ProductionRoutingVersionMapper productionRoutingVersionMapper;

    // issue #4423 P2 / #4432（V72）新增的 4 个 mapper —— **必须一并 @MockBean**：
    // 本上下文排除了 MybatisPlusAutoConfiguration（无 SqlSessionFactory），
    // 任何**未被 mock** 的 mapper 都会在上下文启动时真去创建 ⇒
    // `Property 'sqlSessionFactory' or 'sqlSessionTemplate' are required` ⇒ 整类 26 条全红。
    // （既有口径见上方 StockLedgerMapper 的注释；#4386 的 ProcessingFeeCombinationMapper 同款。）
    @MockBean
    private com.migao.admin.mapper.ProductionOperationPositionMapper productionOperationPositionMapper;

    @MockBean
    private com.migao.admin.mapper.ProductionRouteTemplateMapper productionRouteTemplateMapper;

    @MockBean
    private com.migao.admin.mapper.ProductionRouteRuleMapper productionRouteRuleMapper;

    // 部位价目矩阵格**计件单价**版本账（issue #4587 ⑤，V86）：同族坑再犯一次 ——
    // `ProductionOperationPositionCommandService` 的构造参数含它，未 mock ⇒ 上下文起不来
    // ⇒ 本类 26 条安全用例连坐全 error（实测：「Property 'sqlSessionFactory' … are required」）。
    @MockBean
    private com.migao.admin.mapper.ProductionOperationPositionPriceVersionMapper
            productionOperationPositionPriceVersionMapper;

    @MockBean
    private com.migao.admin.mapper.ProductionCraftMapper productionCraftMapper;

    // 算料公式租户级配置（issue #4528 = 包 E，V80）。**同族坑第 4 次**：
    // 新增一个 Mapper 就必须在此 `@MockBean` 顶替 —— 漏了不会在「新增 mapper 的那个测试」里红，
    // 而是在**本类**全 error（`Property 'sqlSessionFactory' or 'sqlSessionTemplate' are required`），
    // 归因错位。守卫 = tests/unit_ci_workflows/test_security_config_mapper_mocks.py（双向判据）。
    @MockBean
    private com.migao.admin.mapper.CraftCalcConfigMapper craftCalcConfigMapper;

    // 企业参数变更留痕（issue #5131 P6，V131）。**同族坑第 6 次**：新增 Mapper（此处 =
    // TenantParamAuditMapper，经 TenantParamAuditService ← CraftCalcConfigService ← CraftCalcConfigController
    // 被拉进上下文）必须在此 `@MockBean` 顶替 —— 漏了不会在「新增 mapper 的那个测试」里红，
    // 而是在**本类**全 error（`Property 'sqlSessionFactory' or 'sqlSessionTemplate' are required`），归因错位。
    // 本次实测：漏 mock 时本类 43 条全 error（守卫 tests/unit_ci_workflows/test_security_config_mapper_mocks.py 同时判红）。
    @MockBean
    private com.migao.admin.mapper.TenantParamAuditMapper tenantParamAuditMapper;

    // 未定价实例补价动作账（issue #4709 C，V94）。**同族坑第 5 次**：新增 Mapper 必须在此
    // `@MockBean` 顶替 —— 它是 ProductionInstanceRepricingService（→ ProductionController 的
    // 字段注入依赖）的构造参数，未 mock ⇒ 上下文起不来 ⇒ 本类 26 条安全用例连坐全 error
    // 「Property 'sqlSessionFactory' or 'sqlSessionTemplate' are required」（实测）。
    // 双向守卫 = tests/unit_ci_workflows/test_security_config_mapper_mocks.py。
    @MockBean
    private com.migao.admin.mapper.ProductionInstanceRepricingLogMapper productionInstanceRepricingLogMapper;

    // 加工费组合定价（issue #4386，V68）：组合表 + 版本账 + 读面要用的订单行 Mapper。同族坑第 3 次
    // —— 漏任何一个 ⇒ ProcessingFeeQueryService / ProcessingFeeCombinationCommandService
    // 的构造依赖建不出来 ⇒ 本类全 error「Property 'sqlSessionTemplate' are required」。
    @MockBean
    private com.migao.admin.mapper.ProcessingFeeCombinationMapper processingFeeCombinationMapper;
    @MockBean
    private com.migao.admin.mapper.ProcessingFeeCombinationVersionMapper processingFeeCombinationVersionMapper;
    @MockBean
    private com.migao.admin.service.ProductionService productionService;

    // 智能每日经营简报（issue #3468）：Mapper / Service / ai-agent 客户端
    @MockBean
    private com.migao.admin.mapper.DailyBriefingMapper dailyBriefingMapper;
    @MockBean
    private com.migao.admin.service.DailyBriefingService dailyBriefingService;
    @MockBean
    private com.migao.admin.service.BriefingGenerateClient briefingGenerateClient;
    @MockBean
    private com.migao.admin.mapper.PlatformAdminMapper platformAdminMapper;
    @MockBean
    private com.migao.admin.mapper.FinanceTransactionMapper financeTransactionMapper;

    @MockBean
    private com.migao.admin.service.FinanceService financeService;

    // 批量更新的批次资源（issue #5314 服务端包）：两个 Mapper 必须在这里被 mock ——
    // 本上下文 `@EnableAutoConfiguration(exclude = {MybatisPlusAutoConfiguration})` ⇒ **真 Mapper 建不出来**
    // （`Property 'sqlSessionFactory' or 'sqlSessionTemplate' are required`）⇒ 整个上下文起不来
    // ⇒ 本类 43 条判据全变 error（实测形态）。Service 留真身：它只依赖这两个 Mapper + 已 mock 的 ProductService。
    @MockBean
    private com.migao.admin.mapper.AgentBatchMapper agentBatchMapper;
    @MockBean
    private com.migao.admin.mapper.AgentBatchItemMapper agentBatchItemMapper;

    // ======================== 公开端点测试 ========================

    @Test
    @DisplayName("公开端点 - 登录接口无需认证即可访问")
    void publicEndpoint_LoginAccessible() throws Exception {
        // Given: 模拟登录成功
        LoginResponse loginResponse = LoginResponse.builder()
                .accessToken("mock-token")
                .refreshToken("mock-refresh")
                .expiresIn(7200L)
                .user(LoginResponse.UserInfo.builder()
                        .id("user-001")
                        .nickname("admin")
                        .role("admin")
                        .identityType("account")
                        .roles(List.of("admin"))
                        .build())
                .build();

        // #375: 密码登录已禁用
        LoginRequest request = new LoginRequest();
        request.setUsername("admin");
        request.setPassword("password");
        request.setTenantId(1L);

        mockMvc.perform(post("/api/auth/admin/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("AUTH_FAILED"));
    }

    // ======================== 受保护端点测试 ========================

    @Test
    @DisplayName("受保护端点 - 未认证访问返回 401")
    void protectedEndpoint_Unauthorized() throws Exception {
        // When & Then: 无 Token 访问受保护端点应返回 401
        mockMvc.perform(get("/api/admin/products")
                        .contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isUnauthorized());
    }

    @Test
    @DisplayName("受保护端点 - 未认证访问商品详情返回 401")
    void protectedEndpoint_ProductDetail_Unauthorized() throws Exception {
        // When & Then
        mockMvc.perform(get("/api/admin/products/prod-001")
                        .contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isUnauthorized());
    }

    @Test
    @DisplayName("受保护端点 - 未认证访问用户信息返回 401")
    void protectedEndpoint_CurrentUser_Unauthorized() throws Exception {
        // When & Then
        mockMvc.perform(get("/api/auth/me")
                        .contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isUnauthorized());
    }

    // ======================== 垂直越权防护测试 ========================
    // 修复背景：此前 /api/admin/** 仅要求 authenticated()，任意已登录角色
    // （含 customer/agent）均可访问管理后台接口，构成垂直越权。

    @Test
    @DisplayName("越权防护 - customer 角色访问 /api/admin/** 返回 403")
    void authorization_customerRole_cannotAccessAdminEndpoint() throws Exception {
        mockMvc.perform(get("/api/admin/products")
                        .with(user("customer-1").roles("CUSTOMER")))
                .andExpect(status().isForbidden());
    }

    @Test
    @DisplayName("越权防护 - agent 角色访问 /api/admin/** 返回 403")
    void authorization_agentRole_cannotAccessAdminEndpoint() throws Exception {
        mockMvc.perform(get("/api/admin/products")
                        .with(user("agent-1").roles("AGENT")))
                .andExpect(status().isForbidden());
    }

    @Test
    @DisplayName("越权防护 - admin 角色可访问 /api/admin/**")
    void authorization_adminRole_canAccessAdminEndpoint() throws Exception {
        when(productService.getProducts(any(), nullable(Long.class))).thenReturn(new PageResponse<>());
        when(roleService.getUserPermissions(any())).thenReturn(List.of("*"));

        mockMvc.perform(get("/api/admin/products")
                        .with(user("admin-1").roles("ADMIN")))
                .andExpect(status().isOk());
    }

    @Test
    @DisplayName("越权防护 - super_admin 角色可访问 /api/admin/**")
    void authorization_superAdminRole_canAccessAdminEndpoint() throws Exception {
        when(productService.getProducts(any(), nullable(Long.class))).thenReturn(new PageResponse<>());

        mockMvc.perform(get("/api/admin/products")
                        .with(user("sa-1").roles("SUPER_ADMIN")))
                .andExpect(status().isOk());
    }

    @Test
    @DisplayName("越权防护 - 内部服务 ROLE_SERVICE 可访问 /api/admin/**")
    void authorization_serviceRole_canAccessAdminEndpoint() throws Exception {
        when(productService.getProducts(any(), nullable(Long.class))).thenReturn(new PageResponse<>());

        mockMvc.perform(get("/api/admin/products")
                        .with(user("svc-1").roles("SERVICE")))
                .andExpect(status().isOk());
    }

    // ======================== Service Token 透传商户员工 — 细粒度鉴权（issue #4105 F2）========================
    // 背景：ai-agent 调用 admin-api 始终带 X-Service-Token + X-Tenant-Id + X-User-Id，
    // ServiceTokenFilter 此前一律构造 role=service 的身份 ⇒ PermissionInterceptor.hasBypassRole()
    // 直接放行，商户员工（受限岗位）能让米宝执行自己无权执行的写操作，admin-api 完全无感。
    // 目标：X-User-Id 命中同租户商户员工时挂真实角色，交由 @RequirePermission 校验并返回 F1 的可执行 403。

    @Test
    @DisplayName("服务令牌 + 商户员工无 product:list ⇒ 403 且响应体携带缺失权限码 + 可执行 suggestion")
    void serviceToken_merchantStaffWithoutPermission_deniedWithActionableBody() throws Exception {
        when(userMapper.selectById("staff-1")).thenReturn(staffUser("staff-1", 1L, "operator", "active"));
        when(roleService.getUserPermissions("staff-1")).thenReturn(List.of("dashboard:view"));

        mockMvc.perform(get("/api/admin/products")
                        .header("X-Service-Token", SERVICE_SECRET)
                        .header("X-Tenant-Id", "1")
                        .header("X-User-Id", "staff-1"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("PERMISSION_DENIED"))
                .andExpect(jsonPath("$.error.message").value(containsString("product:list")))
                .andExpect(jsonPath("$.error.details[0].field").value("requiredPermission"))
                .andExpect(jsonPath("$.error.details[0].message").value("product:list"))
                .andExpect(jsonPath("$.suggestion").value(containsString("product:list")))
                .andExpect(jsonPath("$.suggestion").value(containsString("不要重复调用同一工具")));

        // 负向控制（本用例的承重判据）：旧实现命中 service 旁路 ⇒ getUserPermissions 一次都不被调用、
        // 且响应是 200 —— 上面两条断言与下面这条 verify 会同时变红，证明新守卫真的在承重。
        verify(roleService).getUserPermissions("staff-1");
        verify(productService, never()).getProducts(any(), any());
    }

    @Test
    @DisplayName("#5641 生产概览端点缺 production:view ⇒ 403（无权限是**拒绝**，不是静默返回空列表）")
    void todoOverviewWithoutProductionViewIsDenied() throws Exception {
        when(userMapper.selectById("staff-1")).thenReturn(staffUser("staff-1", 1L, "operator", "active"));
        // 有经营看板读码、**没有**生产域读码 —— 正是「打开了数据 Tab 但看不到生产待办」的那个角色
        when(roleService.getUserPermissions("staff-1")).thenReturn(List.of("dashboard:view"));

        mockMvc.perform(get("/api/admin/production/todo-overview")
                        .header("X-Service-Token", SERVICE_SECRET)
                        .header("X-Tenant-Id", "1")
                        .header("X-User-Id", "staff-1"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("PERMISSION_DENIED"))
                .andExpect(jsonPath("$.error.details[0].field").value("requiredPermission"))
                .andExpect(jsonPath("$.error.details[0].message").value("production:view"));

        // 承重判据：拒绝发生在**进业务之前**。「无权限」与「今天没有待处理」必须可区分 ——
        // `{"success":true,"data":{"todo_total":0}}` 那种静默空列表正是本单要防的形态。
        verify(roleService).getUserPermissions("staff-1");
    }

    @Test
    @DisplayName("服务令牌 + 商户员工持有 product:list ⇒ 200（细粒度校验放行，不再走旁路）")
    void serviceToken_merchantStaffWithPermission_allowed() throws Exception {
        when(userMapper.selectById("staff-2")).thenReturn(staffUser("staff-2", 1L, "operator", "active"));
        when(roleService.getUserPermissions("staff-2")).thenReturn(List.of("product:list"));
        when(productService.getProducts(any(), nullable(Long.class))).thenReturn(new PageResponse<>());

        mockMvc.perform(get("/api/admin/products")
                        .header("X-Service-Token", SERVICE_SECRET)
                        .header("X-Tenant-Id", "1")
                        .header("X-User-Id", "staff-2"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));

        // 旁路若仍在，getUserPermissions 永不被调用 ⇒ 本断言变红
        verify(roleService).getUserPermissions("staff-2");
    }

    @Test
    @DisplayName("服务令牌 + C 端消费者 X-User-Id ⇒ 行为与今日一致（C 端路径零回归）")
    void serviceToken_customerXUserId_keepsLegacyServiceBypass() throws Exception {
        when(userMapper.selectById("customer-9")).thenReturn(staffUser("customer-9", 1L, "customer", "active"));
        when(productService.getProducts(any(), nullable(Long.class))).thenReturn(new PageResponse<>());

        mockMvc.perform(get("/api/admin/products")
                        .header("X-Service-Token", SERVICE_SECRET)
                        .header("X-Tenant-Id", "1")
                        .header("X-User-Id", "customer-9"))
                .andExpect(status().isOk());

        // C 端消费者不属于商户员工：仍走内部服务身份，不引入细粒度权限查询（逐字节保持今日路径）
        verify(roleService, never()).getUserPermissions(anyString());
    }

    private static com.migao.admin.entity.User staffUser(String id, Long tenantId, String role, String status) {
        return com.migao.admin.entity.User.builder()
                .id(id)
                .tenantId(tenantId)
                .role(role)
                .status(status)
                .deleted(0)
                .build();
    }

    // ======================== Agent 订单退款：action 级细粒度鉴权（issue #4148）========================
    // 背景：`AgentOrderController` 的统一 PATCH 端点一个入口覆盖 status/logistics/payment/cancel/**refund**
    // ⇒ 只按端点码放行，就等于「能改单 = 能退款」（内置岗位里 customer_service/sales/finance 都没有
    // order:refund）；表单路径 `OrderController` 的退款路由用的是 order:refund，两条路径口径不一致。
    // 目标：退款仍走同一条链（ServiceTokenFilter 解析真实员工 → 权限判定），但**退款这一个 action**
    // 额外要求 order:refund。
    // 🔴 issue #5246 追加单：本端点的**门槛码**已从读码 `order:list` 换成写码 `order:update` ——
    // 于是「仅持读码」连改单都进不来（这正是追加单要关掉的口子），下面三个用例的门槛码随之改判：
    // ① 仅持 order:update ⇒ 改单 200、退款 403（缺 order:refund）；② 持两者 ⇒ 退款 200；
    // ③ 仅持 order:list ⇒ 改单 403（改前是 200，**有意**改红，判据从「不收窄」变成「收窄到位」）。

    @Test
    @DisplayName("Agent 退款 - 商户员工持 order:update 但无 order:refund ⇒ 403（缺失权限码 + 可执行 suggestion），且退款从未下发服务层")
    void agentRefund_merchantStaffWithoutRefundPermission_deniedWithActionableBody() throws Exception {
        when(userMapper.selectById("staff-cs")).thenReturn(staffUser("staff-cs", 1L, "customer_service", "active"));
        // order:update 是**真实的端点码**（issue #5246 起）—— 它必须照旧放行到业务层，
        // 否则本用例测的不是退款那道门（缺的会是 order:update）
        when(roleService.getUserPermissions("staff-cs")).thenReturn(List.of("order:update"));

        mockMvc.perform(patch("/api/admin/agent/orders/ORD-20260101-0001")
                        .header("X-Service-Token", SERVICE_SECRET)
                        .header("X-Tenant-Id", "1")
                        .header("X-User-Id", "staff-cs")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"action\":\"refund\",\"refundAmount\":299.0,\"refundReason\":\"质量问题\"}"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("PERMISSION_DENIED"))
                // 缺的必须是 order:refund（若 403 来自端点码 order:update，这里会变成 order:update ⇒ 本用例红）
                .andExpect(jsonPath("$.error.details[0].field").value("requiredPermission"))
                .andExpect(jsonPath("$.error.details[0].message").value("order:refund"))
                .andExpect(jsonPath("$.suggestion").value(containsString("order:refund")))
                .andExpect(jsonPath("$.suggestion").value(containsString("不要重复调用同一工具")));

        // 承重判据（负向控制）：退款**一次都不许**进服务层 —— 缺此断言时，
        // 「返回 403 但订单已被退款」这种最坏形态会照样绿。
        verify(orderService, never()).updateOrderForAgent(anyString(), any(), any());
    }

    @Test
    @DisplayName("Agent 退款 - 商户员工持有 order:refund ⇒ 200（正向对照：未过度收窄）")
    void agentRefund_merchantStaffWithRefundPermission_allowed() throws Exception {
        when(userMapper.selectById("staff-op")).thenReturn(staffUser("staff-op", 1L, "operator", "active"));
        when(roleService.getUserPermissions("staff-op")).thenReturn(List.of("order:update", "order:refund"));
        when(orderService.updateOrderForAgent(anyString(), any(), any()))
                .thenReturn(new com.migao.admin.dto.OrderDetailResponse());

        mockMvc.perform(patch("/api/admin/agent/orders/ORD-20260101-0001")
                        .header("X-Service-Token", SERVICE_SECRET)
                        .header("X-Tenant-Id", "1")
                        .header("X-User-Id", "staff-op")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"action\":\"refund\",\"refundAmount\":299.0}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));

        verify(orderService).updateOrderForAgent(anyString(), any(), any());
    }

    @Test
    @DisplayName("Agent 改单 - update_status 收窄为写码：仅持读码 order:list ⇒ 403 order:update（本单要关掉的口子）")
    void agentUpdateStatus_merchantStaffWithOnlyReadCode_denied() throws Exception {
        when(userMapper.selectById("staff-cs")).thenReturn(staffUser("staff-cs", 1L, "customer_service", "active"));
        // issue #5246 追加单：改单的**门槛码**由读码 order:list 换成写码 order:update ⇒
        // 「能看订单列表」不再等于「能改订单」。本用例改前是**期望 200** 的（旧契约「其余 action 不收窄」），
        // 现按新契约改判为 403 —— 这是**有意**的判据翻转，不是回归。
        when(roleService.getUserPermissions("staff-cs")).thenReturn(List.of("order:list"));

        mockMvc.perform(patch("/api/admin/agent/orders/ORD-20260101-0001")
                        .header("X-Service-Token", SERVICE_SECRET)
                        .header("X-Tenant-Id", "1")
                        .header("X-User-Id", "staff-cs")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"action\":\"update_status\",\"status\":\"confirmed\"}"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.details[0].message").value("order:update"));

        // 负向控制：被拒的改单**一次都不许**进服务层
        verify(orderService, never()).updateOrderForAgent(anyString(), any(), any());
    }

    @Test
    @DisplayName("Agent 改单 - 持写码 order:update ⇒ 200（正向对照：改单不是被一刀切死）")
    void agentUpdateStatus_merchantStaffWithWriteCode_allowed() throws Exception {
        when(userMapper.selectById("staff-cs")).thenReturn(staffUser("staff-cs", 1L, "customer_service", "active"));
        when(roleService.getUserPermissions("staff-cs")).thenReturn(List.of("order:update"));
        when(orderService.updateOrderForAgent(anyString(), any(), any()))
                .thenReturn(new com.migao.admin.dto.OrderDetailResponse());

        mockMvc.perform(patch("/api/admin/agent/orders/ORD-20260101-0001")
                        .header("X-Service-Token", SERVICE_SECRET)
                        .header("X-Tenant-Id", "1")
                        .header("X-User-Id", "staff-cs")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"action\":\"update_status\",\"status\":\"confirmed\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));

        verify(orderService).updateOrderForAgent(anyString(), any(), any());
    }

    @Test
    @DisplayName("Agent 退款 - 纯内部服务调用（无 X-User-Id）保持既有旁路 ⇒ 200（零回归）")
    void agentRefund_internalServiceCall_keepsBypass() throws Exception {
        when(orderService.updateOrderForAgent(anyString(), any(), any()))
                .thenReturn(new com.migao.admin.dto.OrderDetailResponse());

        mockMvc.perform(patch("/api/admin/agent/orders/ORD-20260101-0001")
                        .header("X-Service-Token", SERVICE_SECRET)
                        .header("X-Tenant-Id", "1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"action\":\"refund\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));
    }

    // ======================== 商户员工角色门禁测试 ========================
    // 背景：此前 /api/admin/** 仅放行 ADMIN/SUPER_ADMIN/SERVICE，导致 operator 等
    // 商户员工角色登录后访问任何管理接口一律 403（验收 P1「角色权限真实生效」）。
    // 目标：商户员工角色（含自定义角色）可进入 /api/admin/**，细粒度由 @RequirePermission 控制；
    //       customer/agent（小程序/B2C 用户）仍一律 403（垂直越权防护不回归）。

    @Test
    @DisplayName("商户员工 - operator 角色持有 product:list 可访问商品接口")
    void authorization_operatorRole_canAccessAdminEndpoint() throws Exception {
        when(productService.getProducts(any(), nullable(Long.class))).thenReturn(new PageResponse<>());
        when(roleService.getUserPermissions(any())).thenReturn(List.of("product:list"));

        mockMvc.perform(get("/api/admin/products")
                        .with(user("operator-1").roles("OPERATOR")))
                .andExpect(status().isOk());
    }

    @Test
    @DisplayName("商户员工 - 自定义角色持有 product:list 可访问商品接口")
    void authorization_customRole_canAccessAdminEndpoint() throws Exception {
        when(productService.getProducts(any(), nullable(Long.class))).thenReturn(new PageResponse<>());
        when(roleService.getUserPermissions(any())).thenReturn(List.of("product:list"));

        mockMvc.perform(get("/api/admin/products")
                        .with(user("custom-1").roles("STORE_MANAGER")))
                .andExpect(status().isOk());
    }

    @Test
    @DisplayName("商户员工 - operator 无 product:list 权限访问商品接口返回 403")
    void authorization_operatorRole_withoutPermission_denied() throws Exception {
        when(roleService.getUserPermissions(any())).thenReturn(List.of());

        mockMvc.perform(get("/api/admin/products")
                        .with(user("operator-2").roles("OPERATOR")))
                .andExpect(status().isForbidden());
    }

    // ======================== 员工管理接口细粒度鉴权测试 ========================

    @Test
    @DisplayName("员工管理 - admin(*) 可创建员工")
    void employeeCreate_admin_canCreateUser() throws Exception {
        when(roleService.getUserPermissions(any())).thenReturn(List.of("*"));
        when(userService.createUser(any(), any(), any(), any(), any(), any(), any()))
                .thenReturn(new com.migao.admin.entity.User());

        mockMvc.perform(post("/api/admin/users")
                        .with(user("admin-2").roles("ADMIN"))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"测试\",\"phone\":\"13900000002\",\"position\":\"客服\",\"permissions\":[\"employee:list\"]}"))
                .andExpect(status().isOk());
    }

    @Test
    @DisplayName("员工管理 - operator 持有 employee:create 可创建员工")
    void employeeCreate_operatorWithPermission_canCreateUser() throws Exception {
        when(roleService.getUserPermissions(any())).thenReturn(List.of("employee:create"));
        when(userService.createUser(any(), any(), any(), any(), any(), any(), any()))
                .thenReturn(new com.migao.admin.entity.User());

        mockMvc.perform(post("/api/admin/users")
                        .with(user("operator-3").roles("OPERATOR"))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"测试\",\"phone\":\"13900000003\",\"position\":\"客服\",\"permissions\":[\"employee:list\"]}"))
                .andExpect(status().isOk());
    }

    @Test
    @DisplayName("员工管理 - operator 无 employee:create 创建员工返回 403")
    void employeeCreate_operatorWithoutPermission_denied() throws Exception {
        when(roleService.getUserPermissions(any())).thenReturn(List.of("employee:list"));

        mockMvc.perform(post("/api/admin/users")
                        .with(user("operator-4").roles("OPERATOR"))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"测试\",\"phone\":\"13900000004\",\"position\":\"客服\"}"))
                .andExpect(status().isForbidden());
    }

    @Test
    @DisplayName("员工管理 - operator 持有 employee:list 可查看员工列表")
    void employeeList_operatorWithPermission_canListUsers() throws Exception {
        when(roleService.getUserPermissions(any())).thenReturn(List.of("employee:list"));
        when(userService.getUserPage(anyLong(), anyLong(), any(), any(), any(), any()))
                .thenReturn(com.migao.admin.dto.PageResponse.of(0L, 1L, 10L, List.of()));

        mockMvc.perform(get("/api/admin/users")
                        .with(user("operator-5").roles("OPERATOR")))
                .andExpect(status().isOk());
    }

    @Test
    @DisplayName("员工管理 - operator 无 employee:list 查看员工列表返回 403")
    void employeeList_operatorWithoutPermission_denied() throws Exception {
        when(roleService.getUserPermissions(any())).thenReturn(List.of("dashboard:view"));

        mockMvc.perform(get("/api/admin/users")
                        .with(user("operator-6").roles("OPERATOR")))
                .andExpect(status().isForbidden());
    }

    // ======================== 工人档案接口（issue #4869）=======================

    @Test
    @DisplayName("越权防护 - 工人角色（worker）访问 /api/admin/workers 返回 403（新入口被同一道门禁覆盖）")
    void authorization_workerRole_cannotAccessWorkerEndpoints() throws Exception {
        mockMvc.perform(get("/api/admin/workers")
                        .with(user("worker-1").roles("WORKER")))
                .andExpect(status().isForbidden());

        mockMvc.perform(post("/api/admin/workers")
                        .with(user("worker-1").roles("WORKER"))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"W-1001\",\"name\":\"张三\",\"pin\":\"246810\"}"))
                .andExpect(status().isForbidden());

        // 不是「拒绝了但业务已执行」：请求根本没进到服务层
        verify(workerAdminService, never()).createWorker(any(), any(), any());
        verify(workerAdminService, never()).listWorkers(anyLong(), anyLong(), any(), any());
    }

    @Test
    @DisplayName("工人档案 - operator 持 employee:create 可建工人（正向对照：不是被一刀切死）")
    void workerCreate_operatorWithPermission_allowed() throws Exception {
        when(roleService.getUserPermissions(any())).thenReturn(List.of("employee:create"));
        when(workerAdminService.createWorker(any(), any(), any()))
                .thenReturn(new com.migao.admin.entity.User());

        mockMvc.perform(post("/api/admin/workers")
                        .with(user("operator-7").roles("OPERATOR"))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"W-1001\",\"name\":\"张三\",\"pin\":\"246810\"}"))
                .andExpect(status().isOk());
    }

    @Test
    @DisplayName("工人档案 - operator 无 employee:create 建工人返回 403（权限码复用员工域，不新增权限码）")
    void workerCreate_operatorWithoutPermission_denied() throws Exception {
        when(roleService.getUserPermissions(any())).thenReturn(List.of("employee:list"));

        mockMvc.perform(post("/api/admin/workers")
                        .with(user("operator-8").roles("OPERATOR"))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"W-1001\",\"name\":\"张三\",\"pin\":\"246810\"}"))
                .andExpect(status().isForbidden());
    }

    // ======================== CORS 测试 ========================

    @Test
    @DisplayName("CORS - OPTIONS 预检请求应返回正确的 CORS 头")
    void cors_PreflightRequest() throws Exception {
        mockMvc.perform(options("/api/auth/admin/login")
                        .header("Origin", "http://localhost:3000")
                        .header("Access-Control-Request-Method", "POST")
                        .header("Access-Control-Request-Headers", "Content-Type,Authorization"))
                .andExpect(status().isOk())
                .andExpect(header().exists("Access-Control-Allow-Origin"));
    }

    /**
     * 🔴 工人端 H5 的预检必须放行 {@code X-Worker-Session-Id}（issue #4716；缺口由 #4733 登记）。
     *
     * <p><b>为什么这条必须有</b>：{@code allowedHeaders} 是**逐项白名单** —— 少一个头，
     * 浏览器预检就不放行它，真实请求**根本发不出去**（前端只看到 CORS 报错，看不出病因）。
     * 症状是「工人登录成功，之后所有请求全 401」，而服务端日志里连请求都没有。</p>
     *
     * <p><b>红证形态</b>：把 {@code allowedHeaders} 里的 {@code "X-Worker-Session-Id"} 去掉
     * ⇒ 本用例必红（改前实测输出见 PR body）。</p>
     */
    @Test
    @DisplayName("CORS - 工人登录态头 X-Worker-Session-Id 必须被预检放行（去掉该头 ⇒ 必红）")
    void cors_PreflightAllowsWorkerSessionHeader() throws Exception {
        mockMvc.perform(options("/api/worker/production/scan")
                        .header("Origin", "http://localhost:3000")
                        .header("Access-Control-Request-Method", "GET")
                        .header("Access-Control-Request-Headers", "X-Worker-Session-Id,Content-Type"))
                .andExpect(status().isOk())
                .andExpect(header().string("Access-Control-Allow-Headers",
                        containsString("X-Worker-Session-Id")));
    }

    /**
     * 🔴 稳定短链 {@code GET /s/{短码}} 必须是**公开入口**（issue #4802；设计 #4716 §1.3 / §7.2）。
     *
     * <p><b>为什么这条必须有</b>：印刷品上的码对**任何**持码人等价（扫码工具/系统相机/手输 URL），
     * 而它落在 {@code anyRequest().authenticated()} 上 ⇒ 未登录访问只会拿到 **401**，
     * 短链**等于没用**（扫码工具显示「未认证」而不是报工页）。</p>
     *
     * <p><b>判据形态</b>：未认证请求能**到达控制器**（⇒ 未知短码得 404，而不是 401）。
     * 本用例只钉「没被 401 拦下」这一半；**302 那一半**由紧随其后的
     * {@link #shortLinkRedirectsThroughSecurityChain()}（同一条安全链 + 真实控制器）钉，
     * 另有 {@code WorkerShortLinkControllerTest} 钉 404 / 410 / 归一化等分支。</p>
     *
     * <p><b>红证</b>：改前（{@code origin/main}）该路径不在 {@code permitAll} 且无路由
     * ⇒ 实测 **401**（不是 404）⇒ 本用例必红。</p>
     */
    @Test
    @DisplayName("公开端点 - 稳定短链 /s/{短码} 无需认证（改前 401 ⇒ 必红）")
    void shortLinkIsPublic() throws Exception {
        mockMvc.perform(get("/s/7K3M9QP2"))
                .andExpect(status().isNotFound());
    }

    /**
     * 🔴 全链路（安全过滤链 + 路由 + 控制器 + 服务）：有效短码 ⇒ **302** + {@code Location}。
     *
     * <p><b>与上一条的分工</b>：上一条只钉「未登录不会被 401 拦下」（⇒ 404 而不是 401）；
     * 本条钉「过了安全链之后真的出 302」。两条合起来才覆盖硬要求
     * 「标准 HTTPS URL + **服务端** 302」—— 前端 JS 跳转**不可能**产出 302 状态行。</p>
     *
     * <p>走的是**真实**控制器 + 真实 {@code WorkerShortLinkService}（本类的
     * {@code processingSetPartTokenMapper} 是 {@code @MockBean}）⇒ 归一化 / 装配口径
     * 都是生产那一份，不是测试里另写的一套。</p>
     */
    @Test
    @DisplayName("🔴 公开短链全链路：有效短码 ⇒ 302 + Location（服务端跳转，不是前端 JS）")
    void shortLinkRedirectsThroughSecurityChain() throws Exception {
        String shortCode = "4T7Y2BQ9";
        String partCode = "fake-part-code-fixture-4802";
        when(processingSetPartTokenMapper.selectByShortCode(shortCode))
                .thenReturn(com.migao.admin.entity.ProcessingSetPartToken.builder()
                        .id("t-1").tenantId(7L).token(partCode).shortCode(shortCode).deleted(0).build());

        mockMvc.perform(get("/s/" + shortCode))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", "/w/?t=" + partCode + "&tenant_id=7"))
                // 不泄露身份/权限：302 的响应体为空
                .andExpect(content().string(""));
    }

    // ======================== 刷新 Token 公开端点测试 ========================
    @Test
    @DisplayName("公开端点 - Token 刷新接口无需认证")
    void publicEndpoint_RefreshToken() throws Exception {
        // When & Then: /api/auth/refresh 应可以访问，不返回 401
        mockMvc.perform(post("/api/auth/refresh")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"refreshToken\":\"test-token\"}"))
                .andExpect(result -> {
                    int status = result.getResponse().getStatus();
                    assert status != 401 : "刷新端点不应返回 401，实际返回: " + status;
                });
    }

    // ======================== 权限注解面审计（issue #4727）========================
    // 背景：#4727 逐 controller 核清「无 @RequirePermission」的面 ⇒ 只对**明确漏了**的租户级配置面补注解，
    // 并为工人端预留拒绝集合（#4716 设计 C11）。**以下每条都是红证**：
    // 把对应的注解 / ADMIN_API_REJECTED_ROLES 改动回退 ⇒ 该用例必红（改前实测输出见 PR body）。

    @Test
    @DisplayName("权限审计 - 商户员工无 system:view 访问 /api/admin/permissions ⇒ 403（改前放行）")
    void permissionAudit_permissions_withoutSystemManage_denied() throws Exception {
        when(roleService.getUserPermissions(any())).thenReturn(List.of("dashboard:view"));

        // issue #5291：该端点是**读**面（权限目录）⇒ 生效码 = 新增的读码 `system:view`
        //（原持 `system:manage` 的岗位由 V128 迁移同批补授读码 ⇒ 可见性零变化）。
        mockMvc.perform(get("/api/admin/permissions")
                        .with(user("staff-p1").roles("OPERATOR")))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error.code").value("PERMISSION_DENIED"))
                .andExpect(jsonPath("$.error.details[0].message").value("system:view"));

        // 承重判据（负向控制）：改前该端点放行到业务层 ⇒ 这条 verify 会红
        verify(permissionService, never()).getAllPermissions();
    }

    @Test
    @DisplayName("权限审计 - 商户员工持 system:view 访问 /api/admin/permissions ⇒ 200（正向对照，未过度收窄）")
    void permissionAudit_permissions_withSystemManage_allowed() throws Exception {
        when(roleService.getUserPermissions(any())).thenReturn(List.of("system:view"));
        when(permissionService.getAllPermissions()).thenReturn(List.of());

        mockMvc.perform(get("/api/admin/permissions")
                        .with(user("staff-p2").roles("OPERATOR")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));
    }

    @Test
    @DisplayName("权限审计 - 商户员工无 system:manage 访问 /api/admin/notification-rules ⇒ 403（改前放行）")
    void permissionAudit_notificationRules_withoutSystemManage_denied() throws Exception {
        when(roleService.getUserPermissions(any())).thenReturn(List.of("dashboard:view"));

        mockMvc.perform(get("/api/admin/notification-rules")
                        .with(user("staff-n1").roles("OPERATOR")))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error.details[0].message").value("system:manage"));

        verify(notificationRuleService, never()).queryRules(anyLong(), anyLong(), any(), any());
    }

    @Test
    @DisplayName("权限审计 - 商户员工持 system:manage 访问 /api/admin/notification-rules ⇒ 200")
    void permissionAudit_notificationRules_withSystemManage_allowed() throws Exception {
        when(roleService.getUserPermissions(any())).thenReturn(List.of("system:manage"));
        when(notificationRuleService.queryRules(anyLong(), anyLong(), any(), any()))
                .thenReturn(PageResponse.<com.migao.admin.dto.NotificationRuleDTO>of(0L, 1L, 20L, List.of()));

        mockMvc.perform(get("/api/admin/notification-rules")
                        .with(user("staff-n2").roles("OPERATOR")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));
    }

    @Test
    @DisplayName("权限审计 - 商户员工无 system:manage 访问 /api/admin/notification-templates ⇒ 403（改前放行）")
    void permissionAudit_notificationTemplates_withoutSystemManage_denied() throws Exception {
        when(roleService.getUserPermissions(any())).thenReturn(List.of("dashboard:view"));

        mockMvc.perform(get("/api/admin/notification-templates")
                        .with(user("staff-t1").roles("OPERATOR")))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error.details[0].message").value("system:manage"));

        verify(notificationTemplateService, never()).queryTemplates(anyLong(), anyLong(), any());
    }

    @Test
    @DisplayName("权限审计 - 商户员工持 system:manage 访问 /api/admin/notification-templates ⇒ 200")
    void permissionAudit_notificationTemplates_withSystemManage_allowed() throws Exception {
        when(roleService.getUserPermissions(any())).thenReturn(List.of("system:manage"));
        when(notificationTemplateService.queryTemplates(anyLong(), anyLong(), any()))
                .thenReturn(PageResponse.<com.migao.admin.dto.NotificationTemplateDTO>of(0L, 1L, 20L, List.of()));

        mockMvc.perform(get("/api/admin/notification-templates")
                        .with(user("staff-t2").roles("OPERATOR")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));
    }

    // ======================== 工人端拒绝集合预留（#4716 设计 C11 / issue #4727）========================

    @Test
    @DisplayName("权限审计 - worker 身份访问 /api/admin/** 一律 403（含此前无注解的 user/info 与 menus）")
    void permissionAudit_workerRole_cannotEnterAdminApi() throws Exception {
        // 承重两条：这两个端点在 #4727 之前**没有任何 @RequirePermission** ⇒
        // 拒绝集合不含 worker 时它们会落到业务层并返回 200（本用例红）。
        mockMvc.perform(get("/api/admin/user/info").with(user("worker-1").roles("WORKER")))
                .andExpect(status().isForbidden());
        mockMvc.perform(get("/api/admin/menus").with(user("worker-1").roles("WORKER")))
                .andExpect(status().isForbidden());
        // 已有注解的端点：拒绝必须发生在**门禁**而不是业务层
        mockMvc.perform(get("/api/admin/products").with(user("worker-1").roles("WORKER")))
                .andExpect(status().isForbidden());

        verify(roleService, never()).getUserPermissions(anyString());
    }

    // ======================== 反向护栏（issue #4727 红线）：C 端可达性一字不变 ========================
    // 红线：误给 customer/agent 端点加 @RequirePermission = 线上故障（C 端能力被砍）。
    // 每条都必须是「改前 200；误加注解 ⇒ 403 ⇒ 必红」。

    @Test
    @DisplayName("反向护栏 - customer 身份仍可达 /api/customer/agent-sessions/**（误加注解 ⇒ 必红）")
    void reverseGuard_customerCanStillReachCustomerAgentSessions() throws Exception {
        SecurityUser customer = securityUser("customer-1", 1L, "customer");
        when(agentSessionService.getSessionByAiSessionId(eq("ai-1"), eq("customer-1")))
                .thenReturn(AgentSessionDetailResponse.builder()
                        .id("as-1").aiSessionId("ai-1").status("active").messages(List.of()).build());
        when(agentSessionService.sendMessage(eq("as-1"), eq("customer"), eq("customer-1"), anyString(), anyBoolean()))
                .thenReturn(AgentMessage.builder()
                        .id("m-1").sessionId("as-1").senderType("customer").senderId("customer-1")
                        .contentType("text").content("你好").build());

        mockMvc.perform(get("/api/customer/agent-sessions/by-ai/ai-1")
                        .with(authentication(authOf(customer))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.id").value("as-1"));

        mockMvc.perform(post("/api/customer/agent-sessions/as-1/messages")
                        .with(authentication(authOf(customer)))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"content\":\"你好\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.content").value("你好"));

        // C 端路径**不得**进入权限码校验（误加注解 ⇒ 403 + 本断言红）
        verify(roleService, never()).getUserPermissions(anyString());
    }

    @Test
    @DisplayName("反向护栏 - customer/agent 身份仍可达 /api/auth/me（误加注解 ⇒ 必红）")
    void reverseGuard_customerAndAgentCanStillReachAuthMe() throws Exception {
        for (String role : List.of("customer", "agent")) {
            mockMvc.perform(get("/api/auth/me")
                            .with(authentication(authOf(securityUser(role + "-1", 1L, role)))))
                    .andExpect(status().isOk());
        }
        verify(roleService, never()).getUserPermissions(anyString());
    }

    @Test
    @DisplayName("反向护栏 - C 端驱动的内部服务路径仍可达：转人工站内信 + 写审计上报（误加注解 ⇒ 必红）")
    void reverseGuard_customerDrivenInternalServicePathsStillWork() throws Exception {
        // human_handoff（allowed_roles=["customer"]）与写审计上报都走 X-Service-Token + C 端 X-User-Id
        when(userMapper.selectById("customer-9")).thenReturn(staffUser("customer-9", 1L, "customer", "active"));

        mockMvc.perform(post("/api/admin/notifications")
                        .header("X-Service-Token", SERVICE_SECRET)
                        .header("X-Tenant-Id", "1")
                        .header("X-User-Id", "customer-9")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"recipientId\":\"staff-1\",\"recipientType\":\"employee\",\"title\":\"转人工\",\"content\":\"有新工单\"}"))
                .andExpect(status().isOk());

        mockMvc.perform(post("/api/admin/agent/audit-logs")
                        .header("X-Service-Token", SERVICE_SECRET)
                        .header("X-Tenant-Id", "1")
                        .header("X-User-Id", "customer-9")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"action\":\"create\",\"resourceType\":\"order\",\"toolName\":\"order_create\"}"))
                .andExpect(status().isOk());

        // C 端身份不引入细粒度查询（与 serviceToken_customerXUserId_keepsLegacyServiceBypass 同口径）
        verify(roleService, never()).getUserPermissions(anyString());
    }

    @Test
    @DisplayName("反向护栏 - 零权限商户员工仍可达 /api/admin/user/info 与 /api/admin/menus（误加注解 ⇒ 必红）")
    void reverseGuard_zeroPermissionStaffCanStillReachSelfInfoAndMenuTree() throws Exception {
        when(userMapper.selectById("staff-zero")).thenReturn(staffUser("staff-zero", 1L, "operator", "active"));
        when(roleService.getUserRoleCodes("staff-zero")).thenReturn(List.of("operator"));
        when(roleService.getUserPermissions("staff-zero")).thenReturn(List.of());

        // 自助首屏：任何商户员工（哪怕零权限）都必须能拿到自己的角色/权限/菜单
        mockMvc.perform(get("/api/admin/user/info")
                        .with(authentication(authOf(securityUser("staff-zero", 1L, "operator")))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));

        // 权限码目录树：静态常量，是「员工管理」页勾选树的唯一来源
        mockMvc.perform(get("/api/admin/menus")
                        .with(authentication(authOf(securityUser("staff-zero", 1L, "operator")))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data").isArray());
    }

    @Test
    @DisplayName("反向护栏 - C 端/公开端点控制器类级不得有 @RequirePermission（误加 ⇒ 必红）")
    void reverseGuard_cEndControllersMustNotDeclareClassLevelPermission() {
        for (Class<?> type : List.of(CustomerAgentSessionController.class, AuthController.class, SmsController.class)) {
            assertNull(type.getAnnotation(RequirePermission.class),
                    type.getSimpleName() + " 是 C 端/公开端点控制器：类级 @RequirePermission 会砍掉 C 端可达性"
                            + "（issue #4727 红线）；确需收窄请用**方法级**注解");
        }
    }

    // ======================== 完整上下文加载：工人会话链不得成环（issue #4770，P0 热修）========================
    // 线上形态（服务器实测 `docker logs migao-deploy-admin-api-1`）：
    //   APPLICATION FAILED TO START — The dependencies of some of the beans in the application context form a cycle:
    //   securityConfig → workerSessionFilter → workerSessionService → securityConfig
    //   （`Requested bean is currently in creation`）⇒ admin-api 每次启动都崩 ⇒ nginx 502。
    //
    // 逐参数链（构造参数下标；@RequiredArgsConstructor 按字段声明顺序）：
    //   SecurityConfig[2]=workerSessionFilter → WorkerSessionFilter[1]=workerSessionService
    //   → WorkerSessionService[2]=passwordEncoder → **SecurityConfig 里的 @Bean passwordEncoder()** ⇒ 成环。
    //
    // 破环方式 = **结构性**：把 passwordEncoder @Bean 挪到 PasswordEncoderConfig ⇒ 依赖单向化
    // （SecurityConfig → WorkerSessionFilter → WorkerSessionService → PasswordEncoderConfig）。

    /**
     * 上下文加载判据：工人会话链**真实装配**且**不成环**。
     *
     * <p><b>为什么本类此前没红</b>（#4770 要求核清并修，不是只加一条新测试）：本类曾
     * {@code @MockBean WorkerSessionService} ⇒ 环上那条边被 mock 切断 ⇒ 环在本上下文里
     * **根本不存在** ⇒ 上下文当然起得来。该 {@code @MockBean} 已删除。</p>
     *
     * <p><b>红证</b>：把 {@code PasswordEncoder} 的 @Bean 挪回 {@code SecurityConfig}
     * ⇒ 本类**整个上下文起不来**（本类**全部**用例 error），报错与线上逐字同形
     * （{@code form a cycle} / {@code Requested bean is currently in creation}）。</p>
     */
    @Test
    @DisplayName("🔴 上下文加载 - 工人会话链真实装配且不成环（SecurityConfig→WorkerSessionFilter→WorkerSessionService→PasswordEncoder）")
    void contextLoads_workerSessionChainIsReallyWired() {
        // ① 环上三个 bean 必须是**真身**：任一被 @MockBean 顶替 ⇒ 环被切断 ⇒ 本判据失去承重能力 ⇒ 红。
        //    这是「防旧漏检形态复发」的护栏（#4770 的漏检正是 @MockBean WorkerSessionService）。
        for (Object bean : List.<Object>of(workerSessionService, workerSessionFilter, passwordEncoder)) {
            assertFalse(mockingDetails(bean).isMock(),
                    bean.getClass().getName() + " 被 mock 顶替 ⇒ 工人会话链的环被切断 ⇒ "
                            + "本上下文加载判据不再承重（issue #4770 的漏检形态）");
        }

        // ② 承重判据：环上那条**回流边**真的由容器解析过 —— WorkerSessionService 持有的
        //    PasswordEncoder 就是容器里那一个。（@Transactional ⇒ 先取目标对象再读私有字段；
        //    显式落成 Object 局部变量：否则 ReflectionTestUtils.getField 会走 (Class,String) 重载。）
        Object workerSessionServiceTarget = AopTestUtils.getTargetObject(workerSessionService);
        assertSame(passwordEncoder,
                ReflectionTestUtils.getField(workerSessionServiceTarget, "passwordEncoder"),
                "WorkerSessionService 的 PasswordEncoder 必须来自容器 —— 这条边就是线上成环的那条边");

        // ③ 结构性收口：环的**成因**不得复发 —— SecurityConfig 不得再声明 PasswordEncoder @Bean。
        //    一旦挪回，本上下文立即启动失败（报错与线上同形），本断言是「挪回」的静态判据。
        for (java.lang.reflect.Method method : SecurityConfig.class.getDeclaredMethods()) {
            assertFalse(method.isAnnotationPresent(Bean.class)
                            && PasswordEncoder.class.equals(method.getReturnType()),
                    "SecurityConfig 不得声明 PasswordEncoder @Bean（issue #4770）：本类构造期依赖 "
                            + "WorkerSessionFilter ⇒ 立即复现启动期环。它属于 PasswordEncoderConfig。");
        }
    }

    /** 构造带业务身份的认证（C 端 customer/agent 的主体是 {@link SecurityUser}，不是 Spring 的 User）。 */
    private static SecurityUser securityUser(String userId, Long tenantId, String... roles) {
        List<String> roleList = List.of(roles);
        List<SimpleGrantedAuthority> authorities = roleList.stream()
                .map(r -> new SimpleGrantedAuthority("ROLE_" + r.toUpperCase(Locale.ROOT)))
                .toList();
        return new SecurityUser(userId, tenantId, userId, roleList, authorities);
    }

    private static Authentication authOf(SecurityUser securityUser) {
        return new UsernamePasswordAuthenticationToken(
                securityUser, null, securityUser.getAuthorities());
    }
}
