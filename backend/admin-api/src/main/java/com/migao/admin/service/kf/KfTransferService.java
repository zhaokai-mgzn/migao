package com.migao.admin.service.kf;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.AgentSession;
import com.migao.admin.entity.KfChannel;
import com.migao.admin.entity.KfSessionRemote;
import com.migao.admin.entity.Session;
import com.migao.admin.mapper.AgentSessionMapper;
import com.migao.admin.mapper.KfChannelMapper;
import com.migao.admin.mapper.KfSessionRemoteMapper;
import com.migao.admin.mapper.SessionMapper;
import com.migao.admin.service.AgentSessionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;

/**
 * 转人工（issue #9185）：先建工作台 waiting 会话，再 trans(2)；trans 失败回滚工作台会话。
 * 这里不是 human_handoff 工具复活——是通道能力。
 */
@Slf4j
@Service
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfTransferService {

    private final KfSessionRemoteMapper remoteMapper;
    private final KfChannelMapper channelMapper;
    private final SessionMapper sessionMapper;
    private final KfAccessTokenService tokenService;
    private final WechatKfClient client;
    private final AgentSessionService agentSessionService;
    private final AgentSessionMapper agentSessionMapper;

    public String transferToHuman(Long tenantId, String sessionId, String reason) {
        TenantContext.setTenantId(tenantId);
        try {
            KfSessionRemote remote = remoteMapper.selectBySessionId(sessionId);
            if (remote == null || remote.getClosedAt() != null) {
                throw new IllegalStateException("会话当前段已结束: " + sessionId);
            }
            Session session = sessionMapper.selectById(sessionId);
            if (session == null || !tenantId.equals(session.getTenantId())) {
                throw new IllegalArgumentException("不是本租户的会话: " + sessionId);
            }
            KfChannel channel = channelMapper.selectByOpenKfid(remote.getOpenKfid());
            if (channel == null) {
                throw new IllegalStateException("渠道不存在: " + remote.getOpenKfid());
            }
            String token = tokenService.token(channel);
            if (token == null) {
                throw new IllegalStateException("渠道 secret 不可用");
            }

            AgentSession agentSession = agentSessionService.createSessionForHandoff(
                    sessionId, session.getCustomerId(), tenantId,
                    reason == null || reason.isBlank() ? "客户请求转人工" : reason);
            try {
                client.transServiceState(token, remote.getOpenKfid(), remote.getExternalUserid(), 2);
            } catch (RuntimeException e) {
                agentSessionMapper.deleteById(agentSession.getId());
                throw e;
            }
            remoteMapper.updateState(sessionId, 2);
            log.info("[kf-transfer] 转人工成功 session={} agentSession={}", sessionId, agentSession.getId());
            return agentSession.getId();
        } finally {
            TenantContext.clear();
        }
    }
}
