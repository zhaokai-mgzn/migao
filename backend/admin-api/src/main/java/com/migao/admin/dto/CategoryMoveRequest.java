package com.migao.admin.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

/**
 * 分类移动请求 DTO
 * direction: up（上移）/ down（下移）
 */
@Data
public class CategoryMoveRequest {

    /**
     * 移动方向：up / down
     */
    @NotBlank(message = "direction 不能为空")
    private String direction;
}