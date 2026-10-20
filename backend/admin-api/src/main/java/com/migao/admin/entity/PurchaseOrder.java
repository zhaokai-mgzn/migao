package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * 采购单（issue #7369，P0-1 段 4）。
 *
 * <p>对应表 {@code purchase_orders}（V175）。一张单可分**多次**收货（分批到货是常态）。
 *
 * <h3>状态机（服务层派生，客户端不可写）</h3>
 * <pre>
 *   ordered ──收货(部分)──▶ partially_received ──收货(收齐)──▶ received
 *      │                          │
 *      └──────── close(原因) ──────┴──▶ closed      ← 断货 / 取消 / 到不齐都走这条，不删单
 * </pre>
 *
 * <p>🔴 状态**不在请求体里**：`receive` / `close` 之后由服务层按 Σ收货数量重算 ——
 * 状态可写就会出现「单据说没收齐、实际收齐了」的两面口径。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("purchase_orders")
public class PurchaseOrder {

    public static final String STATUS_ORDERED = "ordered";
    public static final String STATUS_PARTIALLY_RECEIVED = "partially_received";
    public static final String STATUS_RECEIVED = "received";
    public static final String STATUS_CLOSED = "closed";

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** CG-yyyyMMdd-NNNN（租户内唯一） */
    private String poNo;

    private String supplierId;

    private LocalDate orderDate;

    /** 预计到货日（可空：没约定就不写，不拿下单日冒充） */
    private LocalDate expectedDate;

    private String status;

    /** 明细金额之和（落单时冻结；后续调价走新的单据，不改历史） */
    private BigDecimal totalAmount;

    private OffsetDateTime closedAt;

    private String closedBy;

    private String closedReason;

    private String remark;

    private String createdBy;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Boolean deleted;
}
