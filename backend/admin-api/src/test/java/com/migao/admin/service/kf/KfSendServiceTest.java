// case_ids: KF-015
package com.migao.admin.service.kf;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.KfSessionRemote;
import com.migao.admin.entity.Session;
import com.migao.admin.mapper.KfOutboxMapper;
import com.migao.admin.mapper.KfSendBudgetMapper;
import com.migao.admin.mapper.KfSessionRemoteMapper;
import com.migao.admin.mapper.SessionMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class KfSendServiceTest {

    private SessionMapper sessionMapper;
    private KfSessionRemoteMapper remoteMapper;
    private KfSendBudgetMapper budgetMapper;
    private KfOutboxMapper outboxMapper;
    private KfSendService service;

    @BeforeEach
    void setUp() {
        sessionMapper = mock(SessionMapper.class);
        remoteMapper = mock(KfSessionRemoteMapper.class);
        budgetMapper = mock(KfSendBudgetMapper.class);
        outboxMapper = mock(KfOutboxMapper.class);
        service = new KfSendService(sessionMapper, remoteMapper, budgetMapper, outboxMapper, new ObjectMapper());
    }

    @Test
    @DisplayName("正常入队：校验会话 → 扣预算 → outbox 一条")
    void enqueueOk() {
        when(sessionMapper.selectById("s1")).thenReturn(Session.builder()
                .id("s1").tenantId(1L).channel("wechat_kf").build());
        when(remoteMapper.selectBySessionId("s1"))
                .thenReturn(KfSessionRemote.builder().sessionId("s1").openKfid("wk").build());
        when(budgetMapper.tryConsume("s1", 1L)).thenReturn(1);

        String msgid = service.enqueueReply(1L, "s1", "你好");

        assertThat(msgid).hasSize(32);
        verify(outboxMapper).enqueue(eq(1L), eq("s1"), eq(msgid), anyString());
    }

    @Test
    @DisplayName("预算耗尽 ⇒ 429 语义异常，不写 outbox")
    void budgetExhausted() {
        when(sessionMapper.selectById("s1")).thenReturn(Session.builder()
                .id("s1").tenantId(1L).channel("wechat_kf").build());
        when(remoteMapper.selectBySessionId("s1"))
                .thenReturn(KfSessionRemote.builder().sessionId("s1").openKfid("wk").build());
        when(budgetMapper.tryConsume("s1", 1L)).thenReturn(0);

        assertThatThrownBy(() -> service.enqueueReply(1L, "s1", "你好"))
                .isInstanceOf(KfBudgetExhaustedException.class);
        verify(outboxMapper, never()).enqueue(anyLong(), anyString(), anyString(), anyString());
    }

    @Test
    @DisplayName("非微信客服会话 / 超 2048 字节 ⇒ 拒绝")
    void rejectsInvalid() {
        when(sessionMapper.selectById("s1")).thenReturn(Session.builder()
                .id("s1").tenantId(1L).channel("wechat_h5").build());
        assertThatThrownBy(() -> service.enqueueReply(1L, "s1", "你好"))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> service.enqueueReply(1L, "s1", "x".repeat(2049)))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
