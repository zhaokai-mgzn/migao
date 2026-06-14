package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.Role;
import com.migao.admin.service.RoleService;
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
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * AdminRoleController 单元测试
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("AdminRoleController 角色管理测试")
class AdminRoleControllerTest {

    private MockMvc mockMvc;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private RoleService roleService;

    @InjectMocks
    private AdminRoleController adminRoleController;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(1L);
        mockMvc = MockMvcBuilders.standaloneSetup(adminRoleController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Nested
    @DisplayName("GET /api/admin/roles")
    class GetRoles {

        @Test
        @DisplayName("分页查询角色列表 -> 200")
        void getRolesPaginated() throws Exception {
            PageResponse<Role> page = new PageResponse<>();
            page.setItems(List.of());
            page.setTotal(0L);
            when(roleService.getRolePage(anyLong(), anyLong(), any())).thenReturn(page);

            mockMvc.perform(get("/api/admin/roles"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.items").isArray());
        }

        @Test
        @DisplayName("支持 keyword 过滤 -> 200")
        void keywordFilter() throws Exception {
            when(roleService.getRolePage(anyLong(), anyLong(), any())).thenReturn(new PageResponse<>());

            mockMvc.perform(get("/api/admin/roles").param("keyword", "admin"))
                    .andExpect(status().isOk());
        }
    }

    @Nested
    @DisplayName("GET /api/admin/roles/all")
    class GetAllRoles {

        @Test
        @DisplayName("返回所有角色 -> 200")
        void getAllRoles() throws Exception {
            when(roleService.getAllRoles(any())).thenReturn(List.of());

            mockMvc.perform(get("/api/admin/roles/all"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data").isArray());
        }
    }

    @Nested
    @DisplayName("GET /api/admin/roles/{id}")
    class GetRole {

        @Test
        @DisplayName("查询单个角色 -> 200")
        void getRoleById() throws Exception {
            Role role = new Role();
            role.setId(1L);
            role.setName("admin");
            role.setCode("admin");
            when(roleService.getRoleById(anyLong(), anyLong())).thenReturn(role);

            mockMvc.perform(get("/api/admin/roles/1"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.name").value("admin"));
        }
    }

    @Nested
    @DisplayName("POST /api/admin/roles")
    class CreateRole {

        @Test
        @DisplayName("创建角色 -> 200")
        void createRole() throws Exception {
            Role role = new Role();
            role.setId(2L);
            role.setName("operator");
            when(roleService.createRole(anyLong(), any())).thenReturn(role);

            Map<String, Object> body = Map.of("name", "operator", "code", "op", "permissionIds", List.of(1, 2));

            mockMvc.perform(post("/api/admin/roles")
                            .contentType("application/json")
                            .content(objectMapper.writeValueAsString(body)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true));
        }
    }

    @Nested
    @DisplayName("PUT /api/admin/roles/{id}")
    class UpdateRole {

        @Test
        @DisplayName("更新角色 -> 200")
        void updateRole() throws Exception {
            doNothing().when(roleService).updateRole(anyLong(), anyLong(), any());

            Map<String, Object> body = Map.of("name", "updated");

            mockMvc.perform(put("/api/admin/roles/1")
                            .contentType("application/json")
                            .content(objectMapper.writeValueAsString(body)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true));
        }
    }

    @Nested
    @DisplayName("DELETE /api/admin/roles/{id}")
    class DeleteRole {

        @Test
        @DisplayName("删除角色 -> 200")
        void deleteRole() throws Exception {
            doNothing().when(roleService).deleteRole(anyLong(), anyLong());

            mockMvc.perform(delete("/api/admin/roles/1"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true));
        }
    }
}
