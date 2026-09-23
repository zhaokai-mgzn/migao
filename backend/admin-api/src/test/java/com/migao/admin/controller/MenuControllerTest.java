package com.migao.admin.controller;

// case_ids: PG-021

import com.migao.admin.config.GlobalExceptionHandler;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * MenuController 单元测试
 *
 * <p>验证权限勾选树（{@code GET /api/admin/menus}）与 issue #5271 的新 IA **逐值同构**。
 * 真值源 = {@code frontend/admin-web/src/config/menu.ts}（组 key / 组名 / 组顺序 / 组内菜单项名），
 * 三源同构判据 = tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py。</p>
 *
 * <p>强度口径（#4440 教训）：**每个组的 label 列表与 code 列表都做精确断言**（不是 contains），
 * 顶层组的 key 与顺序也精确断言 —— 「节点数 N / 权限码 M」这类自相矛盾必须在这里被钉死
 * （#4440 实测过：labels 改了 codes 漏改 ⇒ 才是真回归）。</p>
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

    /** #5271 新 IA 的顶层组 key（顺序即真值 = 前端 `menuGroups` 顺序）。 */
    private static final List<String> GROUP_KEYS = List.of(
            "workspace", "smart-customer-service", "product-center", "trade-center",
            "production-center", "inventory-center", "org-center");

    /** 顶层组名（与 GROUP_KEYS 同序）。 */
    private static final List<String> GROUP_LABELS = List.of(
            "工作台", "智能客服", "商品与加工项", "交易管理", "生产管理", "仓储与物料", "组织管理");

    /** #5271 的 20 个菜单项名（一项不少不减；「通知中心」是一级独立项、不在本权限树内）。 */
    private static final List<String> MENU_ITEM_LABELS = List.of(
            "经营看板", "每日简报", "在线接待", "知识库", "商品列表", "加工项管理",
            "订单列表", "售后工单", "客户列表", "财务对账",
            "生产看板", "池看板", "工艺配置", "计件工资",
            "入库单", "余料台账", "省料看板", "员工管理", "岗位权限", "企业基础信息");

    /** 动作码节点（非菜单项）4 个，**统一追加在组尾**：product:create / product:category / order:detail / employee:create。 */
    private static final List<String> ACTION_NODE_LABELS = List.of(
            "新增商品", "商品分类管理", "订单详情", "新增员工");

    /**
     * 拉取菜单树 DOM —— jsonPath 的过滤表达式对「单元素结果是否解包」语义不稳，
     * 故逐字段断言一律走 DOM 真值（同族踩坑见 #4186）。
     */
    private JsonNode fetchTree() throws Exception {
        String body = mockMvc.perform(get("/api/admin/menus"))
                .andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString(StandardCharsets.UTF_8);
        return objectMapper.readTree(body).path("data");
    }

    private static List<String> codes(Iterable<JsonNode> nodes) {
        List<String> out = new ArrayList<>();
        nodes.forEach(n -> out.add(n.path("code").asText()));
        return out;
    }

    private static List<String> labels(Iterable<JsonNode> nodes) {
        List<String> out = new ArrayList<>();
        nodes.forEach(n -> out.add(n.path("label").asText()));
        return out;
    }

    /** 取指定组 key 的节点（找不到 ⇒ 报错并附实得 key 列表，避免后续断言假绿）。 */
    private static JsonNode group(JsonNode tree, String key) {
        for (JsonNode node : tree) {
            if (key.equals(node.path("code").asText())) {
                return node;
            }
        }
        throw new AssertionError("菜单树缺少组 key = " + key + "（实得 = " + codes(tree) + "）");
    }

    /** 全树所有子节点（用于「一项不少不减」/「重复节点」这类**跨组**判据）。 */
    private static List<JsonNode> allChildren(JsonNode tree) {
        List<JsonNode> out = new ArrayList<>();
        tree.forEach(g -> g.path("children").forEach(out::add));
        return out;
    }

    @Test
    @DisplayName("GET /api/admin/menus — 返回完整菜单树 -> 200")
    void returnsMenuTree() throws Exception {
        mockMvc.perform(get("/api/admin/menus"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data").isArray())
                // issue #5271：七大组（旧树是 9 个顶层条目）。组数变化必须在这里显式改判，不许静默
                //（净结果 = 「客户管理组消失」+「工作台由独立项变组」）。
                .andExpect(jsonPath("$.data.length()").value(7));
    }

    @Test
    @DisplayName("#5271 新 IA：七个顶层组的 key 与组名按 menu.ts 顺序逐值一致")
    void topLevelGroupsMirrorFrontendOrder() throws Exception {
        JsonNode tree = fetchTree();
        assertEquals(GROUP_KEYS, codes(tree), "顶层组 key / 顺序与前端 config/menu.ts 的 menuGroups 不一致");
        assertEquals(GROUP_LABELS, labels(tree), "顶层组名 / 顺序与前端 config/menu.ts 的 menuGroups 不一致");
    }

    @Test
    @DisplayName("工作台组：经营看板 + 每日简报（同码 dashboard:view，企业开关不在服务端过滤）")
    void workspaceGroupMirrorsMenuTs() throws Exception {
        JsonNode workspace = group(fetchTree(), "workspace");
        assertEquals("工作台", workspace.path("label").asText());
        assertEquals(List.of("经营看板", "每日简报"), labels(workspace.path("children")));
        assertEquals(List.of("dashboard:view", "dashboard:view"), codes(workspace.path("children")));
    }

    @Test
    @DisplayName("智能客服组：在线接待 + 知识库（旧「会话监控」节点已删除）")
    void smartCustomerServiceGroupMirrorsMenuTs() throws Exception {
        JsonNode cs = group(fetchTree(), "smart-customer-service");
        assertEquals("智能客服", cs.path("label").asText());
        assertEquals(List.of("在线接待", "知识库"), labels(cs.path("children")));
        // issue #5246（已合入 main）：知识库节点码 = 读码 knowledge:view
        assertEquals(List.of("agent:session", "knowledge:view"), codes(cs.path("children")));
    }

    @Test
    @DisplayName("商品与加工项组：导航项（商品列表/加工项管理）+ 组尾动作码（新增商品/商品分类管理）")
    void productCenterGroupMirrorsMenuTs() throws Exception {
        JsonNode products = group(fetchTree(), "product-center");
        assertEquals("商品与加工项", products.path("label").asText());
        // 顺序：导航项（= menu.ts 该组逐字顺序）在前，动作码节点**统一追加在组尾**
        assertEquals(List.of("商品列表", "加工项管理", "新增商品", "商品分类管理"),
                labels(products.path("children")));
        assertEquals(List.of("product:list", "processing:manage", "product:create", "product:category"),
                codes(products.path("children")));
    }

    @Test
    @DisplayName("交易管理组：订单列表/售后工单/客户列表/财务对账 + 组尾动作码（订单详情）（客户管理组并入）")
    void tradeCenterGroupMirrorsMenuTs() throws Exception {
        JsonNode trade = group(fetchTree(), "trade-center");
        assertEquals("交易管理", trade.path("label").asText());
        assertEquals(List.of("订单列表", "售后工单", "客户列表", "财务对账", "订单详情"),
                labels(trade.path("children")));
        // issue #5246（已合入 main）：售后工单节点码 = 读码 after_sales:view（原写码 order:refund）
        assertEquals(List.of("order:list", "after_sales:view", "customer:view", "finance:view", "order:detail"),
                codes(trade.path("children")));
    }

    @Test
    @DisplayName("生产管理组：生产看板/池看板/工艺配置/计件工资（四项同码 processing:manage，物料三项已拆出）")
    void productionCenterGroupMirrorsMenuTs() throws Exception {
        JsonNode production = group(fetchTree(), "production-center");
        assertEquals("生产管理", production.path("label").asText());
        assertEquals(List.of("生产看板", "池看板", "工艺配置", "计件工资"),
                labels(production.path("children")));
        assertEquals(List.of("processing:manage", "processing:manage",
                "processing:manage", "processing:manage"), codes(production.path("children")));
    }

    @Test
    @DisplayName("仓储与物料组（#5271 新组）：入库单(inbound:view) + 余料台账 + 省料看板")
    void inventoryCenterGroupMirrorsMenuTs() throws Exception {
        JsonNode inventory = group(fetchTree(), "inventory-center");
        assertEquals("仓储与物料", inventory.path("label").asText());
        assertEquals(List.of("入库单", "余料台账", "省料看板"), labels(inventory.path("children")));
        // 入库单是**仓储**动作、权限码独立为 inbound:view —— 并进 processing:manage 会让
        // 「有 inbound:view、没有 processing:manage」的仓管看不到菜单（#4203 点名的同族坑）。
        assertEquals(List.of("inbound:view", "processing:manage", "processing:manage"),
                codes(inventory.path("children")));
    }

    @Test
    @DisplayName("组织管理组：员工管理/岗位权限/企业基础信息 + 组尾动作码（新增员工）")
    void orgCenterGroupMirrorsMenuTs() throws Exception {
        JsonNode org = group(fetchTree(), "org-center");
        assertEquals("组织管理", org.path("label").asText());
        assertEquals(List.of("员工管理", "岗位权限", "企业基础信息", "新增员工"),
                labels(org.path("children")));
        assertEquals(List.of("employee:list", "system:manage", "system:manage", "employee:create"),
                codes(org.path("children")));
    }

    @Test
    @DisplayName("旧顶层组（dashboard/orders/products/employees/customers/finance/settings/agent/production）不再存在")
    void legacyTopLevelGroupsAreGone() throws Exception {
        List<String> topKeys = codes(fetchTree());
        for (String legacy : List.of("dashboard", "orders", "products", "employees", "customers",
                "finance", "settings", "agent", "production", "customer-center")) {
            assertFalse(topKeys.contains(legacy),
                    "旧顶层组 `" + legacy + "` 仍在菜单树里（#5271 已并入七大组）—— 实得 = " + topKeys);
        }
    }

    @Test
    @DisplayName("agent:session 只出现一次（= 在线接待）；旧「会话监控」节点不得复活")
    void sessionMonitorNodeIsRemoved() throws Exception {
        List<JsonNode> children = allChildren(fetchTree());
        assertFalse(labels(children).stream().anyMatch("会话监控"::equals),
                "旧节点「会话监控」复活了（agent:session 已由「在线接待」承载，"
                        + "页面 /agent-workspace/sessions 从来不在侧边栏里）");
        assertEquals(1, children.stream().filter(c -> "agent:session".equals(c.path("code").asText())).count(),
                "agent:session 在权限树上必须**恰好一处**（重复节点 = 员工权限页上的重复勾选项）");
    }

    @Test
    @DisplayName("菜单项一项不少不减（20 项各恰好一次）+ 4 个动作码节点（合计 24 节点）")
    void everyMenuItemAppearsExactlyOnce() throws Exception {
        List<String> all = labels(allChildren(fetchTree()));
        for (String name : MENU_ITEM_LABELS) {
            assertEquals(1, all.stream().filter(name::equals).count(),
                    "菜单项「" + name + "」在权限树上的出现次数不是 1（实得全表 = " + all + "）");
        }
        for (String action : ACTION_NODE_LABELS) {
            assertEquals(1, all.stream().filter(action::equals).count(),
                    "动作码节点「" + action + "」缺失或重复（实得全表 = " + all + "）");
        }
        assertEquals(MENU_ITEM_LABELS.size() + ACTION_NODE_LABELS.size(), all.size(),
                "权限树节点总数 = 20 菜单项 + 4 动作码节点（实得全表 = " + all + "）");
    }

    @Test
    @DisplayName("多次调用返回一致结果（幂等）")
    void idempotent() throws Exception {
        var result1 = mockMvc.perform(get("/api/admin/menus")).andReturn();
        var result2 = mockMvc.perform(get("/api/admin/menus")).andReturn();
        // 两次调用 data 部分应一致（忽略 requestId/timestamp）
        var data1 = objectMapper.readTree(result1.getResponse().getContentAsString()).get("data");
        var data2 = objectMapper.readTree(result2.getResponse().getContentAsString()).get("data");
        assertEquals(data1, data2);
    }
}