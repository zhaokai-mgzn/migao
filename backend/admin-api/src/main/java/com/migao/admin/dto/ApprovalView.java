package com.migao.admin.dto;

import com.migao.admin.entity.Approval;
import lombok.Builder;
import lombok.Data;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 审批读面（issue #7374）—— 一次审批的完整留痕：谁申请、谁裁决、何时、批了多少钱、用在哪。
 */
@Data
@Builder
public class ApprovalView {

    private String id;

    private String objectType;

    private String objectRef;

    private String objectLabel;

    private BigDecimal amount;

    private String payload;

    private String reason;

    private String status;

    private String requestedBy;

    private String requestedByName;

    private OffsetDateTime requestedAt;

    private String decidedBy;

    private String decidedByName;

    private OffsetDateTime decidedAt;

    private String decisionNote;

    private OffsetDateTime consumedAt;

    private String consumedRef;

    public static ApprovalView of(Approval approval) {
        if (approval == null) {
            return null;
        }
        return ApprovalView.builder()
                .id(approval.getId())
                .objectType(approval.getObjectType())
                .objectRef(approval.getObjectRef())
                .objectLabel(approval.getObjectLabel())
                .amount(approval.getAmount())
                .payload(approval.getPayload())
                .reason(approval.getReason())
                .status(approval.getStatus())
                .requestedBy(approval.getRequestedBy())
                .requestedByName(approval.getRequestedByName())
                .requestedAt(approval.getRequestedAt())
                .decidedBy(approval.getDecidedBy())
                .decidedByName(approval.getDecidedByName())
                .decidedAt(approval.getDecidedAt())
                .decisionNote(approval.getDecisionNote())
                .consumedAt(approval.getConsumedAt())
                .consumedRef(approval.getConsumedRef())
                .build();
    }
}
