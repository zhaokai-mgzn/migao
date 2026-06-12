package com.migao.admin.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

/**
 * 分类创建请求 DTO
 */
@Data
public class CategoryCreateRequest {

    /**
     * 分类名称
     */
    @NotBlank(message = "分类名称不能为空")
    private String name;

    /**
     * 父分类ID（为空表示顶级分类）
     */
    private String parentId;

    /**
     * 层级
     */
    private Integer level = 1;

    /**
     * 排序号
     */
    private Integer sortOrder = 0;

    /**
     * 图标
     */
    private String icon;

    /**
     * 状态：active（启用）、inactive（禁用）
     */
    private String status = "active";
}
