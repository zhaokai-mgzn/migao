package com.migao.admin.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.time.OffsetDateTime;

/**
 * 通知响应 DTO
 */
@Data
public class NotificationDTO {

    /**
     * 通知ID
     */
    private String id;

    /**
     * 通知标题
     */
    private String title;

    /**
     * 通知内容
     */
    private String content;

    /**
     * 业务对象类型：order / after_sales / inbound_order（issue #7524）
     */
    private String bizType;

    /**
     * 业务对象 ID
     */
    private String bizId;

    /**
     * 业务对象单号（展示用）
     */
    private String bizNo;

    /**
     * 前端落地页（含 query），空 = 无可跳转页面
     */
    private String targetPath;

    /**
     * 严重级：info / warn / urgent
     */
    private String severity;

    /**
     * 业务发生时间
     */
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private OffsetDateTime occurredAt;

    /**
     * 通知渠道：wechat / sms / email / internal
     */
    private String channel;

    /**
     * 通知状态：pending / sent / failed / read
     */
    private String status;

    /**
     * 接收人类型：user / employee
     */
    private String recipientType;

    /**
     * 创建时间
     */
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private OffsetDateTime createdAt;

    /**
     * 已读时间
     */
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private OffsetDateTime readAt;
}
