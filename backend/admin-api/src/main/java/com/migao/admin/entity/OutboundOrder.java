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
import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * 出库单（V196，issue #7750）—— 与入库单**同形**的另一半：布料手工出库 + 成品发货出库。
 *
 * <p><b>没有草稿态</b>（{@link #STATUS_POSTED} 是唯一取值，DB CHECK 兜住）：出库是物理动作
 * （货已经拉走了），留草稿只多一个「谁忘了过账」的坑。建单 = 扣库存 + 落台账 + 写单据，
 * 一步完成、失败整笔回滚。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("outbound_orders")
public class OutboundOrder {

    /** 已过账 —— 出库单**唯一**状态（建单即过账，见类注释） */
    public static final String STATUS_POSTED = "posted";

    /** 业务类别 · 布料：扣 SKU 库存 + 落库存台账 */
    public static final String BIZ_FABRIC = "fabric";
    /** 业务类别 · 成品：把 {@code finished_goods_stock} 的 in_stock 行置为 shipped（释放仓位） */
    public static final String BIZ_FINISHED = "finished";

    /** 手工出库（布料） */
    public static final String SOURCE_MANUAL = "manual";
    /** 发货出库（成品，由发货动作自动建单） */
    public static final String SOURCE_SHIP = "ship";

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 业务单号 CK-yyyyMMdd-NNNN（租户内唯一；DB 唯一索引兜底防重号） */
    private String outboundNo;

    /** {@link #BIZ_FABRIC} / {@link #BIZ_FINISHED} */
    private String bizCategory;

    /** {@link #SOURCE_MANUAL} / {@link #SOURCE_SHIP} */
    private String source;

    /** 仓库引用（NULL = 未指定；存量/手工单可空） */
    private Long warehouseId;

    /** 仓库文本快照（与入库单同款） */
    private String warehouse;

    private LocalDate outboundDate;

    /** 见 {@link #STATUS_POSTED} */
    private String status;

    /** 单据总额 = Σ 行金额（成本未知的行按 0 计，不用 0 冒充「成本为零」——金额列本身可空） */
    private BigDecimal totalAmount;

    /** 成品出库的来源订单（布料手工单为空） */
    private String orderId;

    private String orderNo;

    private String remark;

    private OffsetDateTime postedAt;

    private String postedBy;

    private String createdBy;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
