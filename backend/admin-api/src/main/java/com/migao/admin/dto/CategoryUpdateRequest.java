package com.migao.admin.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;

/**
 * 分类更新请求 DTO
 */
@Data
public class CategoryUpdateRequest {

    /**
     * 分类名称
     */
    @NotBlank(message = "分类名称不能为空")
    private String name;

    /**
     * 父分类ID
     */
    private String parentId;

    /**
     * 层级
     */
    private Integer level;

    /**
     * 排序号（JSON 字段名 sortOrder，DB 列 sort_order）
     *
     * <p>issue #9007：与创建请求同口径 —— 主名 {@code sortOrder}，{@code sort} 保留为兼容别名。
     */
    @JsonAlias("sort")
    private Integer sortOrder;

    /**
     * 图标
     */
    private String icon;

    /**
     * 状态：active（启用）、inactive（禁用）
     */
    private String status;
}
