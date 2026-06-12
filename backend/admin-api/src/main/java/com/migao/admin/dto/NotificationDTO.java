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
