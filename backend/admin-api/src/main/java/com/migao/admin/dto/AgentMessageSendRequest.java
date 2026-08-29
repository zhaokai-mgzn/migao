package com.migao.admin.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

/**
 * 人工客服消息发送请求
 */
@Data
public class AgentMessageSendRequest {

    /** 消息内容 */
    @NotBlank(message = "消息内容不能为空")
    private String content;

    /** 是否内部备注（仅客服可见，默认 false） */
    private Boolean isInternal;
}
