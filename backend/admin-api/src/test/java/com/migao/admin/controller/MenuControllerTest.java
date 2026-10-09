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

    /** #5271 新 IA 的顶层**组** key（顺序即真值 = 前端 `menuGroups` 顺序）。
     *  2026-09-29（issue #5778）：七组 → **六组**（`smart-customer-service` → `customer-service`；
     *  `product-center` 撤销）—— 另有一个**顶层一级项**（商品管理）不在本表（它不是组，
     *  见 `topLevelStandaloneItemMirrorsFrontend`）。 */
    private static final List<String> GROUP_KEYS = List.of(
            "workspace", "customer-service", "trade-center",
            "production-center", "inventory-center", "org-center");

    /** 顶层组名（与 GROUP_KEYS 同序）。 */
    private static final List<String> GROUP_LABELS = List.of(
            "工作台", "客户服务", "交易管理", "生产管理", "仓储与物料", "组织管理");

    /** #5778 的 **23 个菜单项名**（一项不少不减；「通知中心」是一级独立项、不在本权限树内）。
     *  ⚠️ #6404：菜单项 21 → 22（+「库存明细」`/stock-ledger`）。
     *  ⚠️ #6573：菜单项 22 → 23（+顶层一级项「参数总览」`/settings/params`，取既有读码 `production:view`）。
     *  ⚠️ 含两个顶层一级项「商品管理」「参数总览」（它们不属于任何组，但仍是菜单项）。
     *  🔴 2026-10-06（issue #6457，用户裁定方案 A1）：**顺序重排**（项数不变）——
     *  客户服务组「接待与工具 → 售后 → 档案」、生产管理组「先备资料 → 再生产」、
     *  仓储组「单据（进 → 账 → 出）→ 台账 → 分析」，且一级项「商品管理」沉到**所有分组之后**。 */
    private static final List<String> MENU_ITEM_LABELS = List.of(
            "经营看板", "每日简报",
            "在线接待", "知识库", "售后工单", "客户列表",
            "订单列表", "财务对账",
            // 🔴 2026-10-09（issue #6580，用户裁定「移除加工项管理和工艺配置这两个菜单」）：
            // 「加工项管理」「工艺配置」两个菜单项已移除（功能体并入「企业基础设置」页内的配置域）。
            "生产看板", "智能派单", "计件工资",
            "入库单", "库存明细", "发货单", "余料台账", "省料看板",
            "员工管理", "岗位权限",
            // 组内的**权限码节点**（无 path、不是菜单项）：只为让经营域的码仍可授予
            "企业基础设置（经营域）",
            "商品管理",
            // 顶层一级项（由组织管理组升上来，席位即原「参数总览」）
            "企业基础设置");

    /** 动作码节点（非菜单项）2 个，**统一追加在组尾**：order:detail / employee:create。
     *  🔴 2026-09-29（#5778）：原 4 个 → **2 个** —— 「新增商品」/「商品分类管理」两个节点原挂在
     *  已撤销的 `product-center` 组下，组撤销后它们在权限树上**无处安放** ⇒ 同批删除
     *（权限码本身仍在权限目录里，删的是「菜单树上有这两个勾选项」这一事实）。 */
    private static final List<String> ACTION_NODE_LABELS = List.of(
            "订单详情", "新增员工");

    /** 顶层**一级项**名（`children` 为空、直接跳转的那些，**不属于任何组**）。
     *  🔴 #6580 起两个：商品管理 / 企业基础设置（原「参数总览」的席位）—— 它们不参与
     *  `allChildren` 的组内计数，由 `topLevelStandaloneItems` 单独断言（避免两处都算它们 ⇒ 重复计数）。 */
    private static final List<String> TOP_LEVEL_STANDALONE_LABELS = List.of("商品管理", "企业基础设置");

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

    /**
     * 顶层**组**（`children` 非空的那些）—— #5778 起顶层节点里混有一个**一级项**
     * （「商品管理」，`children` 为空）。
     *
     * ⚠️ 不能用 `codes(tree)` 直接比对组序列：一级项与组共用同一层，且它的 `code` 是
     * `product:list`（与「省料看板」同码，`code` 不唯一）⇒ 混进来会让断言失败。
     * ⚠️ 也不能用 `path` 区分：`MenuNode`（`GET /api/admin/menus` 的 DTO）**没有 `path` 字段**
     * —— 它的字段只有 `code` / `label` / `children` ⇒ 唯一可靠的判据是 **`children` 是否非空**。
     */
    private static List<JsonNode> topLevelGroups(JsonNode tree) {
        List<JsonNode> out = new ArrayList<>();
        tree.forEach(n -> {
            if (n.path("children").size() > 0) {
                out.add(n);
            }
        });
        return out;
    }

    /** 顶层**一级项**（`children` 为空、直接跳转的那些 —— 现为「商品管理」）。 */
    private static List<JsonNode> topLevelStandaloneItems(JsonNode tree) {
        List<JsonNode> out = new ArrayList<>();
        tree.forEach(n -> {
            if (n.path("children").size() == 0) {
                out.add(n);
            }
        });
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
                // issue #5271：七大组（旧树是 9 个顶层条目）。
                // 🔴 2026-10-09（issue #6580）：**六大组 + 两个顶层一级项「商品管理」「企业基础设置」= 8 个顶层条目**
                //（`product-center` 撤销、`smart-customer-service` → `customer-service`、商品列表升为一级项；
                //  「参数总览」由 issue #6573 从 `/settings` 的 tab 升为一级项）。
                .andExpect(jsonPath("$.data.length()").value(8));
    }

    @Test
    @DisplayName("新 IA：顶层一级项（商品管理 / 企业基础设置，后者由 #6580 从组织管理组升上来）不在任何组内，且排在**所有分组之后**")
    void topLevelStandaloneItemMirrorsFrontend() throws Exception {
        JsonNode tree = fetchTree();
        var tops = topLevelStandaloneItems(tree);
        assertEquals(2, tops.size(), "顶层一级项应恰有 2 个（商品管理 / 企业基础设置）—— 实得 = " + labels(tree));
        assertEquals("商品管理", tops.get(0).path("label").asText(),
                "第 1 个顶层一级项必须是「商品管理」—— 实得 = " + labels(tree));
        // 🔴 issue #6580：第 2 个一级项 = 「企业基础设置」（由组织管理组升上来，席位即原「参数总览」；
        // 码取既有读码 `production:view`，不新造码）。
        assertEquals("企业基础设置", tops.get(1).path("label").asText(),
                "第 2 个顶层一级项必须是「企业基础设置」—— 实得 = " + labels(tree));
        // 🔴 2026-10-06（issue #6457，用户裁定方案 A1）：一级项**排在所有分组之后**（原「工作台组之后」）
        // —— 组名即「分组」，渲染在组与组之间会让「大菜单并列」自相矛盾。
        // 顶层**位次**：第 0 项 = 「工作台」组、第 6 项（末项）= 一级项「商品管理」。
        // 判据 = 三源同构守卫的顶层布局序列（tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py）。
        assertEquals("workspace", tree.get(0).path("code").asText(),
                "顶层第 0 项必须是「工作台」组 —— 实得 = " + codes(tree));
        assertEquals("org-center", tree.get(tree.size() - 3).path("code").asText(),
                "顶层倒数第 3 项必须是「组织管理」组（两个一级项紧跟在它之后）—— 实得 = " + codes(tree));
        assertEquals("product:list", tree.get(tree.size() - 2).path("code").asText(),
                "顶层倒数第 2 项必须是「商品管理」（排在**所有分组之后**）—— 实得 = " + codes(tree));
        // 🔴 issue #6580：末项 = 「企业基础设置」（与「商品管理」并列、同排在所有分组之后）
        assertEquals("production:view", tree.get(tree.size() - 1).path("code").asText(),
                "顶层末项必须是「企业基础设置」—— 实得 = " + codes(tree));
        assertEquals("product:list", tops.get(0).path("code").asText());
        assertEquals(0, tops.get(0).path("children").size(),
                "一级项不得有子节点（它不是组）—— 有子节点说明它被写成了组");
    }

    @Test
    @DisplayName("#5271 新 IA：七个顶层组的 key 与组名按 menu.ts 顺序逐值一致")
    void topLevelGroupsMirrorFrontendOrder() throws Exception {
        JsonNode tree = fetchTree();
        // #5778：顶层混有一个**一级项**（商品管理）⇒ 组序列取「有 key 的那些」
        assertEquals(GROUP_KEYS, codes(topLevelGroups(tree)),
                "顶层组 key / 顺序与前端 config/menu.ts 的 menuGroups 不一致");
        assertEquals(GROUP_LABELS, labels(topLevelGroups(tree)),
                "顶层组名 / 顺序与前端 config/menu.ts 的 menuGroups 不一致");
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
    @DisplayName("客户服务组（#5778 新建；2026-10-06 组内重排）：在线接待 + 知识库 + 售后工单 + 客户列表")
    void customerServiceGroupMirrorsMenuTs() throws Exception {
        JsonNode cs = group(fetchTree(), "customer-service");
        assertEquals("客户服务", cs.path("label").asText());
        // 顺序 = menu.ts 的 `customer-service` 组逐字顺序（三源同构守卫按前缀子序列比对）
        assertEquals(List.of("在线接待", "知识库", "售后工单", "客户列表"), labels(cs.path("children")));
        // issue #5246（已合入 main）：知识库 = 读码 knowledge:view、售后工单 = 读码 after_sales:view；
        // 客户列表本轮由交易管理组移入本组，码不变（customer:view）。
        assertEquals(List.of("agent:session", "knowledge:view", "after_sales:view", "customer:view"),
                codes(cs.path("children")));
    }

    @Test
    @DisplayName("商品与加工项组（#5778 撤销）：顶层不再有该组，且「新增商品/商品分类管理」两个动作节点已删除")
    void productCenterGroupIsGone() throws Exception {
        List<String> topKeys = codes(fetchTree());
        assertFalse(topKeys.contains("product-center"),
                "旧组 `product-center` 仍在顶层（#5778 已撤销：加工项归生产管理、商品列表升为一级项）—— 实得 = " + topKeys);
        List<String> all = labels(allChildren(fetchTree()));
        assertFalse(all.contains("新增商品") || all.contains("商品分类管理"),
                "两个商品域动作码节点应随组撤销而删除（权限码本身仍在权限目录里）—— 实得全表 = " + all);
    }

    @Test
    @DisplayName("交易管理组（#5778 收窄）：订单列表 + 财务对账 + 组尾动作码（订单详情）")
    void tradeCenterGroupMirrorsMenuTs() throws Exception {
        JsonNode trade = group(fetchTree(), "trade-center");
        assertEquals("交易管理", trade.path("label").asText());
        // 本轮：客户列表 / 售后工单已移入「客户服务」组 ⇒ 只剩「下单 → 收款」两项 + 组尾动作码
        assertEquals(List.of("订单列表", "财务对账", "订单详情"),
                labels(trade.path("children")));
        assertEquals(List.of("order:list", "finance:view", "order:detail"),
                codes(trade.path("children")));
    }

    @Test
    @DisplayName("生产管理组（#6580 收拢为 3 项 + #5291/#5699 P4）：生产看板/计件工资 production:view、智能派单 processing:view")
    void productionCenterGroupMirrorsMenuTs() throws Exception {
        JsonNode production = group(fetchTree(), "production-center");
        assertEquals("生产管理", production.path("label").asText());
        // 🔴 2026-10-09（issue #6580）：本组**由 5 项收拢为 3 项** —— 「加工项管理」「工艺配置」
        // 两个菜单项按用户裁定移除 ⇒ 只剩「生产看板 → 智能派单 → 计件工资」。
        assertEquals(List.of("生产看板", "智能派单", "计件工资"),
                labels(production.path("children")));
        // issue #5699（P4，子菜单粒度）：每个节点码 ≡ 该页第一屏读码 —— 智能派单 = processing:view
        //（ProductionPoolController 两个读端点同码）；工艺配置 = production:view（该页第一屏 6 个读端点
        // 本次整页收敛到该码；两码持有岗位集合逐值相同 ⇒ 零 delta）；#5291 的 production:view
        // 仍覆盖生产看板与计件工资。
        // 🔴 #6580：两项移除后组内码为 [生产看板, 智能派单, 计件工资]。
        assertEquals(List.of("production:view", "processing:view", "production:view"),
                codes(production.path("children")));
    }

    @Test
    @DisplayName("仓储与物料组（#5271 新组；#5939 加「发货单」；#6404 加「库存明细」）：入库单(inbound:view) + 发货单(order:list) + 余料台账 + 省料看板/库存明细(product:list)")
    void inventoryCenterGroupMirrorsMenuTs() throws Exception {
        JsonNode inventory = group(fetchTree(), "inventory-center");
        assertEquals("仓储与物料", inventory.path("label").asText());
        // 🔴 2026-10-06（issue #6457，方案 A1）：单据（进 → 账 → 出）→ 台账 → 分析。
        assertEquals(List.of("入库单", "库存明细", "发货单", "余料台账", "省料看板"),
                labels(inventory.path("children")));
        // 入库单是**仓储**动作、权限码独立为 inbound:view —— 并进 processing:manage 会让
        // 「有 inbound:view、没有 processing:manage」的仓管看不到菜单（#4203 点名的同族坑）。
        // issue #5699（P4）：省料看板节点码 = 该页第一屏读码 product:list（StockBatchController）。
        // issue #5939：「发货单」取**既有** order:list（与订单列表同码、与页面/端点同码）⇒ 零授权 delta。
        // 🔴 issue #6404：「库存明细」同样取**既有** product:list（与省料看板同码；
        // 码不唯一是有意的 —— 两个页面各自的读端点注解就是这个码）。
        assertEquals(List.of("inbound:view", "product:list", "order:list", "processing:manage", "product:list"),
                codes(inventory.path("children")));
    }

    @Test
    @DisplayName("组织管理组：员工管理/岗位权限/企业基础设置（经营域，权限码节点） + 组尾动作码（新增员工）")
    void orgCenterGroupMirrorsMenuTs() throws Exception {
        JsonNode org = group(fetchTree(), "org-center");
        assertEquals("组织管理", org.path("label").asText());
        // 🔴 2026-10-09（issue #6580）：第 3 项由「企业基础信息」菜单项改为**权限码节点**
        // 「企业基础设置（经营域）」——菜单项本体已升为**顶层一级项**（见
        // `topLevelStandaloneItemMirrorsFrontend`），这里保留的是**经营域权限码**的挂载点
        //（否则 `system:manage` 会从权限勾选树上消失，页内经营域永远无法授予）。
        assertEquals(List.of("员工管理", "岗位权限", "企业基础设置（经营域）", "新增员工"),
                labels(org.path("children")));
        // issue #5291：岗位权限节点改挂**读**码 system:view（经营域码节点仍是 system:manage）。
        assertEquals(List.of("employee:list", "system:view", "system:manage", "employee:create"),
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
    @DisplayName("菜单项一项不少不减（**18 组内项** + **1 个组内权限码节点** + **2 顶层一级项**各恰好一次）+ 2 个动作码节点")
    void everyMenuItemAppearsExactlyOnce() throws Exception {
        List<String> all = labels(allChildren(fetchTree()));
        for (String name : MENU_ITEM_LABELS) {
            int expected = 1;
            // 顶层**一级项**（「商品管理」「企业基础设置」）是**叶子** ⇒ 不在 `allChildren`
            // （它们不属于任何组），改在顶层一级项集合里各断言恰好一次。
            // ⚠️ 这里按**名单**判断而不是按名字硬编码：将来再加一级项，忘了登记就会落到下面那条
            // 「组内节点出现次数不是 1」上 ⇒ 当场红（不会静默跳过）。
            if (TOP_LEVEL_STANDALONE_LABELS.contains(name)) {
                assertEquals(1, topLevelStandaloneItems(fetchTree()).stream()
                                .filter(n -> name.equals(n.path("label").asText())).count(),
                        "顶层一级项「" + name + "」的出现次数不是 1");
                continue;
            }
            assertEquals(expected, all.stream().filter(name::equals).count(),
                    "菜单项「" + name + "」在权限树上的出现次数不是 1（实得全表 = " + all + "）");
        }
        for (String action : ACTION_NODE_LABELS) {
            assertEquals(1, all.stream().filter(action::equals).count(),
                    "动作码节点「" + action + "」缺失或重复（实得全表 = " + all + "）");
        }
        // 组内节点总数 = 18 个**组内**菜单项（21 项 − **2 个**顶层一级项「商品管理」「企业基础设置」）
        // + 2 动作码节点 = 23。
        // （#5939：菜单项 21 → 22；#6404：菜单项 22 → 23，组内项 21 → 22；#6573：菜单项 23 → 24，
        //   组内项**不变**（新增的是顶层一级项）⇒ 总数 24 → 25，组内 22 → 21 + 2 动作码。）
        // ⚠️ 顶层一级项是**叶子**（不在任何组内）⇒ 不被 `allChildren` 收录，它们的存在由
        // `topLevelStandaloneItemMirrorsFrontend` 单独断言（避免两处都算它 ⇒ 重复计数）。
        assertEquals(MENU_ITEM_LABELS.size() - 2 + ACTION_NODE_LABELS.size(), all.size(),
                "组内节点总数 = 21 组内菜单项 + 2 动作码节点（实得全表 = " + all + "）");
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