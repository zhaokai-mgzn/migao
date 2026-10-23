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
     * 标题模板（可选，issue #7524）：支持 {{var}}（如「入库单 {{inboundNo}} 已过账」）；
     * 不传则标题回落为 {@link #name}（老模板零改动）
     */
    private String titleTemplate;

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