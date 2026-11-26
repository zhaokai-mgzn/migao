// case_ids: KF-009
package com.migao.admin.service.kf;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.KfSessionRemote;
import com.migao.admin.entity.Session;
import com.migao.admin.entity.SessionMessage;
import com.migao.admin.mapper.KfSessionRemoteMapper;
import com.migao.admin.mapper.SessionMapper;
import com.migao.admin.mapper.SessionMessageMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.dao.DuplicateKeyException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class KfSessionIngestServiceTest {

    private final ObjectMapper mapper = new ObjectMapper();
    private SessionMapper sessionMapper;
    private SessionMessageMapper messageMapper;
    private KfSessionRemoteMapper remoteMapper;
    private KfSessionIngestService service;

    @BeforeEach
    void setUp() {
        sessionMapper = mock(SessionMapper.class);
        messageMapper = mock(SessionMessageMapper.class);
        remoteMapper = mock(KfSessionRemoteMapper.class);
        service = new KfSessionIngestService(sessionMapper, messageMapper, remoteMapper);
    }

    @Test
    @DisplayName("首条客户消息 ⇒ 建 sessions + 当前段 + session_messages")
    void firstMessageCreatesSession() throws Exception {
        when(remoteMapper.selectCurrent(1L, "wk", "wm")).thenReturn(null);
        when(remoteMapper.insertIgnore(anyString(), anyLong(), anyString(), anyString())).thenReturn(1);

        boolean ok = service.ingest(1L, "wk", mapper.readTree("""
                {"origin":3,"msgid":"m1","external_userid":"wm","msgtype":"text","text":{"content":"你好"}}
                """));

        assertThat(ok).isTrue();
        ArgumentCaptor<Session> session = ArgumentCaptor.forClass(Session.class);
        verify(sessionMapper).insert(session.capture());
        assertThat(session.getValue().getChannel()).isEqualTo("wechat_kf");
        assertThat(session.getValue().getTenantId()).isEqualTo(1L);

        ArgumentCaptor<SessionMessage> msg = ArgumentCaptor.forClass(SessionMessage.class);
        verify(messageMapper).insert(msg.capture());
        assertThat(msg.getValue().getExternalMsgId()).isEqualTo("m1");
        assertThat(msg.getValue().getContent()).isEqualTo("你好");
        assertThat(msg.getValue().getRole()).isEqualTo("user");
        verify(remoteMapper).touch(session.getValue().getId());
    }

    @Test
    @DisplayName("重复 msgid ⇒ 幂等返回 false，不重复落库")
    void duplicateMessage() throws Exception {
        when(remoteMapper.selectCurrent(1L, "wk", "wm"))
                .thenReturn(KfSessionRemote.builder().sessionId("s1").build());
        when(messageMapper.insert(any(SessionMessage.class))).thenThrow(new DuplicateKeyException("dup"));

        boolean ok = service.ingest(1L, "wk", mapper.readTree("""
                {"origin":3,"msgid":"m1","external_userid":"wm","msgtype":"text","text":{"content":"你好"}}
                """));

        assertThat(ok).isFalse();
        verify(sessionMapper, never()).insert(any(Session.class));
    }

    @Test
    @DisplayName("非客户消息（origin=5）⇒ 忽略")
    void ignoresServicerEcho() throws Exception {
        boolean ok = service.ingest(1L, "wk", mapper.readTree("""
                {"origin":5,"msgid":"m1","external_userid":"wm","msgtype":"text"}
                """));
        assertThat(ok).isFalse();
        verify(messageMapper, never()).insert(any(SessionMessage.class));
    }
}
