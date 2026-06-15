package com.migao.admin.controller;

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.entity.Permission;
import com.migao.admin.service.PermissionService;
import com.fasterxml.jackson.databind.ObjectMapper;
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

import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * AdminPermissionController 单元测试
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("AdminPermissionController 权限查询测试")
class AdminPermissionControllerTest {

    private MockMvc mockMvc;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private PermissionService permissionService;

    @InjectMocks
    private AdminPermissionController adminPermissionController;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(adminPermissionController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @Test
    @DisplayName("查询所有权限 → 200 返回列表")
    void getPermissions_returnsList() throws Exception {
        Permission p1 = new Permission();
        p1.setCode("product:list");
        p1.setName("商品列表");
        Permission p2 = new Permission();
        p2.setCode("order:list");
        p2.setName("订单列表");
        when(permissionService.getAllPermissions()).thenReturn(List.of(p1, p2));

        mockMvc.perform(get("/api/admin/permissions"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data").isArray())
                .andExpect(jsonPath("$.data.length()").value(2));
    }

    @Test
    @DisplayName("查询所有权限 → 空列表返回 200")
    void getPermissions_emptyList() throws Exception {
        when(permissionService.getAllPermissions()).thenReturn(List.of());

        mockMvc.perform(get("/api/admin/permissions"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data").isArray())
                .andExpect(jsonPath("$.data.length()").value(0));
    }
}
