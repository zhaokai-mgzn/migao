package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * AI 对话上下文快照消息（转人工时点；GB/T 47746-2026 对齐，issue #2776）
 *
 * 由 ai-agent-service human_handoff 在转人工时随人工会话创建请求传入，
 * 供人工客服工作台展示顾客与 AI（小布）转人工前的对话，避免顾客重复复述。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class AgentAiContextMessage {

    /** user / assistant */
    private String role;

    /** 消息文本（服务端按 500 字符截断） */
    private String content;

    /** 内容类型（text/image…），可空 */
    private String contentType;

    /** 消息创建时间（ISO 字符串），可空 */
    private String createdAt;
}
