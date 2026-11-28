package com.migao.admin.service.kf;

import com.fasterxml.jackson.databind.JsonNode;
import com.migao.admin.entity.KfChannel;
import com.migao.admin.entity.KfSyncCursor;
import com.migao.admin.mapper.KfChannelMapper;
import com.migao.admin.mapper.KfOutboxMapper;
import com.migao.admin.mapper.KfSyncCursorMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

/**
 * 每 30s 拉取 dirty 游标（issue #9176）：claim → sync_msg（has_more 循环）→ ingest → 清 dirty。
 *
 * <p>回调只是加速器：即使回调丢失，worker 也会在下一轮把消息拉回来。失败只释放 claim，
 * dirty 保留 ⇒ 下一轮重试；连续失败不会推进 cursor（不会静默丢消息）。</p>
 */
@Slf4j
@Component
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfSyncWorker {

    private static final int PAGE_LIMIT = 100;
    private static final int MAX_PAGES = 10;

    private final KfSyncCursorMapper cursorMapper;
    private final KfChannelMapper channelMapper;
    private final KfAccessTokenService tokenService;
    private final WechatKfClient client;
    private final KfSessionIngestService ingestService;
    private final KfOutboxMapper outboxMapper;
    private final KfMediaService mediaService;
    /** AI_REPLY 一跳（issue #9302）：判定 → 内核产文 → 入队 / 转人工。 */
    private final KfAiReplyLoop replyLoop;
    private final String instanceId;
    private final int claimStaleSeconds;

    public KfSyncWorker(KfSyncCursorMapper cursorMapper,
                        KfChannelMapper channelMapper,
                        KfAccessTokenService tokenService,
                        WechatKfClient client,
                        KfSessionIngestService ingestService,
                        KfOutboxMapper outboxMapper,
                        KfMediaService mediaService,
                        KfAiReplyLoop replyLoop,
                        @Value("${wechat.kf.sync.claim-stale-seconds:300}") int claimStaleSeconds) {
        this.cursorMapper = cursorMapper;
        this.channelMapper = channelMapper;
        this.tokenService = tokenService;
        this.client = client;
        this.ingestService = ingestService;
        this.outboxMapper = outboxMapper;
        this.mediaService = mediaService;
        this.replyLoop = replyLoop;
        this.instanceId = "kf-" + UUID.randomUUID().toString().substring(0, 8);
        this.claimStaleSeconds = claimStaleSeconds;
    }

    /**
     * 媒体消息归档（issue #9200）：**消息优先** —— 归档失败只留日志，绝不把已落库的消息判成失败
     * （否则游标不前进，同一条消息会被反复重放）。
     */
    private void archiveMedia(Long tenantId, String openKfid, JsonNode msg, String accessToken) {
        String type = msg.path("msgtype").asText("text");
        if (!"image".equals(type) && !"voice".equals(type)
                && !"video".equals(type) && !"file".equals(type)) {
            return;
        }
        String mediaId = msg.path(type).path("media_id").asText("");
        if (mediaId.isBlank()) {
            return;
        }
        try {
            mediaService.archiveInbound(tenantId, openKfid, mediaId, accessToken);
        } catch (Exception e) {
            log.warn("[kf-sync] 媒体归档失败（消息已落库，游标照常前进）msgid={} type={} err={}",
                    msg.path("msgid").asText(""), type, e.getMessage());
        }
    }

    @Scheduled(fixedDelayString = "${wechat.kf.sync-interval-ms:30000}", scheduler = "kfScheduler")
    public void poll() {
        try {
            syncOnce();
        } catch (Exception e) {
            log.error("[kf-sync] 轮询失败", e);
        }
    }

    /** 可测入口：返回本轮成功 sync 的游标数。 */
    public int syncOnce() {
        OffsetDateTime staleBefore = OffsetDateTime.now().minusSeconds(claimStaleSeconds);
        List<KfSyncCursor> due = cursorMapper.claimDue(staleBefore, 20, instanceId);
        int ok = 0;
        for (KfSyncCursor cursor : due) {
            if (syncCursor(cursor)) {
                ok++;
            }
        }
        return ok;
    }

    private void handleEvent(JsonNode msg) {
        if ("msg_send_fail".equals(msg.path("event_type").asText())) {
            String failMsgid = msg.path("fail_msgid").asText("");
            int failType = msg.path("fail_type").asInt(0);
            int updated = outboxMapper.markFailedBySentMsgid(failMsgid, failType);
            if (updated == 0) {
                log.warn("[kf-sync] msg_send_fail 找不到 outbox（孤儿事件） fail_msgid={}", failMsgid);
            }
        }
    }

    /**
     * AI_REPLY 一跳（issue #9302）：判定 → 内核产文 → 入队 / 转人工。
     *
     * <p><b>失败只记日志</b>：客户消息已落库，同步轮必须继续推进游标（消息优先）——
     * 生成/转人工的任何异常都不得把整轮 sync 打死（否则同一条消息会被反复重放）。</p>
     */
    private void replySafely(Long tenantId, KfSessionIngestService.Ingested ingested) {
        try {
            replyLoop.onCustomerMessage(tenantId, ingested.sessionId(), ingested.state(), ingested.text());
        } catch (RuntimeException e) {
            log.error("[kf-sync] AI_REPLY 一跳失败（消息已落库，游标照常前进）session={}",
                    ingested.sessionId(), e);
        }
    }

    private boolean syncCursor(KfSyncCursor cursor) {
        Long tenantId = cursor.getTenantId();
        String openKfid = cursor.getOpenKfid();
        try {
            KfChannel channel = channelMapper.selectByOpenKfid(openKfid);
            if (channel == null) {
                log.warn("[kf-sync] 渠道不存在或未激活 openKfid={}", openKfid);
                cursorMapper.releaseClaim(tenantId, openKfid, instanceId);
                return false;
            }
            String accessToken = tokenService.token(channel);
            if (accessToken == null) {
                cursorMapper.releaseClaim(tenantId, openKfid, instanceId);
                return false;
            }

            String current = cursor.getCursor();
            for (int page = 0; page < MAX_PAGES; page++) {
                JsonNode resp = client.syncMsg(accessToken, openKfid, current, null, PAGE_LIMIT);
                JsonNode list = resp.path("msg_list");
                if (list.isArray()) {
                    for (JsonNode msg : list) {
                        try {
                            if ("event".equals(msg.path("msgtype").asText())) {
                                handleEvent(msg);
                                continue;
                            }
                            KfSessionIngestService.Ingested ingested =
                                    ingestService.ingest(tenantId, openKfid, msg);
                            if (ingested != null) {
                                archiveMedia(tenantId, openKfid, msg, accessToken);
                                replySafely(tenantId, ingested);
                            }
                        } catch (Exception e) {
                            log.error("[kf-sync] 单条消息落库失败 msgid={}", msg.path("msgid").asText(""), e);
                        }
                    }
                }
                String next = resp.path("next_cursor").asText(current);
                boolean hasMore = resp.path("has_more").asInt(0) == 1;
                if (!hasMore || next.equals(current)) {
                    current = next;
                    break;
                }
                current = next;
            }
            cursorMapper.clearDirty(tenantId, openKfid, current);
            return true;
        } catch (Exception e) {
            log.error("[kf-sync] 失败，保留 dirty 待重试 openKfid={}", openKfid, e);
            cursorMapper.releaseClaim(tenantId, openKfid, instanceId);
            return false;
        }
    }
}
