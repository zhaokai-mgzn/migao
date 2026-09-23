package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.MenuNode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

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
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/menus")
@RequiredArgsConstructor
public class MenuController {

    private static final List<MenuNode> MENU_TREE = buildMenuTree();

    private static List<MenuNode> buildMenuTree() {
        // 权限码格式: 模块:操作 — 与 DB permissions.code 格式一致。
        //
        // 🔴 issue #5271 菜单重设计（信息架构按业务动线重排）：本树的**顶层组 = 前端
        // `frontend/admin-web/src/config/menu.ts` 的 `menuGroups`**（组 key / 组名 / 组顺序），
        // 组内节点 = 该组的**菜单项**（label 与菜单名**逐字一致**）+ 该业务域的**动作码节点**
        // （后者**统一追加在组尾** —— 集成方口径：导航项必须是动作码节点之前的连续前缀子序列）。
        // 本树是 `GET /api/admin/menus` 的读面，被前端「员工管理」页渲染成权限勾选树
        // （`children[].code` → `label`）—— 与 `AuthService.buildMenusByPermissions`（登录下发菜单）、
        // 前端 `config/menu.ts`（真实侧边栏）**三处同构**；漏一处就是「岗位权限页勾得动、
        // 侧边栏看不到」（issue #4203 点名的同族坑）。
        // 判据：tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py（#5271 起比对全树）。
        //
        // 本次重排相对旧树的变化：
        //   · 新建 `inventory-center`（仓储与物料）组 —— 从「生产管理」组拆出入库单 / 余料台账 / 省料看板；
        //   · `customer-center`（客户管理）组**不再存在** —— 客户列表、财务对账并入 `trade-center`；
        //   · 组 key `production` → **`production-center`**（与前端 / AuthService 收口，三源一致）；
        //   · 组名「商品管理」→「商品与加工项」、「订单管理」→「交易管理」；
        //   · 旧顶层组 `dashboard` / `orders` / `products` / `employees` / `customers` / `finance` /
        //     `settings` / `agent` 全部并入下列七组，**不再作为顶层组**。
        MenuNode d1 = new MenuNode("dashboard:view", "经营看板");
        // 每日简报（issue #3468）：与「经营看板」**同码** `dashboard:view` —— 本树沿用既有形态
        // 「多个导航节点共用一个权限码」（同生产管理组的 processing:manage 四节点）。
        // ⚠️ 企业开关**不在服务端**过滤（服务端拿不到该开关）：开关由前端按 `menu.ts` 的
        // `briefingToggle` 判定后隐藏该项，本树只负责权限码这一维。
        MenuNode d2 = new MenuNode("dashboard:view", "每日简报");
        // 智能客服：🔴 旧节点 `new MenuNode("agent:session", "会话监控")` 在 #5271 **删除** ——
        // `agent:session` 已由「在线接待」承载，而「会话监控」对应的页面 `/agent-workspace/sessions`
        // 从来不在侧边栏里 ⇒ 它只是权限树上一个重复勾选项。
        // （#3094 已把「米宝 · 在线对话」菜单入口移除，智能体对话走右下角 FAB。）
        MenuNode cs1 = new MenuNode("agent:session", "在线接待");
        // issue #5246（已合入 main）：知识库节点码 = **读**码 `knowledge:view`（原 `knowledge:manage`）——
        // #5271 重排本树时必须保留该码（漏带 = 静默回退别人刚修的授权口径）。
        MenuNode cs2 = new MenuNode("knowledge:view", "知识库");
        MenuNode p1 = new MenuNode("product:list", "商品列表");
        MenuNode p4 = new MenuNode("processing:manage", "加工项管理");
        // 动作码节点（非菜单项）：与菜单项同域，**统一追加在组尾**（导航项 = 前缀子序列）
        MenuNode p2 = new MenuNode("product:create", "新增商品");
        MenuNode p3 = new MenuNode("product:category", "商品分类管理");
        MenuNode o1 = new MenuNode("order:list", "订单列表");
        // 旧 label「退换货」→「售后工单」（#5271 改名消除与菜单名的漂移）；
        // code 由 issue #5246 改为**读**码 `after_sales:view`（原写码 `order:refund`）。
        MenuNode o3 = new MenuNode("after_sales:view", "售后工单");
        // 旧 label「客户管理」→「客户列表」（#5271；code 不变 customer:view）——
        // 该节点原挂在已消失的 `customers` 顶层组，现随交易动线并入 `trade-center`。
        MenuNode c1 = new MenuNode("customer:view", "客户列表");
        MenuNode f1 = new MenuNode("finance:view", "财务对账");
        // 动作码节点：组尾追加（与权限页「操作权限」一节单独勾选的形态一致）
        MenuNode o2 = new MenuNode("order:detail", "订单详情");
        // 生产管理（issue #4203/#4205/#4308/#5177）：四项共用 processing:manage ——
        // 与 `AuthService.buildMenusByPermissions` 的侧边栏节点、前端 menu.ts **三处同构**
        // （漏一处 = 「岗位权限页勾得动、侧边栏看不到」）。
        MenuNode pr1 = new MenuNode("processing:manage", "生产看板");
        MenuNode prPool = new MenuNode("processing:manage", "池看板");
        // 🔴 「工艺配置」= issue #4416 把「工序库」+「工艺路线」**合并为单一入口**后的名称
        // （工序库半边 = 该页左栏；旧路径 /production/operations 保留为重定向）。
        // 权限码沿用 processing:manage（不要新造权限码）。
        MenuNode pr2 = new MenuNode("processing:manage", "工艺配置");
        MenuNode pr3 = new MenuNode("processing:manage", "计件工资");
        // 仓储与物料（issue #5271 **新组**）：面料进出与消耗 —— 入库 → 批次 → 余料 → 省料。
        // 入库单（V111，issue #5034）权限码**独立**（inbound:view，与 @RequirePermission 同码）；
        // 余料台账（issue #5191）/ 省料看板（issue #5159）沿用 processing:manage ——
        // 与 RemnantController 的类级 @RequirePermission 同码（门禁不放宽也不收紧）。
        MenuNode i1 = new MenuNode("inbound:view", "入库单");
        MenuNode prRemnants = new MenuNode("processing:manage", "余料台账");
        MenuNode prSaving = new MenuNode("processing:manage", "省料看板");
        // 旧 label「员工列表」→「员工管理」（#5271；code 不变 employee:list）
        MenuNode e1 = new MenuNode("employee:list", "员工管理");
        MenuNode r1 = new MenuNode("system:manage", "岗位权限");
        // 旧 label「租户设置」→「企业基础信息」（#5271；code 不变 system:manage）——
        // 节点原挂在已消失的 `settings` 顶层组，现随组织面并入 `org-center`。
        MenuNode s1 = new MenuNode("system:manage", "企业基础信息");
        // 动作码节点：组尾追加
        MenuNode e2 = new MenuNode("employee:create", "新增员工");

        return List.of(
            new MenuNode("workspace", "工作台", List.of(d1, d2)),
            new MenuNode("smart-customer-service", "智能客服", List.of(cs1, cs2)),
            new MenuNode("product-center", "商品与加工项", List.of(p1, p4, p2, p3)),
            new MenuNode("trade-center", "交易管理", List.of(o1, o3, c1, f1, o2)),
            new MenuNode("production-center", "生产管理", List.of(pr1, prPool, pr2, pr3)),
            new MenuNode("inventory-center", "仓储与物料", List.of(i1, prRemnants, prSaving)),
            new MenuNode("org-center", "组织管理", List.of(e1, r1, s1, e2))
        );
    }

    @GetMapping
    public ApiResponse<List<MenuNode>> getMenuTree() {
        return ApiResponse.success(MENU_TREE);
    }
}