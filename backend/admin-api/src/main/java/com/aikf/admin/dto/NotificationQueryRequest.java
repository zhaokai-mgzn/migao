package com.aikf.admin.dto;

import lombok.Data;

import java.time.OffsetDateTime;

/**
 * 通知查询请求 DTO
 */
@Data
public class NotificationQueryRequest {

    /**
     * 通知状态：pending / sent / failed / read
     */
    private String status;

    /**
     * 通知渠道：wechat / sms / email / internal
     */
    private String channel;

    /**
     * 开始日期
     */
    private OffsetDateTime dateFrom;

    /**
     * 结束日期
     */
    private OffsetDateTime dateTo;

    /**
     * 页码，默认 1
     */
    private Long page = 1L;

    /**
     * 每页大小，默认 20
     */
    private Long size = 20L;
}
