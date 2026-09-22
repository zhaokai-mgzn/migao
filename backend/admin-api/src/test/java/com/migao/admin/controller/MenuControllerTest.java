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
    @DisplayName("生产管理组：生产看板/工艺配置/计件工资 + 入库单（issue #4203/#4205/#4440/#5045）")
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
        // 五节点（issue #4416 把「工序库」+「工艺路线」合并为「工艺配置」；issue #5045 新增「入库单」；
        // issue #5177 新增「池看板」；issue #4440 把本树同步到前端 IA）。
        // 精确断言（不是 contains）：漏加菜单项 ⇒ 岗位权限页勾得动、侧边栏看不到（#4203 同族坑）。
        org.junit.jupiter.api.Assertions.assertEquals(
                // issue #4440：节点名与前端 config/menu.ts 同步 —— 「工序库」+「工艺路线」
                // 已由 issue #4416 合并为单入口「工艺配置」⇒ 服务端与前端**必须同构**
                // （本树被前端「岗位权限」页消费）。
                // issue #5177：「池看板」(/production/pool) 插在「生产看板」之后 —— 它是池化派单的
                // **决策屏**，与「生产看板」同权（processing:manage），三处同构见下一个断言。
                java.util.List.of("生产看板", "池看板", "工艺配置", "计件工资", "入库单"), childLabels);
        // 加工三项共用 processing:manage（岗位权限页勾一处 = 那三项可见）；
        // 「入库单」是**仓储**动作、权限码独立为 inbound:view（issue #5045）——
        // 并进 processing:manage 会让「有 inbound:view、没有 processing:manage」的仓管看不到菜单。
        // 本断言与 frontend/admin-web/src/config/menu.ts、AuthService.buildMenusByPermissions 三处同构。
        // ⚠️ issue #4440：本列表与上面的 childLabels 是**同一组节点的两个字段**，必须**同时改**——
        // 只改一处就造出「节点数 4 / 权限码 5」的自相矛盾（本 PR 首轮 CI 实测：labels 已改、codes 漏改
        // ⇒ admin-api unit tests 判红 expected 5 vs actual 4）。
        org.junit.jupiter.api.Assertions.assertEquals(
                java.util.List.of("processing:manage", "processing:manage", "processing:manage",
                        "processing:manage", "inbound:view"), childCodes);
    }
}
