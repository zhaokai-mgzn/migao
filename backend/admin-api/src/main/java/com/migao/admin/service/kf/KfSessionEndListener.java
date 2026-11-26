package com.migao.admin.service.kf;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.AgentSession;
import com.migao.admin.entity.KfSessionRemote;
import com.migao.admin.event.SessionEndedEvent;
import com.migao.admin.mapper.AgentSessionMapper;
import com.migao.admin.mapper.KfSessionRemoteMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;

/**
 * 人工会话结束 ⇒ 微信客服联动结束当前段（issue #9198 = 母单 #9194 子项 5）。
 *
 * <p>结束路径已经存在且只走一条：`AgentSessionService.endSession` 在事务内发布
 * {@link SessionEndedEvent}（issue #3090）。本监听器在这个既有事件上补 KF 联动，
 * 于是「工作台结束会话」不再需要有人手工调 `/api/internal/kf/end`。</p>
 *
 * <p>三条边界：</p>
 * <ol>
 *   <li><b>只联动人工中的段</b>（{@code state == 2}）—— AI 段的 ended 不该去打扰微信侧状态；</li>
 *   <li><b>非微信客服会话零动作</b>（没有 {@code kf_session_remote} 行 / 没有 aiSessionId）；</li>
 *   <li><b>失败只留日志</b>：{@code AFTER_COMMIT} 时主流程的 ended 已经提交，联动失败不回滚、不抛错。</li>
 * </ol>
 */
@Slf4j
@Component
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfSessionEndListener {

    /** 微信客服「人工接待中」状态（trans(2)）。 */
    private static final int STATE_HUMAN = 2;
    private static final String CLOSE_REASON = "human_end";

    private final AgentSessionMapper agentSessionMapper;
    private final KfSessionRemoteMapper remoteMapper;
    private final KfTransferService transferService;

    @Async
    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void onSessionEnded(SessionEndedEvent event) {
        if (event == null || event.sessionId() == null) {
            return;
        }
        TenantContext.setTenantId(event.tenantId());
        try {
            AgentSession session = agentSessionMapper.selectById(event.sessionId());
            String aiSessionId = session == null ? null : session.getAiSessionId();
            if (aiSessionId == null || aiSessionId.isBlank()) {
                return;
            }
            KfSessionRemote remote = remoteMapper.selectBySessionId(aiSessionId);
            if (remote == null || remote.getClosedAt() != null) {
                return;
            }
            if (remote.getState() == null || remote.getState() != STATE_HUMAN) {
                return;
            }
            transferService.endHumanSession(event.tenantId(), aiSessionId, CLOSE_REASON);
            log.info("[kf-end] 人工会话结束联动 trans(4) 成功: agentSession={} kfSession={}",
                    event.sessionId(), aiSessionId);
        } catch (Exception e) {
            // 主流程的 ended 已提交 ⇒ 这里只留痕，不回滚、不冒泡
            log.warn("[kf-end] 人工会话结束联动失败（不影响主流程）: agentSession={}",
                    event.sessionId(), e);
        } finally {
            TenantContext.clear();
        }
    }
}
