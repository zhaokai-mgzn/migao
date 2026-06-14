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
        MenuNode d1 = new MenuNode("dashboard.view", "数据看板");
        MenuNode o1 = new MenuNode("orders.list", "订单列表");
        MenuNode o2 = new MenuNode("orders.detail", "订单详情");
        MenuNode o3 = new MenuNode("orders.refund", "退换货");
        MenuNode p1 = new MenuNode("products.list", "商品列表");
        MenuNode p2 = new MenuNode("products.create", "新增商品");
        MenuNode p3 = new MenuNode("products.categories", "商品分类管理");
        MenuNode p4 = new MenuNode("products.processing", "加工项管理");
        MenuNode a1 = new MenuNode("agent.sessions", "会话监控");
        MenuNode a2 = new MenuNode("agent.quickreplies", "快捷回复");
        MenuNode e1 = new MenuNode("employees.list", "员工列表");
        MenuNode e2 = new MenuNode("employees.create", "新增员工");
        MenuNode s1 = new MenuNode("settings.tenant", "租户设置");

        return List.of(
            new MenuNode("dashboard", "工作台", List.of(d1)),
            new MenuNode("orders", "订单管理", List.of(o1, o2, o3)),
            new MenuNode("products", "商品管理", List.of(p1, p2, p3, p4)),
            new MenuNode("agent", "客服工作台", List.of(a1, a2)),
            new MenuNode("employees", "员工管理", List.of(e1, e2)),
            new MenuNode("settings", "系统设置", List.of(s1))
        );
    }

    @GetMapping
    public ApiResponse<List<MenuNode>> getMenuTree() {
        return ApiResponse.success(MENU_TREE);
    }
}
