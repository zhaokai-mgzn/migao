package com.migao.admin.dto;

import lombok.EqualsAndHashCode;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.ToString;

import java.util.ArrayList;
import java.util.List;

/**
 * 菜单树节点（一级 + 二级，用于权限多选 UI）
 *
 * <p>issue #6759：{@link #mobileTitles} = 该节点**权限码**在手机端（bmini H5 / 小程序）对应的
 * 可见面中文名 —— 让管理员在权限勾选树上看得见「勾这个码 = 员工手机上多一个入口」。
 * 真值**现取** {@code MobileSurfaces}（服务端投影的唯一真值，issue #6570/#6574），由
 * {@code MenuController} 派生；🔴 前端**只渲染服务端给的**，不得自备「码 → 手机端面」映射表
 * （第二份会漂的真值；判据 =
 * {@code tests/unit_ci_workflows/test_mobile_surface_annotation_single_source.py}）。</p>
 *
 * <p>空清单 = 该码在手机端**没有**任何面（如 {@code order:list} / {@code employee:create}
 * 这类纯 PC 权限）⇒ 前端不追加任何标注（不摆内部标识、不产生噪音）。</p>
 */
@Getter
@ToString
@EqualsAndHashCode
@NoArgsConstructor
public class MenuNode {
    private String code;
    private String label;
    private List<MenuNode> children;
    /** 该节点权限码对应的手机端可见面中文名（派生自 {@code MobileSurfaces}；无码 / 无面 ⇒ 空）。 */
    private List<String> mobileTitles = new ArrayList<>();

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

    /**
     * 追加一个手机端可见面中文名（派生期调用；同码多节点各是独立对象 ⇒ 无共享可变状态）。
     * 幂等：同名不重复追加。
     */
    public void addMobileTitle(String title) {
        List<String> next = new ArrayList<>(this.mobileTitles == null ? List.of() : this.mobileTitles);
        if (title != null && !title.isBlank() && !next.contains(title)) {
            next.add(title);
        }
        this.mobileTitles = next;
    }
}
