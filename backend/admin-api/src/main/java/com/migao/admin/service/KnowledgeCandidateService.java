package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.KnowledgeCandidate;
import com.migao.admin.entity.KnowledgeCard;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.KnowledgeCandidateMapper;
import com.migao.admin.mapper.KnowledgeCardMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.time.OffsetDateTime;

/**
 * 知识提炼候选服务（LLM WIKI 板块 P5，issue #3051 — 待确认队列闭环）
 *
 * 闭环二（无死端）：会话/文档 → candidate(pending) → 采纳/编辑后采纳 → 卡片(published) → 可检索；
 * 拒绝记 status_note。队列必须有读路径（分页/计数）与写路径（采纳/编辑/拒绝）。
 * 核心不变式：AI 只产生候选，发布权在商家。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class KnowledgeCandidateService {

    private final KnowledgeCandidateMapper knowledgeCandidateMapper;
    private final KnowledgeCardMapper knowledgeCardMapper;

    /** 待确认队列分页（status 缺省 pending） */
    public PageResponse<KnowledgeCandidate> page(String status, long page, long size) {
        Long tenantId = TenantContext.getTenantId();
        LambdaQueryWrapper<KnowledgeCandidate> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(KnowledgeCandidate::getTenantId, tenantId);
        if (StringUtils.hasText(status)) {
            wrapper.eq(KnowledgeCandidate::getStatus, status);
        } else {
            wrapper.eq(KnowledgeCandidate::getStatus, "pending");
        }
        wrapper.orderByDesc(KnowledgeCandidate::getCreatedAt);
        Page<KnowledgeCandidate> result = knowledgeCandidateMapper.selectPage(new Page<>(page, size), wrapper);
        return PageResponse.of(result);
    }

    /** 待确认数量（前端红点/角标） */
    public long pendingCount() {
        Long tenantId = TenantContext.getTenantId();
        Long count = knowledgeCandidateMapper.selectCount(new LambdaQueryWrapper<KnowledgeCandidate>()
                .eq(KnowledgeCandidate::getTenantId, tenantId)
                .eq(KnowledgeCandidate::getStatus, "pending"));
        return count == null ? 0 : count;
    }

    /**
     * 采纳：候选 → 知识卡片（published，可立即被检索）
     * 卡片来源继承候选来源（conversation/document → 徽标「会话提炼/文档提炼」）
     */
    public KnowledgeCard adopt(String id) {
        return adoptInternal(id, null);
    }

    /** 编辑后采纳：人工修订候选内容再转卡片 */
    public KnowledgeCard adoptEdited(String id, KnowledgeCandidate patch) {
        if (!StringUtils.hasText(patch.getSuggestedTitle()) || !StringUtils.hasText(patch.getSuggestedAnswer())) {
            throw BusinessException.validationError("采纳的知识卡片标题与回答不能为空");
        }
        return adoptInternal(id, patch);
    }

    /** 拒绝：记录拒绝原因，不产生卡片 */
    public void reject(String id, String note) {
        KnowledgeCandidate candidate = getOwned(id);
        if (!"pending".equals(candidate.getStatus())) {
            throw BusinessException.validationError("仅待确认的候选可拒绝");
        }
        candidate.setStatus("rejected");
        candidate.setStatusNote(StringUtils.hasText(note) ? note : "商家拒绝");
        candidate.setReviewedBy("admin");
        candidate.setReviewedAt(OffsetDateTime.now());
        knowledgeCandidateMapper.updateById(candidate);
        log.info("拒绝提炼候选: id={}, tenantId={}, note={}", id, candidate.getTenantId(), note);
    }

    private KnowledgeCard adoptInternal(String id, KnowledgeCandidate patch) {
        KnowledgeCandidate candidate = getOwned(id);
        if (!"pending".equals(candidate.getStatus())) {
            throw BusinessException.validationError("仅待确认的候选可采纳");
        }
        String title = patch != null ? patch.getSuggestedTitle() : candidate.getSuggestedTitle();
        String answer = patch != null ? patch.getSuggestedAnswer() : candidate.getSuggestedAnswer();
        String category = patch != null ? patch.getSuggestedCategory() : candidate.getSuggestedCategory();
        String keywords = patch != null ? patch.getSuggestedKeywords() : candidate.getSuggestedKeywords();

        KnowledgeCard card = KnowledgeCard.builder()
                .tenantId(candidate.getTenantId())
                .title(title)
                .category(StringUtils.hasText(category) ? category : "faq")
                .industry("curtain")
                .sourceType(candidate.getSourceType())
                .sourceRef(candidate.getSourceRef())
                .question(title)
                .answer(answer)
                .keywords(keywords)
                .status("published")
                .version(1)
                .createdBy("adopt")
                .build();
        knowledgeCardMapper.insert(card);

        candidate.setStatus(patch != null ? "edited" : "adopted");
        candidate.setReviewedBy("admin");
        candidate.setReviewedAt(OffsetDateTime.now());
        knowledgeCandidateMapper.updateById(candidate);
        log.info("采纳提炼候选: id={}, tenantId={}, cardId={}, edited={}", id, candidate.getTenantId(), card.getId(), patch != null);
        return card;
    }

    /** 取候选并做租户归属校验（IDOR 防护） */
    private KnowledgeCandidate getOwned(String id) {
        KnowledgeCandidate candidate = knowledgeCandidateMapper.selectById(id);
        if (candidate == null || !candidate.getTenantId().equals(TenantContext.getTenantId())) {
            throw BusinessException.notFound("提炼候选");
        }
        return candidate;
    }
}
