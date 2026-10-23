package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 通知记录实体类
 * 对应表：notifications
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("notifications")
public class Notification {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String ruleId;

    private String templateId;

    private String recipientId;

    /** user / employee */
    private String recipientType;

    private String channel;

    private String title;

    private String content;

    /**
     * 业务对象类型：order / after_sales / inbound_order（issue #7524）。
     * 与 {@link #bizId} 一起让通知**挂得住单据**：铃铛/通知中心可点开对应页面，也能按类型筛选。
     */
    private String bizType;

    /** 业务对象 ID（主键，非展示用） */
    private String bizId;

    /** 业务对象单号（展示用，如 RK-20261023-0001） */
    private String bizNo;

    /** 前端落地页（含 query），空 = 该事件没有可跳转的页面 */
    private String targetPath;

    /** 严重级：info / warn / urgent —— 站内信圆点与排序口径 */
    private String severity;

    /** 业务发生时间（与 createdAt 区分：补发/重放时业务时间不变） */
    private OffsetDateTime occurredAt;

    /**
     * 幂等键（issue #7524）：同一事件 × 同一业务对象 × 同一收件人只落一条。
     * 唯一索引 uk_notifications_dedupe 兜底，服务层先查一次（避免撞索引把事务打成 aborted）。
     */
    private String dedupeKey;

    /** pending / sent / failed / read */
    private String status;

    private OffsetDateTime sentAt;

    private OffsetDateTime readAt;

    private String errorMessage;

    private Integer retryCount;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;
}
