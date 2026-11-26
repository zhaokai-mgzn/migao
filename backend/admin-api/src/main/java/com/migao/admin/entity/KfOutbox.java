package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/** 发件箱：msgid 幂等；accepted ≠ 送达，等 msg_send_fail 定终态。 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("kf_outbox")
public class KfOutbox {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private String sessionId;
    private String msgid;
    private String parts;
    private String status;
    private Integer attempts;
    private String sentMsgid;
    private Integer failType;
    private OffsetDateTime sendingAt;
    private String leaseOwner;
    private OffsetDateTime createdAt;
}
