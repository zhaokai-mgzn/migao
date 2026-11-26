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

    /** 合法状态集合（与 V217 的 ck_kf_channels_status 同源；写面必须用常量，禁止裸字符串）。 */
    public static final String STATUS_ACTIVE = "active";
    public static final String STATUS_UNAUTHORIZED = "unauthorized";
    public static final String STATUS_EXPIRED = "expired";
    public static final String STATUS_REVOKED = "revoked";

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
