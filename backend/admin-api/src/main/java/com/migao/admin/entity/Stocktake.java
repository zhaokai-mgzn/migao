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
 * 盘点单（V184，issue #7373 P1-1 段 2）：按仓库出任务 → 录实盘 → 差异经审批后调整。
 *
 * <p>同一仓库**同时只能有一个进行中的盘点**（部分唯一索引兜住）：两个人各盘一遍时，
 * 「谁的结果算数」必须由系统回答，不能靠人记。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("stocktakes")
public class Stocktake {

    public static final String STATUS_COUNTING = "counting";
    public static final String STATUS_COMPLETED = "completed";
    public static final String STATUS_CANCELLED = "cancelled";

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String stocktakeNo;

    private Long warehouseId;

    private String status;

    private String note;

    private String countedBy;

    private String countedByName;

    private OffsetDateTime completedAt;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
