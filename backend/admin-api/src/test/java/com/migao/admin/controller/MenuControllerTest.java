package com.migao.admin.controller;

// case_ids: PG-021

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
                .andExpect(jsonPath("$.data.length()").value(9));   // 8 组 + 生产管理（issue #4203/#4205）
    }

    @Test
    @DisplayName("菜单树包含预期的顶级节点: dashboard, orders, products, agent, employees, customers, finance, settings")
    void topLevelKeys() throws Exception {
        mockMvc.perform(get("/api/admin/menus"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[?(@.code=='dashboard')]").exists())
                .andExpect(jsonPath("$.data[?(@.code=='orders')]").exists())
                .andExpect(jsonPath("$.data[?(@.code=='products')]").exists())
                .andExpect(jsonPath("$.data[?(@.code=='agent')]").exists())
                .andExpect(jsonPath("$.data[?(@.code=='employees')]").exists())
                .andExpect(jsonPath("$.data[?(@.code=='customers')]").exists())
                .andExpect(jsonPath("$.data[?(@.code=='finance')]").exists())
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

    @Test
    @DisplayName("生产管理组：生产看板/工序库/计件工资 三节点，权限码统一 processing:manage（issue #4203/#4205）")
    void productionGroupIsExposedWithUnifiedPermissionCode() throws Exception {
        String body = mockMvc.perform(get("/api/admin/menus"))
                .andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString(java.nio.charset.StandardCharsets.UTF_8);

        // 用 DOM 真值逐字段断言（jsonPath 的过滤表达式对「单元素结果是否解包」语义不稳，
        // 同族踩坑见 #4186：判「页面含某文案」不能用 innerText，要看结构真值）
        com.fasterxml.jackson.databind.JsonNode production = null;
        for (com.fasterxml.jackson.databind.JsonNode node : objectMapper.readTree(body).path("data")) {
            if ("production".equals(node.path("code").asText())) {
                production = node;
            }
        }
        org.junit.jupiter.api.Assertions.assertNotNull(production, "菜单树缺少「生产管理」组");
        org.junit.jupiter.api.Assertions.assertEquals("生产管理", production.path("label").asText());

        java.util.List<String> childLabels = new java.util.ArrayList<>();
        java.util.List<String> childCodes = new java.util.ArrayList<>();
        production.path("children").forEach(child -> {
            childLabels.add(child.path("label").asText());
            childCodes.add(child.path("code").asText());
        });
        // 四节点（issue #4308 新增「工艺路线」= 路线/信号/工序写面的用户面入口）。
        // 精确断言（不是 contains）：漏加菜单项 ⇒ 岗位权限页勾得动、侧边栏看不到（#4203 同族坑）。
        org.junit.jupiter.api.Assertions.assertEquals(
                java.util.List.of("生产看板", "工序库", "计件工资", "工艺路线"), childLabels);
        // 四节点共用同一权限码：岗位权限页勾一处 = 整组可见（与 menu.ts / AuthService 同构）
        org.junit.jupiter.api.Assertions.assertEquals(
                java.util.List.of("processing:manage", "processing:manage", "processing:manage",
                        "processing:manage"), childCodes);
    }
}
