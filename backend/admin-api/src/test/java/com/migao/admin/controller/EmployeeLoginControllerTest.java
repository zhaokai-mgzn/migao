// case_ids: AU-003
package com.migao.admin.controller;

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantDomainResolver;
import com.migao.admin.dto.LoginResponse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.AuthService;
import com.migao.admin.service.MiniPhoneBindService;
import com.migao.admin.support.LoginIdentifiers;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * {@code POST /api/auth/employee/login} 端点契约测试（issue #5485 AU-003）。
 *
 * <p>钉的是**响应形状与反枚举出口**：成功时 {@code data.user.mustChangePassword} 必须在响应里
 * （前端靠它决定是否跳改密页）；失败时无论哪种病因都是同一 401 + 同一 error.code / 文案。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("AuthController - 员工登录端点")
class EmployeeLoginControllerTest {

    private MockMvc mockMvc;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private AuthService authService;
    @Mock
    private MiniPhoneBindService miniPhoneBindService;
    @Mock
    private TenantDomainResolver tenantDomainResolver;

    @InjectMocks
    private AuthController authController;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(authController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    private String body(String identifier, String password) throws Exception {
        return objectMapper.writeValueAsString(java.util.Map.of("identifier", identifier, "password", password));
    }

    @Test
    @DisplayName("AU-001/AU-003 员工登录成功：透传 identifier 给 service，响应含 mustChangePassword")
    void employeeLogin_success() throws Exception {
        LoginResponse response = LoginResponse.builder()
                .accessToken("employee-access")
                .expiresIn(7200L)
                .user(LoginResponse.UserInfo.builder()
                        .id("user-A").nickname("张三").role("operator").identityType("employee")
                        .roles(List.of("operator")).tenantId(1L).mustChangePassword(true)
                        .build())
                .build();
        when(authService.loginByEmployee(eq("zhangsan@acme"), eq("secret123"), any(HttpServletResponse.class)))
                .thenReturn(response);

        mockMvc.perform(post("/api/auth/employee/login")
                        .contentType("application/json")
                        .content(body("zhangsan@acme", "secret123")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.accessToken").value("employee-access"))
                .andExpect(jsonPath("$.data.user.identityType").value("employee"))
                .andExpect(jsonPath("$.data.user.mustChangePassword").value(true))
                // 审计 07 P1-5 口径不回退：refresh token 只经 HttpOnly cookie，不进响应体
                .andExpect(jsonPath("$.data.refreshToken").doesNotExist());

        verify(authService).loginByEmployee(eq("zhangsan@acme"), eq("secret123"), any(HttpServletResponse.class));
    }

    @Test
    @DisplayName("AU-003 三种病因（企业编码不存在/用户名不存在/密码错）在端点层也是同一 401 同一文案")
    void employeeLogin_failures_areIndistinguishable() throws Exception {
        when(authService.loginByEmployee(any(), any(), any(HttpServletResponse.class)))
                .thenThrow(BusinessException.authFailed(LoginIdentifiers.AUTH_FAILED_MESSAGE));

        for (String identifier : new String[]{"zhangsan@nosuch", "nobody@acme", "zhangsan@acme"}) {
            mockMvc.perform(post("/api/auth/employee/login")
                            .contentType("application/json")
                            .content(body(identifier, "whatever1")))
                    .andExpect(status().isUnauthorized())
                    .andExpect(jsonPath("$.success").value(false))
                    .andExpect(jsonPath("$.error.code").value("AUTH_FAILED"))
                    .andExpect(jsonPath("$.error.message").value("账号或密码错误"));
        }
    }

    @Test
    @DisplayName("AU-003 标识/密码为空 ⇒ 4xx 且**不进业务层**（参数校验，不泄露任何账号信息）")
    void employeeLogin_blankFields_rejectedBeforeService() throws Exception {
        mockMvc.perform(post("/api/auth/employee/login")
                        .contentType("application/json")
                        .content("{\"identifier\":\"\",\"password\":\"\"}"))
                .andExpect(status().is4xxClientError());

        verify(authService, never()).loginByEmployee(any(), any(), any(HttpServletResponse.class));
    }
}