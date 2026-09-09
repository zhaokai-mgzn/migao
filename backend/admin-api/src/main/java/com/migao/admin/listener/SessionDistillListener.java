package com.migao.admin.listener;

import com.migao.admin.event.SessionEndedEvent;
import com.migao.admin.service.KnowledgeDistillService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;

/**
 * 会话结束自动提炼监听器（issue #3090）
 *
 * 人工客服会话结束（status→ended）→ 事务提交后**异步**触发知识提炼：
 * - AFTER_COMMIT：确保会话数据已提交，异步线程可读到完整会话
 * - @Async：LLM 提炼耗时（秒级），不阻塞结束会话接口
 * - 提炼失败仅记日志不抛出：不影响主流程，后续可手动对账补偿
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class SessionDistillListener {

    private final KnowledgeDistillService knowledgeDistillService;

    @Async
    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void onSessionEnded(SessionEndedEvent event) {
        try {
            knowledgeDistillService.distillSession(event.tenantId(), event.sessionId());
        } catch (Exception e) {
            log.error("会话结束自动提炼失败: tenantId={}, sessionId={}", event.tenantId(), event.sessionId(), e);
        }
    }
}
