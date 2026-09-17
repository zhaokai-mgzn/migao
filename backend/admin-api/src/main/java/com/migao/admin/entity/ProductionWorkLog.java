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

    /** 报工三态：normal 正常 / rework 返工 / scrap 报废 */
    private String workType;

    private LocalDate workDate;

    private OffsetDateTime createdAt;

    private Integer deleted;
}
