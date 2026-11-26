// case_ids: KF-010, KF-028
package com.migao.admin.service.kf;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.KfChannel;
import com.migao.admin.entity.KfSyncCursor;
import com.migao.admin.mapper.KfChannelMapper;
import com.migao.admin.mapper.KfOutboxMapper;
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
import static org.mockito.Mockito.doThrow;
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
    private KfOutboxMapper outboxMapper;
    private KfMediaService mediaService;
    private KfSyncWorker worker;

    @BeforeEach
    void setUp() {
        cursorMapper = mock(KfSyncCursorMapper.class);
        channelMapper = mock(KfChannelMapper.class);
        tokenService = mock(KfAccessTokenService.class);
        client = mock(WechatKfClient.class);
        ingestService = mock(KfSessionIngestService.class);
        outboxMapper = mock(KfOutboxMapper.class);
        mediaService = mock(KfMediaService.class);
        worker = new KfSyncWorker(cursorMapper, channelMapper, tokenService, client, ingestService,
                outboxMapper, mediaService, 300);
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
    @DisplayName("图片消息落库后归档媒体（issue #9200）")
    void archivesMediaAfterIngest() throws Exception {
        when(cursorMapper.claimDue(any(), anyInt(), anyString()))
                .thenReturn(List.of(KfSyncCursor.builder().tenantId(1L).openKfid("wk").cursor("c0").build()));
        when(channelMapper.selectByOpenKfid("wk"))
                .thenReturn(KfChannel.builder().tenantId(1L).openKfid("wk").corpId("corp").build());
        when(tokenService.token(any(KfChannel.class))).thenReturn("tok");
        when(client.syncMsg("tok", "wk", "c0", null, 100)).thenReturn(mapper.readTree("""
                {"has_more":0,"next_cursor":"c1","msg_list":[
                  {"origin":3,"msgid":"m1","external_userid":"wm","msgtype":"image","image":{"media_id":"mid-1"}}]}
                """));
        when(ingestService.ingest(eq(1L), eq("wk"), any(JsonNode.class))).thenReturn(true);

        assertThat(worker.syncOnce()).isEqualTo(1);
        verify(mediaService).archiveInbound(1L, "wk", "mid-1", "tok");
    }

    @Test
    @DisplayName("媒体归档失败 ⇒ 消息不回滚、游标照常前进（消息优先）")
    void mediaFailureDoesNotBlockSync() throws Exception {
        when(cursorMapper.claimDue(any(), anyInt(), anyString()))
                .thenReturn(List.of(KfSyncCursor.builder().tenantId(1L).openKfid("wk").cursor("c0").build()));
        when(channelMapper.selectByOpenKfid("wk"))
                .thenReturn(KfChannel.builder().tenantId(1L).openKfid("wk").corpId("corp").build());
        when(tokenService.token(any(KfChannel.class))).thenReturn("tok");
        when(client.syncMsg("tok", "wk", "c0", null, 100)).thenReturn(mapper.readTree("""
                {"has_more":0,"next_cursor":"c1","msg_list":[
                  {"origin":3,"msgid":"m1","external_userid":"wm","msgtype":"file","file":{"media_id":"mid-2"}}]}
                """));
        when(ingestService.ingest(eq(1L), eq("wk"), any(JsonNode.class))).thenReturn(true);
        doThrow(new KfMediaException("媒体下载失败"))
                .when(mediaService).archiveInbound(1L, "wk", "mid-2", "tok");

        assertThat(worker.syncOnce()).isEqualTo(1);
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

    @Test
    @DisplayName("msg_send_fail 事件 ⇒ 按 sent_msgid 回写 outbox")
    void msgSendFailEvent() throws Exception {
        when(cursorMapper.claimDue(any(), anyInt(), anyString()))
                .thenReturn(List.of(KfSyncCursor.builder().tenantId(1L).openKfid("wk").cursor("c0").build()));
        when(channelMapper.selectByOpenKfid("wk")).thenReturn(KfChannel.builder().corpId("corp").build());
        when(tokenService.token(any(KfChannel.class))).thenReturn("tok");
        when(client.syncMsg("tok", "wk", "c0", null, 100)).thenReturn(mapper.readTree("""
                {"has_more":0,"next_cursor":"c1","msg_list":[
                  {"msgtype":"event","event_type":"msg_send_fail","fail_msgid":"sent-1","fail_type":6}]}
                """));

        assertThat(worker.syncOnce()).isEqualTo(1);
        verify(outboxMapper).markFailedBySentMsgid("sent-1", 6);
        verify(cursorMapper).clearDirty(1L, "wk", "c1");
    }
}
