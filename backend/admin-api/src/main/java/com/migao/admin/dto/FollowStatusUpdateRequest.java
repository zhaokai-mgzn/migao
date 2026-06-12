package com.migao.admin.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

/**
 * 跟进状态更新请求 DTO
 */
@Data
public class FollowStatusUpdateRequest {

    @NotBlank(message = "跟进状态不能为空")
    private String followStatus;
}
