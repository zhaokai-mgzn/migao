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
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/menus")
@RequiredArgsConstructor
public class MenuController {

    private static final List<MenuNode> MENU_TREE = buildMenuTree();

    private static List<MenuNode> buildMenuTree() {
        // 权限码格式: 模块:操作 — 与 DB permissions.code 格式一致
        MenuNode d1 = new MenuNode("dashboard:view", "经营看板");
        MenuNode o1 = new MenuNode("order:list", "订单列表");
        MenuNode o2 = new MenuNode("order:detail", "订单详情");
        MenuNode o3 = new MenuNode("order:refund", "退换货");
        MenuNode p1 = new MenuNode("product:list", "商品列表");
        MenuNode p2 = new MenuNode("product:create", "新增商品");
        MenuNode p3 = new MenuNode("product:category", "商品分类管理");
        MenuNode p4 = new MenuNode("processing:manage", "加工项管理");
        // 生产管理（issue #4203/#4205 后端半边 + #4308 的「工艺路线」第四项）：节点共用 processing:manage ——
        // 与 AuthService.buildMenusByPermissions 的侧边栏节点**必须同构**（否则「岗位权限」页
        // 勾得动、侧边栏看不到），也与前端 menu.ts 同构。
        MenuNode pr1 = new MenuNode("processing:manage", "生产看板");
        // 池看板（issue #5177）：与 AuthService.buildMenusByPermissions 的侧边栏节点、
        // 前端 config/menu.ts 的 `production-pool` **三处同构**（漏一处 = 「岗位权限页勾得动、
        // 侧边栏看不到」）；权限码沿用 processing:manage（不新造权限码）。
        MenuNode prPool = new MenuNode("processing:manage", "池看板");
        // 省料看板（issue #5159）：与 AuthService.buildMenusByPermissions 的侧边栏节点、
        // 前端 config/menu.ts 的 `production-saving-board` **三处同构**
        // （漏一处 = 「岗位权限页勾得动、侧边栏看不到」）；权限码沿用 processing:manage。
        MenuNode prSaving = new MenuNode("processing:manage", "省料看板");
        // 余料台账（issue #5191）：与 AuthService.buildMenusByPermissions 的侧边栏节点、
        // 前端 config/menu.ts 的 `production-remnants` **三处同构**
        // （漏一处 = 「岗位权限页勾得动、侧边栏看不到」）；权限码沿用 processing:manage
        // —— 与 RemnantController 的类级 @RequirePermission 同码。
        MenuNode prRemnants = new MenuNode("processing:manage", "余料台账");
        // 🔴 「工艺配置」= issue #4416 把「工序库」+「工艺路线」**合并为单一入口**后的名称
        // （工序库半边 = 该页左栏；旧路径 /production/operations 保留为重定向）。
        // issue #4440：本树此前仍是**合并前**的两个节点（工序库 / 工艺路线）⇒ 与前端 config/menu.ts 漂移，
        // 而前端「岗位权限」页**确实消费**本树（`GET /api/admin/menus`）⇒ 商家勾选的菜单项与真实侧边栏对不上。
        // 权限码沿用 processing:manage（不要新造权限码）。
        MenuNode pr2 = new MenuNode("processing:manage", "工艺配置");
        MenuNode pr3 = new MenuNode("processing:manage", "计件工资");
        MenuNode a1 = new MenuNode("agent:session", "会话监控");
        MenuNode e1 = new MenuNode("employee:list", "员工列表");
        MenuNode e2 = new MenuNode("employee:create", "新增员工");
        MenuNode s1 = new MenuNode("system:manage", "租户设置");
        // 入库单（V111，issue #5034）：与 AuthService.buildMenusByPermissions 的侧边栏节点、
        // 前端 config/menu.ts **必须同构**（否则「岗位权限」页勾得动、侧边栏看不到）。
        // 权限码 = inbound:view（列表）—— 与 @RequirePermission("inbound:view") 同码。
        MenuNode i1 = new MenuNode("inbound:view", "入库单");
        MenuNode c1 = new MenuNode("customer:view", "客户管理");
        MenuNode f1 = new MenuNode("finance:view", "财务对账");

        return List.of(
            new MenuNode("dashboard", "工作台", List.of(d1)),
            new MenuNode("orders", "订单管理", List.of(o1, o2, o3)),
            new MenuNode("products", "商品管理", List.of(p1, p2, p3, p4)),
            new MenuNode("production", "生产管理", List.of(pr1, prPool, prSaving, prRemnants, pr2, pr3, i1)),
            new MenuNode("agent", "客服工作台", List.of(a1)),
            new MenuNode("employees", "员工管理", List.of(e1, e2)),
            new MenuNode("customers", "客户管理", List.of(c1)),
            new MenuNode("finance", "财务对账", List.of(f1)),
            new MenuNode("settings", "系统设置", List.of(s1))
        );
    }

    @GetMapping
    public ApiResponse<List<MenuNode>> getMenuTree() {
        return ApiResponse.success(MENU_TREE);
    }
}
