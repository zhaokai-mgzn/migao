package com.aikf.admin.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

/**
 * 加工分类更新请求 DTO
 */
@Data
public class ProcessingCategoryUpdateRequest {

    /**
     * 分类名称
     */
    @NotBlank(message = "分类名称不能为空")
    private String name;

    /**
     * 排序号
     */
    private Integer sortOrder;

    /**
     * 状态：active（启用）、inactive（禁用）
     */
    private String status;
}
