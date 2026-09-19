package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 计件工资**结算单**（V75，issue #4483 = 母单 #4347 §二.4）
 * 对应表：{@code production_piecework_settlements}。
 *
 * <p><b>它回答的问题</b>：报表回答「这段时间挣了多少」，本表回答「**这笔钱结了没有**」。
 * 没有这一层，工资可以被事后静默改写（报工可增可改，而**已发出去的钱**不该跟着变）。</p>
 *
 * <p><b>锁定语义（本层的核心）</b>：{@code status='settled'} 之后，该
 * {@code (tenantId, period, workerKey)} 的报工**不得再被改动**；补报走调整单，不回改历史 ——
 * 与既有纪律「快照冻结、不回算历史工资」（V61 / issue #4351）同源。</p>
 *
 * <p><b>不加审批环节</b>（用户裁定 2026-09-19「先做到可核对」）：{@code draft → settled}
 * 一步确认即可，不引入多级审批状态机。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "production_piecework_settlements", autoResultMap = true)
public class ProductionPieceworkSettlement {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 结算期 {@code YYYY-MM}（自然月），与既有 {@code pieceworkSummary} 的 period 同口径。 */
    private String period;

    /** 工人 id（可空：存量报工可能没有 id）⇒ 唯一性由 {@link #workerKey} 承担。 */
    private String workerId;

    /** 工人唯一键（{@code workerId} 非空取它，否则取 {@code workerName}）。 */
    private String workerKey;

    private String workerName;

    /** 金额**快照**（结算那一刻的聚合值）；此后报工再变也不回改本行。 */
    private BigDecimal amount;

    private BigDecimal qty;

    /** 本次结算包含的报工笔数（逐笔明细在 {@code production_piecework_settlement_lines}）。 */
    private Integer lineCount;

    /** {@code draft} = 已生成待确认；{@code settled} = 已确认并**锁定**。 */
    private String status;

    private OffsetDateTime settledAt;

    private String settledBy;

    private String remark;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;
}
