package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
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
        LambdaQueryWrapper<NotificationTemplate> wrapper = visibleToCurrentTenant(tenantId);
        wrapper.orderByDesc(NotificationTemplate::getUpdatedAt);

        IPage<NotificationTemplate> result = templateMapper.selectPage(p, wrapper);
        List<NotificationTemplateDTO> dtos = result.getRecords().stream()
                .map(this::toDTO)
                .collect(Collectors.toList());
        return PageResponse.of(result.getTotal(), result.getCurrent(), result.getSize(), dtos);
    }

    /**
     * 归属认定（issue #6167）：该模板在**当前租户**下可见吗。
     *
     * <p>「可见」= 可读面，与 {@link #queryTemplates} **同一份谓词**
     * （{@code tenant_id = 当前租户 OR tenant_id = 0}）—— 本次登记把它从查询里提出来复用，
     * 语义一字未改。写归属判定要在**载荷校验之前**跑（见 {@code TenantOwnershipInterceptor}），
     * 那时控制器还没执行，所以查询必须由本服务提供。</p>
     *
     * @param id 模板ID
     * @return 当前租户可读（含系统内置行）⇒ true
     */
    public boolean existsForCurrentTenant(String id) {
        return templateMapper.selectCount(visibleToCurrentTenant(TenantContext.getTenantId())
                .eq(NotificationTemplate::getId, id)) > 0;
    }

    /**
     * 归属认定（issue #6167）：该模板**可写**吗 ——
     * {@code tenant_id = 当前租户}（**不含** {@code tenant_id=0} 的系统内置行，它只读）。
     *
     * <p>这是 {@link #assertTenantOwned} 的精确谓词那一半（与 {@link #updateTemplate} 的
     * {@code selectById} + 比较租户同一份判定），**不**新造第二套语义、不抛异常（调用方决定状态码）。</p>
     *
     * @param id 模板ID
     * @return 属于当前租户的自定义模板 ⇒ true
     */
    public boolean isWritableByCurrentTenant(String id) {
        NotificationTemplate existing = templateMapper.selectById(id);
        return existing != null && TenantContext.getTenantId().equals(existing.getTenantId());
    }

    /**
     * 可读面谓词：本租户 + 系统内置（{@code tenant_id=0}）。**唯一出处** ——
     * {@link #queryTemplates} 与 {@link #existsForCurrentTenant} 共用，避免两份漂移。
     */
    private static LambdaQueryWrapper<NotificationTemplate> visibleToCurrentTenant(Long tenantId) {
        long tenant = tenantId == null ? 0L : tenantId;
        return new LambdaQueryWrapper<NotificationTemplate>()
                .and(w -> w.eq(NotificationTemplate::getTenantId, tenant)
                        .or().eq(NotificationTemplate::getTenantId, 0L));
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