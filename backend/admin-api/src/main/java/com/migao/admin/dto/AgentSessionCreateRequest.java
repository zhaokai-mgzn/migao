package com.migao.admin.dto;

import lombok.Data;

import java.util.List;

/**
 * 人工客服会话创建请求（转人工桥接用）
 * 由 ai-agent-service 的 human_handoff 工具调用
 */
@Data
public class AgentSessionCreateRequest {

    /** AI 会话 ID（sessions 表，用于关联回溯 AI 对话） */
    private String aiSessionId;

    /** 客户 ID（customer_profiles） */
    private String customerId;

    /** 转人工原因 */
    private String reason;

    /** 转人工时点 AI 会话上下文摘要（选填；GB/T 47746-2026 对齐，issue #2776） */
    private String aiContextSummary;

    /** 转人工时点 AI 会话最近 N 轮消息快照（选填，role: user/assistant） */
    private List<AgentAiContextMessage> aiContextMessages;
}
