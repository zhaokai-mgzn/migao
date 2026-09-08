package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.KnowledgeCard;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.KnowledgeCardMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * 知识卡片服务（LLM WIKI 板块，issue #3051）
 *
 * 知识卡片生命周期闭环：draft → pending_review → published → archived（编辑 version 递增），
 * 每个状态都有明确 API 动作；检索仅返回 published 知识卡片，租户隔离（显式 eq tenant_id，
 * 吸取审计 07 P1-6 `.or()` 跨租户泄露教训——OR 必须嵌套在 eq 内）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class KnowledgeCardService {

    private final KnowledgeCardMapper knowledgeCardMapper;

    /** 可发布状态：草稿 / 待审核 */
    private static final String STATUS_DRAFT = "draft";
    private static final String STATUS_PENDING_REVIEW = "pending_review";
    private static final String STATUS_PUBLISHED = "published";
    private static final String STATUS_ARCHIVED = "archived";

    /**
     * 创建知识卡片（商家手动创建，sourceType=manual）
     * title/answer 必填；status 缺省 draft，仅接受 draft/published
     */
    public KnowledgeCard create(KnowledgeCard input) {
        if (!StringUtils.hasText(input.getTitle())) {
            throw BusinessException.validationError("知识卡片标题不能为空");
        }
        if (!StringUtils.hasText(input.getAnswer())) {
            throw BusinessException.validationError("知识卡片回答不能为空");
        }

        String status = STATUS_DRAFT;
        if (StringUtils.hasText(input.getStatus())) {
            if (STATUS_PUBLISHED.equals(input.getStatus())) {
                status = STATUS_PUBLISHED;
            } else {
                status = STATUS_DRAFT;
            }
        }

        KnowledgeCard entry = KnowledgeCard.builder()
                .tenantId(TenantContext.getTenantId())
                .title(input.getTitle().trim())
                .category(input.getCategory())
                .industry(StringUtils.hasText(input.getIndustry()) ? input.getIndustry() : "curtain")
                .sourceType("manual")
                .sourceRef(input.getSourceRef())
                .question(input.getQuestion())
                .answer(input.getAnswer())
                .keywords(input.getKeywords())
                .applyProducts(input.getApplyProducts())
                .variables(input.getVariables())
                .status(status)
                .version(1)
                .createdBy("admin")
                .build();
        knowledgeCardMapper.insert(entry);
        log.info("创建知识卡片: id={}, tenantId={}, title={}, status={}", entry.getId(), entry.getTenantId(), entry.getTitle(), entry.getStatus());
        return entry;
    }

    /**
     * 编辑知识卡片（租户校验 + version 递增）
     */
    public KnowledgeCard update(String id, KnowledgeCard patch) {
        KnowledgeCard existing = getOwned(id);
        if (StringUtils.hasText(patch.getTitle())) {
            existing.setTitle(patch.getTitle().trim());
        }
        if (StringUtils.hasText(patch.getCategory())) {
            existing.setCategory(patch.getCategory());
        }
        if (StringUtils.hasText(patch.getQuestion())) {
            existing.setQuestion(patch.getQuestion());
        }
        if (StringUtils.hasText(patch.getAnswer())) {
            existing.setAnswer(patch.getAnswer());
        }
        if (StringUtils.hasText(patch.getKeywords())) {
            existing.setKeywords(patch.getKeywords());
        }
        if (patch.getApplyProducts() != null) {
            existing.setApplyProducts(patch.getApplyProducts());
        }
        if (patch.getVariables() != null) {
            existing.setVariables(patch.getVariables());
        }
        if (StringUtils.hasText(patch.getReviewNote())) {
            existing.setReviewNote(patch.getReviewNote());
        }
        existing.setVersion(existing.getVersion() == null ? 1 : existing.getVersion() + 1);
        knowledgeCardMapper.updateById(existing);
        log.info("编辑知识卡片: id={}, tenantId={}, version={}", id, existing.getTenantId(), existing.getVersion());
        return existing;
    }

    /**
     * 发布知识卡片：draft / pending_review → published（记录审核人/时间）
     */
    public KnowledgeCard publish(String id) {
        KnowledgeCard entry = getOwned(id);
        if (!STATUS_DRAFT.equals(entry.getStatus()) && !STATUS_PENDING_REVIEW.equals(entry.getStatus())) {
            throw BusinessException.validationError("当前状态（" + entry.getStatus() + "）不可发布");
        }
        entry.setStatus(STATUS_PUBLISHED);
        entry.setReviewedBy("admin");
        entry.setReviewedAt(OffsetDateTime.now());
        knowledgeCardMapper.updateById(entry);
        log.info("发布知识卡片: id={}, tenantId={}", id, entry.getTenantId());
        return entry;
    }

    /**
     * 归档知识卡片：published → archived（发布后不可检索）
     */
    public KnowledgeCard archive(String id) {
        KnowledgeCard entry = getOwned(id);
        if (!STATUS_PUBLISHED.equals(entry.getStatus())) {
            throw BusinessException.validationError("仅已发布知识卡片可归档");
        }
        entry.setStatus(STATUS_ARCHIVED);
        knowledgeCardMapper.updateById(entry);
        log.info("归档知识卡片: id={}, tenantId={}", id, entry.getTenantId());
        return entry;
    }

    /**
     * 删除知识卡片（逻辑删除，租户校验）
     */
    public void delete(String id) {
        getOwned(id);
        knowledgeCardMapper.deleteById(id);
        log.info("删除知识卡片: id={}", id);
    }

    /**
     * 分页查询知识卡片（keyword/category/sourceType/status 筛选）
     */
    public PageResponse<KnowledgeCard> page(long page, long size, String keyword,
                                             String category, String sourceType, String status) {
        LambdaQueryWrapper<KnowledgeCard> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(KnowledgeCard::getTenantId, TenantContext.getTenantId());

        if (StringUtils.hasText(keyword)) {
            wrapper.and(w -> w.like(KnowledgeCard::getTitle, keyword)
                    .or().like(KnowledgeCard::getKeywords, keyword)
                    .or().like(KnowledgeCard::getQuestion, keyword)
                    .or().like(KnowledgeCard::getAnswer, keyword));
        }
        if (StringUtils.hasText(category)) {
            wrapper.eq(KnowledgeCard::getCategory, category);
        }
        if (StringUtils.hasText(sourceType)) {
            wrapper.eq(KnowledgeCard::getSourceType, sourceType);
        }
        if (StringUtils.hasText(status)) {
            wrapper.eq(KnowledgeCard::getStatus, status);
        }
        wrapper.orderByDesc(KnowledgeCard::getUpdatedAt);

        Page<KnowledgeCard> resultPage = knowledgeCardMapper.selectPage(new Page<>(page, size), wrapper);
        return PageResponse.of(resultPage);
    }

    /**
     * 知识卡片检索（AI 客服/管理后台用）：仅返回本租户 published 知识卡片。
     * 关键词命中 title/keywords/question/answer；.or() 必须嵌套在 eq 内（P1-6 回归）。
     */
    public List<KnowledgeCard> search(String query, String productId, String category) {
        LambdaQueryWrapper<KnowledgeCard> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(KnowledgeCard::getTenantId, TenantContext.getTenantId())
                .eq(KnowledgeCard::getStatus, STATUS_PUBLISHED);

        if (StringUtils.hasText(query)) {
            wrapper.and(w -> w.like(KnowledgeCard::getTitle, query)
                    .or().like(KnowledgeCard::getKeywords, query)
                    .or().like(KnowledgeCard::getQuestion, query)
                    .or().like(KnowledgeCard::getAnswer, query));
        }
        if (StringUtils.hasText(productId)) {
            // apply_products JSONB 数组包含匹配（如 ["prod-1","prod-2"]）
            wrapper.apply("apply_products @> {0}::jsonb", "[\"" + productId + "\"]");
        }
        if (StringUtils.hasText(category)) {
            wrapper.eq(KnowledgeCard::getCategory, category);
        }
        wrapper.last("LIMIT 20");
        return knowledgeCardMapper.selectList(wrapper);
    }

    /**
     * 取知识卡片并做租户归属校验（IDOR 防护）：不存在或跨租户一律 404
     */
    private KnowledgeCard getOwned(String id) {
        KnowledgeCard entry = knowledgeCardMapper.selectById(id);
        if (entry == null || !entry.getTenantId().equals(TenantContext.getTenantId())) {
            throw BusinessException.notFound("知识卡片");
        }
        return entry;
    }
}
