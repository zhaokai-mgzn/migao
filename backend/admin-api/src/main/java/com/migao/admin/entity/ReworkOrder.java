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
