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
 * 入库单实体（issue #5034）
 * 对应表：inbound_orders（V111）—— 一次布料收货 = 一张单。
 *
 * <p>状态机（V111）：{@code draft}（草稿，**不动库存**）→ {@code posted}（过账：加库存 + 落台账 + 算移动加权成本）；
 * {@code draft} → {@code cancelled}（作废，未动库存）。</p>
 *
 * <p><b>posted 是终态</b>（不可改不可删）：库存已进 {@code stock_ledger_entries}，
 * 冲销须另开单据，不原地改历史。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("inbound_orders")
public class InboundOrder {

    /** 草稿：可改可删，**不动库存** */
    public static final String STATUS_DRAFT = "draft";
    /** 已过账：加库存 + 落台账 + 算成本；**终态** */
    public static final String STATUS_POSTED = "posted";
    /** 已作废：仅 draft 可作废 */
    public static final String STATUS_CANCELLED = "cancelled";

    /** 采购收货（默认来源：普通入库单） */
    public static final String SOURCE_PURCHASE = "purchase";
    /** 期初建账（迁移导入的历史库存；下游「批次建账」单凭它做基线冻结点 —— V117 / issue #5148） */
    public static final String SOURCE_OPENING = "opening";

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 业务单号 RK-yyyyMMdd-NNNN（**租户内**唯一，V117 起；DB 唯一索引兜底防重号） */
    private String inboundNo;

    /** 供应商（文本，MVP 不建主数据） */
    private String supplier;

    /** 供应商送货单号（对账用） */
    private String supplierDocNo;

    /** 仓库/仓位（文本） */
    private String warehouse;

    /** 入库日期（业务日期，可回填历史单） */
    private LocalDate inboundDate;

    /** 见 {@link #STATUS_DRAFT} / {@link #STATUS_POSTED} / {@link #STATUS_CANCELLED} */
    private String status;

    /** 单据总额 = Σ 行金额（过账时冻结） */
    private BigDecimal totalAmount;

    /** 单据来源：见 {@link #SOURCE_PURCHASE} / {@link #SOURCE_OPENING}（V117 起；CHECK 约束限定取值） */
    private String source;

    /**
     * 建单**运行级**幂等键（V117，issue #5148）。
     *
     * <p>同一 {@code (tenantId, importRunId)} 至多一张未软删的单（部分唯一索引
     * {@code uk_inbound_orders_tenant_import_run}）⇒ 同一份导入重跑不会建出第二张草稿单
     * （两张都过账 = 库存加两次）。{@code NULL} = 普通建单，不参与去重。</p>
     */
    private String importRunId;

    private String remark;

    private OffsetDateTime postedAt;

    private String postedBy;

    private OffsetDateTime cancelledAt;

    private String cancelledBy;

    private String cancelledReason;

    private String createdBy;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    /** 软删：标 @TableLogic ⇒ 查询自动带 deleted = 0（软删行不得出现在列表/详情里） */
    @TableLogic
    private Integer deleted;
}
