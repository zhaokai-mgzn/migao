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
 * 调拨单（V182，issue #7373 P1-1 段 1）：调出仓 → 调入仓，逐批次明细。
 *
 * <p>段 1 = **即时调拨**（确认即两端到位，`status = completed`）：没有在途窗口，
 * 因此不存在「在途可售」的问题。两阶段在途（`in_transit`）见段 2（迁移已预留状态值）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("stock_transfers")
public class StockTransfer {

    public static final String STATUS_COMPLETED = "completed";

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String transferNo;

    private Long fromWarehouseId;

    private Long toWarehouseId;

    private String status;

    private String note;

    private String createdBy;

    private String createdByName;

    private OffsetDateTime completedAt;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
