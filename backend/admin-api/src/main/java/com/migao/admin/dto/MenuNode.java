package com.migao.admin.dto;

import lombok.EqualsAndHashCode;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.ToString;

import java.util.ArrayList;
import java.util.List;

/**
 * 菜单树节点（一级 + 二级，用于权限多选 UI）
 */
@Getter
@ToString
@EqualsAndHashCode
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
