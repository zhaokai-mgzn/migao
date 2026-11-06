package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.MenuNode;
import com.migao.admin.service.MobileSurfaces;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 菜单权限控制器 — 返回一级+二级菜单树，供前端权限多选用
 *
 * <p>issue #5246（审计裁定「该放行」）：{@code GET /api/admin/menus} **有意不加权限注解** ——
 * 本类是**静态常量目录**（{@link #MENU_TREE}，不含任何租户数据），且「员工管理」页的权限树
 * （frontend/admin-web/src/app/(dashboard)/employees/page.tsx）必须能读到它才能勾选岗位权限；
 * 加码会让「有员工管理权、无 system:manage」的人勾不动权限树。</p>
 *
 * <p>issue #5271（菜单重设计）：本树**顶层组**由 9 个权限域节点重建为 7 个**与侧边栏同构**的组
 * （组 key / 组名 / 组顺序与 {@code frontend/admin-web/src/config/menu.ts} 逐值相等）；组内节点 =
 * 该组菜单项（顺序一致）+ 同域**动作码**节点（统一追加在组尾）。改这里必须同批改 menu.ts 与
 * {@link com.migao.admin.service.AuthService#buildMenusByPermissions}，
 * 判据见 tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py（#5271 起比对**全树**）。</p>
 *
 * <p>issue #6759：节点上的**手机端可见面标注**（{@link MenuNode#getMobileTitles()}）**派生**自
 * {@link MobileSurfaces}（手机端菜单的服务端投影，唯一真值 = issue #6570/#6574）——
 * 本类**不写**任何「码 → 手机端面」的字面表。管理员在权限勾选树上因此看得见
 * 「勾这个码 = 员工手机上多一个入口」（员工管理页 / 岗位权限页都渲染它）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/menus")
@RequiredArgsConstructor
public class MenuController {

    private static final List<MenuNode> MENU_TREE = buildMenuTree();

    /**
     * 送往 {@code GET /api/admin/menus} 的那棵树（= {@link #MENU_TREE} **加**手机端可见面标注，
     * issue #6759）。
     *
     * <p>⚠️ 为什么要单开一个常量而不是在 {@code buildMenuTree()} 里就地标注：
     * {@code tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py} 的**顶层布局序列**
     * 解析器锚的是「{@code buildMenuTree()} 里**最终**那个 {@code return List.of(}」这一字面形态
     * （它按括号深度切顶层条目）。把返回值改成「先赋给局部变量、标注后再 return」会让那个锚
     * **找不到** ⇒ 判据当场报「解析失配」（红）。这里改成**工厂方法 + 独立常量**：解析面零变化，
     * 标注仍是**同一棵树对象的原地标注**（{@link MenuNode#addMobileTitle} 是 setter 语义）。</p>
     */
    private static final List<MenuNode> ANNOTATED_MENU_TREE = annotatedMenuTree();

    private static List<MenuNode> annotatedMenuTree() {
        annotateMobileTitles(MENU_TREE);
        return MENU_TREE;
    }

    private static List<MenuNode> buildMenuTree() {
        // 权限码格式: 模块:操作 — 与 DB permissions.code 格式一致。
        //
        // 🔴 本树的**顶层组 = 前端 `frontend/admin-web/src/config/menu.ts` 的 `menuGroups`**
        // （组 key / 组名 / 组顺序），组内节点 = 该组的**菜单项**（label 与菜单名**逐字一致**）
        // + 该业务域的**动作码节点**（后者**统一追加在组尾** —— 导航项必须是动作码节点之前的连续前缀）。
        // 本树是 `GET /api/admin/menus` 的读面，被前端「员工管理」页渲染成权限勾选树 ——
        // 与 `AuthService.buildMenusByPermissions`（登录下发菜单）、前端 `config/menu.ts`（真实侧边栏）
        // **三处同构**；漏一处就是「岗位权限页勾得动、侧边栏看不到」（issue #4203 点名的同族坑）。
        // 判据：tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py（#5271 起比对全树）。
        //
        // 🔴 2026-11-06（用户裁定「观星台菜单调整」）：八大组 ——
        //   客户服务 / 订单/商品 / 生产管理 / 质量管理 / 仓储/物料 / 财务 / 供应链 / 组织管理；
        //   尾席位「企业基础设置」的插入位 = **供应链之后、组织管理之前**
        //   （前端 `STANDALONE_TOP_AFTER_GROUP_KEY = 'supply-chain'`）。
        //   本轮**只动信息架构**（分组 / 组名 / 组内顺序 / 席位位置）：权限码与路径一字不动 ⇒ 零授权 delta。
        //
        // ⚠️ 「经营概览」「企业基础设置」**两种写法都要有，且各自服务一个解析器**（与「商品管理」同款，不是笔误）：
        //   · **变量声明** —— `test_agent_permission_parity.py` 的 `_iter_menu_controller`
        //     只认这一形态（`rbac/manifest.json` 的 `menus.controller` 靠它）；
        //   · `List.of(...)` 里的**内联**节点 —— `test_menu_three_sources_are_isomorphic.py`
        //     的顶层布局序列解析器只认这一形态。
        MenuNode d1 = new MenuNode("dashboard:view", "经营概览");
        // 客户服务（2026-11-06 组内顺序 = 在线接待 → 售后工单 → 知识库，与 menu.ts 逐项一致）
        MenuNode cs1 = new MenuNode("agent:session", "在线接待");
        // issue #5246：售后工单节点码 = **读**码 `after_sales:view`（原写码 `order:refund`）。
        MenuNode o3 = new MenuNode("after_sales:view", "售后工单");
        // issue #5246：知识库节点码 = **读**码 `knowledge:view`（原 `knowledge:manage`）。
        MenuNode cs2 = new MenuNode("knowledge:view", "知识库");
        // 订单/商品（2026-11-06 新组：旧「交易管理」+「基础资料」合并；组内顺序 = 用户逐字）
        MenuNode o1 = new MenuNode("order:list", "销售订单");
        MenuNode p1 = new MenuNode("product:list", "商品管理");
        // 价格本（issue #7375 段 3）：读面码 = 该页第一屏读码 `order:list`（`PricingController` 类级码）
        MenuNode priceBooks = new MenuNode("order:list", "价格本");
        MenuNode c1 = new MenuNode("customer:view", "客户列表");
        // 动作码节点：组尾追加（与权限页「操作权限」一节单独勾选的形态一致）
        MenuNode o2 = new MenuNode("order:detail", "订单详情");
        // 生产管理（issue #6580 起两项菜单项已移除；2026-11-06 计件工资移出本组 → 财务）
        MenuNode pr1 = new MenuNode("production:view", "作业单");
        MenuNode prPool = new MenuNode("processing:view", "智能派单");   // #5699 P4：= 该页读码
        // 质量管理（issue #8086 拆出独立组；2026-11-06 组名正名为「质量管理」）
        MenuNode pr4 = new MenuNode("production:inspect", "质检记录");
        MenuNode prRework = new MenuNode("after_sales:view", "返工单");
        // 仓储/物料（2026-11-06：入库单由供应链移入、排本组第一；组内顺序 = 用户逐字）
        MenuNode i1 = new MenuNode("inbound:view", "入库单");
        MenuNode stocktakes = new MenuNode("stock:view", "盘点单");
        MenuNode iOutbound = new MenuNode("stock:view", "出库单");
        MenuNode i2 = new MenuNode("order:list", "发货单");
        MenuNode prLedger = new MenuNode("product:list", "库存明细");
        MenuNode prRemnants = new MenuNode("processing:manage", "余料台账");
        MenuNode prSaving = new MenuNode("product:list", "省料分析");   // #5699 P4：= 该页读码
        // 财务（2026-11-06 新组）：财务对账 + 计件工资（后者由生产管理移入 —— 计件是结算）
        MenuNode f1 = new MenuNode("finance:view", "财务对账");
        MenuNode pr3 = new MenuNode("production:view", "计件工资");
        // 供应链（issue #7369；2026-11-06 组内顺序 = 采购单 → 供应商，入库单已移出本组）
        MenuNode iPurchases = new MenuNode("purchase:view", "采购单");
        MenuNode iSupplier = new MenuNode("supplier:view", "供应商");
        // 组织管理（#6580 起「企业基础设置」已移出本组 ⇒ 只剩人与权限）
        MenuNode e1 = new MenuNode("employee:list", "员工管理");
        MenuNode r1 = new MenuNode("system:view", "岗位权限");
        // 🔴 本节点**不是菜单项** —— 它只为让经营域那个码**仍可授予**：企业信息 / AI 客服 /
        // 工人端页面 / 通知设置都挂 `system:manage`，而菜单项 `/settings` 已改挂
        // `production:view` ⇒ 若此处不留一个 `system:manage` 节点，该码会从**权限勾选树**里
        // 彻底消失（页内经营域随之永远无法授予，只能靠 DB 手改）。
        // 「它为什么不是菜单项」逐条登记在
        // `tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py` 的
        // `ACTION_NODES['org-center']`（该守卫对组内多出节点的判据就是这个台账：**只许登记、
        // 不许放宽判据**）。
        MenuNode s1 = new MenuNode("system:manage", "企业基础设置（经营域）");
        // 动作码节点：组尾追加
        MenuNode e2 = new MenuNode("employee:create", "新增员工");
        // 🔴 issue #6759（2026-10-12）：两个**手机端写码**补进权限勾选树（用户当日裁定
        // 「手机端两个写动作码要补进员工管理的个人权限勾选树」）—— 它们是**动作**（不是菜单项），
        // 所以按本树既有口径**追加在各自业务域的组尾**（导航项必须保持为它们之前的连续前缀）。
        // 中文名逐字取 `rbac/manifest.json` 的 `codes.names`（改这里必须同批改
        // `tests/unit_ci_workflows/test_rbac_derived_pages.py` 的 `ACTION_NODE_CODES` 与
        // `tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py` 的 `ACTION_NODES`，
        // 并重生成 `rbac/readings.json` —— 缺一即红）。
        MenuNode prUpdate = new MenuNode("processing:update", "加工单操作");
        MenuNode iCreate = new MenuNode("inbound:create", "入库单操作");

        return List.of(
            // 🔴 最前席位一级项「经营概览」（前端 `standaloneHeadItems`）—— 三处同批表达同一位置：
            // 本处（顶层**首个**节点）/ `AuthService` 的**首个**顶层 add / 前端 `standaloneHeadItems`
            // （三源同构守卫按**顶层布局序列**比对，含位置）。
            new MenuNode("dashboard:view", "经营概览"),
            // 报表中心（issue #7376 / #7377）：与经营概览同属**经营数据面** ⇒ 紧随其后、同为最前席位；
            // 码取同一把尺子 `dashboard:view`（报表是看板的下钻，零授权 delta）。
            new MenuNode("dashboard:view", "报表中心"),
            // 客户服务（#5778 新建；2026-11-06 用户重新给定组内顺序）
            new MenuNode("customer-service", "客户服务", List.of(cs1, o3, cs2)),
            // 订单/商品（2026-11-06 新组）：旧「交易管理」（#5271 收窄为下单 → 收款）+ 旧「基础资料」
            // （#8086）合并 —— 用户本轮把「销售订单 / 商品管理 / 价格本 / 客户列表」定为同一组。
            new MenuNode("orders-products", "订单/商品", List.of(o1, p1, priceBooks, c1, o2)),
            // 生产管理（2026-11-06：计件工资移出 ⇒ 作业单 / 智能派单；组尾动作码 = 加工单操作）
            new MenuNode("production-center", "生产管理", List.of(pr1, prPool, prUpdate)),
            // 质量管理（2026-11-06：组名由「质量」正名为「质量管理」；码不动，拆码见 issue #8087）
            new MenuNode("quality", "质量管理", List.of(pr4, prRework)),
            // 仓储/物料（2026-11-06：组名由「仓储与物料」正名；入库单移入并排第一；组尾动作码 = 入库单操作）
            new MenuNode("inventory-center", "仓储/物料",
                    List.of(i1, stocktakes, iOutbound, i2, prLedger, prRemnants, prSaving, iCreate)),
            // 财务（2026-11-06 新组）：财务对账 + 计件工资
            new MenuNode("finance-center", "财务", List.of(f1, pr3)),
            // 供应链（2026-11-06：入库单移出 ⇒ 采购单 / 供应商）
            new MenuNode("supply-chain", "供应链", List.of(iPurchases, iSupplier)),
            // 🔴 尾席位一级项「企业基础设置」（前端 `standaloneTopItems`）——
            // 2026-11-06 用户裁定：**排在供应链之后、组织管理之前**（前端由
            // `STANDALONE_TOP_AFTER_GROUP_KEY = 'supply-chain'` 表达同一位置）。
            // 🔴 **两种写法都要有**（见方法头注释）：变量声明给 parity 解析器，本内联节点给布局解析器。
            // ⚠️ 本树**有意不含**尾部「通知中心」（无权限码、不进权限勾选树；三源同构守卫比对时
            // 从前端侧按**条目数**去掉尾部项）。
            new MenuNode("production:view", "企业基础设置"),
            new MenuNode("org-center", "组织管理", List.of(e1, r1, s1, e2))
        );
    }

    @GetMapping
    public ApiResponse<List<MenuNode>> getMenuTree() {
        return ApiResponse.success(ANNOTATED_MENU_TREE);
    }

    // ══════════════════════════ 手机端可见面标注（issue #6759） ══════════════════════════

    /**
     * 把「权限码 → 手机端可见面中文名」写到树上每个节点上（{@link MenuNode#addMobileTitle}）。
     *
     * <p><b>真值只有一份</b>：清单来自 {@code MobileSurfaces.ALL + TABS}（手机端菜单的服务端投影，
     * issue #6570/#6574 的用户裁定「走 B」）⇒ 本类只做**投影**，没有任何「码 → 手机端面」字面表。</p>
     *
     * <p><b>为什么是 public static 且收 {@code List<Surface>}</b>（issue #6759 的红证要求）：
     * 判据必须能喂一份**改过的**清单来证明「标注是派生的、不是硬编码的」——即改某个面的
     * {@code readPermission} ⇒ 对应节点的标注随之改变 / 消失。生产路径只调
     * {@link #annotateMobileTitles(List)}（清单固定 = 服务端真值）。</p>
     *
     * <p><b>落到哪些节点</b>（issue #6781 修法 1）：每个码**只**标注它在**树序上的首个承载节点** ——
     * 逐节点复制会踩 §31 P2（同屏重复：两个 {@code dashboard:view} 节点各带一遍「手机端：数据」）
     * 与 P4（名实不符：与生产面共用 {@code production:view} 的「企业基础设置」被告知会开通手机端报表）。
     * 规则是**确定的**（深度优先顺序 + 「该码是否已标注过」一个集合），不含任何名字匹配启发式。</p>
     */
    public static void annotateMobileTitles(List<MenuNode> tree, List<MobileSurfaces.Surface> surfaces) {
        Map<String, List<String>> byCode = mobileTitlesByCode(surfaces);
        // 🔴 issue #6781（修法 1）：一个权限码在树上有多个承载节点（#5699/#5291 的有意设计面，
        // 如 `production:view` 三处承载 = 作业看板 / 计件工资 / 企业基础设置）——
        // 标注**只落到该码在树序上的首个承载节点**。逐节点复制会同时踩两条 §31：
        //   · P2 信息不重复：「作业看板 · 手机端：计件工资报表、生产待办 / 计件工资 · 手机端：计件工资报表、
        //     生产待办」同屏两条一模一样的标注；
        //   · P4 可据以行动：「企业基础设置 · 手机端：计件工资报表、生产待办」名实不符
        //     （勾它的真实意图是配置生产面，与手机端报表无关）。
        Set<String> annotatedCodes = new HashSet<>();
        for (MenuNode node : tree) {
            annotateFirstCarrierOnly(node, byCode, annotatedCodes);
        }
    }

    /**
     * 生产入口：用**服务端真值**（{@code MobileSurfaces.ALL + TABS}）标注整棵树。
     * 顺序 = {@code ALL} 在前、{@code TABS} 在后（只在「同一码既开页面入口又开底栏」时可见）。
     */
    public static void annotateMobileTitles(List<MenuNode> tree) {
        List<MobileSurfaces.Surface> surfaces = new ArrayList<>(MobileSurfaces.ALL);
        surfaces.addAll(MobileSurfaces.TABS);
        annotateMobileTitles(tree, surfaces);
    }

    /** 面清单 → `权限码 → [面中文名…]`（无码的面 —— 如底栏「问黄金策 / 我的」—— 不进索引）。 */
    private static Map<String, List<String>> mobileTitlesByCode(List<MobileSurfaces.Surface> surfaces) {
        Map<String, List<String>> byCode = new LinkedHashMap<>();
        for (MobileSurfaces.Surface surface : surfaces) {
            String code = surface.readPermission();
            if (code == null || code.isBlank()) {
                continue;
            }
            List<String> titles = byCode.computeIfAbsent(code, key -> new ArrayList<>());
            if (!titles.contains(surface.title())) {
                titles.add(surface.title());
            }
        }
        return byCode;
    }

    /**
     * 深度优先（= 树序 / 渲染顺序）把标注写到**该码的首个承载节点**上（issue #6781 修法 1）。
     *
     * <p>读不到手机端面的码不进 {@code byCode}；同码后继节点直接跳过（不再追加任何标注）。</p>
     */
    private static void annotateFirstCarrierOnly(MenuNode node, Map<String, List<String>> byCode,
                                                 Set<String> annotatedCodes) {
        String code = node.getCode();
        if (byCode.containsKey(code) && annotatedCodes.add(code)) {
            for (String title : byCode.get(code)) {
                node.addMobileTitle(title);
            }
        }
        List<MenuNode> children = node.getChildren();
        if (children != null) {
            for (MenuNode child : children) {
                annotateFirstCarrierOnly(child, byCode, annotatedCodes);
            }
        }
    }
}