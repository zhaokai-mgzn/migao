package com.migao.admin.controller;

// case_ids: PG-021, MC-091

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.dto.MenuNode;
import com.migao.admin.service.MobileSurfaces;
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
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

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
     *  `product-center` 撤销）。
     *  🔴 2026-10-17（issue #7087，用户裁定「经营看板直接作为一级菜单，移除工作台」）：
     *  「**工作台**」组**整组撤销** ⇒ **五组**；顶层另混有**三个一级项**（最前席位「经营看板」+
     *  尾席位「商品管理」「企业基础设置」），它们**不是组**（见 `topLevelStandaloneItemMirrorsFrontend`）。 */
    private static final List<String> GROUP_KEYS = List.of(
            "customer-service", "trade-center",
            "production-center", "supply-chain", "inventory-center", "org-center");

    /** 顶层组名（与 GROUP_KEYS 同序）。 */
    private static final List<String> GROUP_LABELS = List.of(
            "客户服务", "交易管理", "生产管理", "供应链", "仓储与物料", "组织管理");

    /** 菜单项名总表（一项不少不减；「通知中心」是一级独立项、不在本权限树内）。
     *  ⚠️ #6404：菜单项 21 → 22（+「库存明细」`/stock-ledger`）。
     *  ⚠️ #6573：菜单项 22 → 23（+顶层一级项「参数总览」`/settings/params`，取既有读码 `production:view`）。
     *  ⚠️ 含**顶层一级项**（它们不属于任何组，但仍是菜单项）——由 `TOP_LEVEL_STANDALONE_LABELS` 分流。
     *  🔴 2026-10-06（issue #6457，用户裁定方案 A1）：**顺序重排**（项数不变）——
     *  客户服务组「接待与工具 → 售后 → 档案」、生产管理组「先备资料 → 再生产」、
     *  仓储组「单据（进 → 账 → 出）→ 台账 → 分析」，且一级项「商品管理」沉到**所有分组之后**。
     *  🔴 2026-10-17（issue #7087，用户裁定）：**「每日简报」删除**（那行结论就在经营看板上）；
     *  **「经营看板」由「工作台」组内项升为最前席位一级项** ⇒ 仍在本表、但落到顶层一级项那一支。 */
    private static final List<String> MENU_ITEM_LABELS = List.of(
            "经营看板",
            "在线接待", "知识库", "售后工单", "客户列表",
            // 🔴 2026-10-22（issue #7375 段 3）：交易管理组新增「价格本」（组内第一项，码 order:list）
            "价格本",
            "销售订单", "财务对账",
            // 🔴 2026-10-09（issue #6580，用户裁定「移除加工项管理和工艺配置这两个菜单」）：
            // 「加工项管理」「工艺配置」两个菜单项已移除（功能体并入「企业基础设置」页内的配置域）。
            "作业看板", "智能派单", "计件工资",
            // 🔴 2026-10-17（issue #7140）：生产管理组新增「质检记录」（读码 production:inspect）
            "质检记录",
            // 🔴 2026-10-20（issue #7369 段 4）：仓储与物料组新增「采购单」（同取 inbound:view，紧随供应商）
            "入库单", "供应商", "采购单", "库存明细", "发货单", "余料台账", "省料看板",
            "员工管理", "岗位权限",
            // 组内的**权限码节点**（无 path、不是菜单项）：只为让经营域的码仍可授予
            "企业基础设置（经营域）",
            "商品管理",
            // 顶层一级项（由组织管理组升上来，席位即原「参数总览」）
            "企业基础设置");

    /** 动作码节点（非菜单项）2 个，**统一追加在组尾**：order:detail / employee:create。
     *  🔴 2026-09-29（#5778）：原 4 个 → **2 个** —— 「新增商品」/「商品分类管理」两个节点原挂在
     *  已撤销的 `product-center` 组下，组撤销后它们在权限树上**无处安放** ⇒ 同批删除
     *（权限码本身仍在权限目录里，删的是「菜单树上有这两个勾选项」这一事实）。
     *  🔴 2026-10-12（issue #6759）：**2 个 → 4 个** —— 补两个**手机端写码**节点
     *  「加工单操作」（`processing:update`，挂生产管理组尾）与
     *  「入库单操作」（`inbound:create`，挂仓储与物料组尾）。 */
    private static final List<String> ACTION_NODE_LABELS = new ArrayList<>(List.of(
            "订单详情", "新增员工",
            // 🔴 2026-10-12（issue #6759）：两个手机端写码的动作节点（中文名逐字取
            // `rbac/manifest.json` 的 `codes.names`）。
            "加工单操作", "入库单操作"));

    /** 顶层**一级项**名（`children` 为空、直接跳转的那些，**不属于任何组**）。
     *  🔴 2026-10-17（issue #7087）起**三个**：**最前席位**「经营看板」（前端 `standaloneHeadItems`
     *  的对应物）+ 尾席位「商品管理」「企业基础设置」（#6580 的席位）—— 它们不参与 `allChildren`
     *  的组内计数，由 `topLevelStandaloneItems` 单独断言（避免两处都算它们 ⇒ 重复计数）。 */
    private static final List<String> TOP_LEVEL_STANDALONE_LABELS =
            List.of("经营看板", "商品管理", "企业基础设置");

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
                // 🔴 2026-10-17（issue #7087）：**最前席位一级项「经营看板」+ 五大组 + 两个尾席位一级项
                // 「商品管理」「企业基础设置」= 8 个顶层条目**（与「六大组 + 两个一级项」同数不同序：
                //  「工作台」组撤销、经营看板由组内项升为最前席位一级项、「每日简报」项删除）。
                .andExpect(jsonPath("$.data.length()").value(10));
    }

    @Test
    @DisplayName("新 IA（#7087 + #7376）：四个顶层一级项 —— 最前席位「经营看板」（码 dashboard:view）+ 尾席位「商品管理」「企业基础设置」；五个组紧跟在「经营看板」之后")
    void topLevelStandaloneItemMirrorsFrontend() throws Exception {
        JsonNode tree = fetchTree();
        var tops = topLevelStandaloneItems(tree);
        assertEquals(4, tops.size(),
                "顶层一级项应恰有 4 个（经营看板 / 报表中心 / 商品管理 / 企业基础设置）—— 实得 = " + labels(tree));
        // 🔴 2026-10-17（issue #7087，用户裁定「经营看板直接作为一级菜单，移除工作台」）：
        // 第 1 个顶层一级项 = 「经营看板」，落在**最前席位**（= 整个顶层序列的第 0 项）——
        // 前端 `menu.ts` 的 `standaloneHeadItems` 的对应物。为什么**必须最前**：`landingPath()` =
        // **第一个可见菜单项**（issue #6758）⇒ 与「商品管理」并列的尾席位会让登录落点变成「在线接待」。
        // 码 = `dashboard:view`（与升为一级项之前**一字未动** ⇒ 零授权 delta）。
        assertEquals("经营看板", tops.get(0).path("label").asText(),
                "第 1 个顶层一级项必须是「经营看板」—— 实得 = " + labels(tree));
        // 🔴 issue #7376：第 2 个一级项 = 「报表中心」（同为**最前席位**，紧跟经营看板）
        assertEquals("报表中心", tops.get(1).path("label").asText(),
                "第 2 个顶层一级项必须是「报表中心」—— 实得 = " + labels(tree));
        // 🔴 issue #6580：第 3 / 4 个一级项 = 「商品管理」「企业基础设置」（尾席位，排在所有分组之后）
        assertEquals("商品管理", tops.get(2).path("label").asText(),
                "第 3 个顶层一级项必须是「商品管理」—— 实得 = " + labels(tree));
        assertEquals("企业基础设置", tops.get(3).path("label").asText(),
                "第 4 个顶层一级项必须是「企业基础设置」—— 实得 = " + labels(tree));
        // 顶层**位次**：第 0 项 = 最前席位一级项「经营看板」→ 第 1~5 项 = 五个组 → 末两项 = 尾席位一级项
        //（#7087 起「工作台」组不再占第 0 项）。判据 = 三源同构守卫的顶层布局序列
        //（tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py）。
        assertEquals("dashboard:view", tree.get(0).path("code").asText(),
                "顶层第 0 项必须是**最前席位**一级项「经营看板」—— 实得 = " + codes(tree));
        // 最前席位是**两项**（经营看板 → 报表中心，#7376）⇒ 组从下标 2 开始
        assertEquals(GROUP_KEYS, codes(tree).subList(2, 2 + GROUP_KEYS.size()),
                "顶层第 2~" + (1 + GROUP_KEYS.size()) + " 项必须依次是五个组（「工作台」组已撤销）—— 实得 = " + codes(tree));
        assertEquals("org-center", tree.get(tree.size() - 3).path("code").asText(),
                "顶层倒数第 3 项必须是「组织管理」组（两个尾席位一级项紧跟在它之后）—— 实得 = " + codes(tree));
        assertEquals("product:list", tree.get(tree.size() - 2).path("code").asText(),
                "顶层倒数第 2 项必须是「商品管理」（排在**所有分组之后**）—— 实得 = " + codes(tree));
        // 🔴 issue #6580：末项 = 「企业基础设置」（与「商品管理」并列、同排在所有分组之后）
        assertEquals("production:view", tree.get(tree.size() - 1).path("code").asText(),
                "顶层末项必须是「企业基础设置」—— 实得 = " + codes(tree));
        assertEquals("dashboard:view", tops.get(1).path("code").asText(),
                "报表中心与经营看板同码（报表是看板的下钻）");
        assertEquals("product:list", tops.get(2).path("code").asText());
        assertEquals(0, tops.get(0).path("children").size(),
                "一级项不得有子节点（它不是组）—— 有子节点说明它被写成了组");
    }

    @Test
    @DisplayName("#5271 新 IA：顶层五个组的 key 与组名按 menu.ts 顺序逐值一致（#7087 起「工作台」组不再存在）")
    void topLevelGroupsMirrorFrontendOrder() throws Exception {
        JsonNode tree = fetchTree();
        // #5778 起顶层混有**一级项**（#7087 起三个：最前席位「经营看板」+ 尾席位两项）
        // ⇒ 组序列取「有 children 的那些」
        assertEquals(GROUP_KEYS, codes(topLevelGroups(tree)),
                "顶层组 key / 顺序与前端 config/menu.ts 的 menuGroups 不一致");
        assertEquals(GROUP_LABELS, labels(topLevelGroups(tree)),
                "顶层组名 / 顺序与前端 config/menu.ts 的 menuGroups 不一致");
    }

    @Test
    @DisplayName("🔴 #7087：经营看板 = 顶层**一级项**（最前席位），码 dashboard:view（与前端 standaloneHeadItems 同构）")
    void dashboardIsTopLevelHeadStandaloneItem() throws Exception {
        JsonNode tree = fetchTree();
        JsonNode head = tree.get(0);
        assertEquals("dashboard:view", head.path("code").asText(),
                "最前席位一级项的码必须是 dashboard:view（升为一级项**不改码**）—— 实得 = " + codes(tree));
        assertEquals("经营看板", head.path("label").asText(),
                "最前席位一级项必须是「经营看板」—— 实得 = " + labels(tree));
        assertEquals(0, head.path("children").size(),
                "「经营看板」必须是无子节点的**一级项**（升为一级菜单后不再是组）—— 有子节点 = 写回了组形态");
    }

    @Test
    @DisplayName("🔴 #7087 反向断言：树里没有「工作台」组（含空组形态），也没有「每日简报」节点")
    void workspaceGroupAndDailyBriefingAreGone() throws Exception {
        JsonNode tree = fetchTree();
        assertFalse(codes(tree).contains("workspace"),
                "旧「工作台」组（key `workspace`）仍在顶层（#7087 整组撤销）—— 实得 = " + codes(tree));
        assertFalse(labels(tree).contains("工作台"),
                "「工作台」组名不得再出现在权限树上 —— 实得 = " + labels(tree));
        List<String> all = labels(allNodes(tree));
        assertFalse(all.contains("每日简报"),
                "「每日简报」菜单项仍在树上（#7087 已撤销：那行结论就在经营看板上）—— 实得全表 = " + all);
        // 同码承载节点只剩一处（旧形态是「工作台」组里两个 dashboard:view）—— 反向对照的**对象**还在
        assertEquals(1, all.stream().filter("经营看板"::equals).count(),
                "「经营看板」在树上必须**恰好一处**（顶层一级项）—— 实得全表 = " + all);
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
    @DisplayName("交易管理组（#5778 收窄 + #7375）：价格本 + 销售订单 + 财务对账 + 组尾动作码（订单详情）")
    void tradeCenterGroupMirrorsMenuTs() throws Exception {
        JsonNode trade = group(fetchTree(), "trade-center");
        assertEquals("交易管理", trade.path("label").asText());
        // 本轮：客户列表 / 售后工单已移入「客户服务」组 ⇒ 只剩「定价 → 下单 → 收款」+ 组尾动作码
        // 🔴 2026-10-22（issue #7375 段 3）：新增组内第一项「价格本」（码 order:list —— 与销售订单同码，
        // 因为价格本页第一屏读的就是 PricingController 的类级 `order:list`）。
        assertEquals(List.of("价格本", "销售订单", "财务对账", "订单详情"),
                labels(trade.path("children")));
        assertEquals(List.of("order:list", "order:list", "finance:view", "order:detail"),
                codes(trade.path("children")));
    }

    @Test
    @DisplayName("生产管理组（#6580 收拢为 3 项 + #5291/#5699 P4 + #6759 组尾动作码）：作业看板/计件工资 production:view、智能派单 processing:view、加工单操作 processing:update")
    void productionCenterGroupMirrorsMenuTs() throws Exception {
        JsonNode production = group(fetchTree(), "production-center");
        assertEquals("生产管理", production.path("label").asText());
        // 🔴 2026-10-09（issue #6580）：本组**由 5 项收拢为 3 项** —— 「加工项管理」「工艺配置」
        // 两个菜单项按用户裁定移除 ⇒ 只剩「作业看板 → 智能派单 → 计件工资」。
        // 🔴 2026-10-12（issue #6759）：**组尾**追加动作码节点「加工单操作」（`processing:update`
        // = 手机端派单的写码）—— 动作节点统一追加在组尾，导航项仍是它之前的连续前缀。
        assertEquals(List.of("作业看板", "智能派单", "计件工资", "质检记录", "加工单操作"),
                labels(production.path("children")));
        // issue #5699（P4，子菜单粒度）：每个节点码 ≡ 该页第一屏读码 —— 智能派单 = processing:view
        //（ProductionPoolController 两个读端点同码）；工艺配置 = production:view（该页第一屏 6 个读端点
        // 本次整页收敛到该码；两码持有岗位集合逐值相同 ⇒ 零 delta）；#5291 的 production:view
        // 仍覆盖作业看板与计件工资。
        // 🔴 #6580：两项移除后组内码为 [作业看板, 智能派单, 计件工资]；#6759 追加 processing:update。
        assertEquals(List.of("production:view", "processing:view", "production:view",
                        "production:inspect", "processing:update"),
                codes(production.path("children")));
    }

    @Test
    @DisplayName("仓储与物料组（#5271 新组；#5939 加「发货单」；#6404 加「库存明细」；#6759 组尾加动作码）：入库单(inbound:view) + 发货单(order:list) + 余料台账 + 省料看板/库存明细(product:list) + 入库单操作(inbound:create)")
    void inventoryCenterGroupMirrorsMenuTs() throws Exception {
        JsonNode inventory = group(fetchTree(), "inventory-center");
        assertEquals("仓储与物料", inventory.path("label").asText());
        // 🔴 2026-10-06（issue #6457，方案 A1）：单据（进 → 账 → 出）→ 台账 → 分析。
        // 🔴 2026-10-12（issue #6759）：**组尾**追加动作码节点「入库单操作」（`inbound:create`
        // = 手机端过账的写码）。
        assertEquals(List.of("库存明细", "发货单", "余料台账", "省料看板", "入库单操作"),
                labels(inventory.path("children")));
        // 入库单是**仓储**动作、权限码独立为 inbound:view —— 并进 processing:manage 会让
        // 「有 inbound:view、没有 processing:manage」的仓管看不到菜单（#4203 点名的同族坑）。
        // issue #5699（P4）：省料看板节点码 = 该页第一屏读码 product:list（StockBatchController）。
        // issue #5939：「发货单」取**既有** order:list（与销售订单同码、与页面/端点同码）⇒ 零授权 delta。
        // 🔴 issue #6404：「库存明细」同样取**既有** product:list（与省料看板同码；
        // 码不唯一是有意的 —— 两个页面各自的读端点注解就是这个码）。
        // issue #7369：「供应商」与「入库单」同码（inbound:view）—— 档案面与单据面同群，零授权 delta。
        // 用户 2026-10-20：单据类节点（入库单/供应商/采购单）已移到「供应链」组 ⇒ 本组只剩库存与出库。
        assertEquals(List.of("product:list", "order:list", "processing:manage", "product:list",
                        "inbound:create"),
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
    @DisplayName("旧顶层组（dashboard/orders/products/employees/customers/finance/settings/agent/production/customer-center/**workspace**）不再存在")
    void legacyTopLevelGroupsAreGone() throws Exception {
        List<String> topKeys = codes(fetchTree());
        // 🔴 2026-10-17（issue #7087）：「工作台」组（`workspace`）加入本表 —— 它与上面那些旧组同为
        // 「不再作为**任何形态**存在」的组（既不是组，也不是空组）。
        for (String legacy : List.of("dashboard", "orders", "products", "employees", "customers",
                "finance", "settings", "agent", "production", "customer-center", "workspace")) {
            assertFalse(topKeys.contains(legacy),
                    "旧顶层组 `" + legacy + "` 仍在菜单树里（#5271 / #7087 已撤销）—— 实得 = " + topKeys);
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
    @DisplayName("菜单项一项不少不减（组内 17 个节点 = 16 菜单项 + 1 权限码节点；3 个顶层一级项各恰好一次）+ 4 个动作码节点（#6759 起）")
    void everyMenuItemAppearsExactlyOnce() throws Exception {
        JsonNode tree = fetchTree();
        List<String> all = labels(allChildren(tree));
        for (String name : MENU_ITEM_LABELS) {
            int expected = 1;
            // 顶层**一级项**（「经营看板」「商品管理」「企业基础设置」）是**叶子** ⇒ 不在 `allChildren`
            // （它们不属于任何组），改在顶层一级项集合里各断言恰好一次。
            // ⚠️ 这里按**名单**判断而不是按名字硬编码：将来再加一级项，忘了登记就会落到下面那条
            // 「组内节点出现次数不是 1」上 ⇒ 当场红（不会静默跳过）。
            if (TOP_LEVEL_STANDALONE_LABELS.contains(name)) {
                assertEquals(1, topLevelStandaloneItems(tree).stream()
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
        // 组内节点总数 = **17 个组内菜单项**（`MENU_ITEM_LABELS` 20 项 − 3 个顶层一级项
        // 「经营看板」「商品管理」「企业基础设置」）+ **4 个动作码节点** = 21。
        // （#5939：菜单项 21 → 22；#6404：+「库存明细」；#6573：新增的是顶层一级项 ⇒ 组内项不变；
        //   🔴 #6759：动作码节点 2 → 4 —— 运行时追加「加工单操作」/「入库单操作」⇒ 这里按**现取表长**
        //   算，两处都不会漏算或重复计数。
        //   🔴 #7087（issue #7087）：「工作台」组撤销、「经营看板」升为最前席位一级项、「每日简报」删除
        //   ⇒ 组内项 21 → 17、顶层一级项 2 → 3；故减数取 `TOP_LEVEL_STANDALONE_LABELS.size()`
        //   **而不是写死的 2** —— 名单变了公式自己跟着变。）
        // ⚠️ 顶层一级项是**叶子**（不在任何组内）⇒ 不被 `allChildren` 收录，它们的存在由
        // `topLevelStandaloneItemMirrorsFrontend` 单独断言（避免两处都算它 ⇒ 重复计数）。
        assertEquals(MENU_ITEM_LABELS.size() - TOP_LEVEL_STANDALONE_LABELS.size() + ACTION_NODE_LABELS.size(),
                all.size(),
                "组内节点总数 = 19 组内菜单项 + 4 动作码节点（实得全表 = " + all + "）");
        // 🔴 #6759：动作码节点由 2 → 4（+「加工单操作」`processing:update` / 「入库单操作」`inbound:create`）
        assertEquals(4, ACTION_NODE_LABELS.size(),
                "动作码节点台账应恰有 4 条（订单详情 / 新增员工 / 加工单操作 / 入库单操作）");
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

    // ══════════════════════════════════════════════════════════════════════════
    // issue #6759 需求②：两个手机端写码进权限勾选树（动作码节点，挂各自业务域组尾）
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 #6759：手机端两个写码节点已在树上 —— label 与 `rbac/manifest.json` 的 `codes.names` 逐字相等、码逐字相等、且都在各自组尾")
    void mobileWriteCodesAreInTheTreeWithManifestLabels() throws Exception {
        JsonNode tree = fetchTree();

        // ① 中文名逐字取自 `rbac/manifest.json` 的 `codes.names`：加工单操作 / 入库单操作
        //   （真值面由 test_rbac_derived_pages.py 的 ACTION_NODE_CODES 与
        //    rbac/readings.json 的 codes.names 同批钉住；这里是最靠近读面的一道）。
        JsonNode processed = group(tree, "production-center").path("children");
        assertEquals("加工单操作", processed.get(processed.size() - 1).path("label").asText(),
                "生产管理组组尾必须是动作码节点「加工单操作」（codes.names['processing:update']）");
        assertEquals("processing:update", processed.get(processed.size() - 1).path("code").asText(),
                "「加工单操作」的码必须是 processing:update（手机端派单写码）");

        JsonNode inventory = group(tree, "inventory-center").path("children");
        assertEquals("入库单操作", inventory.get(inventory.size() - 1).path("label").asText(),
                "仓储与物料组组尾必须是动作码节点「入库单操作」（codes.names['inbound:create']）");
        assertEquals("inbound:create", inventory.get(inventory.size() - 1).path("code").asText(),
                "「入库单操作」的码必须是 inbound:create（手机端过账写码）");

        // ② 它在权限树上是**恰好一次**（重复节点 = 员工权限页上的重复勾选项）
        List<String> all = labels(allChildren(tree));
        for (String label : List.of("加工单操作", "入库单操作")) {
            assertEquals(1, all.stream().filter(label::equals).count(),
                    "动作码节点「" + label + "」在权限树上的出现次数不是 1（实得全表 = " + all + "）");
        }

        // ③ 两个**导航项**仍是动作节点之前的连续前缀（动作节点只许在组尾）
        assertEquals(List.of("作业看板", "智能派单", "计件工资", "质检记录"),
                labels(processed).subList(0, processed.size() - 1));
        assertEquals(List.of("库存明细", "发货单", "余料台账", "省料看板"),
                labels(inventory).subList(0, inventory.size() - 1));
    }

    // ══════════════════════════════════════════════════════════════════════════
    // issue #6759 需求①：手机端可见面标注**派生**自 MobileSurfaces（唯一真值）
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 #6759：树上手机端标注 = `MobileSurfaces` 的现取派生（逐码相等，不是我抄的表）")
    void mobileTitlesAreDerivedFromMobileSurfaces() throws Exception {
        JsonNode tree = fetchTree();

        // 真值 = 由 MobileSurfaces.ALL + TABS 现取（判据自己算一遍，不看实现里的中间量）
        Map<String, List<String>> expected = new LinkedHashMap<>();
        for (MobileSurfaces.Surface surface : MOBILE_SURFACES) {
            if (surface.readPermission() == null) {
                continue;
            }
            List<String> titles = expected.computeIfAbsent(surface.readPermission(), key -> new ArrayList<>());
            if (!titles.contains(surface.title())) {
                titles.add(surface.title());
            }
        }
        assertFalse(expected.isEmpty(),
                "MobileSurfaces 一个带码的面都没有 ⇒ 本判据会空跑（fail-closed）");

        Map<String, List<String>> actual = mobileTitlesOf(tree);
        assertEquals(expected, actual,
                "树上「权限码 → 手机端面」与 MobileSurfaces 现取派生不一致"
                        + "（不等即说明有人抄了第二份映射，或派生没接上）");

        // 逐点读数（防「两边都是空」这类假绿）：确有标注、且只出现在**手机端有面**的码上
        assertEquals(List.of("智能派单"), actual.get("processing:view"),
                "`processing:view` 的手机端面必须是「智能派单」（MobileSurfaces 的 pool）");
        assertEquals(List.of("入库过账"), actual.get("inbound:view"),
                "`inbound:view` 的手机端面必须是「入库过账」（MobileSurfaces 的 inbound）");
        assertFalse(actual.containsKey("order:list"),
                "`order:list`（销售订单 / 发货单）在手机端没有任何面 ⇒ 不得有标注（不在手机上多一个入口）");
        assertFalse(actual.containsKey("employee:create"),
                "`employee:create`（新增员工）在手机端没有任何面 ⇒ 不得有标注");
    }

    @Test
    @DisplayName("🔴 #6759 红证：改／删 MobileSurfaces 某个面的 readPermission ⇒ 标注随之改变／消失（标注不是我抄的表）")
    void mobileTitleAnnotationFollowsTheSurfacesCatalog() throws Exception {
        // 注入面①：把 inbound 面的读码改到 `processing:view`（模拟「改 MobileSurfaces 里某个面的 readPermission」）
        // 注入面②：`production-todos`（能力位）直接删掉
        List<MobileSurfaces.Surface> mutated = new ArrayList<>();
        for (MobileSurfaces.Surface surface : MOBILE_SURFACES) {
            if ("inbound".equals(surface.key())) {
                mutated.add(new MobileSurfaces.Surface("inbound", "入库过账", surface.route(), "processing:view"));
            } else if (!"production-todos".equals(surface.key())) {
                mutated.add(surface);
            }
        }
        List<MenuNode> scratch = List.of(
                new MenuNode("inventory-center", "仓储与物料", List.of(
                        new MenuNode("inbound:view", "入库单"),
                        new MenuNode("order:list", "发货单"))),
                new MenuNode("production-center", "生产管理", List.of(
                        new MenuNode("processing:view", "智能派单"),
                        new MenuNode("production:view", "作业看板"))));
        MenuController.annotateMobileTitles(scratch, mutated);

        Map<String, List<String>> got = new LinkedHashMap<>();
        scratch.get(0).getChildren().forEach(n -> got.put(n.getCode(), n.getMobileTitles()));
        scratch.get(1).getChildren().forEach(n -> got.put(n.getCode(), n.getMobileTitles()));
        Map<String, List<String>> want = new LinkedHashMap<>();
        want.put("inbound:view", List.of());
        want.put("order:list", List.of());
        want.put("processing:view", List.of("智能派单", "入库过账"));
        want.put("production:view", List.of("计件工资报表"));
        assertEquals(want, got,
                "喂一份改过的面清单 ⇒ 标注必须跟着变：`inbound:view` 的标注**消失**、"
                        + "`processing:view` **多出**「入库过账」、`production:view` 随 production-todos 被删"
                        + "**只剩**「计件工资报表」（同一码还有另一个面时不跟着消失）");

        // 反向对照：生产入口（真清单）**零变化** —— 证明上面那次变异进的是判据的入参，不是全局态
        JsonNode tree = fetchTree();
        assertEquals(List.of("入库过账"), mobileTitlesOf(tree).get("inbound:view"),
                "真清单下 `inbound:view` 仍应是「入库过账」⇒ 现场那次注入没有污染全局真值");
    }

    // ══════════════════════════════════════════════════════════════════════════
    // issue #6781：手机端标注**只落在该权限码在树序上的首个承载节点**（修法 1）
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 #6781：每个权限码在树上**只**标注一处（树序首个承载节点）—— 同屏重复与名实不符两条口径都不得命中")
    void mobileTitlesAnnotateOnlyTheFirstCarrierOfEachCode() throws Exception {
        JsonNode tree = fetchTree();
        Map<String, List<String>> carriers = carrierLabelsByCode(tree);
        Map<String, List<String>> annotated = mobileTitlesByLabel(tree);

        // ① 同屏重复：同一个码被标注了不止一处 ⇒ 同屏出现两条一模一样的标注（§31 P2）
        List<String> codesWithSeveralAnnotations = annotated.keySet().stream()
                .collect(Collectors.groupingBy(MenuControllerTest::codeOf, LinkedHashMap::new, Collectors.counting()))
                .entrySet().stream().filter(e -> e.getValue() > 1)
                .map(e -> e.getKey() + " × " + e.getValue()).toList();
        assertTrue(codesWithSeveralAnnotations.isEmpty(),
                "这些权限码在树上被标注了不止一处（同屏重复）：" + codesWithSeveralAnnotations
                        + "（实得标注 = " + annotated + "）");

        // ② 判定基准 = 该码在**树序上的首个承载节点**（这是本实现声明的语义；逐字对照见本类
        //    `injectedPerNodeCopyIsCaughtByTheFirstCarrierRule`）—— 标注落在别的节点上就是名实不符
        Map<String, String> firstCarrier = new LinkedHashMap<>();
        carriers.forEach((code, labels) -> firstCarrier.put(code, labels.get(0)));
        // 名实不符（issue #6781 的逐字定义）：某节点被标注了面 X，而该码还有**别的承载节点**，
        // 且节点 label 与面名 X **无任何公共子串** ⇒ 红（具名报出「哪个节点 / 哪个标注」）
        List<String> mislabeled = new ArrayList<>();
        for (Map.Entry<String, List<String>> entry : annotated.entrySet()) {
            String label = entry.getKey();
            List<String> others = carriers.getOrDefault(codeOf(label), List.of()).stream()
                    .filter(other -> !other.equals(label)).toList();
            if (others.isEmpty()) {
                continue;   // 只有它一个承载节点 ⇒ 标注说的就是它，不存在名实不符
            }
            for (String title : entry.getValue()) {
                if (!label.equals(firstCarrier.get(codeOf(label))) && !sharesAChar(label, title)) {
                    mislabeled.add("「" + label + "」· 手机端：" + title
                            + "（码 " + codeOf(label) + " 还有承载节点 " + others + "）");
                }
            }
        }
        assertTrue(mislabeled.isEmpty(),
                "名实不符的标注（节点名与面名没有任何公共子串，却把该面挂在它头上）：" + mislabeled);

        // ③ 真语料读数：真树上被标注的恰好是这 6 处（同码后继节点一个都不许再带标注）
        assertEquals(List.of("经营看板", "在线接待", "售后工单", "作业看板", "智能派单", "入库单"),
                new ArrayList<>(annotated.keySet()),
                "真树上的标注点必须收敛到这 6 处（实得 = " + annotated + "）");
        // 🔴 2026-10-17（issue #7087）：「每日简报」删除、「经营看板」升为顶层一级项 ⇒ `dashboard:view`
        // 在真树上**只剩一处**承载节点（旧语料是「工作台」组里两个）——「同屏重复」的真语料因此
        // 改由 `production:view`（三处承载）承担，见下一个测试。
        // 🔴 2026-10-22（issue #7376）：`dashboard:view` 现由**两个**顶层一级项承载
        //（经营看板 + 报表中心 —— 报表是看板的下钻，同码零授权 delta）；手机端标注仍只打在第一处。
        assertEquals(List.of("经营看板", "报表中心"), carriers.get("dashboard:view"),
                "`dashboard:view` 在真树上的承载节点（#7376 起为最前席位两项）");
        assertEquals(List.of("作业看板", "计件工资", "企业基础设置"), carriers.get("production:view"),
                "`production:view` 在真树上的承载节点（「同屏重复 / 名实不符」的语料）");
        // 逐点反向对照：两个同码后继节点在树上存在、但不得带任何标注
        for (String label : List.of("计件工资", "企业基础设置")) {
            List<JsonNode> flat = allNodes(tree);
            assertEquals(1, flat.stream().filter(n -> label.equals(n.path("label").asText())).count(),
                    "前置：真树上应恰有一个「" + label + "」节点（没有它这条对照就没有对象）");
            assertFalse(annotated.containsKey(label),
                    "同码后继节点「" + label + "」不得再带手机端标注（它的码 " + codeOf(label)
                            + " 已在树序首个承载节点上标注）");
        }
    }

    @Test
    @DisplayName("🔴 #6781 红证①：未修形态的**真语料**（按码复制到每个承载节点）⇒ 同屏重复 1 个码 + 名实不符 2 条当场红")
    void mobileTitlesCopiedPerNodeAreRejected() throws Exception {
        // 未修形态的**真语料**（issue #6781 的逐字实测读数：真栈上 40 行里 9 行带标注）。
        // 🔴 2026-10-17（issue #7087）：原语料里「每日简报」（与「经营看板」同码 `dashboard:view`）
        // 随菜单撤销删除 ⇒ 同屏重复的**真语料**只剩 `production:view` 那一族（三处承载）；
        // 「经营看板」保留在语料里作**反向对照**（该码只有它一处承载 ⇒ 判据①不得命中它）。
        Map<String, List<String>> perNodeAnnotations = new LinkedHashMap<>();
        perNodeAnnotations.put("经营看板", List.of("数据"));
        perNodeAnnotations.put("作业看板", List.of("计件工资报表", "生产待办"));
        perNodeAnnotations.put("计件工资", List.of("计件工资报表", "生产待办"));
        perNodeAnnotations.put("企业基础设置", List.of("计件工资报表", "生产待办"));

        // 真值（承载关系）现取自真树 —— 注入的只是「标注怎么落」，不是另抄一张承载表
        Map<String, List<String>> carriers = carrierLabelsByCode(fetchTree());

        // 判据①（同屏重复）当场红：`production:view` 三处（= 同屏三条一模一样的标注）；
        // 「经营看板」的码只承载一次 ⇒ **不得**出现在这份清单里（反向对照）
        Map<String, Long> perCode = new LinkedHashMap<>();
        for (String label : perNodeAnnotations.keySet()) {
            perCode.merge(codeOf(label), 1L, Long::sum);
        }
        assertEquals(List.of("production:view × 3"),
                perCode.entrySet().stream().filter(e -> e.getValue() > 1)
                        .map(e -> e.getKey() + " × " + e.getValue()).toList(),
                "未修形态下同码必然多处标注 —— 判据①必须当场红（且只此一个码）");

        // 判据②（名实不符）当场红：未修形态下，**树序非首承载节点**（= 该码还有别的承载节点、
        // 本该什么都不标的节点）恰好是这两个 —— 逐字取自真树（承载关系现取，不另抄一张表）。
        List<String> offenders = perNodeAnnotations.keySet().stream()
                .filter(label -> !carriers.getOrDefault(codeOf(label), List.of()).isEmpty())
                .filter(label -> carriers.get(codeOf(label)).indexOf(label) > 0)
                .toList();
        assertEquals(List.of("计件工资", "企业基础设置"), offenders,
                "名实不符的**非首承载节点**必须恰是这两个（实得 = " + offenders + "）");
        List<String> unrelated = offenders.stream()
                .filter(label -> perNodeAnnotations.get(label).stream().noneMatch(title -> sharesAChar(label, title)))
                .toList();
        assertEquals(List.of("企业基础设置"), unrelated,
                "真语料里「无任何公共子串」的那个节点（企业基础设置命中两个面）—— 判据②当场红");

        // 判据④（相关的一律不许判红）：节点名与面名有公共子串 ⇒ 不在上面任何一份清单里
        for (String[] related : List.of(new String[]{"售后工单", "售后处理"}, new String[]{"入库单", "入库过账"})) {
            assertTrue(sharesAChar(related[0], related[1]),
                    "「" + related[0] + "↔" + related[1] + "」是**相关**的（有公共子串）⇒ 不许被判红");
            assertFalse(unrelated.contains(related[0]),
                    "相关形态「" + related[0] + "↔" + related[1] + "」被误判成名实不符");
        }
    }

    @Test
    @DisplayName("🔴 #6781 红证②（注入式 · 不读磁盘）：把标注按码复制到每个承载节点 ⇒ 落在非首承载节点上即刻可判红；改回修后形态 ⇒ 绿")
    void injectedPerNodeCopyIsCaughtByTheFirstCarrierRule() {
        // 用真机制（`annotateMobileTitles`）造两棵树：同一组「承载节点」，唯一变量 = **回落策略**。
        // 承载节点取**真语料**里的一对同码节点：`production:view` = 作业看板（树序首个）+ 计件工资
        // （🔴 2026-10-17 issue #7087：原用 `dashboard:view` 的「经营看板 + 每日简报」，但
        //  「每日简报」与「工作台」组已撤销 ⇒ 换成仍在树上的这一对，判据语义一字未变）。
        List<MenuNode> duplicated = List.of(
                new MenuNode("production-center", "生产管理", List.of(
                        new MenuNode("production:view", "作业看板"),
                        new MenuNode("production:view", "计件工资"))));
        MenuController.annotateMobileTitles(duplicated, MOBILE_SURFACES);
        // 注入「未修形态」：把树序首承载节点的标注按**同一个码**复制到它的同码后继节点上
        MenuNode first = duplicated.get(0).getChildren().get(0);
        MenuNode second = duplicated.get(0).getChildren().get(1);
        first.getMobileTitles().forEach(second::addMobileTitle);

        // 判据（注入形态）：同一个码 → 两处一模一样的标注（同屏重复）+ 后一处是**非首承载节点**（名实不符）
        assertEquals(List.of("计件工资报表", "生产待办"), first.getMobileTitles());
        assertEquals(List.of("计件工资报表", "生产待办"), second.getMobileTitles(),
                "前置：注入式复制已生效（同码后继节点上出现了同一串标注）");
        assertEquals(2, duplicated.get(0).getChildren().stream()
                        .filter(n -> !n.getMobileTitles().isEmpty()).count(),
                "注入形态下被标注的节点数 = 2 ⇒ 判据①当场红");

        // 修后形态（本单实现）：同一个码只标注树序首个承载节点 ⇒ 后继节点零标注
        List<MenuNode> fixed = List.of(
                new MenuNode("production-center", "生产管理", List.of(
                        new MenuNode("production:view", "作业看板"),
                        new MenuNode("production:view", "计件工资"))));
        MenuController.annotateMobileTitles(fixed, MOBILE_SURFACES);
        assertEquals(List.of("计件工资报表", "生产待办"), fixed.get(0).getChildren().get(0).getMobileTitles());
        assertTrue(fixed.get(0).getChildren().get(1).getMobileTitles().isEmpty(),
                "修后形态：非首承载节点「计件工资」不得带任何标注（实得 = "
                        + fixed.get(0).getChildren().get(1).getMobileTitles() + "）");
        assertEquals(1, fixed.get(0).getChildren().stream()
                        .filter(n -> !n.getMobileTitles().isEmpty()).count(),
                "修后形态下被标注的节点数 = 1");
    }

    /** 现取「权限码 → 该码在树上的**承载节点 label** 清单」（深度优先；组节点 / 空码不进）。 */
    private static Map<String, List<String>> carrierLabelsByCode(JsonNode tree) {
        Map<String, List<String>> out = new LinkedHashMap<>();
        for (JsonNode node : allNodes(tree)) {
            String code = node.path("code").asText();
            if (code.isBlank() || node.path("children").size() > 0) {
                continue;   // 组节点（有 children）不是权限码承载节点
            }
            out.computeIfAbsent(code, key -> new ArrayList<>()).add(node.path("label").asText());
        }
        return out;
    }

    /** 现取「被标注的节点 label → 面名清单」（深度优先 = 渲染顺序；**不带标注的节点不进**）。 */
    private static Map<String, List<String>> mobileTitlesByLabel(JsonNode tree) {
        Map<String, List<String>> out = new LinkedHashMap<>();
        for (JsonNode node : allNodes(tree)) {
            List<String> titles = new ArrayList<>();
            node.path("mobileTitles").forEach(t -> titles.add(t.asText()));
            if (!titles.isEmpty()) {
                out.put(node.path("label").asText(), titles);
            }
        }
        return out;
    }

    /** 深度优先拍平整棵树（组 → 组内节点 → 顶层一级项，顺序 = 树序 / 渲染顺序）。 */
    private static List<JsonNode> allNodes(JsonNode tree) {
        List<JsonNode> out = new ArrayList<>();
        for (JsonNode group : tree) {
            flatten(group, out);
        }
        return out;
    }

    private static void flatten(JsonNode node, List<JsonNode> out) {
        out.add(node);
        for (JsonNode child : node.path("children")) {
            flatten(child, out);
        }
    }

    /** 两个串是否有**任何公共子串** = 至少共享一个字符（空串 / null 一律不算公共）。 */
    private static boolean sharesAChar(String left, String right) {
        if (left == null || right == null || left.isEmpty() || right.isEmpty()) {
            return false;
        }
        return left.codePoints().anyMatch(cp -> right.contains(new String(Character.toChars(cp))));
    }

    /** 真语料里用到的码（与真树逐值一致；写在判据侧的**语料**，不是实现里的映射表）。
     *  🔴 2026-10-17（issue #7087）：「每日简报」已删除 ⇒ 语料里只剩它一处承载的「经营看板」。 */
    private static String codeOf(String label) {
        return switch (label) {
            case "经营看板" -> "dashboard:view";
            case "作业看板", "计件工资", "企业基础设置" -> "production:view";
            case "智能派单" -> "processing:view";
            case "入库单" -> "inbound:view";
            case "在线接待" -> "agent:session";
            case "售后工单" -> "after_sales:view";
            default -> throw new IllegalArgumentException("真语料里没有这个节点：" + label);
        };
    }

    /** 面清单（`MobileSurfaces.ALL + TABS`）—— 与实现同一个真值源，判据侧现取。 */
    private static final List<MobileSurfaces.Surface> MOBILE_SURFACES = mobileSurfaces();

    private static List<MobileSurfaces.Surface> mobileSurfaces() {
        List<MobileSurfaces.Surface> all = new ArrayList<>(MobileSurfaces.ALL);
        all.addAll(MobileSurfaces.TABS);
        return List.copyOf(all);
    }

    /** 从响应树里现取「权限码 → [手机端面名…]」（只收**非空**的那些 —— 空 = 「没有手机端入口」）。
     *  🔴 2026-10-17（issue #7087）：遍历面由「组内子节点」改为**整棵树** —— 「经营看板」升为
     *  **顶层一级项**后不再属于任何组，只扫组内会把它整条漏掉（而它的码 `dashboard:view` 在
     *  `MobileSurfaces.TABS` 里有面「数据」）⇒ 与判据侧现取的 `expected` 不等而**假红**。 */
    private static Map<String, List<String>> mobileTitlesOf(JsonNode tree) {
        Map<String, List<String>> out = new LinkedHashMap<>();
        for (JsonNode node : allNodes(tree)) {
            List<String> titles = new ArrayList<>();
            node.path("mobileTitles").forEach(t -> titles.add(t.asText()));
            if (!titles.isEmpty()) {
                out.put(node.path("code").asText(), titles);
            }
        }
        return out;
    }
}