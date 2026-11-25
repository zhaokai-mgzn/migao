// case_ids: KF-010
package com.migao.admin.service.kf;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.KfChannel;
import com.migao.admin.entity.KfSyncCursor;
import com.migao.admin.mapper.KfChannelMapper;
import com.migao.admin.mapper.KfSyncCursorMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class KfSyncWorkerTest {

    private final ObjectMapper mapper = new ObjectMapper();
    private KfSyncCursorMapper cursorMapper;
    private KfChannelMapper channelMapper;
    private KfAccessTokenService tokenService;
    private WechatKfClient client;
    private KfSessionIngestService ingestService;
    private KfSyncWorker worker;

    @BeforeEach
    void setUp() {
        cursorMapper = mock(KfSyncCursorMapper.class);
        channelMapper = mock(KfChannelMapper.class);
        tokenService = mock(KfAccessTokenService.class);
        client = mock(WechatKfClient.class);
        ingestService = mock(KfSessionIngestService.class);
        worker = new KfSyncWorker(cursorMapper, channelMapper, tokenService, client, ingestService, 300);
    }

    @Test
    @DisplayName("claim → sync → ingest → 推进 cursor 并清 dirty")
    void syncOk() throws Exception {
        when(cursorMapper.claimDue(any(), anyInt(), anyString()))
                .thenReturn(List.of(KfSyncCursor.builder().tenantId(1L).openKfid("wk").cursor("c0").build()));
        when(channelMapper.selectByOpenKfid("wk"))
                .thenReturn(KfChannel.builder().tenantId(1L).openKfid("wk").corpId("corp").build());
        when(tokenService.token(any(KfChannel.class))).thenReturn("tok");
        JsonNode resp = mapper.readTree("""
                {"has_more":0,"next_cursor":"c1","msg_list":[
                  {"origin":3,"msgid":"m1","external_userid":"wm","msgtype":"text","text":{"content":"hi"}}]}
                """);
        when(client.syncMsg("tok", "wk", "c0", null, 100)).thenReturn(resp);

        assertThat(worker.syncOnce()).isEqualTo(1);
        verify(ingestService).ingest(eq(1L), eq("wk"), any(JsonNode.class));
        verify(cursorMapper).clearDirty(1L, "wk", "c1");
    }

    @Test
    @DisplayName("has_more=1 且空列表 ⇒ 用 next_cursor 继续，不死循环")
    void emptyListWithMoreAdvances() throws Exception {
        when(cursorMapper.claimDue(any(), anyInt(), anyString()))
                .thenReturn(List.of(KfSyncCursor.builder().tenantId(1L).openKfid("wk").cursor("c0").build()));
        when(channelMapper.selectByOpenKfid("wk")).thenReturn(KfChannel.builder().corpId("corp").build());
        when(tokenService.token(any(KfChannel.class))).thenReturn("tok");
        when(client.syncMsg("tok", "wk", "c0", null, 100))
                .thenReturn(mapper.readTree("{\"has_more\":1,\"next_cursor\":\"c1\",\"msg_list\":[]}"));
        when(client.syncMsg("tok", "wk", "c1", null, 100))
                .thenReturn(mapper.readTree("{\"has_more\":0,\"next_cursor\":\"c2\",\"msg_list\":[]}"));

        assertThat(worker.syncOnce()).isEqualTo(1);
        verify(client, times(2)).syncMsg(anyString(), anyString(), anyString(), any(), anyInt());
        verify(cursorMapper).clearDirty(1L, "wk", "c2");
    }

    @Test
    @DisplayName("接口异常 ⇒ 只释放 claim，不推进 cursor")
    void apiErrorKeepsDirty() {
        when(cursorMapper.claimDue(any(), anyInt(), anyString()))
                .thenReturn(List.of(KfSyncCursor.builder().tenantId(1L).openKfid("wk").cursor("c0").build()));
        when(channelMapper.selectByOpenKfid("wk")).thenReturn(KfChannel.builder().corpId("corp").build());
        when(tokenService.token(any(KfChannel.class))).thenReturn("tok");
        when(client.syncMsg(anyString(), anyString(), anyString(), any(), anyInt()))
                .thenThrow(new KfApiException(42001, "access_token expired"));

        assertThat(worker.syncOnce()).isZero();
        verify(cursorMapper).releaseClaim(eq(1L), eq("wk"), anyString());
        verify(cursorMapper, never()).clearDirty(anyLong(), anyString(), anyString());
    }
}
