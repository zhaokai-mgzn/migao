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
 * 结算明细（V75，issue #4483）：**逐笔**指回 {@code production_work_logs}。
 *
 * <p>满足真值源 §4「**逐笔可追溯**」—— 结算金额必须能拆回每一笔报工，
 * 而不是只有一个总数（总数对不上时无法定位是哪一笔）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "production_piecework_settlement_lines", autoResultMap = true)
public class ProductionPieceworkSettlementLine {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String settlementId;

    /** 指回 {@code production_work_logs.id}（逐笔可追溯的锚点）。 */
    private String workLogId;

    private String processingOrderId;

    private String operationName;

    private LocalDate workDate;

    /** 该笔金额（与报工行的 unit_price/factor 快照同源：金额在报工那一刻已固化）。 */
    private BigDecimal amount;

    private BigDecimal qty;

    private OffsetDateTime createdAt;

    private Integer deleted;
}
