package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/** sync_msg 游标 + claim 状态（复合主键 tenant_id + open_kfid）。 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("kf_sync_cursor")
public class KfSyncCursor {

    private Long tenantId;
    private String openKfid;
    private String cursor;
    private OffsetDateTime dirtyAt;
    private OffsetDateTime lastSuccessAt;
    private String claimedBy;
    private OffsetDateTime claimedAt;
    private OffsetDateTime updatedAt;
}
