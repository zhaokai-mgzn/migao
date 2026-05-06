package com.aikf.admin.dto;

import lombok.Data;

/**
 * 入驻审批请求 DTO
 */
@Data
public class RegistrationReviewRequest {

    /**
     * 驳回原因（驳回时必填）
     */
    private String rejectReason;
}
