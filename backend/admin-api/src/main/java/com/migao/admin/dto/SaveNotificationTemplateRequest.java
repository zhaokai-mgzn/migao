package com.migao.admin.dto;

import lombok.Data;

/**
 * 通知模板保存/更新请求（issue #2965 补齐模板管理）
 */
@Data
public class SaveNotificationTemplateRequest {

    /**
     * 模板名称（唯一标识，如 order_created）
     */
    private String name;

    /**
     * 模板类型（order / after_sales 等业务域）
     */
    private String type;

    /**
     * 通知渠道：internal / sms / wechat / email，默认站内信
     */
    private String channel = "internal";

    /**
     * 模板内容，变量用 {{var}} 占位
     */
    private String templateContent;

    /**
     * 变量说明（可选，逗号分隔或 JSON 文本）
     */
    private String variables;

    /**
     * 状态：active / disabled，默认启用
     */
    private String status = "active";
}