package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 批次消耗台账实体（V116，issue #5145 阶段 1）
 * 对应表：stock_batch_consumptions —— 一行 = 一次**批次余量**变更。
 *
 * <p><b>与 {@link StockLedger} 是两本账</b>（用户裁定「路线 A」）：{@code stock_ledger_entries}
 * 是 <b>SKU 级销售账</b>（{@code product_skus.stock} 随支付扣，本单**一字不动**）；
 * 本表是 <b>批次级实物账</b>（随加工单生成而扣、随作废而回补）。把批次行塞进 SKU 账会
 * 破坏它「同一 SKU 相邻两行首尾相接」的不变式（理由详见
 * {@code backend/admin-api/src/main/resources/db/migration/V116__create_stock_batch_consumptions.sql} 文件头）。</p>
 *
 * <p><b>余量是派生值</b>：{@code remaining = stock_batches.quantity + Σ(delta)}——
 * <b>不原地改</b> {@code stock_batches.quantity}（V111 裁定「批次行不可改、冲销走新单据」），
 * 故 {@code delta} 带符号：负 = 派工扣减、正 = 作废回补。</p>
 *
 * <p>{@code beforeQty}/{@code afterQty} 是**该批次余量**的前后值（不是 SKU 库存）——
 * 与 {@link StockLedger} 的同名列**量纲不同**，但本表只有一种量纲（{@code batchId} 非空）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("stock_batch_consumptions")
public class StockBatchConsumption {

    /** 变更来源：派加工单扣减（{@code StockBatchConsumptionService.apply}） */
    public static final String REASON_PROCESSING_ORDER = "processing_order";
    /** 变更来源：加工单作废回补（{@code StockBatchConsumptionService.reverse}） */
    public static final String REASON_PROCESSING_ORDER_CANCELLED = "processing_order_cancelled";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** 批次主键（批次行不可删 ⇒ 有 FK：扣一个不存在的批次当场失败） */
    private Long batchId;

    /** 批次号 PC-yyyyMMdd-NNNN（冗余，读面按批次号查/展示不必 join） */
    private String batchNo;

    private String productId;

    /** SKU 主键（无 FK：SKU 会被硬删重建），追溯优先用 skuCode */
    private Long skuId;

    private String skuCode;

    /** 变化量（正 = 回补，负 = 扣减），恒等于 afterQty - beforeQty（NUMERIC(12,1)，V115/#5063） */
    private BigDecimal delta;

    /** 变更前**该批次余量** */
    private BigDecimal beforeQty;

    /** 变更后**该批次余量** */
    private BigDecimal afterQty;

    /** 见 {@link #REASON_PROCESSING_ORDER} / {@link #REASON_PROCESSING_ORDER_CANCELLED} */
    private String reason;

    /** 加工单号 JG-yyyyMMdd-NNNN（扣减与回补同号 ⇒ 可按整单对账） */
    private String processingOrderNo;

    /** 订单号（冗余，便于「按订单查回来」时不 join processing_orders） */
    private String orderNo;

    /**
     * 订单明细行 id（= 加工单快照行的 itemId；NOT NULL —— 答不出「哪一行用掉的」就无法与订单对账）。
     * 类型与 {@code order_items.id} 逐字一致：它是 {@code ASSIGN_UUID} 主键（VARCHAR(36)），**不是** BIGINT。
     */
    private String orderItemId;

    private String operator;

    private String note;

    private OffsetDateTime createdAt;

    @TableLogic
    private Integer deleted;
}
