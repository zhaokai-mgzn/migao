package com.aikf.admin.service;

import com.aikf.admin.dto.PageResponse;
import com.aikf.admin.dto.QuickReplyCreateRequest;
import com.aikf.admin.dto.QuickReplyResponse;
import com.aikf.admin.dto.QuickReplyUpdateRequest;
import com.aikf.admin.entity.QuickReplyTemplate;
import com.aikf.admin.exception.BusinessException;
import com.aikf.admin.mapper.QuickReplyTemplateMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.List;
import java.util.Objects;
import java.util.stream.Collectors;

/**
 * 快捷回复模板服务类
 * 处理人工客服工作台快捷回复的增删改查
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class QuickReplyTemplateService extends ServiceImpl<QuickReplyTemplateMapper, QuickReplyTemplate> {

    private final QuickReplyTemplateMapper quickReplyTemplateMapper;

    /**
     * 分页查询模板
     */
    public PageResponse<QuickReplyResponse> getTemplatePage(
            long page, long size, String category, String keyword, Long tenantId) {

        LambdaQueryWrapper<QuickReplyTemplate> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(QuickReplyTemplate::getTenantId, tenantId);

        if (StringUtils.hasText(category)) {
            wrapper.eq(QuickReplyTemplate::getCategory, category);
        }
        if (StringUtils.hasText(keyword)) {
            wrapper.and(w -> w.like(QuickReplyTemplate::getTitle, keyword)
                    .or()
                    .like(QuickReplyTemplate::getContent, keyword));
        }

        // 按使用次数倒序（常用的排前面）
        wrapper.orderByDesc(QuickReplyTemplate::getUsageCount);

        Page<QuickReplyTemplate> templatePage = new Page<>(page, size);
        Page<QuickReplyTemplate> resultPage = quickReplyTemplateMapper.selectPage(templatePage, wrapper);

        List<QuickReplyResponse> responses = resultPage.getRecords().stream()
                .map(this::convertToResponse)
                .collect(Collectors.toList());

        return PageResponse.of(resultPage.getTotal(), resultPage.getCurrent(), resultPage.getSize(), responses);
    }

    /**
     * 创建模板
     */
    public QuickReplyResponse createTemplate(QuickReplyCreateRequest request, Long tenantId) {
        QuickReplyTemplate template = QuickReplyTemplate.builder()
                .tenantId(tenantId)
                .category(request.getCategory())
                .title(request.getTitle())
                .content(request.getContent())
                .shortcut(request.getShortcut())
                .isPublic(request.getIsPublic() != null ? request.getIsPublic() : true)
                .usageCount(0)
                .build();

        quickReplyTemplateMapper.insert(template);
        log.info("创建快捷回复模板成功: id={}, title={}", template.getId(), template.getTitle());
        return convertToResponse(template);
    }

    /**
     * 更新模板
     */
    public QuickReplyResponse updateTemplate(String id, QuickReplyUpdateRequest request) {
        QuickReplyTemplate template = quickReplyTemplateMapper.selectById(id);
        if (template == null) {
            throw BusinessException.notFound("快捷回复模板");
        }

        if (StringUtils.hasText(request.getCategory())) {
            template.setCategory(request.getCategory());
        }
        if (StringUtils.hasText(request.getTitle())) {
            template.setTitle(request.getTitle());
        }
        if (StringUtils.hasText(request.getContent())) {
            template.setContent(request.getContent());
        }
        if (request.getShortcut() != null) {
            template.setShortcut(request.getShortcut());
        }
        if (request.getIsPublic() != null) {
            template.setIsPublic(request.getIsPublic());
        }

        quickReplyTemplateMapper.updateById(template);
        log.info("更新快捷回复模板成功: id={}", id);
        return convertToResponse(template);
    }

    /**
     * 删除模板（逻辑删除）
     */
    public void deleteTemplate(String id) {
        QuickReplyTemplate template = quickReplyTemplateMapper.selectById(id);
        if (template == null) {
            throw BusinessException.notFound("快捷回复模板");
        }
        removeById(id);
        log.info("删除快捷回复模板: id={}", id);
    }

    /**
     * 获取所有分类
     */
    public List<String> getCategories(Long tenantId) {
        QueryWrapper<QuickReplyTemplate> wrapper = new QueryWrapper<>();
        wrapper.select("DISTINCT category")
                .eq("tenant_id", tenantId)
                .eq("deleted", 0);
        List<QuickReplyTemplate> results = quickReplyTemplateMapper.selectList(wrapper);
        return results.stream()
                .map(QuickReplyTemplate::getCategory)
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
    }

    /**
     * 增加使用计数
     */
    public void incrementUsageCount(String id) {
        LambdaUpdateWrapper<QuickReplyTemplate> wrapper = new LambdaUpdateWrapper<>();
        wrapper.eq(QuickReplyTemplate::getId, id)
                .setSql("usage_count = usage_count + 1");
        quickReplyTemplateMapper.update(null, wrapper);
    }

    /**
     * Entity转响应DTO
     */
    private QuickReplyResponse convertToResponse(QuickReplyTemplate template) {
        return QuickReplyResponse.builder()
                .id(template.getId())
                .category(template.getCategory())
                .title(template.getTitle())
                .content(template.getContent())
                .shortcut(template.getShortcut())
                .usageCount(template.getUsageCount())
                .isPublic(template.getIsPublic())
                .createdBy(template.getCreatedBy())
                .createdAt(template.getCreatedAt())
                .updatedAt(template.getUpdatedAt())
                .build();
    }
}
