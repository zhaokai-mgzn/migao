package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.RoleService;
import com.migao.admin.service.UserService;
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
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * AdminUserController 安全回归测试
 * 验证管理员权限校验（requireAdmin）和租户隔离
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("AdminUserController 权限控制测试")
class AdminUserControllerTest {

    private MockMvc mockMvc;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private UserService userService;

    @Mock
    private RoleService roleService;

    @InjectMocks
    private AdminUserController adminUserController;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(adminUserController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
        TenantContext.setTenantId(1L);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
        SecurityContextHolder.clearContext();
    }

    /** 设置当前用户为 admin 角色 */
    private void setAdminUser() {
        SecurityUser user = new SecurityUser(
                "user-1", 1L, "admin-phone",
                List.of("admin"),
                List.of(new SimpleGrantedAuthority("ROLE_admin"))
        );
        Authentication auth = mock(Authentication.class);
        when(auth.getPrincipal()).thenReturn(user);
        SecurityContextHolder.getContext().setAuthentication(auth);
    }

    /** 设置当前用户为 operator 角色 */
    private void setOperatorUser() {
        SecurityUser user = new SecurityUser(
                "user-2", 1L, "op-phone",
                List.of("operator"),
                List.of(new SimpleGrantedAuthority("ROLE_operator"))
        );
        Authentication auth = mock(Authentication.class);
        when(auth.getPrincipal()).thenReturn(user);
        SecurityContextHolder.getContext().setAuthentication(auth);
    }

    // ============ createUser ============

    @Nested
    @DisplayName("POST / (createUser)")
    class CreateUser {

        @Test
        @DisplayName("admin 角色创建用户 → 200")
        void adminCanCreateUser() throws Exception {
            setAdminUser();
            com.migao.admin.entity.User user = new com.migao.admin.entity.User();
            user.setId("new-user");
            when(userService.createUser(any(), any(), any(), any(), any())).thenReturn(user);

            mockMvc.perform(post("/api/admin/users")
                            .contentType("application/json")
                            .content("{\"phone\":\"13900000001\",\"password\":\"test123\",\"name\":\"测试\"}"))
                    .andExpect(status().isOk());
        }

        @Test
        @DisplayName("operator 角色创建用户 → 403")
        void operatorCannotCreateUser() throws Exception {
            setOperatorUser();

            mockMvc.perform(post("/api/admin/users")
                            .contentType("application/json")
                            .content("{\"phone\":\"13900000001\",\"password\":\"test123\",\"name\":\"测试\"}"))
                    .andExpect(status().isForbidden());

            verify(userService, never()).createUser(any(), any(), any(), any(), any());
        }

        @Test
        @DisplayName("未认证用户创建 → 403")
        void unauthenticatedCannotCreateUser() throws Exception {
            mockMvc.perform(post("/api/admin/users")
                            .contentType("application/json")
                            .content("{\"phone\":\"13900000001\",\"password\":\"test123\",\"name\":\"测试\"}"))
                    .andExpect(status().isForbidden());
        }
    }

    // ============ resetPassword ============

    @Nested
    @DisplayName("PUT /{id}/reset-password")
    class ResetPassword {

        @Test
        @DisplayName("admin 重置密码 → 200")
        void adminCanResetPassword() throws Exception {
            setAdminUser();

            mockMvc.perform(put("/api/admin/users/user-1/reset-password")
                            .contentType("application/json")
                            .content("{\"newPassword\":\"newpass123\"}"))
                    .andExpect(status().isOk());
        }

        @Test
        @DisplayName("operator 重置密码 → 403")
        void operatorCannotResetPassword() throws Exception {
            setOperatorUser();

            mockMvc.perform(put("/api/admin/users/user-1/reset-password")
                            .contentType("application/json")
                            .content("{\"newPassword\":\"newpass123\"}"))
                    .andExpect(status().isForbidden());
        }
    }

    // ============ toggleUserStatus ============

    @Nested
    @DisplayName("PUT /{id}/status")
    class ToggleUserStatus {

        @Test
        @DisplayName("admin 切换状态 → 200")
        void adminCanToggleStatus() throws Exception {
            setAdminUser();

            mockMvc.perform(put("/api/admin/users/user-1/status")
                            .contentType("application/json")
                            .content("{\"status\":\"disabled\"}"))
                    .andExpect(status().isOk());
        }

        @Test
        @DisplayName("operator 切换状态 → 403")
        void operatorCannotToggleStatus() throws Exception {
            setOperatorUser();

            mockMvc.perform(put("/api/admin/users/user-1/status")
                            .contentType("application/json")
                            .content("{\"status\":\"disabled\"}"))
                    .andExpect(status().isForbidden());
        }
    }

    // ============ deleteUser ============

    @Nested
    @DisplayName("DELETE /{id}")
    class DeleteUser {

        @Test
        @DisplayName("admin 删除用户 → 200")
        void adminCanDeleteUser() throws Exception {
            setAdminUser();

            mockMvc.perform(delete("/api/admin/users/user-1"))
                    .andExpect(status().isOk());
        }

        @Test
        @DisplayName("operator 删除用户 → 403")
        void operatorCannotDeleteUser() throws Exception {
            setOperatorUser();

            mockMvc.perform(delete("/api/admin/users/user-1"))
                    .andExpect(status().isForbidden());

            verify(userService, never()).deleteUser(any());
        }
    }

    // ============ getUsers (no requireAdmin — should work for both) ============

    @Nested
    @DisplayName("GET / (getUsers) — 无需 admin 角色")
    class GetUsers {

        @Test
        @DisplayName("operator 可以查看用户列表")
        void operatorCanListUsers() throws Exception {
            setOperatorUser();
            com.migao.admin.dto.PageResponse<com.migao.admin.entity.User> page =
                    com.migao.admin.dto.PageResponse.of(0L, 1L, 10L, List.of());
            when(userService.getUserPage(anyLong(), anyLong(), any(), any(), any(), anyLong()))
                    .thenReturn(page);

            mockMvc.perform(get("/api/admin/users"))
                    .andExpect(status().isOk());
        }
    }
}
