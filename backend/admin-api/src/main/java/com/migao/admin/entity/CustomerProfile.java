package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import com.fasterxml.jackson.annotation.JsonProperty;
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
    // 🔴 三个缩写字段的线上键名由 **getter 上的 @JsonProperty** 显式钉住（issue #5459）：
    //    `getRScore()` 这类「前两个字母都大写」的名字被 Jackson 的默认 Bean 命名折叠成全小写
    //    （rscore）⇒ 同一字段在「画像视图」（按 #5362 的**声明字段名**构造）与「列表 / 详情 / PUT」
    //    （实体直接序列化）两个面上名字不同。声明名是唯一基准 ⇒ 统一钉成 rScore / fScore / mScore。
    //    ⚠️ 注解**必须落在 getter 上**：实体字段是 private 且不带 Jackson 注解 ⇒ 对 Jackson 不可见，
    //    属性只由 `getXxx/setXxx` 派生；把 @JsonProperty 标在**字段**上会让字段变得可见，于是
    //    「字段 rScore」与「getter 折叠出的 rscore」变成**两个属性**（实测键数 42 → 45，多出
    //    rscore/fscore/mscore 三个重复键）。标在 getter 上则是把同一个属性**改名** ⇒ 键数仍是 42。
    //    判据：backend/admin-api/src/test/java/com/migao/admin/controller/CustomerProfileWireKeyParityTest.java
    private Integer rScore;

    private Integer fScore;

    private Integer mScore;

    @JsonProperty("rScore")
    public Integer getRScore() {
        return rScore;
    }

    @JsonProperty("fScore")
    public Integer getFScore() {
        return fScore;
    }

    @JsonProperty("mScore")
    public Integer getMScore() {
        return mScore;
    }

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

    // --- 工艺画像与常用物流（issue #3984，M2-D）---
    /** standard 跟随企业固定工艺 / economy 主动省料 / self_quoted 自报用料 */
    private String craftMode;

    /** 工艺偏好 JSON（开数/定型/档位等默认，M3-F 报价协商读取） */
    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object craftProfile;

    /** 常用物流类型：express 快递 / logistics 物流专线 */
    private String defaultLogisticsType;

    /** 客户常用物流/快递公司（下单自动带出） */
    private String defaultLogisticsCompany;

    // --- 默认收货信息（issue #4419，V70；客户管理「收货信息」卡片）---
    /** 默认收货人姓名（新增订单选客户自动带出） */
    private String defaultReceiverName;

    /** 默认收货人电话（新增订单选客户自动带出） */
    private String defaultReceiverPhone;

    /** 默认收货详细地址（单字段文本，与 orders.customer_address 同口径） */
    private String defaultReceiverAddress;

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
