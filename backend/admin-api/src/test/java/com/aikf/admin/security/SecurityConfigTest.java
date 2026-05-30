package com.aikf.admin.security;

import com.aikf.admin.config.GlobalExceptionHandler;
import com.aikf.admin.controller.AuthController;
import com.aikf.admin.controller.ProductController;
import com.aikf.admin.dto.LoginRequest;
import com.aikf.admin.dto.LoginResponse;
import com.aikf.admin.service.AuthService;
import com.aikf.admin.service.ProductService;
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
    private com.aikf.admin.service.RegistrationService registrationService;

    @MockBean
    private com.aikf.admin.service.UserService userService;

    @MockBean
    private com.aikf.admin.service.AfterSalesTicketService afterSalesTicketService;

    @MockBean
    private com.aikf.admin.service.AgentEmployeeService agentEmployeeService;

    @MockBean
    private com.aikf.admin.service.AgentSessionService agentSessionService;

    @MockBean
    private com.aikf.admin.service.AuditLogService auditLogService;

    @MockBean
    private com.aikf.admin.service.CategoryService categoryService;

    @MockBean
    private com.aikf.admin.service.CustomerService customerService;

    @MockBean
    private com.aikf.admin.service.NotificationService notificationService;

    @MockBean
    private com.aikf.admin.service.OrderService orderService;

    @MockBean
    private com.aikf.admin.service.OrderLogisticsService orderLogisticsService;

    // 注意：FileStorageService 是接口，LocalFileStorageService 已默认启用，
    // OssService 带有 @ConditionalOnBean 在测试环境下不会被加载，
    // 因此不需要 @MockBean FileStorageService / OssService，
    // 避免由于多个实现导致 NoUniqueBeanDefinitionException。

    @MockBean
    private com.aikf.admin.service.PermissionService permissionService;

    @MockBean
    private com.aikf.admin.service.ProcessingCategoryService processingCategoryService;

    @MockBean
    private com.aikf.admin.service.ProcessingItemService processingItemService;

    @MockBean
    private com.aikf.admin.service.QuickReplyTemplateService quickReplyTemplateService;

    @MockBean
    private com.aikf.admin.service.RoleService roleService;

    @MockBean
    private com.aikf.admin.service.SmsService smsService;

    @MockBean
    private com.aikf.admin.service.WechatService wechatService;

    @MockBean
    private StringRedisTemplate redisTemplate;

    // 注意：UserService 已实现 UserDetailsService，上面的 @MockBean userService 会同时
    // 满足 UserService 和 UserDetailsService 两种类型的依赖注入需求，
    // 因此不再重复声明 UserDetailsService 的 @MockBean，避免覆盖后导致
    // UserService 类型不可被装配。

    // Mock all mapper beans that @MapperScan might try to create
    @MockBean
    private com.aikf.admin.mapper.AfterSalesTicketMapper afterSalesTicketMapper;
    @MockBean
    private com.aikf.admin.mapper.AgentEmployeeMapper agentEmployeeMapper;
    @MockBean
    private com.aikf.admin.mapper.AgentMessageMapper agentMessageMapper;
    @MockBean
    private com.aikf.admin.mapper.AgentSessionMapper agentSessionMapper;
    @MockBean
    private com.aikf.admin.mapper.AuditLogMapper auditLogMapper;
    @MockBean
    private com.aikf.admin.mapper.CategoryMapper categoryMapper;
    @MockBean
    private com.aikf.admin.mapper.CustomerProfileMapper customerProfileMapper;
    @MockBean
    private com.aikf.admin.mapper.CustomerSegmentMapper customerSegmentMapper;
    @MockBean
    private com.aikf.admin.mapper.CustomerSegmentMemberMapper customerSegmentMemberMapper;
    @MockBean
    private com.aikf.admin.mapper.CustomerTagMapper customerTagMapper;
    @MockBean
    private com.aikf.admin.mapper.KnowledgeChunkMapper knowledgeChunkMapper;
    @MockBean
    private com.aikf.admin.mapper.KnowledgeDocumentMapper knowledgeDocumentMapper;
    @MockBean
    private com.aikf.admin.mapper.KnowledgeSyncHistoryMapper knowledgeSyncHistoryMapper;
    @MockBean
    private com.aikf.admin.mapper.NotificationMapper notificationMapper;
    @MockBean
    private com.aikf.admin.mapper.NotificationRuleMapper notificationRuleMapper;
    @MockBean
    private com.aikf.admin.mapper.NotificationTemplateMapper notificationTemplateMapper;
    @MockBean
    private com.aikf.admin.mapper.OrderItemMapper orderItemMapper;
    @MockBean
    private com.aikf.admin.mapper.OrderLogisticsMapper orderLogisticsMapper;
    @MockBean
    private com.aikf.admin.mapper.OrderMapper orderMapper;
    @MockBean
    private com.aikf.admin.mapper.PermissionMapper permissionMapper;
    @MockBean
    private com.aikf.admin.mapper.ProcessingCategoryMapper processingCategoryMapper;
    @MockBean
    private com.aikf.admin.mapper.ProcessingItemMapper processingItemMapper;
    @MockBean
    private com.aikf.admin.mapper.ProductMapper productMapper;
    @MockBean
    private com.aikf.admin.mapper.ProductColorMapper productColorMapper;
    @MockBean
    private com.aikf.admin.mapper.ProductSkuMapper productSkuMapper;
    @MockBean
    private com.aikf.admin.mapper.QuickReplyTemplateMapper quickReplyTemplateMapper;
    @MockBean
    private com.aikf.admin.mapper.RoleMapper roleMapper;
    @MockBean
    private com.aikf.admin.mapper.SessionMapper sessionMapper;
    @MockBean
    private com.aikf.admin.mapper.SessionMessageMapper sessionMessageMapper;
    @MockBean
    private com.aikf.admin.mapper.TenantAiConfigMapper tenantAiConfigMapper;
    @MockBean
    private com.aikf.admin.mapper.TenantAppMapper tenantAppMapper;
    @MockBean
    private com.aikf.admin.mapper.TenantMapper tenantMapper;
    @MockBean
    private com.aikf.admin.mapper.TicketNoteMapper ticketNoteMapper;
    @MockBean
    private com.aikf.admin.mapper.TicketTimelineMapper ticketTimelineMapper;
    @MockBean
    private com.aikf.admin.mapper.UserIdentityMapper userIdentityMapper;
    @MockBean
    private com.aikf.admin.mapper.UserMapper userMapper;
    @MockBean
    private com.aikf.admin.mapper.UserRoleMapper userRoleMapper;
    @MockBean
    private com.aikf.admin.mapper.TenantApplicationMapper tenantApplicationMapper;

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

        when(authService.adminLogin(any(LoginRequest.class), any()))
                .thenReturn(loginResponse);

        LoginRequest request = new LoginRequest();
        request.setUsername("admin");
        request.setPassword("password");
        request.setTenantId(1L);

        // When & Then: 登录接口应返回 200
        mockMvc.perform(post("/api/auth/admin/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.accessToken").value("mock-token"));
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
