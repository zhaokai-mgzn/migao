// case_ids: KF-009
package com.migao.admin.service.kf;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.KfSessionRemote;
import com.migao.admin.entity.Session;
import com.migao.admin.entity.SessionMessage;
import com.migao.admin.mapper.KfSendBudgetMapper;
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
    private KfSendBudgetMapper budgetMapper;
    private KfSessionIngestService service;

    @BeforeEach
    void setUp() {
        sessionMapper = mock(SessionMapper.class);
        messageMapper = mock(SessionMessageMapper.class);
        remoteMapper = mock(KfSessionRemoteMapper.class);
        budgetMapper = mock(KfSendBudgetMapper.class);
        service = new KfSessionIngestService(sessionMapper, messageMapper, remoteMapper, budgetMapper);
    }

    @Test
    @DisplayName("首条客户消息 ⇒ 建 sessions + 当前段 + session_messages")
    void firstMessageCreatesSession() throws Exception {
        when(remoteMapper.selectCurrent(1L, "wk", "wm")).thenReturn(null);
        when(remoteMapper.insertIgnore(anyString(), anyLong(), anyString(), anyString())).thenReturn(1);

        KfSessionIngestService.Ingested ok = service.ingest(1L, "wk", mapper.readTree("""
                {"origin":3,"msgid":"m1","external_userid":"wm","msgtype":"text","text":{"content":"你好"}}
                """));

        assertThat(ok).isNotNull();
        assertThat(ok.text()).isEqualTo("你好");
        assertThat(ok.state()).isZero();
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
        // 客户新消息 ⇒ 预算窗口重置（窗口起点 = 客户最后一条消息，issue #9302）
        verify(budgetMapper).resetWindow(session.getValue().getId(), 1L);
    }

    @Test
    @DisplayName("重复 msgid ⇒ 幂等返回 false，不重复落库")
    void duplicateMessage() throws Exception {
        when(remoteMapper.selectCurrent(1L, "wk", "wm"))
                .thenReturn(KfSessionRemote.builder().sessionId("s1").build());
        when(messageMapper.insert(any(SessionMessage.class))).thenThrow(new DuplicateKeyException("dup"));

        KfSessionIngestService.Ingested ok = service.ingest(1L, "wk", mapper.readTree("""
                {"origin":3,"msgid":"m1","external_userid":"wm","msgtype":"text","text":{"content":"你好"}}
                """));

        assertThat(ok).isNull();
        verify(sessionMapper, never()).insert(any(Session.class));
        // 重放不得白送 5 条额度
        verify(budgetMapper, never()).resetWindow(anyString(), anyLong());
    }

    @Test
    @DisplayName("非客户消息（origin=5）⇒ 忽略")
    void ignoresServicerEcho() throws Exception {
        KfSessionIngestService.Ingested ok = service.ingest(1L, "wk", mapper.readTree("""
                {"origin":5,"msgid":"m1","external_userid":"wm","msgtype":"text"}
                """));
        assertThat(ok).isNull();
        verify(messageMapper, never()).insert(any(SessionMessage.class));
        verify(budgetMapper, never()).resetWindow(anyString(), anyLong());
    }
}
