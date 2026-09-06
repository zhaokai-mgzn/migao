package com.migao.admin.dto;

import lombok.Data;

/**
 * 通知规则保存/更新请求（issue #2965 补齐规则管理）
 */
@Data
public class SaveNotificationRuleRequest {

    /**
     * 事件类型（order_created / order_status_changed / after_sales_created / after_sales_status_changed 等）
     */
    private String eventType;

    /**
     * 接收人类型：user / employee，默认 user
     */
    private String recipientType = "user";

    /**
     * 触发渠道，逗号分隔（internal,sms,...），默认站内信
     */
    private String channels = "internal";

    /**
     * 是否启用，默认启用
     */
    private Boolean enabled = true;

    /**
     * 关联模板 ID（必须存在）
     */
    private String templateId;
}