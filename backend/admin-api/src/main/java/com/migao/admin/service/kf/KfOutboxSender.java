package com.migao.admin.service.kf;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.KfChannel;
import com.migao.admin.entity.KfOutbox;
import com.migao.admin.entity.KfSessionRemote;
import com.migao.admin.mapper.KfChannelMapper;
import com.migao.admin.mapper.KfOutboxMapper;
import com.migao.admin.mapper.KfSessionRemoteMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

/**
 * 发件箱 sender（issue #9181）：claim → send_msg（同一 msgid 重试）→ accepted/failed。
 *
 * <p>accepted ≠ 送达；`msg_send_fail` 事件到达后按 `sent_msgid` 回写终态。</p>
 */
@Slf4j
@Component
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfOutboxSender {

    private final KfOutboxMapper outboxMapper;
    private final KfSessionRemoteMapper remoteMapper;
    private final KfChannelMapper channelMapper;
    private final KfAccessTokenService tokenService;
    private final WechatKfClient client;
    private final ObjectMapper objectMapper;
    private final String instanceId;
    private final int staleSeconds;

    public KfOutboxSender(KfOutboxMapper outboxMapper,
                          KfSessionRemoteMapper remoteMapper,
                          KfChannelMapper channelMapper,
                          KfAccessTokenService tokenService,
                          WechatKfClient client,
                          ObjectMapper objectMapper,
                          @Value("${wechat.kf.outbox.stale-seconds:120}") int staleSeconds) {
        this.outboxMapper = outboxMapper;
        this.remoteMapper = remoteMapper;
        this.channelMapper = channelMapper;
        this.tokenService = tokenService;
        this.client = client;
        this.objectMapper = objectMapper;
        this.instanceId = "kf-out-" + UUID.randomUUID().toString().substring(0, 8);
        this.staleSeconds = staleSeconds;
    }

    @Scheduled(fixedDelayString = "${wechat.kf.outbox-interval-ms:5000}", scheduler = "kfScheduler")
    public void poll() {
        try {
            sendOnce();
        } catch (Exception e) {
            log.error("[kf-outbox] 轮询失败", e);
        }
    }

    public int sendOnce() {
        List<KfOutbox> due = outboxMapper.claimDue(
                OffsetDateTime.now().minusSeconds(staleSeconds), 10, instanceId);
        int ok = 0;
        for (KfOutbox out : due) {
            if (sendOne(out)) {
                ok++;
            }
        }
        return ok;
    }

    private boolean sendOne(KfOutbox out) {
        try {
            KfSessionRemote remote = remoteMapper.selectBySessionId(out.getSessionId());
            if (remote == null || remote.getClosedAt() != null) {
                outboxMapper.markFailed(out.getId(), "failed", 5);
                return false;
            }
            KfChannel channel = channelMapper.selectByOpenKfid(remote.getOpenKfid());
            if (channel == null) {
                outboxMapper.markFailed(out.getId(), "failed", 0);
                return false;
            }
            String token = tokenService.token(channel);
            if (token == null) {
                outboxMapper.markFailed(out.getId(), "failed", 0);
                return false;
            }
            String text = firstText(out.getParts());
            if (text == null) {
                outboxMapper.markFailed(out.getId(), "failed", 12);
                return false;
            }
            String sent = client.sendText(token, remote.getOpenKfid(), remote.getExternalUserid(),
                    text, out.getMsgid());
            outboxMapper.markAccepted(out.getId(), sent);
            return true;
        } catch (KfApiException e) {
            // 5 条/48h/未认证等：落 failed + fail_type，让运营看见可执行原因
            log.warn("[kf-outbox] send_msg 失败 msgid={} errcode={}", out.getMsgid(), e.getErrcode());
            outboxMapper.markFailed(out.getId(), "failed", e.getErrcode());
            return false;
        } catch (Exception e) {
            // 网络超时：结果未知，保留 unknown 等对账（同 msgid 重试不会重复）
            log.error("[kf-outbox] 发送结果未知 msgid={}", out.getMsgid(), e);
            outboxMapper.markFailed(out.getId(), "unknown", null);
            return false;
        }
    }

    private String firstText(String partsJson) {
        try {
            JsonNode parts = objectMapper.readTree(partsJson);
            for (JsonNode p : parts) {
                if ("text".equals(p.path("type").asText())) {
                    return p.path("content").asText(null);
                }
            }
            return null;
        } catch (Exception e) {
            return null;
        }
    }
}
