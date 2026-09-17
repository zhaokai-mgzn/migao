package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 库存流水/台账（issue #4055）
 * 对应表：stock_ledger_entries（V53）。
 *
 * <p>一行 = **一次 SKU 级库存变更**（before → after）。库存为什么从 X 变成 Y，
 * 靠本表逐行首尾相接回答（{@code before_qty} == 上一个同 SKU 行的 {@code after_qty}）。</p>
 *
 * <p>粒度 = SKU 级（issue #4038：{@code product_skus.stock} 是库存权威，{@code products.stock} 是派生）。
 * 追加写、不可变；不设 TTL，随订单生命周期软删（{@code deleted}）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("stock_ledger_entries")
public class StockLedger {

    /** 变更来源：订单扣减（写入方在 OrderService，本批未落码） */
    public static final String REASON_ORDER = "order";
    /** 变更来源：售后回补（AfterSalesTicketService.maybeRestockOnReturn） */
    public static final String REASON_AFTERSALES = "aftersales";
    /** 变更来源：手工调整（ProductService.adjustStockForAgent） */
    public static final String REASON_MANUAL = "manual";

    /** IDENTITY 单调递增：为「同 SKU 相邻两行首尾相接」提供全序（created_at 会撞毫秒） */
    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String productId;

    /** SKU 主键（无 FK：SKU 会被硬删重建），追溯优先用 skuCode */
    private Long skuId;

    private String skuCode;

    /** 变化量（正=入库/回补，负=出库/扣减），恒等于 afterQty - beforeQty */
    private Integer delta;

    private Integer beforeQty;

    private Integer afterQty;

    /** 见 {@link #REASON_ORDER} / {@link #REASON_AFTERSALES} / {@link #REASON_MANUAL} */
    private String reason;

    /** 业务单据号：订单号（order）/ 工单号（aftersales）；manual 为空 */
    private String refNo;

    /** 人类可读的变更原因（如 Agent 传入的「盘点」「报损」） */
    private String note;

    /** 操作人（登录用户名；内部服务调用 = internal-service；无认证上下文 = system） */
    private String operator;

    private OffsetDateTime createdAt;

    @TableLogic
    private Integer deleted;
}