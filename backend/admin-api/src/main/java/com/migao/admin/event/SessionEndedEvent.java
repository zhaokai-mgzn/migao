package com.migao.admin.event;

/**
 * 会话结束事件（issue #3090）：转人工会话结束时发布，
 * 事务提交后由 SessionDistillListener 异步触发知识提炼。
 *
 * @param tenantId  租户 ID
 * @param sessionId 已结束的会话 ID
 */
public record SessionEndedEvent(Long tenantId, String sessionId) {
}
