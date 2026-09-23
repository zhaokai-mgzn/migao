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
import java.math.RoundingMode;
import java.time.OffsetDateTime;

/**
 * 批次消耗台账实体（V116，issue #5145 阶段 1）
 * 对应表：stock_batch_consumptions —— 一行 = 一次**批次余量**变更。
 *
 * <p><b>与 {@link StockLedger} 是两本账</b>（用户裁定「路线 A」）：{@code stock_ledger_entries}
 * 是 <b>SKU 级销售账</b>（{@code product_skus.stock} 随支付扣，本单**一字不动**）；
 * 本表是 <b>批次级实物账</b>（随加工单生成而扣、随作废而回补）。把批次行塞进 SKU 账会
 * 破坏它「同一 SKU 相邻两行首尾相接」的不变式（理由详见
 * {@code backend/admin-api/src/main/resources/db/migration-archive/V116__create_stock_batch_consumptions.sql} 文件头）。</p>
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

    /**
     * **行业公式口径**米数（= {@code toStockScaleByCeiling(order_items.quantity)}，与销售账扣减同源）
     * —— 即本单之前的扣减口径（V119，issue #5158；硬要求来自 #5159 L1）。
     *
     * <p><b>带符号</b>，与 {@link #delta} 同向：扣减行为正、回补行为负（回补行 = 原值的相反数
     * ⇒ 作废后整单两列净额都归零，读面不必再做一次「扣减 − 回补」的减法）。</p>
     */
    private BigDecimal formulaMeters;

    /**
     * **排料口径**米数（A 类完整布并排后的应领米数）= 本行**实际扣减**口径，恒等于 {@code -delta}。
     *
     * <p>单独立列是为让「两个米数」在账上**逐行自证**（#5159 L1 的逐单审计面）：读的人不必知道
     * {@code delta} 的符号约定就能同时读出两个口径。DB 侧有约束保证
     * {@code planned_meters <= formula_meters}（**只多不少**）且两列同号。</p>
     */
    private BigDecimal plannedMeters;

    /**
     * **当时**该批次均价（元/米）快照（源 {@code stock_batches.unit_cost}，V119）。
     *
     * <p>🔴 均价随行**快照**（而不是读面 join 批次）是判据「换价后历史单的 {@code saved_amount}
     * 不得变」的**唯一**实现方式。{@code NULL} = 未知（V119 之前的历史行：那时没记这个数，
     * **不回填、不猜** —— 拿今天的批次价冒充当时价正是本列要防的事）。</p>
     */
    private BigDecimal unitCost;

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

    /**
     * 排料省下的米数 = {@code formula_meters − planned_meters}（**派生，不落库** —— 落库就是第三个数，
     * 与两个真值之间迟早对不上）。两列同号 ⇒ 作废行得到的是负数（整单净额仍然对），
     * 「宁可为 0，不许估」由约束 {@code planned <= formula} 保证不为负。
     *
     * <p>两列缺一（历史形态 / 未取到）⇒ {@code null}（不造值）。</p>
     */
    public BigDecimal getSavedMeters() {
        return formulaMeters == null || plannedMeters == null
                ? null : formulaMeters.subtract(plannedMeters);
    }

    /**
     * 省下的钱 = {@code saved_meters × 当时该批次均价}（{@link #getSavedMeters()} 的派生）。
     *
     * <p>均价是**行内快照**（{@link #unitCost}）⇒ 事后改 {@code stock_batches.unit_cost}
     * **不会**改掉历史单的这个数（#5159 硬约束二）。金额按**分**（2 位，{@code HALF_UP}）计
     * —— 与批次均价同为金额口径；均价未知（历史行）⇒ {@code null}，**不按 0 或现价折算**。</p>
     */
    public BigDecimal getSavedAmount() {
        BigDecimal saved = getSavedMeters();
        return saved == null || unitCost == null
                ? null : saved.multiply(unitCost).setScale(2, RoundingMode.HALF_UP);
    }
}
