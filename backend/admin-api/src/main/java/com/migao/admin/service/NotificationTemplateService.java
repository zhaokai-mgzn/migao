package com.migao.admin.service;

import com.migao.admin.dto.NotificationRuleDTO;
import com.migao.admin.dto.NotificationTemplateDTO;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.SaveNotificationTemplateRequest;
import com.migao.admin.entity.NotificationRule;
import com.migao.admin.entity.NotificationTemplate;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.NotificationRuleMapper;
import com.migao.admin.mapper.NotificationTemplateMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.BeanUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.stream.Collectors;

/**
 * 通知模板管理服务（issue #2965 补齐）
 * 主流设计：系统内置模板（tenantId=0，只读）+ 租户自定义模板（tenantId=租户）；
 * 查询时两者可见，修改/删除仅限本租户模板，被规则引用的模板禁止删除。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class NotificationTemplateService {

    private final NotificationTemplateMapper templateMapper;
    private final NotificationRuleMapper ruleMapper;

    /**
     * 分页查询模板（本租户 + 系统内置）
     */
    public PageResponse<NotificationTemplateDTO> queryTemplates(long page, long size, Long tenantId) {
        Page<NotificationTemplate> p = new Page<>(page, size);
        LambdaQueryWrapper<NotificationTemplate> wrapper = new LambdaQueryWrapper<>();
        wrapper.and(w -> w.eq(NotificationTemplate::getTenantId, tenantId)
                        .or().eq(NotificationTemplate::getTenantId, 0L))
                .orderByDesc(NotificationTemplate::getUpdatedAt);

        IPage<NotificationTemplate> result = templateMapper.selectPage(p, wrapper);
        List<NotificationTemplateDTO> dtos = result.getRecords().stream()
                .map(this::toDTO)
                .collect(Collectors.toList());
        return PageResponse.of(result.getTotal(), result.getCurrent(), result.getSize(), dtos);
    }

    /**
     * 创建租户自定义模板
     */
    @Transactional(rollbackFor = Exception.class)
    public NotificationTemplateDTO createTemplate(Long tenantId, SaveNotificationTemplateRequest request) {
        validateRequest(request);
        NotificationTemplate template = NotificationTemplate.builder()
                .tenantId(tenantId)
                .name(request.getName().trim())
                .type(request.getType())
                .channel(StringUtils.hasText(request.getChannel()) ? request.getChannel().trim() : "internal")
                .templateContent(request.getTemplateContent().trim())
                .variables(request.getVariables())
                .status(StringUtils.hasText(request.getStatus()) ? request.getStatus().trim() : "active")
                .createdAt(OffsetDateTime.now())
                .updatedAt(OffsetDateTime.now())
                .build();
        templateMapper.insert(template);
        log.info("创建通知模板成功: id={}, name={}, tenantId={}", template.getId(), template.getName(), tenantId);
        return toDTO(template);
    }

    /**
     * 更新租户自定义模板（系统模板只读）
     */
    @Transactional(rollbackFor = Exception.class)
    public NotificationTemplateDTO updateTemplate(Long tenantId, String id, SaveNotificationTemplateRequest request) {
        validateRequest(request);
        NotificationTemplate existing = templateMapper.selectById(id);
        if (existing == null) {
            throw BusinessException.notFound("通知模板");
        }
        assertTenantOwned(tenantId, existing.getTenantId(), "模板");

        existing.setName(request.getName().trim());
        existing.setType(request.getType());
        existing.setChannel(StringUtils.hasText(request.getChannel()) ? request.getChannel().trim() : "internal");
        existing.setTemplateContent(request.getTemplateContent().trim());
        existing.setVariables(request.getVariables());
        existing.setStatus(StringUtils.hasText(request.getStatus()) ? request.getStatus().trim() : "active");
        existing.setUpdatedAt(OffsetDateTime.now());
        templateMapper.updateById(existing);
        log.info("更新通知模板成功: id={}, tenantId={}", id, tenantId);
        return toDTO(existing);
    }

    /**
     * 删除模板（系统模板只读；被规则引用的模板需先解除引用）
     */
    @Transactional(rollbackFor = Exception.class)
    public void deleteTemplate(Long tenantId, String id) {
        NotificationTemplate existing = templateMapper.selectById(id);
        if (existing == null) {
            throw BusinessException.notFound("通知模板");
        }
        assertTenantOwned(tenantId, existing.getTenantId(), "模板");

        // 引用完整性：被通知规则引用的模板禁止删除（防止触发任务悬空）
        LambdaQueryWrapper<NotificationRule> refWrapper = new LambdaQueryWrapper<>();
        refWrapper.eq(NotificationRule::getTemplateId, id);
        if (!ruleMapper.selectList(refWrapper).isEmpty()) {
            throw BusinessException.validationError("模板已被通知规则引用，请先解除关联后再删除");
        }

        templateMapper.deleteById(id);
        log.info("删除通知模板成功: id={}, tenantId={}", id, tenantId);
    }

    private void validateRequest(SaveNotificationTemplateRequest request) {
        if (request == null
                || !StringUtils.hasText(request.getName())
                || !StringUtils.hasText(request.getTemplateContent())) {
            throw BusinessException.validationError("模板名称与模板内容不能为空");
        }
    }

    /**
     * 租户归属校验：系统内置（tenantId=0）只读，跨租户禁止操作
     */
    private void assertTenantOwned(Long tenantId, Long ownerTenantId, String resource) {
        if (ownerTenantId != null && ownerTenantId == 0L) {
            throw BusinessException.validationError("系统内置" + resource + "不允许修改/删除，可复制后新建自定义" + resource);
        }
        if (!tenantId.equals(ownerTenantId)) {
            throw BusinessException.permissionDenied();
        }
    }

    private NotificationTemplateDTO toDTO(NotificationTemplate template) {
        NotificationTemplateDTO dto = new NotificationTemplateDTO();
        BeanUtils.copyProperties(template, dto);
        return dto;
    }
}