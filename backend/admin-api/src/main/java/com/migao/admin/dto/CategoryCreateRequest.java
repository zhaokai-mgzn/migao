package com.migao.admin.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
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
     * 父分类ID（已废弃：父子概念移除，服务端忽略）
     */
    private String parentId;

    /**
     * 层级（已废弃：服务端固定为 1）
     */
    private Integer level = 1;

    /**
     * 排序号（JSON 契约字段名为 sort，DB 列 sort_order）。
     * 未传（null）时服务端自动追加到列表末尾
     */
    @JsonProperty("sort")
    private Integer sortOrder;

    /**
     * 图标
     */
    private String icon;

    /**
     * 状态：active（启用）、inactive（禁用）
     */
    private String status = "active";
}
