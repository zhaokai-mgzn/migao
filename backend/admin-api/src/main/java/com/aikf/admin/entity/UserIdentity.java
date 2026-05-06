package com.aikf.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 用户身份实体类
 * 对应表：user_identities
 * 说明：一个用户可以有多个端身份（微信小程序、公众号H5、账号密码）
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("user_identities")
public class UserIdentity {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String userId;

    private String identityType;

    private String appId;

    private String openid;

    private String unionid;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
