package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/** 微信客服渠道（corp_id + open_kfid 唯一）。 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("kf_channels")
public class KfChannel {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;
    private String corpId;
    private String openKfid;
    private String authMode;
    private String suiteId;
    private String callbackToken;
    private String encodingAesKey;
    private String secretEnc;
    private String secretKeyId;
    private String status;
    private OffsetDateTime createdAt;
    private OffsetDateTime updatedAt;
}
