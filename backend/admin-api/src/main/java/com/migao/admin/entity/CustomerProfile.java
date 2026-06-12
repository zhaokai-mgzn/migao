package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 客户档案实体类
 * 对应表：customer_profiles
 * 说明：CRM 核心表，存储客户完整画像
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "customer_profiles", autoResultMap = true)
public class CustomerProfile {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    // --- 基础信息 ---
    private String wechatOpenid;

    private String wechatUnionid;

    private String wechatNickname;

    private String phone;

    /** male / female / unknown */
    private String gender;

    private String regionProvince;

    private String regionCity;

    private String regionDistrict;

    private String avatarUrl;

    // --- 客户等级与状态 ---
    /** normal / vip1 / vip2 / vip3 */
    private String vipLevel;

    /** active / silent / churn_warning / churned */
    private String customerStatus;

    /** wechat_mini / h5 / web */
    private String sourceChannel;

    // --- RFM 评分 ---
    private Integer rScore;

    private Integer fScore;

    private Integer mScore;

    private Integer rfmTotalScore;

    // --- 统计数据 ---
    private Integer totalOrders;

    private BigDecimal totalConsumption;

    private BigDecimal totalRefundAmount;

    private BigDecimal avgOrderValue;

    private BigDecimal repurchaseRate;

    // --- 时间字段 ---
    private OffsetDateTime firstOrderAt;

    private OffsetDateTime lastOrderAt;

    private OffsetDateTime lastActiveAt;

    private OffsetDateTime registeredAt;

    // --- 备注与标签 ---
    private String agentNotes;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object tags;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object customFields;

    // --- 生命周期 ---
    /** new / growing / mature / declining / churned */
    private String lifecycleStage;

    private BigDecimal churnRiskScore;

    private Integer nextPurchasePredictionDays;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;
}
