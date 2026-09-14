// case_ids: HR-001, HR-002, HR-003, HR-004
package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.entity.Role;
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
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * AdminUserController 安全回归测试
 * 验证管理员权限校验（requireAdmin）和租户隔离
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
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
            when(userService.createUser(any(), any(), any(), any(), any(), any(), any())).thenReturn(user);

            mockMvc.perform(post("/api/admin/users")
                            .contentType("application/json")
                            .content("{\"phone\":\"13900000001\",\"password\":\"test123\",\"name\":\"测试\"}"))
                    .andExpect(status().isOk());
        }

        @Test
        @DisplayName("operator 创建用户 → 200（细粒度权限已上移至 PermissionInterceptor，集成层见 SecurityConfigTest）")
        void operatorCanCreateUser() throws Exception {
            setOperatorUser();
            when(userService.createUser(any(), any(), any(), any(), any(), any(), any()))
                    .thenReturn(new com.migao.admin.entity.User());

            mockMvc.perform(post("/api/admin/users")
                            .contentType("application/json")
                            .content("{\"phone\":\"13900000001\",\"password\":\"test123\",\"name\":\"测试\"}"))
                    .andExpect(status().isOk());

            verify(userService, times(1)).createUser(any(), any(), any(), any(), any(), any(), any());
        }
    }

    // ============ updateUser ============

    /**
     * 回归防线（issue #3550）：ai-agent 的 employee_manage 与 admin-web 员工编辑都下发
     * `phone` / `roleIds`，但 updateUser 原先只读 name/avatar/role/position/password/permissions
     * → 两个字段被 Jackson 静默忽略 → HTTP 200 + 「更新成功」= 假成功（库里角色/手机号未变）。
     */
    @Nested
    @DisplayName("PUT /{id} (updateUser)")
    class UpdateUser {

        private com.migao.admin.entity.User existingUser() {
            com.migao.admin.entity.User u = new com.migao.admin.entity.User();
            u.setId("user-1");
            u.setTenantId(1L);
            u.setNickname("张三");
            u.setRole("operator");
            return u;
        }

        private Role roleWithCode(String code) {
            Role role = new Role();
            role.setId("role-" + code);
            role.setCode(code);
            return role;
        }

        @Test
        @DisplayName("下发 phone → 手机号进入更新实参（不再被静默丢弃）")
        void phoneIsForwardedToUpdate() throws Exception {
            setAdminUser();
            when(userService.updateUser(any(), any(), any(), any(), any(), any(), any()))
                    .thenReturn(existingUser());

            mockMvc.perform(put("/api/admin/users/user-1")
                            .contentType("application/json")
                            .content("{\"name\":\"张三\",\"phone\":\"13900000002\"}"))
                    .andExpect(status().isOk());

            verify(userService).updateUser(eq("user-1"), eq("张三"), nullable(String.class), nullable(String.class),
                    nullable(String.class), nullable(String.class), eq("13900000002"));
        }

        @Test
        @DisplayName("下发 roleIds（角色表主键）→ 解析为角色 code 并进入更新实参")
        void roleIdsIsResolvedToRoleCode() throws Exception {
            setAdminUser();
            when(roleService.getRoleById("role-manager")).thenReturn(roleWithCode("manager"));
            when(userService.updateUser(any(), any(), any(), any(), any(), any(), any()))
                    .thenReturn(existingUser());

            mockMvc.perform(put("/api/admin/users/user-1")
                            .contentType("application/json")
                            .content("{\"roleIds\":[\"role-manager\"]}"))
                    .andExpect(status().isOk());

            verify(userService).updateUser(eq("user-1"), nullable(String.class), nullable(String.class), eq("manager"),
                    nullable(String.class), nullable(String.class), nullable(String.class));
        }

        @Test
        @DisplayName("未显式传 role/roleIds 时仍按 position 解析岗位角色（#2969 不回归）")
        void positionFallbackStillWorksWhenNoRoleProvided() throws Exception {
            setAdminUser();
            when(roleService.getRoleByPosition("客服主管", 1L)).thenReturn(roleWithCode("manager"));
            when(userService.updateUser(any(), any(), any(), any(), any(), any(), any()))
                    .thenReturn(existingUser());

            mockMvc.perform(put("/api/admin/users/user-1")
                            .contentType("application/json")
                            .content("{\"position\":\"客服主管\"}"))
                    .andExpect(status().isOk());

            verify(userService).updateUser(eq("user-1"), nullable(String.class), nullable(String.class), eq("manager"),
                    eq("客服主管"), nullable(String.class), nullable(String.class));
        }

        @Test
        @DisplayName("显式 role 优先于 roleIds（与 createUser 口径一致）")
        void explicitRoleWinsOverRoleIds() throws Exception {
            setAdminUser();
            when(userService.updateUser(any(), any(), any(), any(), any(), any(), any()))
                    .thenReturn(existingUser());

            mockMvc.perform(put("/api/admin/users/user-1")
                            .contentType("application/json")
                            .content("{\"role\":\"admin\",\"roleIds\":[\"role-manager\"]}"))
                    .andExpect(status().isOk());

            verify(userService).updateUser(eq("user-1"), nullable(String.class), nullable(String.class), eq("admin"),
                    nullable(String.class), nullable(String.class), nullable(String.class));
            verify(roleService, never()).getRoleById(any());
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
        @DisplayName("operator 重置密码 → 200（细粒度权限已上移至 PermissionInterceptor，集成层见 SecurityConfigTest）")
        void operatorCanResetPassword() throws Exception {
            setOperatorUser();

            mockMvc.perform(put("/api/admin/users/user-1/reset-password")
                            .contentType("application/json")
                            .content("{\"newPassword\":\"newpass123\"}"))
                    .andExpect(status().isOk());
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
        @DisplayName("operator 切换状态 → 200（细粒度权限已上移至 PermissionInterceptor，集成层见 SecurityConfigTest）")
        void operatorCanToggleStatus() throws Exception {
            setOperatorUser();

            mockMvc.perform(put("/api/admin/users/user-1/status")
                            .contentType("application/json")
                            .content("{\"status\":\"disabled\"}"))
                    .andExpect(status().isOk());
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
        @DisplayName("operator 删除用户 → 200（细粒度权限已上移至 PermissionInterceptor，集成层见 SecurityConfigTest）")
        void operatorCanDeleteUser() throws Exception {
            setOperatorUser();

            mockMvc.perform(delete("/api/admin/users/user-1"))
                    .andExpect(status().isOk());

            verify(userService, times(1)).deleteUser(any());
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
