package com.aikf.admin.entity;

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

    @TableId(type = IdType.AUTO)
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

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;
}
