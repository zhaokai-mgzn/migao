package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * 订单实体类
 * 对应表：orders
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("orders")
public class Order {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String orderNo;

    private String customerName;

    private String customerPhone;

    private String customerAddress;

    /**
     * 收货——物流类型（issue #4872；V100：{@code orders.logistics_type VARCHAR(16) DEFAULT 'express'}）：
     * {@code express} 快递 / {@code logistics} 物流专线。NULL = 建单未传 ⇒ 由列默认承担。
     */
    private String logisticsType;

    /**
     * 收货——物流/快递公司（issue #4872；V100：{@code orders.logistics_company VARCHAR(128)}）。
     * NULL = 建单未传（不猜）。
     */
    private String logisticsCompany;

    /**
     * 订单级**加急标记**（V120，issue #5177）—— {@code true} = 该单**插队**：**不进池**、
     * 立刻走既有**单订单**路径派工（{@code pooled=false}）；把它混进 {@code pooled=true} 的
     * 成批批次 ⇒ **整批显式拒绝**（{@code ProcessingOrderService.assertNoUrgentInPooledBatch}）。
     *
     * <p>🔴 <b>与售后工单的 {@code priority} 不共享来源、不联动、不派生</b>（用户裁定逐字：
     * 「加急不能跟售后工单绑定，得在订单上直接做」）—— 售后 {@code priority} 描述「工单处理的
     * 紧急度」，本列描述「这张单要不要插队派工」，是**两个事实**：绑定会同时坏掉两边
     * （给订单标加急会改掉售后排班序，改售后优先级又会让生产插队）。售后 {@code priority}
     * 只作**命名/文案风格**先例，**不是**数据来源。</p>
     *
     * <p>列 {@code NOT NULL DEFAULT FALSE}（V120）⇒ <b>没有第三态</b>：「未标加急」与
     * 「明确不加急」同值。建单/改单都不传 ⇒ 落 {@code FALSE} ⇒ 行为与今天逐字相同
     * （记录期零污染）。</p>
     *
     * <p>⚠️ 类型必须是 {@code Boolean} 而**不是** {@code boolean}：字段名以 {@code is} 开头时，
     * 原生布尔的 Lombok getter 是 {@code isUrgent()}，JavaBeans 推出的属性名会变成
     * {@code urgent} ⇒ 与列名 {@code is_urgent} 及 DTO 的 JSON 键 {@code isUrgent} 双双对不上
     * （读面静默丢值）。</p>
     */
    private Boolean isUrgent;

    /**
     * **客户要求到货日**（V120，issue #5177；{@code orders.required_delivery_date DATE}）。
     *
     * <p>NULL = <b>未指定</b>（**不猜、不回填** —— 存量单从未采集过这个外部事实，
     * 回填就是编一个日期）。消费者 = **池看板的排序/筛选**（到货日升序、NULL 排**最后**，
     * 不得当成「最紧急」）。它**不影响**对客价格、售价、成品、交期承诺（判据 6）。</p>
     */
    private LocalDate requiredDeliveryDate;

    /**
     * 下单用户 ID（users.id，C 端数据隔离依据；
     * 商户代下单可为空或商户员工 ID）
     */
    private String userId;

    private BigDecimal totalAmount;

    /**
     * 实收款（用户输入的实际收款金额，默认等于 totalAmount）
     */
    private BigDecimal actualAmount;

    /**
     * 优惠金额（应收 totalAmount 与实收 actualAmount 之间的差额，默认 0）
     */
    private BigDecimal discountAmount;

    /**
     * 累计已退款金额（退款/售后完结时累加，默认 0；>0 表示"已退款"）
     */
    private BigDecimal refundAmount;

    /**
     * 最近一次退款时间
     */
    private OffsetDateTime refundAt;

    private String status;

    /**
     * 跟进状态: pending/following/completed
     */
    private String followStatus;

    private String remark;

    /**
     * 关闭原因
     */
    private String closeReason;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
