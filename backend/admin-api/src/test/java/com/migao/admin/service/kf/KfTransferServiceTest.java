// case_ids: KF-021
package com.migao.admin.service.kf;

import com.migao.admin.entity.AgentSession;
import com.migao.admin.entity.KfChannel;
import com.migao.admin.entity.KfSessionRemote;
import com.migao.admin.entity.Session;
import com.migao.admin.mapper.AgentSessionMapper;
import com.migao.admin.mapper.KfChannelMapper;
import com.migao.admin.mapper.KfSessionRemoteMapper;
import com.migao.admin.mapper.SessionMapper;
import com.migao.admin.service.AgentSessionService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class KfTransferServiceTest {

    private KfSessionRemoteMapper remoteMapper;
    private KfChannelMapper channelMapper;
    private SessionMapper sessionMapper;
    private KfAccessTokenService tokenService;
    private WechatKfClient client;
    private AgentSessionService agentSessionService;
    private AgentSessionMapper agentSessionMapper;
    private KfTransferService service;

    @BeforeEach
    void setUp() {
        remoteMapper = mock(KfSessionRemoteMapper.class);
        channelMapper = mock(KfChannelMapper.class);
        sessionMapper = mock(SessionMapper.class);
        tokenService = mock(KfAccessTokenService.class);
        client = mock(WechatKfClient.class);
        agentSessionService = mock(AgentSessionService.class);
        agentSessionMapper = mock(AgentSessionMapper.class);
        service = new KfTransferService(remoteMapper, channelMapper, sessionMapper, tokenService,
                client, agentSessionService, agentSessionMapper);
    }

    @Test
    @DisplayName("先建 waiting 会话 → trans(2) → remote.state=2")
    void transferOk() {
        when(remoteMapper.selectBySessionId("s1")).thenReturn(KfSessionRemote.builder()
                .sessionId("s1").openKfid("wk").externalUserid("wm").build());
        when(sessionMapper.selectById("s1")).thenReturn(Session.builder()
                .id("s1").tenantId(1L).customerId("c1").channel("wechat_kf").build());
        when(channelMapper.selectByOpenKfid("wk")).thenReturn(KfChannel.builder().corpId("corp").build());
        when(tokenService.token(any(KfChannel.class))).thenReturn("tok");
        when(agentSessionService.createSessionForHandoff(anyString(), anyString(), anyLong(), anyString()))
                .thenReturn(AgentSession.builder().id("a1").build());

        assertThat(service.transferToHuman(1L, "s1", "客户要人工")).isEqualTo("a1");
        verify(client).transServiceState("tok", "wk", "wm", 2);
        verify(remoteMapper).updateState("s1", 2);
    }

    @Test
    @DisplayName("trans 失败 ⇒ 回滚工作台会话，不更新 remote")
    void transferRollback() {
        when(remoteMapper.selectBySessionId("s1")).thenReturn(KfSessionRemote.builder()
                .sessionId("s1").openKfid("wk").externalUserid("wm").build());
        when(sessionMapper.selectById("s1")).thenReturn(Session.builder()
                .id("s1").tenantId(1L).channel("wechat_kf").build());
        when(channelMapper.selectByOpenKfid("wk")).thenReturn(KfChannel.builder().corpId("corp").build());
        when(tokenService.token(any(KfChannel.class))).thenReturn("tok");
        when(agentSessionService.createSessionForHandoff(anyString(), any(), anyLong(), anyString()))
                .thenReturn(AgentSession.builder().id("a1").build());
        when(client.transServiceState(anyString(), anyString(), anyString(), anyInt()))
                .thenThrow(new KfApiException(95014, "not activated"));

        assertThatThrownBy(() -> service.transferToHuman(1L, "s1", "x"))
                .isInstanceOf(KfApiException.class);
        verify(agentSessionMapper).deleteById("a1");
        verify(remoteMapper, never()).updateState(anyString(), anyInt());
    }

    @Test
    @DisplayName("结束人工：trans(4) + closeSession；已关闭则幂等返回")
    void endHuman() {
        when(remoteMapper.selectBySessionId("s1")).thenReturn(KfSessionRemote.builder()
                .sessionId("s1").openKfid("wk").externalUserid("wm").build());
        when(channelMapper.selectByOpenKfid("wk")).thenReturn(KfChannel.builder().corpId("corp").build());
        when(tokenService.token(any(KfChannel.class))).thenReturn("tok");

        service.endHumanSession(1L, "s1", "human_end");
        verify(client).transServiceState("tok", "wk", "wm", 4);
        verify(remoteMapper).closeSession("s1", "human_end");

        when(remoteMapper.selectBySessionId("s1")).thenReturn(KfSessionRemote.builder()
                .sessionId("s1").closedAt(java.time.OffsetDateTime.now()).build());
        service.endHumanSession(1L, "s1", "human_end");
        verify(client, times(1)).transServiceState(anyString(), anyString(), anyString(), anyInt());
    }
}
