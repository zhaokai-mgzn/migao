package com.migao.admin.dto;

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
     * 申请状态：approved（AI 甄别通过）/ rejected（AI 甄别驳回）/ pending（兜底，一般不出现）
     */
    private String status;

    /**
     * 提示消息
     */
    private String message;

    /**
     * 驳回原因（status=rejected 时返回，面向申请人）
     */
    private String rejectReason;
}
