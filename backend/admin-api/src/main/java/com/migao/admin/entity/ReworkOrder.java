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
import java.time.OffsetDateTime;

/**
 * 返工单（V185，issue #7377 P1-5 段 2）：售后工单 → 返工 → 完成时回写售后状态。
 *
 * <p>🔴 同一售后单**同时只能有一个未完结返工单**（部分唯一索引）：否则「修完没有」会有两个答案，
 * 成本也会算两次。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("rework_orders")
public class ReworkOrder {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String reworkNo;

    private String afterSalesTicketId;

    private String orderId;

    private String processingOrderId;

    /** 来源（issue #7860，V199）：{@code after_sales} 售后开单 / {@code worker} 车间工人报返工。 */
    private String source;

    /** 返工的工序实例 id（车间来源有值）。 */
    private String operationId;

    /** 返工的工序名（车间来源有值；与报工明细 {@code operation_name} 同源）。 */
    private String operationName;

    /** 返工数量（车间来源有值；单位随工序，**不**参与计件）。 */
    private BigDecimal qty;

    /** 报返工的工人（车间来源有值；服务端从工人 session 解，不信前端）。 */
    private String workerId;

    private String workerName;

    /** 被改记为返工的那一笔报工明细（{@code production_work_logs.id}；车间来源有值）。 */
    private String workLogId;

    /** draft / in_progress / done / cancelled。 */
    private String status;

    private String reason;

    private String createdBy;

    private String createdByName;

    private OffsetDateTime startedAt;

    private OffsetDateTime completedAt;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
