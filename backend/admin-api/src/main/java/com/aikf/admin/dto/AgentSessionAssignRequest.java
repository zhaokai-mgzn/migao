package com.aikf.admin.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 人工客服会话手动分配请求 DTO
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class AgentSessionAssignRequest {

    @NotBlank(message = "客服员工ID不能为空")
    private String employeeId;
}
