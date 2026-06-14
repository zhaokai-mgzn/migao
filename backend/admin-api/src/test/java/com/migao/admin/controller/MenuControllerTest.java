package com.migao.admin.controller;

import com.migao.admin.config.GlobalExceptionHandler;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * MenuController 单元测试
 * 验证返回静态菜单树结构的正确性
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("MenuController 菜单接口测试")
class MenuControllerTest {

    private MockMvc mockMvc;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @InjectMocks
    private MenuController menuController;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(menuController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @Test
    @DisplayName("GET /api/admin/menus — 返回完整菜单树 -> 200")
    void returnsMenuTree() throws Exception {
        mockMvc.perform(get("/api/admin/menus"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data").isArray())
                .andExpect(jsonPath("$.data.length()").value(6));
    }

    @Test
    @DisplayName("菜单树包含预期的顶级节点: dashboard, orders, products, agent, employees, settings")
    void topLevelKeys() throws Exception {
        mockMvc.perform(get("/api/admin/menus"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[?(@.code=='dashboard')]").exists())
                .andExpect(jsonPath("$.data[?(@.code=='orders')]").exists())
                .andExpect(jsonPath("$.data[?(@.code=='products')]").exists())
                .andExpect(jsonPath("$.data[?(@.code=='agent')]").exists())
                .andExpect(jsonPath("$.data[?(@.code=='employees')]").exists())
                .andExpect(jsonPath("$.data[?(@.code=='settings')]").exists());
    }

    @Test
    @DisplayName("订单管理节点包含子菜单")
    void ordersHasChildren() throws Exception {
        mockMvc.perform(get("/api/admin/menus"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[?(@.code=='orders')].children").isArray())
                .andExpect(jsonPath("$.data[?(@.code=='orders')].children.length()").value(3));
    }

    @Test
    @DisplayName("商品管理节点包含4个子菜单")
    void productsHasFourChildren() throws Exception {
        mockMvc.perform(get("/api/admin/menus"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[?(@.code=='products')].children.length()").value(4));
    }

    @Test
    @DisplayName("员工管理节点包含子菜单")
    void employeesHasChildren() throws Exception {
        mockMvc.perform(get("/api/admin/menus"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[?(@.code=='employees')].children.length()").value(2));
    }

    @Test
    @DisplayName("多次调用返回一致结果（幂等）")
    void idempotent() throws Exception {
        var result1 = mockMvc.perform(get("/api/admin/menus")).andReturn();
        var result2 = mockMvc.perform(get("/api/admin/menus")).andReturn();
        // 两次调用 data 部分应一致（忽略 requestId/timestamp）
        var data1 = objectMapper.readTree(result1.getResponse().getContentAsString()).get("data");
        var data2 = objectMapper.readTree(result2.getResponse().getContentAsString()).get("data");
        org.junit.jupiter.api.Assertions.assertEquals(data1, data2);
    }
}
