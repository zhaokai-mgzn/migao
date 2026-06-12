package com.migao.admin.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

import java.util.Map;

/**
 * 创建通知请求 DTO
 */
@Data
public class CreateNotificationRequest {

    /**
     * 接收人ID
     */
    @NotBlank(message = "接收人ID不能为空")
    private String recipientId;

    /**
     * 接收人类型：user / employee
     */
    @NotBlank(message = "接收人类型不能为空")
    private String recipientType;

    /**
     * 通知标题
     */
    @NotBlank(message = "通知标题不能为空")
    private String title;

    /**
     * 通知内容
     */
    @NotBlank(message = "通知内容不能为空")
    private String content;

    /**
     * 通知渠道：wechat / sms / email / internal，默认 internal
     */
    private String channel = "internal";

    /**
     * 关联模板ID（可选）
     */
    private String templateId;

    /**
     * 模板变量（可选）
     */
    private Map<String, String> variables;
}
