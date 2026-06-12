package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 分群成员关联实体类
 * 对应表：customer_segment_members
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("customer_segment_members")
public class CustomerSegmentMember {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String segmentId;

    private String customerId;

    private OffsetDateTime addedAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;
}
