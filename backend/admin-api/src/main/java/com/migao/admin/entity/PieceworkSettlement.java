package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import com.migao.admin.dto.PieceworkSettlementLine;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 计件结算单（V156，issue #5653）—— **生成即冻结的只读快照**。
 *
 * <p>对应表 {@code piecework_settlements}：一行 = 「某期间（月）× 某工人」的应发金额凭证。</p>
 *
 * <h2>口径（用户 2026-10-16 裁定 A：快照式，本类只实现它）</h2>
 * <ul>
 *   <li><b>生成即冻结、不可改</b>：本表**没有**任何 UPDATE 金额 / 期间的路径
 *       （服务层与控制器都没有改写面；要改 ⇒ {@link #voidedAt 作废} + 重开新单）；</li>
 *   <li><b>作废不物理删</b>：{@link #voidedAt} 非空 = 已作废，行**留在表里**（可查、留痕）；</li>
 *   <li><b>跨月按期间键隔离</b>：{@link #period}（{@code YYYY-MM}）参与唯一性
 *       —— 活跃行（{@code deleted = 0 AND voided_at IS NULL}）在同租户 × 同期间 × 同工人上唯一
 *       （部分唯一索引 {@code uk_piecework_settlements_active}）；</li>
 *   <li><b>金额服务端算</b>：{@link #totalAmount} 逐值来自
 *       {@code ProductionService.pieceworkSummary(period, workerName, tenantId)} 的 {@code total}
 *       —— **不在结算侧再算一遍**（那是「同一真值两处投影」）。</li>
 * </ul>
 *
 * <p><b>本轮不做</b>（用户裁定，见 issue #5653 的口径裁定评论）：发放状态字段（已发/未发）、
 * 发放动作、导出、与财务域（{@code FinanceTransaction}）耦合 —— 它们**不在**本载体上。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "piecework_settlements", autoResultMap = true)
public class PieceworkSettlement {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 期间键 {@code YYYY-MM}（跨月隔离的唯一键成分；由服务端解析校验后落库）。 */
    private String period;

    /** 工人名（与 {@code production_work_logs.worker_name} 同一口径的文本键）。 */
    private String workerName;

    /** 应发金额（元）= 生成那一刻 {@code piecework/summary.total} 的**逐值**快照。 */
    private BigDecimal totalAmount;

    /**
     * 明细快照（生成那一刻该工人在该期间的按工序读数；每项 = {@link PieceworkSettlementLine}）。
     *
     * <p>载荷类型放 {@code dto} 包、**不是**本类的静态内部类：仓内「schema.sql 必须覆盖实体声明的列」
     * 的判据按 {@code entity/**.java} 的字段名推导列集 ⇒ 内部类字段会被当成本表的列而判红。</p>
     */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<PieceworkSettlementLine> lineItems;

    /** 生成者（{@code SecurityUser.userId}；无认证上下文 ⇒ {@code null}，不编造）。 */
    private String generatedBy;

    private OffsetDateTime generatedAt;

    /** 作废时刻；{@code null} = 仍然有效。 */
    private OffsetDateTime voidedAt;

    /** 作废者（口径同 {@link #generatedBy}）。 */
    private String voidedBy;

    /** 作废原因（必填 —— 留痕要答得出「为什么作废」）。 */
    private String voidReason;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    private Integer deleted;

}
