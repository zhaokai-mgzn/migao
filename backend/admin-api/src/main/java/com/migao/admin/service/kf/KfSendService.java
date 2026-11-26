package com.migao.admin.service.kf;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.KfSessionRemote;
import com.migao.admin.entity.Session;
import com.migao.admin.mapper.KfOutboxMapper;
import com.migao.admin.mapper.KfSendBudgetMapper;
import com.migao.admin.mapper.KfSessionRemoteMapper;
import com.migao.admin.mapper.SessionMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** 回复入队（issue #9181）：校验会话 → 原子扣预算 → 写 outbox；真正发送由 KfOutboxSender 异步做。 */
@Slf4j
@Service
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfSendService {

    private static final int MAX_TEXT_BYTES = 2048;

    private final SessionMapper sessionMapper;
    private final KfSessionRemoteMapper remoteMapper;
    private final KfSendBudgetMapper budgetMapper;
    private final KfOutboxMapper outboxMapper;
    private final ObjectMapper objectMapper;

    /** @return 32 位 msgid（幂等键） */
    public String enqueueReply(Long tenantId, String sessionId, String text) {
        if (text == null || text.isBlank()) {
            throw new IllegalArgumentException("回复文本不能为空");
        }
        if (text.getBytes(StandardCharsets.UTF_8).length > MAX_TEXT_BYTES) {
            throw new IllegalArgumentException("回复文本超过 2048 字节（微信客服硬上限）");
        }
        TenantContext.setTenantId(tenantId);
        try {
            Session session = sessionMapper.selectById(sessionId);
            if (session == null || !tenantId.equals(session.getTenantId())
                    || !"wechat_kf".equals(session.getChannel())) {
                throw new IllegalArgumentException("不是本租户的微信客服会话: " + sessionId);
            }
            KfSessionRemote remote = remoteMapper.selectBySessionId(sessionId);
            if (remote == null || remote.getClosedAt() != null) {
                throw new IllegalStateException("会话当前段已结束: " + sessionId);
            }
            if (budgetMapper.tryConsume(sessionId, tenantId) == 0) {
                throw new KfBudgetExhaustedException(sessionId);
            }
            String msgid = UUID.randomUUID().toString().replace("-", "");
            String parts = objectMapper.writeValueAsString(List.of(Map.of("type", "text", "content", text)));
            outboxMapper.enqueue(tenantId, sessionId, msgid, parts);
            return msgid;
        } catch (IllegalArgumentException | IllegalStateException | KfBudgetExhaustedException e) {
            throw e;
        } catch (Exception e) {
            throw new IllegalStateException("回复入队失败", e);
        } finally {
            TenantContext.clear();
        }
    }
}
