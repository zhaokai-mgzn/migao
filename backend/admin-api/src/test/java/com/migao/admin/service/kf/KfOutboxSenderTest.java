// case_ids: KF-016
package com.migao.admin.service.kf;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.KfChannel;
import com.migao.admin.entity.KfOutbox;
import com.migao.admin.entity.KfSessionRemote;
import com.migao.admin.mapper.KfChannelMapper;
import com.migao.admin.mapper.KfOutboxMapper;
import com.migao.admin.mapper.KfSessionRemoteMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class KfOutboxSenderTest {

    private KfOutboxMapper outboxMapper;
    private KfSessionRemoteMapper remoteMapper;
    private KfChannelMapper channelMapper;
    private KfAccessTokenService tokenService;
    private WechatKfClient client;
    private KfOutboxSender sender;

    @BeforeEach
    void setUp() {
        outboxMapper = mock(KfOutboxMapper.class);
        remoteMapper = mock(KfSessionRemoteMapper.class);
        channelMapper = mock(KfChannelMapper.class);
        tokenService = mock(KfAccessTokenService.class);
        client = mock(WechatKfClient.class);
        sender = new KfOutboxSender(outboxMapper, remoteMapper, channelMapper, tokenService, client,
                new ObjectMapper(), 120);
    }

    @Test
    @DisplayName("claim → sendText → accepted（sent_msgid 回写）")
    void sendOk() {
        when(outboxMapper.claimDue(any(), anyInt(), anyString())).thenReturn(List.of(
                KfOutbox.builder().id(9L).sessionId("s1").msgid("m1")
                        .parts("[{\"type\":\"text\",\"content\":\"hi\"}]").build()));
        when(remoteMapper.selectBySessionId("s1"))
                .thenReturn(KfSessionRemote.builder().sessionId("s1").openKfid("wk").externalUserid("wm").build());
        when(channelMapper.selectByOpenKfid("wk")).thenReturn(KfChannel.builder().corpId("corp").build());
        when(tokenService.token(any(KfChannel.class))).thenReturn("tok");
        when(client.sendText("tok", "wk", "wm", "hi", "m1")).thenReturn("sent-1");

        assertThat(sender.sendOnce()).isEqualTo(1);
        verify(outboxMapper).markAccepted(9L, "sent-1");
    }

    @Test
    @DisplayName("send_msg 失败 ⇒ failed + fail_type（不是静默）")
    void sendFailed() {
        when(outboxMapper.claimDue(any(), anyInt(), anyString())).thenReturn(List.of(
                KfOutbox.builder().id(9L).sessionId("s1").msgid("m1")
                        .parts("[{\"type\":\"text\",\"content\":\"hi\"}]").build()));
        when(remoteMapper.selectBySessionId("s1"))
                .thenReturn(KfSessionRemote.builder().sessionId("s1").openKfid("wk").externalUserid("wm").build());
        when(channelMapper.selectByOpenKfid("wk")).thenReturn(KfChannel.builder().corpId("corp").build());
        when(tokenService.token(any(KfChannel.class))).thenReturn("tok");
        when(client.sendText(anyString(), anyString(), anyString(), anyString(), anyString()))
                .thenThrow(new KfApiException(45015, "out of window"));

        assertThat(sender.sendOnce()).isZero();
        verify(outboxMapper).markFailed(9L, "failed", 45015);
    }
}
