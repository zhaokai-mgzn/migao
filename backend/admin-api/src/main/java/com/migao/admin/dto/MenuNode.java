package com.migao.admin.dto;

import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * 菜单树节点（一级 + 二级，用于权限多选 UI）
 */
@Data
@NoArgsConstructor
public class MenuNode {
    private String code;
    private String label;
    private List<MenuNode> children;

    public MenuNode(String code, String label) {
        this.code = code;
        this.label = label;
        this.children = new ArrayList<>();
    }

    public MenuNode(String code, String label, List<MenuNode> children) {
        this.code = code;
        this.label = label;
        this.children = children != null ? children : new ArrayList<>();
    }
}
