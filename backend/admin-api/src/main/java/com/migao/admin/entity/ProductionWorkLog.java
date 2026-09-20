package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * 报工记录（issue #3995，M4-G-2）
 * 对应表：production_work_logs（V49）。一次扫码同时推进工序进度 + 记录个人计件；
 * 明细不可变（计件按当时单价快照可追溯，真值源 §4）。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "production_work_logs", autoResultMap = true)
public class ProductionWorkLog {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String processingOrderId;

    /** 工序实例 id（processing_position_operations.id） */
    private String operationId;

    private String operationName;

    private String workerId;

    private String workerName;

    /** 报工数量 */
    private BigDecimal qty;

    /** 合格数量（计件按合格数量） */
    private BigDecimal qualifiedQty;

    /**
     * 计件单价快照（元/单位，issue #4351，V61）——**报工那一刻**从工序实例
     * {@code processing_position_operations.unit_price} 写入。
     *
     * <p>为什么必须固化：计件聚合原先回查工序实例算金额，而重新实例化
     * （{@code POST /production/orders/{orderId}/instantiate}，工艺变更 / 存量单补工序）
     * 会**软删旧实例并重插** ⇒ 旧报工指向已软删实例 ⇒ 被跳过 ⇒ **工人已做的活的钱从合计里
     * 消失且不报错**。真值源 §4「单价版本化，历史报工按当时价，逐笔可追溯」要的正是本列。
     * {@code NULL} = 本列引入之前的存量报工（聚合按实例回查兜底，见 {@code ProductionService.aggregate}）。</p>
     */
    private BigDecimal unitPrice;

    /** 计件系数快照（issue #4351，V61）——与 {@link #unitPrice} 同一次报工写入、同一口径。 */
    private BigDecimal factor;

    /**
     * 计件单价三态标记（V90，issue #4696）：{@code priced} = 有价（含显式定价 0 元）；
     * {@code unpriced} = <b>未定价</b>（{@link #unitPrice} 为 {@code NULL}）⇒ 聚合**不得**按 0 计件，
     * 报表必须显式可见 + 给定价入口。
     *
     * <p>为什么不能复用 {@code unitPrice IS NULL}：V61 已把该形态占用为「本列引入之前的存量报工」
     * （聚合按实例回查兜底，历史金额一字不动）⇒ 未定价必须**显式标记**。
     * 存量行该列为 {@code NULL} = 本列引入前，走既有回查路径。</p>
     */
    private String priceState;

    /** 报工三态：normal 正常 / rework 返工 / scrap 报废 */
    private String workType;

    private LocalDate workDate;

    private OffsetDateTime createdAt;

    private Integer deleted;
}
