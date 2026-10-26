package com.migao.admin.dto;

import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 入库单详情响应（V111，issue #5034）—— 单据头 + 明细行（含批次号）。
 *
 * <p>{@link #source} / {@link #importRunId} 由 V117（issue #5148）追加：
 * 来源（采购收货 / 期初建账）与建单运行级幂等键 —— 下游「批次建账」单凭 source 做基线冻结点。</p>
 */
@Data
public class InboundOrderResponse {

    private String id;

    /** 入库单号 RK-yyyyMMdd-NNNN（租户内唯一） */
    private String inboundNo;

    private String supplier;

    /** 供应商档案引用（issue #7369 段 2）：NULL = 未建档 / 待指派（前端据此显示「待指派」） */
    private String supplierId;

    private String supplierDocNo;

    private String warehouse;

    private LocalDate inboundDate;

    /** draft / posted / cancelled */
    private String status;

    /**
     * 业务类别（V196）：{@code fabric} 原料仓 / {@code finished} 成品仓（issue #7794）。
     *
     * <p>详情弹窗按它切换明细列：成品单显示套号 / 仓位号 / 短码，不显示米数 / 单价 / 金额。</p>
     */
    private String bizCategory;

    private BigDecimal totalAmount;

    /** 单据来源：purchase 采购收货 / opening 期初建账 */
    private String source;

    /** 建单运行级幂等键（未带则为 null） */
    private String importRunId;

    private String remark;

    private OffsetDateTime postedAt;

    private String postedBy;

    private OffsetDateTime cancelledAt;

    private String cancelledBy;

    private String cancelledReason;

    private String createdBy;

    private OffsetDateTime createdAt;

    private List<Item> items;

    /** 明细行：**一行 = 一个批次** */
    @Data
    public static class Item {

        /** 明细行 id（雪花号，> 2^53）⇒ 字符串出参，防 JS 精度丢失（issue #6340）。 */
        @JsonSerialize(using = ToStringSerializer.class)
        private Long id;

        /** SKU ID（雪花号，> 2^53）⇒ 字符串出参，防 JS 精度丢失（issue #6340）。 */
        @JsonSerialize(using = ToStringSerializer.class)
        private Long skuId;

        private String productId;

        /** 快照：入库时点的货号 */
        private String skuCode;

        /** 快照：颜色名 */
        private String colorName;

        /** 快照：门幅 */
        private String doorWidth;

        /** 旧的「数量」列（= 库里原值；新行的口径见 {@link #meters}） */
        private BigDecimal quantity;

        /**
         * **入库米数** —— 这一行真正进了库存多少米（服务端算，issue #7709）。
         *
         * <p>有 {@link #rollCount} ⇒ = 卷数 × {@link #rollLengthM}；否则 = {@link #quantity}。
         * 历史拍照行（`roll_count` 为空且 `source=photo`）按「卷数 × 卷长」补算
         * （口径一处 = `InboundOrderService.storedMeters`）⇒ 入库单、批次余量、库存流水三处能对上同一批货。</p>
         */
        private BigDecimal meters;

        /** 卷数（可空；issue #7709）—— 与 {@link #rollLengthM} 一起决定 {@link #meters} */
        private Integer rollCount;

        private BigDecimal unitCost;

        private BigDecimal amount;

        /** 批次号（**过账后才有**；草稿为 null） */
        private String batchNo;

        /** 供应商缸号（可空） */
        private String dyeLot;

        /** 旧系统批次号（可空；仅期初建账 source=opening 的单会有；V118 / issue #5153） */
        private String legacyBatchNo;

        private BigDecimal rollLengthM;

        /**
         * 以下五个字段只对**成品行**（{@code biz_category=finished}）有值（V194 / V197），
         * 由 {@code BeanUtils.copyProperties(line, item)} 自动带出 —— **不手写映射**（issue #7794）。
         */

        /** 仓位号快照（成品仓入库的意义就在这个号） */
        private String binCode;

        /** 套号快照（V197 / #7762） */
        private String setNo;

        /** 部位码短码快照（V197 / #7762） */
        private String shortCode;

        /** 品名快照（成品行没有 SKU 货号，展示靠它） */
        private String productName;

        /** 计量单位：m = 米（布料行）/ set = 套（成品行） */
        private String unit;

        private String remark;
    }
}
