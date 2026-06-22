package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.entity.AuditLog;
import com.migao.admin.entity.Tenant;
import com.migao.admin.entity.TenantAiConfig;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.TenantAiConfigMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.AuditLogService;
import com.migao.admin.dto.PageResponse;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * SettingsController 单元测试
 * 验证系统设置、AI配置、密码修改、登录日志接口
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("SettingsController 设置接口测试")
class SettingsControllerTest {

    private MockMvc mockMvc;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private TenantMapper tenantMapper;

    @Mock
    private TenantAiConfigMapper tenantAiConfigMapper;

    @Mock
    private AuditLogService auditLogService;

    @Mock
    private UserMapper userMapper;

    @Mock
    private PasswordEncoder passwordEncoder;

    @InjectMocks
    private SettingsController settingsController;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(1L);
        mockMvc = MockMvcBuilders.standaloneSetup(settingsController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
        SecurityContextHolder.clearContext();
    }

    @Nested
    @DisplayName("GET /api/admin/settings")
    class GetSettings {

        @Test
        @DisplayName("租户存在 -> 200 返回设置信息")
        void tenantExists_returnsSettings() throws Exception {
            Tenant tenant = new Tenant();
            tenant.setId(1L);
            tenant.setName("测试租户");
            tenant.setCode("test");
            tenant.setIndustry("布艺");
            tenant.setStatus("active");
            when(tenantMapper.selectById(1L)).thenReturn(tenant);

            mockMvc.perform(get("/api/admin/settings"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.name").value("测试租户"))
                    .andExpect(jsonPath("$.data.industry").value("布艺"));
        }

        @Test
        @DisplayName("租户不存在 -> 404")
        void tenantNotFound_throws404() throws Exception {
            when(tenantMapper.selectById(1L)).thenReturn(null);

            mockMvc.perform(get("/api/admin/settings"))
                    .andExpect(status().isNotFound())
                    .andExpect(jsonPath("$.success").value(false));
        }
    }

    @Nested
    @DisplayName("PUT /api/admin/settings")
    class UpdateSettings {

        @Test
        @DisplayName("更新租户名称 -> 200 返回更新后信息")
        void updateName_returnsUpdated() throws Exception {
            Tenant tenant = new Tenant();
            tenant.setId(1L);
            tenant.setName("旧名称");
            tenant.setCode("test");
            tenant.setIndustry("布艺");
            when(tenantMapper.selectById(1L)).thenReturn(tenant);
            when(tenantMapper.updateById(any(Tenant.class))).thenReturn(1);

            Map<String, Object> body = Map.of("name", "新名称");

            mockMvc.perform(put("/api/admin/settings")
                            .contentType("application/json")
                            .content(objectMapper.writeValueAsString(body)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.name").value("新名称"));
        }

        @Test
        @DisplayName("租户不存在 -> 404")
        void tenantNotFound_throws404() throws Exception {
            when(tenantMapper.selectById(1L)).thenReturn(null);

            Map<String, Object> body = Map.of("name", "新名称");

            mockMvc.perform(put("/api/admin/settings")
                            .contentType("application/json")
                            .content(objectMapper.writeValueAsString(body)))
                    .andExpect(status().isNotFound());
        }

        @Test
        @DisplayName("通过 companyName 更新名称 -> 200")
        void updateCompanyName_returnsUpdated() throws Exception {
            Tenant tenant = new Tenant();
            tenant.setId(1L);
            tenant.setName("旧名称");
            tenant.setCode("test");
            tenant.setIndustry("布艺");
            when(tenantMapper.selectById(1L)).thenReturn(tenant);
            when(tenantMapper.updateById(any(Tenant.class))).thenReturn(1);

            Map<String, Object> body = Map.of("companyName", "新公司名");

            mockMvc.perform(put("/api/admin/settings")
                            .contentType("application/json")
                            .content(objectMapper.writeValueAsString(body)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.name").value("新公司名"))
                    .andExpect(jsonPath("$.data.companyName").value("新公司名"));
        }

        @Test
        @DisplayName("更新行业 -> 200")
        void updateIndustry_returnsUpdated() throws Exception {
            Tenant tenant = new Tenant();
            tenant.setId(1L);
            tenant.setName("测试租户");
            tenant.setCode("test");
            tenant.setIndustry("旧行业");
            when(tenantMapper.selectById(1L)).thenReturn(tenant);
            when(tenantMapper.updateById(any(Tenant.class))).thenReturn(1);

            Map<String, Object> body = Map.of("industry", "皮革");

            mockMvc.perform(put("/api/admin/settings")
                            .contentType("application/json")
                            .content(objectMapper.writeValueAsString(body)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.industry").value("皮革"));
        }
    }

    @Nested
    @DisplayName("GET /api/admin/tenant/ai-config")
    class GetAiConfig {

        @Test
        @DisplayName("AI配置存在 -> 200")
        void configExists_returnsConfig() throws Exception {
            TenantAiConfig config = TenantAiConfig.builder()
                    .tenantId(1L)
                    .botName("小布")
                    .greetingTemplate("你好")
                    .build();
            when(tenantAiConfigMapper.selectOne(any())).thenReturn(config);

            mockMvc.perform(get("/api/admin/tenant/ai-config"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.botName").value("小布"));
        }

        @Test
        @DisplayName("AI配置不存在 -> 200 返回默认空配置")
        void configNotExists_returnsDefault() throws Exception {
            when(tenantAiConfigMapper.selectOne(any())).thenReturn(null);

            mockMvc.perform(get("/api/admin/tenant/ai-config"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.tenantId").value(1));
        }
    }

    @Nested
    @DisplayName("PUT /api/admin/tenant/ai-config")
    class UpdateAiConfig {

        @Test
        @DisplayName("配置不存在，插入新配置 -> 200")
        void configNotExists_insertsNew() throws Exception {
            when(tenantAiConfigMapper.selectOne(any())).thenReturn(null);
            when(tenantAiConfigMapper.insert(any(TenantAiConfig.class))).thenReturn(1);

            TenantAiConfig body = TenantAiConfig.builder()
                    .botName("小布")
                    .greetingTemplate("你好，欢迎光临")
                    .build();

            mockMvc.perform(put("/api/admin/tenant/ai-config")
                            .contentType("application/json")
                            .content(objectMapper.writeValueAsString(body)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.botName").value("小布"));
        }

        @Test
        @DisplayName("配置已存在，更新字段 -> 200")
        void configExists_updates() throws Exception {
            TenantAiConfig existing = TenantAiConfig.builder()
                    .id("cfg-1")
                    .tenantId(1L)
                    .botName("旧名称")
                    .greetingTemplate("旧问候")
                    .build();
            when(tenantAiConfigMapper.selectOne(any())).thenReturn(existing);
            when(tenantAiConfigMapper.updateById(any(TenantAiConfig.class))).thenReturn(1);

            TenantAiConfig body = TenantAiConfig.builder()
                    .botName("新小布")
                    .greetingTemplate("新问候语")
                    .afterHoursMode("offline_reply")
                    .build();

            mockMvc.perform(put("/api/admin/tenant/ai-config")
                            .contentType("application/json")
                            .content(objectMapper.writeValueAsString(body)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.botName").value("新小布"));
        }

        @Test
        @DisplayName("更新布尔和整数字段 -> 200")
        void updateBooleanAndIntegerFields() throws Exception {
            TenantAiConfig existing = TenantAiConfig.builder()
                    .id("cfg-2")
                    .tenantId(1L)
                    .emotionHandoff(false)
                    .aiFallbackThreshold(3)
                    .build();
            when(tenantAiConfigMapper.selectOne(any())).thenReturn(existing);
            when(tenantAiConfigMapper.updateById(any(TenantAiConfig.class))).thenReturn(1);

            TenantAiConfig body = TenantAiConfig.builder()
                    .emotionHandoff(true)
                    .aiFallbackThreshold(5)
                    .build();

            mockMvc.perform(put("/api/admin/tenant/ai-config")
                            .contentType("application/json")
                            .content(objectMapper.writeValueAsString(body)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true));
        }
    }

    @Nested
    @DisplayName("PUT /api/admin/settings/password")
    class ChangePassword {

        @Test
        @DisplayName("未登录 -> 401")
        void notAuthenticated_throws401() throws Exception {
            // SecurityContext is empty by default

            Map<String, String> body = Map.of("oldPassword", "old", "newPassword", "new");

            mockMvc.perform(put("/api/admin/settings/password")
                            .contentType("application/json")
                            .content(objectMapper.writeValueAsString(body)))
                    .andExpect(status().isUnauthorized())
                    .andExpect(jsonPath("$.success").value(false));
        }

        @Test
        @DisplayName("用户已登录，旧密码正确 -> 200")
        void validPasswordChange_returns200() throws Exception {
            // 设置认证上下文
            setAuthenticatedUser();

            com.migao.admin.entity.User user = new com.migao.admin.entity.User();
            user.setId("user-1");
            user.setPasswordHash("hashed_old");
            when(userMapper.selectById("user-1")).thenReturn(user);
            when(passwordEncoder.matches("old", "hashed_old")).thenReturn(true);
            when(passwordEncoder.encode("new")).thenReturn("hashed_new");
            when(userMapper.updateById(any(com.migao.admin.entity.User.class))).thenReturn(1);

            Map<String, String> body = Map.of("oldPassword", "old", "newPassword", "new");

            mockMvc.perform(put("/api/admin/settings/password")
                            .contentType("application/json")
                            .content(objectMapper.writeValueAsString(body)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true));
        }

        @Test
        @DisplayName("旧密码错误 -> 400")
        void wrongOldPassword_throws400() throws Exception {
            setAuthenticatedUser();

            com.migao.admin.entity.User user = new com.migao.admin.entity.User();
            user.setId("user-1");
            user.setPasswordHash("hashed_old");
            when(userMapper.selectById("user-1")).thenReturn(user);
            when(passwordEncoder.matches("wrong", "hashed_old")).thenReturn(false);

            Map<String, String> body = Map.of("oldPassword", "wrong", "newPassword", "new");

            mockMvc.perform(put("/api/admin/settings/password")
                            .contentType("application/json")
                            .content(objectMapper.writeValueAsString(body)))
                    .andExpect(status().is(422))
                    .andExpect(jsonPath("$.success").value(false));
        }

        @Test
        @DisplayName("用户不存在 -> 404")
        void userNotFound_throws404() throws Exception {
            setAuthenticatedUser();

            when(userMapper.selectById("user-1")).thenReturn(null);

            Map<String, String> body = Map.of("oldPassword", "old", "newPassword", "new");

            mockMvc.perform(put("/api/admin/settings/password")
                            .contentType("application/json")
                            .content(objectMapper.writeValueAsString(body)))
                    .andExpect(status().isNotFound())
                    .andExpect(jsonPath("$.success").value(false));
        }
    }

    @Nested
    @DisplayName("GET /api/admin/settings/login-logs")
    class GetLoginLogs {

        @Test
        @DisplayName("返回登录日志分页 -> 200")
        void returnLoginLogs() throws Exception {
            PageResponse<AuditLog> pageResponse = new PageResponse<>();
            pageResponse.setItems(List.of());
            pageResponse.setTotal(0L);
            pageResponse.setPage(1L);
            pageResponse.setSize(10L);
            when(auditLogService.getAuditLogPage(anyLong(), anyLong(), any(), any(), any(), any(), any(), any()))
                    .thenReturn(pageResponse);

            mockMvc.perform(get("/api/admin/settings/login-logs"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.items").isArray());
        }

        @Test
        @DisplayName("指定页码和每页大小 -> 200")
        void paginatedLoginLogs() throws Exception {
            PageResponse<AuditLog> pageResponse = new PageResponse<>();
            pageResponse.setItems(List.of());
            pageResponse.setTotal(50L);
            pageResponse.setPage(2L);
            pageResponse.setSize(20L);
            when(auditLogService.getAuditLogPage(eq(2L), eq(20L), any(), any(), any(), any(), any(), any()))
                    .thenReturn(pageResponse);

            mockMvc.perform(get("/api/admin/settings/login-logs")
                            .param("page", "2")
                            .param("size", "20"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.page").value(2))
                    .andExpect(jsonPath("$.data.size").value(20));
        }
    }

    private void setAuthenticatedUser() {
        SecurityUser securityUser = new SecurityUser(
                "user-1", 1L, "13800000000",
                List.of("admin"),
                List.of(new SimpleGrantedAuthority("ROLE_admin"))
        );
        Authentication auth = mock(Authentication.class);
        when(auth.getPrincipal()).thenReturn(securityUser);
        SecurityContextHolder.getContext().setAuthentication(auth);
    }
}
