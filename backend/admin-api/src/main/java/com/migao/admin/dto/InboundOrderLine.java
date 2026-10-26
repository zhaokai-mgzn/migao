package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * 入库单列表行（V111，issue #5034）—— 含明细聚合（行数 / 总数量）。
 *
 * <p>字段名与 {@code InboundOrderQueryMapper.selectOrderLines} 的 SELECT 别名一一对应
 * （MyBatis 按列别名映射到属性名）。</p>
 */
@Data
public class InboundOrderLine {

    private String id;

    /** 入库单号 RK-yyyyMMdd-NNNN */
    private String inboundNo;

    private String supplier;

    private String supplierDocNo;

    private String warehouse;

    private LocalDate inboundDate;

    /** draft / posted / cancelled */
    private String status;

    /**
     * 业务类别（V196）：{@link com.migao.admin.entity.InboundOrder#BIZ_FABRIC} 原料 /
     * {@link com.migao.admin.entity.InboundOrder#BIZ_FINISHED} 成品。
     *
     * <p>列表页按它分成「原料仓入库 / 成品仓入库」两个视图（issue #7794）：两类单的列与入口不同
     * （成品单只由打包自动建，视图内不渲染建单入口）。</p>
     */
    private String bizCategory;

    private BigDecimal totalAmount;

    private String remark;

    private OffsetDateTime postedAt;

    private String postedBy;

    private OffsetDateTime createdAt;

    /** 明细行数（聚合） */
    private Integer itemCount;

    /** 明细总数量（聚合） */
    private Integer totalQuantity;

    /**
     * **套数合计**（聚合；issue #7794）—— 成品视图那一列。
     *
     * <p>成品入库按「套 × 部位」逐行入库（V197 / issue #7762）⇒ 行数 = 部位数、套数 = 套的个数，
     * 两个数**不同**。没有套号的存量行（V196 订单行粒度：一行 = 一件成品 = 一套）按一行一套计
     * —— 见 {@code InboundOrderQueryMapper} 的 {@code set_count} 聚合。</p>
     */
    private Integer setCount;

    /**
     * 该单**已生成**的批次号（聚合，逗号分隔；issue #5844）。
     *
     * <p>批次号在**过账时逐行**生成（一行 = 一个批次）⇒ 列表只能是聚合展示。
     * 草稿**未过账**时为 {@code null}（草稿不发号：批次号 = 「真的收货了」的标识）；
     * 已作废的单也为 {@code null}（永远不会过账）—— **不得**把 null 读成「没有批次」。</p>
     */
    private String batchNos;
}
