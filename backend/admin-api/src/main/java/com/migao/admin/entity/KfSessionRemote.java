package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/** sessions 的 1:1 微信客服远端镜像（当前段 closed_at IS NULL）。 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("kf_session_remote")
public class KfSessionRemote {

    @TableId
    private String sessionId;
    private Long tenantId;
    private String openKfid;
    private String externalUserid;
    private Integer state;
    private String servicerUserid;
    private Integer version;
    private Integer epoch;
    private OffsetDateTime lastMsgAt;
    private OffsetDateTime lastSyncAt;
    private OffsetDateTime closedAt;
    private String closeReason;
    private OffsetDateTime createdAt;
    private OffsetDateTime updatedAt;
}
