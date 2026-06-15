package com.migao.admin.security;

import com.aliyun.oss.OSS;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.controller.AuthController;
import com.migao.admin.controller.ProductController;
import com.migao.admin.dto.LoginRequest;
import com.migao.admin.dto.LoginResponse;
import com.migao.admin.service.AuthService;
import com.migao.admin.service.ProductService;
import com.fasterxml.jackson.databind.ObjectMapper;
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
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
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

    @MockBean
    private AuthService authService;

    @MockBean
    private ProductService productService;

    @MockBean
    private com.migao.admin.service.RegistrationService registrationService;

    @MockBean
    private com.migao.admin.service.UserService userService;

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

    @MockBean
    private com.migao.admin.service.NotificationService notificationService;

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
    private com.migao.admin.service.QuickReplyTemplateService quickReplyTemplateService;

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
    private com.migao.admin.mapper.KnowledgeChunkMapper knowledgeChunkMapper;
    @MockBean
    private com.migao.admin.mapper.KnowledgeDocumentMapper knowledgeDocumentMapper;
    @MockBean
    private com.migao.admin.mapper.KnowledgeSyncHistoryMapper knowledgeSyncHistoryMapper;
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
    private com.migao.admin.mapper.ProductProcessingItemMapper productProcessingItemMapper;
    @MockBean
    private com.migao.admin.mapper.QuickReplyTemplateMapper quickReplyTemplateMapper;
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
    private com.migao.admin.mapper.UserRoleMapper userRoleMapper;
    @MockBean
    private com.migao.admin.mapper.TenantApplicationMapper tenantApplicationMapper;

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
}
