package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.AgentMessage;
import com.migao.admin.entity.AgentSession;
import com.migao.admin.entity.KnowledgeCandidate;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.AgentMessageMapper;
import com.migao.admin.mapper.AgentSessionMapper;
import com.migao.admin.mapper.KnowledgeCandidateMapper;
import com.migao.admin.mapper.KnowledgeCardMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

/**
 * 会话知识提炼服务（LLM WIKI 板块 P5b，issue #3051 — L3 会话提炼）
 *
 * 闭环三（检索-会话飞轮）：人工客服会话 → AI 提炼候选 → 待确认队列 → 商家采纳 → 知识卡片 → 检索命中。
 * 提炼源 = 已结束人工会话（agent_sessions ended）的顾客/客服文本消息；
 * 去重：已存在同名知识卡片或待确认候选 → 跳过；AI 只产生候选，发布权在商家。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class KnowledgeDistillService {

    private static final int MAX_SESSIONS = 10;
    private static final int MAX_MESSAGES = 20;
    private static final int MAX_PER_SESSION = 5;
    private static final int MESSAGE_CHAR_LIMIT = 200;

    private final AgentSessionMapper agentSessionMapper;
    private final AgentMessageMapper agentMessageMapper;
    private final KnowledgeCardMapper knowledgeCardMapper;
    private final KnowledgeCandidateMapper knowledgeCandidateMapper;
    private final KnowledgeDistillClient distillClient;

    /**
     * 提炼最近 N 小时已结束的人工客服会话，候选写入待确认队列。
     *
     * @return {sessions, candidates, created, skipped}
     */
    public Map<String, Object> distillConversations(Long tenantId, int hoursAgo) {
        OffsetDateTime since = OffsetDateTime.now().minusHours(Math.max(1, hoursAgo));
        List<AgentSession> sessions = agentSessionMapper.selectList(new LambdaQueryWrapper<AgentSession>()
                .eq(AgentSession::getTenantId, tenantId)
                .eq(AgentSession::getStatus, "ended")
                .ge(AgentSession::getEndedAt, since)
                .orderByDesc(AgentSession::getEndedAt)
                .last("LIMIT " + MAX_SESSIONS));

        int candidates = 0;
        int created = 0;
        int skipped = 0;
        for (AgentSession session : sessions) {
            String conversationText = buildConversationText(session.getId(), tenantId);
            if (!StringUtils.hasText(conversationText)) {
                continue;
            }
            List<JsonNode> distilled = distillClient.distill(conversationText, MAX_PER_SESSION, tenantId);
            for (JsonNode c : distilled) {
                String title = c.path("title").asText("");
                String answer = c.path("answer").asText("");
                if (!StringUtils.hasText(title) || !StringUtils.hasText(answer)) {
                    continue;
                }
                candidates++;
                if (isDuplicate(tenantId, title)) {
                    skipped++;
                    continue;
                }
                KnowledgeCandidate candidate = KnowledgeCandidate.builder()
                        .tenantId(tenantId)
                        .sourceType("conversation")
                        .sourceRef(session.getId())
                        .suggestedTitle(title)
                        .suggestedAnswer(answer)
                        .suggestedCategory(c.path("category").asText("faq"))
                        .suggestedKeywords(c.path("keywords").asText(null))
                        .confidence(parseConfidence(c.path("confidence").asText("0.5")))
                        .evidence(c.path("evidence").asText(null))
                        .status("pending")
                        .build();
                knowledgeCandidateMapper.insert(candidate);
                created++;
            }
        }
        log.info("会话提炼完成: tenantId={}, sessions={}, candidates={}, created={}, skipped={}",
                tenantId, sessions.size(), candidates, created, skipped);
        return Map.of("sessions", sessions.size(), "candidates", candidates, "created", created, "skipped", skipped);
    }

    /**
     * 文档提炼（L4，issue #3051）：文档文本 → AI 提炼候选 → 待确认队列。
     * 定位是「文档→知识卡片提炼」而非「文档→切块检索」；原文仅作 evidence，不参与运行时检索。
     *
     * @param title   文档标题（sourceRef 追溯用）
     * @param content 文档文本内容
     * @return {candidates, created, skipped}
     */
    public Map<String, Object> distillDocument(Long tenantId, String title, String content) {
        if (!StringUtils.hasText(content) || content.trim().length() < 50) {
            throw BusinessException.validationError("文档内容过短（至少 50 字），无法提炼");
        }
        String text = content.length() > 8000 ? content.substring(0, 8000) : content;
        List<JsonNode> distilled = distillClient.distill(text, MAX_PER_SESSION, tenantId);
        int candidates = 0;
        int created = 0;
        int skipped = 0;
        for (JsonNode c : distilled) {
            String suggestedTitle = c.path("title").asText("");
            String answer = c.path("answer").asText("");
            if (!StringUtils.hasText(suggestedTitle) || !StringUtils.hasText(answer)) {
                continue;
            }
            candidates++;
            if (isDuplicate(tenantId, suggestedTitle)) {
                skipped++;
                continue;
            }
            KnowledgeCandidate candidate = KnowledgeCandidate.builder()
                    .tenantId(tenantId)
                    .sourceType("document")
                    .sourceRef(StringUtils.hasText(title) ? title : "document")
                    .suggestedTitle(suggestedTitle)
                    .suggestedAnswer(answer)
                    .suggestedCategory(c.path("category").asText("faq"))
                    .suggestedKeywords(c.path("keywords").asText(null))
                    .confidence(parseConfidence(c.path("confidence").asText("0.5")))
                    .evidence(c.path("evidence").asText(null))
                    .status("pending")
                    .build();
            knowledgeCandidateMapper.insert(candidate);
            created++;
        }
        log.info("文档提炼完成: tenantId={}, title={}, candidates={}, created={}, skipped={}",
                tenantId, title, candidates, created, skipped);
        return Map.of("candidates", candidates, "created", created, "skipped", skipped);
    }

    /** 去重：同名知识卡片（任意状态）或同名待确认候选 → 跳过 */
    private boolean isDuplicate(Long tenantId, String title) {
        Long cardCount = knowledgeCardMapper.selectCount(new LambdaQueryWrapper<com.migao.admin.entity.KnowledgeCard>()
                .eq(com.migao.admin.entity.KnowledgeCard::getTenantId, tenantId)
                .eq(com.migao.admin.entity.KnowledgeCard::getTitle, title));
        if (cardCount != null && cardCount > 0) {
            return true;
        }
        Long candidateCount = knowledgeCandidateMapper.selectCount(new LambdaQueryWrapper<KnowledgeCandidate>()
                .eq(KnowledgeCandidate::getTenantId, tenantId)
                .eq(KnowledgeCandidate::getStatus, "pending")
                .eq(KnowledgeCandidate::getSuggestedTitle, title));
        return candidateCount != null && candidateCount > 0;
    }

    /** 组装会话对话文本（顾客/客服轮次，限最近 N 条，单条截断） */
    private String buildConversationText(String sessionId, Long tenantId) {
        List<AgentMessage> messages = agentMessageMapper.selectList(new LambdaQueryWrapper<AgentMessage>()
                .eq(AgentMessage::getTenantId, tenantId)
                .eq(AgentMessage::getSessionId, sessionId)
                .in(AgentMessage::getSenderType, List.of("customer", "agent"))
                .eq(AgentMessage::getIsInternal, false)
                .orderByAsc(AgentMessage::getCreatedAt)
                .last("LIMIT " + MAX_MESSAGES));
        if (messages == null || messages.isEmpty()) {
            return "";
        }
        StringBuilder sb = new StringBuilder();
        for (AgentMessage msg : messages) {
            String content = msg.getContent() == null ? "" : msg.getContent();
            if (content.length() > MESSAGE_CHAR_LIMIT) {
                content = content.substring(0, MESSAGE_CHAR_LIMIT);
            }
            String role = "customer".equals(msg.getSenderType()) ? "顾客" : "客服";
            sb.append(role).append("：").append(content).append('\n');
        }
        return sb.toString();
    }

    private BigDecimal parseConfidence(String value) {
        try {
            double v = Double.parseDouble(value);
            return BigDecimal.valueOf(Math.min(Math.max(v, 0.0), 1.0)).setScale(3, java.math.RoundingMode.HALF_UP);
        } catch (Exception e) {
            return new BigDecimal("0.5");
        }
    }
}
