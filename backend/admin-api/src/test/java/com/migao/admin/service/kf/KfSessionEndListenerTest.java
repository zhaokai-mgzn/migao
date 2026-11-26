// case_ids: KF-027
package com.migao.admin.service.kf;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.AgentSession;
import com.migao.admin.entity.KfSessionRemote;
import com.migao.admin.event.SessionEndedEvent;
import com.migao.admin.mapper.AgentSessionMapper;
import com.migao.admin.mapper.KfSessionRemoteMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 人工会话结束 ⇒ 微信客服联动 endHumanSession（issue #9198 = 母单 #9194 子项 5）。
 *
 * <p>口径：只对**人工中（state=2）**的当前段联动；非微信客服会话**零动作**；
 * 联动失败**绝不**冒泡（主流程的 ended 已经提交，失败只留日志）。</p>
 */
class KfSessionEndListenerTest {

    private final AgentSessionMapper agentSessionMapper = mock(AgentSessionMapper.class);
    private final KfSessionRemoteMapper remoteMapper = mock(KfSessionRemoteMapper.class);
    private final KfTransferService transferService = mock(KfTransferService.class);
    private final KfSessionEndListener listener =
            new KfSessionEndListener(agentSessionMapper, remoteMapper, transferService);

    private static AgentSession agentSession(String aiSessionId) {
        AgentSession s = new AgentSession();
        s.setId("as-1");
        s.setTenantId(7L);
        s.setAiSessionId(aiSessionId);
        return s;
    }

    private static KfSessionRemote remote(int state) {
        KfSessionRemote r = new KfSessionRemote();
        r.setSessionId("s-1");
        r.setState(state);
        return r;
    }

    @Test
    @DisplayName("人工中（state=2）⇒ 联动一次 endHumanSession，且租户上下文不残留")
    void routesToEndHumanSession() {
        when(agentSessionMapper.selectById("as-1")).thenReturn(agentSession("s-1"));
        when(remoteMapper.selectBySessionId("s-1")).thenReturn(remote(2));

        listener.onSessionEnded(new SessionEndedEvent(7L, "as-1"));

        verify(transferService).endHumanSession(7L, "s-1", "human_end");
        assertThat(TenantContext.getTenantId()).isNull();
    }

    @Test
    @DisplayName("非微信客服会话（无镜像行 / 无 aiSessionId）⇒ 零联动")
    void plainSessionsAreNoOps() {
        when(agentSessionMapper.selectById("as-1")).thenReturn(agentSession(null));
        listener.onSessionEnded(new SessionEndedEvent(7L, "as-1"));
        verify(transferService, never()).endHumanSession(7L, "s-1", "human_end");
        verify(remoteMapper, never()).selectBySessionId(null);

        when(agentSessionMapper.selectById("as-2")).thenReturn(agentSession("s-2"));
        when(remoteMapper.selectBySessionId("s-2")).thenReturn(null);
        listener.onSessionEnded(new SessionEndedEvent(7L, "as-2"));
        verify(transferService, never()).endHumanSession(7L, "s-2", "human_end");
        assertThat(TenantContext.getTenantId()).isNull();
    }

    @Test
    @DisplayName("非人工段（state≠2）或已关闭 ⇒ 不联动（AI 段结束不该打扰微信侧）")
    void nonHumanSegmentsAreSkipped() {
        when(agentSessionMapper.selectById("as-1")).thenReturn(agentSession("s-1"));
        when(remoteMapper.selectBySessionId("s-1")).thenReturn(remote(0));

        listener.onSessionEnded(new SessionEndedEvent(7L, "as-1"));

        verify(transferService, never()).endHumanSession(7L, "s-1", "human_end");
    }

    @Test
    @DisplayName("联动失败 ⇒ 不冒泡（主流程已 ended），租户上下文仍被清掉")
    void failuresAreSwallowed() {
        when(agentSessionMapper.selectById("as-1")).thenReturn(agentSession("s-1"));
        when(remoteMapper.selectBySessionId("s-1")).thenReturn(remote(2));
        org.mockito.Mockito.doThrow(new IllegalStateException("渠道 secret 不可用"))
                .when(transferService).endHumanSession(7L, "s-1", "human_end");

        assertThatCode(() -> listener.onSessionEnded(new SessionEndedEvent(7L, "as-1")))
                .doesNotThrowAnyException();
        assertThat(TenantContext.getTenantId()).isNull();
    }
}
