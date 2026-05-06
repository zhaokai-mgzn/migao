package com.aikf.admin.dto;

import lombok.Builder;
import lombok.Data;

/**
 * 企业入驻申请提交结果 DTO
 */
@Data
@Builder
public class RegistrationResponse {

    /**
     * 申请ID
     */
    private Long applicationId;

    /**
     * 申请状态
     */
    private String status;

    /**
     * 提示消息
     */
    private String message;
}
