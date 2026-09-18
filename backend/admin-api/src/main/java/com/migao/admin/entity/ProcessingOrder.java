package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * 加工单实体（issue #3340）
 * 对应表：processing_orders —— 订单 producing 阶段的子进度。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "processing_orders", autoResultMap = true)
public class ProcessingOrder {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String orderId;

    /** 业务单号 JG-YYYYMMDD-序号（DB 唯一约束防重号） */
    private String processingOrderNo;

    /** 加工方（文本，MVP 不建主数据） */
    private String processor;

    /** 交期（手工填写，决策 3） */
    private LocalDate expectedDeliveryDate;

    /** generated/issued/in_processing/completed/cancelled */
    private String status;

    /** 生成时快照：不含销售价（决策 2），加工项含 options */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Object itemsSnapshot;

    private String remark;

    private Integer templateVersion;

    private String generatedBy;

    private OffsetDateTime generatedAt;

    private OffsetDateTime issuedAt;

    private OffsetDateTime inProcessingAt;

    private OffsetDateTime completedAt;

    private OffsetDateTime cancelledAt;

    private String cancelledReason;

    private Integer printCount;

    /** 加工单二维码 token（V49，扫码报工入口；32 位 UUID 去横线） */
    private String qrToken;

    /**
     * 本单**实际使用**的路线键「帘种×工艺」（V60，issue #4308）。
     *
     * <p>T1/T2 时 = 默认 {@code 布帘×韩褶}（与真正实例化出的工序对应）。多部位订单取**最需关注**
     * 的那一条（{@code default} &gt; {@code missing_route} &gt; {@code partial} &gt; {@code derived}）——
     * 列是单值 {@code VARCHAR(32)}，逐部位明细在工序实例里；存在的意义是让「这张单走了哪条路线」
     * 从**五要素快照之外**可查（此前 RouteKey.source 只在路线缺失的 error 日志里被读一次）。</p>
     */
    private String routeKey;

    /**
     * 本单**派生出来想用**的路线键（V60，issue #4308）。
     *
     * <p>两维全不命中（{@code route_source=default}）时为 NULL —— 没有这一列，
     * {@code missing_route} 的提示说不出「识别的 X 在库里没有路线」，用户拿不到可行动的下一步。</p>
     */
    private String routeRequestedKey;

    /**
     * 路线键来源（V60，issue #4308）：{@code derived} 两维均由库中信号命中且路线存在 /
     * {@code partial} 只命中一维（补救 = 补信号）/ {@code missing_route} 派生键在库中无路线
     * （补救 = 建路线）/ {@code default} 两维全不命中（补救 = 补信号）。
     */
    private String routeSource;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    private Integer deleted;
}
