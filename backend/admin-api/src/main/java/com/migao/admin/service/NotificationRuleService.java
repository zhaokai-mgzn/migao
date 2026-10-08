package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.NotificationRuleDTO;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.SaveNotificationRuleRequest;
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
 * 通知规则管理服务（issue #2965 补齐）
 * 主流设计：系统内置规则（tenantId=0，只读）+ 租户自定义规则；
 * 规则将事件类型映射到模板，triggerByEvent 时匹配生效的规则创建站内信。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class NotificationRuleService {

    private final NotificationRuleMapper ruleMapper;
    private final NotificationTemplateMapper templateMapper;

    /**
     * 分页查询规则（本租户 + 系统内置），可按事件类型过滤
     */
    public PageResponse<NotificationRuleDTO> queryRules(long page, long size, Long tenantId, String eventType) {
        Page<NotificationRule> p = new Page<>(page, size);
        LambdaQueryWrapper<NotificationRule> wrapper = new LambdaQueryWrapper<>();
        wrapper.and(w -> w.eq(NotificationRule::getTenantId, tenantId)
                        .or().eq(NotificationRule::getTenantId, 0L));
        if (StringUtils.hasText(eventType)) {
            wrapper.eq(NotificationRule::getEventType, eventType.trim());
        }
        wrapper.orderByDesc(NotificationRule::getUpdatedAt);

        IPage<NotificationRule> result = ruleMapper.selectPage(p, wrapper);
        List<NotificationRuleDTO> dtos = result.getRecords().stream()
                .map(this::toDTO)
                .collect(Collectors.toList());
        return PageResponse.of(result.getTotal(), result.getCurrent(), result.getSize(), dtos);
    }

    /**
     * 归属认定（issue #6167）：该规则在**当前租户**下可见吗。
     *
     * <p>「可见」谓词与 {@link #queryRules} 的 {@code tenant_id = 当前租户 OR tenant_id = 0}
     * **逐字同形**（本单不新造第二份读面判定）—— 写归属判定要在**载荷校验之前**跑
     * （见 {@code TenantOwnershipInterceptor}），那时控制器还没执行，故由本服务提供查询。</p>
     *
     * @param id 规则ID
     * @return 当前租户可读（含系统内置行）⇒ true
     */
    public boolean existsForCurrentTenant(String id) {
        Long tenantId = TenantContext.getTenantId();
        LambdaQueryWrapper<NotificationRule> wrapper = new LambdaQueryWrapper<>();
        wrapper.and(w -> w.eq(NotificationRule::getTenantId, tenantId)
                        .or().eq(NotificationRule::getTenantId, 0L))
                .eq(NotificationRule::getId, id);
        return ruleMapper.selectCount(wrapper) > 0;
    }

    /**
     * 归属认定（issue #6167）：该规则**可写**吗 ——
     * {@code tenant_id = 当前租户}（**不含** {@code tenant_id=0} 的系统内置行，它只读）。
     *
     * <p>这是 {@link #assertTenantOwned} 的精确谓词那一半（与 {@link #updateRule} 的
     * {@code selectById} + 比较租户同一份判定），**不**新造第二套语义、不抛异常。</p>
     *
     * @param id 规则ID
     * @return 属于当前租户的自定义规则 ⇒ true
     */
    public boolean isWritableByCurrentTenant(String id) {
        NotificationRule existing = ruleMapper.selectById(id);
        return existing != null && TenantContext.getTenantId().equals(existing.getTenantId());
    }

    /**
     * 创建租户自定义规则
     */
    @Transactional(rollbackFor = Exception.class)
    public NotificationRuleDTO createRule(Long tenantId, SaveNotificationRuleRequest request) {
        validateAndResolve(tenantId, request);
        NotificationRule rule = NotificationRule.builder()
                .tenantId(tenantId)
                .eventType(request.getEventType().trim())
                .recipientType(StringUtils.hasText(request.getRecipientType()) ? request.getRecipientType().trim() : "user")
                .channels(StringUtils.hasText(request.getChannels()) ? request.getChannels().trim() : "internal")
                .enabled(request.getEnabled() != null ? request.getEnabled() : Boolean.TRUE)
                .templateId(request.getTemplateId())
                .createdAt(OffsetDateTime.now())
                .updatedAt(OffsetDateTime.now())
                .build();
        ruleMapper.insert(rule);
        log.info("创建通知规则成功: id={}, eventType={}, tenantId={}", rule.getId(), rule.getEventType(), tenantId);
        return toDTO(rule);
    }

    /**
     * 更新租户自定义规则（系统规则只读）
     */
    @Transactional(rollbackFor = Exception.class)
    public NotificationRuleDTO updateRule(Long tenantId, String id, SaveNotificationRuleRequest request) {
        validateAndResolve(tenantId, request);
        NotificationRule existing = ruleMapper.selectById(id);
        if (existing == null) {
            throw BusinessException.notFound("通知规则");
        }
        assertTenantOwned(tenantId, existing.getTenantId(), "规则");

        existing.setEventType(request.getEventType().trim());
        existing.setRecipientType(StringUtils.hasText(request.getRecipientType()) ? request.getRecipientType().trim() : "user");
        existing.setChannels(StringUtils.hasText(request.getChannels()) ? request.getChannels().trim() : "internal");
        existing.setEnabled(request.getEnabled() != null ? request.getEnabled() : Boolean.TRUE);
        existing.setTemplateId(request.getTemplateId());
        existing.setUpdatedAt(OffsetDateTime.now());
        ruleMapper.updateById(existing);
        log.info("更新通知规则成功: id={}, tenantId={}", id, tenantId);
        return toDTO(existing);
    }

    /**
     * 删除租户自定义规则（系统规则只读）
     */
    @Transactional(rollbackFor = Exception.class)
    public void deleteRule(Long tenantId, String id) {
        NotificationRule existing = ruleMapper.selectById(id);
        if (existing == null) {
            throw BusinessException.notFound("通知规则");
        }
        assertTenantOwned(tenantId, existing.getTenantId(), "规则");
        ruleMapper.deleteById(id);
        log.info("删除通知规则成功: id={}, tenantId={}", id, tenantId);
    }

    /**
     * 参数校验 + 模板存在性校验
     */
    private void validateAndResolve(Long tenantId, SaveNotificationRuleRequest request) {
        if (request == null || !StringUtils.hasText(request.getEventType())) {
            throw BusinessException.validationError("规则事件类型不能为空");
        }
        if (!StringUtils.hasText(request.getTemplateId())) {
            throw BusinessException.validationError("规则必须关联一个通知模板");
        }
        NotificationTemplate template = templateMapper.selectById(request.getTemplateId());
        if (template == null) {
            throw BusinessException.validationError("关联的通知模板不存在: " + request.getTemplateId());
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

    private NotificationRuleDTO toDTO(NotificationRule rule) {
        NotificationRuleDTO dto = new NotificationRuleDTO();
        BeanUtils.copyProperties(rule, dto);
        // 联查模板名称（展示用）
        if (StringUtils.hasText(rule.getTemplateId())) {
            NotificationTemplate template = templateMapper.selectById(rule.getTemplateId());
            if (template != null) {
                dto.setTemplateName(template.getName());
            }
        }
        return dto;
    }
}