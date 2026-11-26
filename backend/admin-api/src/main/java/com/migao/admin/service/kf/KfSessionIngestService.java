package com.migao.admin.service.kf;

import com.fasterxml.jackson.databind.JsonNode;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.KfSessionRemote;
import com.migao.admin.entity.Session;
import com.migao.admin.entity.SessionMessage;
import com.migao.admin.mapper.KfSessionRemoteMapper;
import com.migao.admin.mapper.SessionMapper;
import com.migao.admin.mapper.SessionMessageMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

/**
 * sync_msg → sessions / session_messages（issue #9176）。
 *
 * <p>只处理 {@code origin=3}（客户）消息；客服端/系统事件只推进游标。
 * 会话以 {@code (open_kfid, external_userid, closed_at IS NULL)} 为当前段，
 * 消息以微信 {@code msgid} 做幂等（{@code session_messages.external_msg_id} 唯一）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfSessionIngestService {

    private final SessionMapper sessionMapper;
    private final SessionMessageMapper sessionMessageMapper;
    private final KfSessionRemoteMapper remoteMapper;

    /** @return true = 新消息已落库；false = 重复/忽略 */
    public boolean ingest(Long tenantId, String openKfid, JsonNode msg) {
        if (msg.path("origin").asInt(0) != 3) {
            return false;
        }
        String externalUserid = msg.path("external_userid").asText("");
        String msgid = msg.path("msgid").asText("");
        if (externalUserid.isBlank() || msgid.isBlank()) {
            return false;
        }
        TenantContext.setTenantId(tenantId);
        try {
            KfSessionRemote remote = remoteMapper.selectCurrent(tenantId, openKfid, externalUserid);
            String sessionId = remote != null ? remote.getSessionId() : createSession(tenantId, openKfid, externalUserid);
            if (sessionId == null) {
                return false;
            }

            Map<String, Object> meta = new LinkedHashMap<>();
            meta.put("kf_msgid", msgid);
            meta.put("msgtype", msg.path("msgtype").asText("text"));
            meta.put("origin", 3);
            SessionMessage message = SessionMessage.builder()
                    .id(UUID.randomUUID().toString().replace("-", ""))
                    .tenantId(tenantId)
                    .sessionId(sessionId)
                    .role(SessionMessage.ROLE_USER)
                    .contentType(contentType(msg))
                    .content(content(msg))
                    .externalMsgId(msgid)
                    .metadata(meta)
                    .tokenCount(0)
                    .build();
            try {
                sessionMessageMapper.insert(message);
            } catch (DuplicateKeyException e) {
                return false;
            }
            remoteMapper.touch(sessionId);
            return true;
        } finally {
            TenantContext.clear();
        }
    }

    private String createSession(Long tenantId, String openKfid, String externalUserid) {
        String sessionId = UUID.randomUUID().toString().replace("-", "");
        Map<String, Object> meta = new LinkedHashMap<>();
        meta.put("open_kfid", openKfid);
        meta.put("external_userid", externalUserid);
        meta.put("source", "wechat_kf");
        sessionMapper.insert(Session.builder()
                .id(sessionId)
                .tenantId(tenantId)
                .channel("wechat_kf")
                .aiEnabled(true)
                .metadata(meta)
                .build());
        // 并发下另一个实例已建当前段 ⇒ 回读它，避免本实例拿不到 sessionId
        int inserted = remoteMapper.insertIgnore(sessionId, tenantId, openKfid, externalUserid);
        if (inserted == 0) {
            KfSessionRemote current = remoteMapper.selectCurrent(tenantId, openKfid, externalUserid);
            return current == null ? null : current.getSessionId();
        }
        return sessionId;
    }

    private static String contentType(JsonNode msg) {
        return switch (msg.path("msgtype").asText("text")) {
            case "image" -> "image";
            case "voice" -> "voice";
            case "video" -> "video";
            case "file" -> "file";
            default -> "text";
        };
    }

    private static String content(JsonNode msg) {
        String type = msg.path("msgtype").asText("text");
        return switch (type) {
            case "text" -> msg.path("text").path("content").asText("");
            case "image" -> "[图片]";
            case "voice" -> "[语音]";
            case "video" -> "[视频]";
            case "file" -> "[文件]";
            default -> "[" + type + "]";
        };
    }
}
