package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 企业入驻申请实体类
 * 对应表：tenant_applications
 * 平台级表，不属于任何租户（无 tenant_id）
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("tenant_applications")
public class TenantApplication {

    @TableId(type = IdType.ASSIGN_ID)
    private Long id;

    private String companyName;

    private String contactName;

    private String phone;

    private String businessLicenseUrl;

    private String industry;

    private String address;

    private String description;

    private String status;

    private String rejectReason;

    private String reviewedBy;

    private OffsetDateTime reviewedAt;

    /** 企业名称规范化（去空格/括号/后缀），用于防重复提交精确匹配 */
    private String companyNameNorm;

    /** 甄别来源：ai（规则层/大模型）/ system（AI 服务不可用降级）/ manual（人工兜底 API） */
    private String reviewSource;

    /** 风险标记 JSON 数组字符串 */
    private String riskFlags;

    /** AI 审查摘要（面向运营/审计） */
    private String reviewSummary;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;
}
