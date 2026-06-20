package com.migao.admin.service;

import com.migao.admin.dto.*;
import com.migao.admin.entity.Notification;
import com.migao.admin.entity.NotificationRule;
import com.migao.admin.entity.NotificationTemplate;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.NotificationMapper;
import com.migao.admin.mapper.NotificationRuleMapper;
import com.migao.admin.mapper.NotificationTemplateMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.BeanUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 通知服务类
 * 处理通知的创建、查询、标记已读、模板发送、事件触发等操作
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class NotificationService {

    private final NotificationMapper notificationMapper;
    private final NotificationTemplateMapper notificationTemplateMapper;
    private final NotificationRuleMapper notificationRuleMapper;

    /**
     * 创建通知
     *
     * @param tenantId 租户ID
     * @param request  创建请求
     * @return 通知DTO
     */
    @Transactional(rollbackFor = Exception.class)
    public NotificationDTO createNotification(Long tenantId, CreateNotificationRequest request) {
        Notification notification = Notification.builder()
                .tenantId(tenantId)
                .recipientId(request.getRecipientId())
                .recipientType(request.getRecipientType())
                .title(request.getTitle())
                .content(request.getContent())
                .channel(request.getChannel())
                .templateId(request.getTemplateId())
                .status("sent")
                .sentAt(OffsetDateTime.now())
                .retryCount(0)
                .build();

        notificationMapper.insert(notification);
        log.info("创建通知成功: id={}, recipientId={}, title={}", notification.getId(), request.getRecipientId(), request.getTitle());

        return convertToDTO(notification);
    }

    /**
     * 通过模板创建通知
     *
     * @param tenantId      租户ID
     * @param templateName  模板名称
     * @param recipientId   接收人ID
     * @param recipientType 接收人类型
     * @param variables     模板变量
     * @return 通知DTO，模板不存在时返回 null
     */
    @Transactional(rollbackFor = Exception.class)
    public NotificationDTO createFromTemplate(Long tenantId, String templateName, String recipientId,
                                               String recipientType, Map<String, String> variables) {
        // 查找模板
        LambdaQueryWrapper<NotificationTemplate> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(NotificationTemplate::getTenantId, tenantId)
                .eq(NotificationTemplate::getName, templateName)
                .eq(NotificationTemplate::getStatus, "active");
        NotificationTemplate template = notificationTemplateMapper.selectOne(wrapper);

        if (template == null) {
            log.warn("通知模板不存在或未启用: tenantId={}, templateName={}", tenantId, templateName);
            return null;
        }

        // 替换模板变量
        String content = template.getTemplateContent();
        if (variables != null) {
            for (Map.Entry<String, String> entry : variables.entrySet()) {
                content = content.replace("{{" + entry.getKey() + "}}", entry.getValue());
            }
        }

        // 创建通知
        Notification notification = Notification.builder()
                .tenantId(tenantId)
                .templateId(template.getId())
                .recipientId(recipientId)
                .recipientType(recipientType)
                .channel(template.getChannel())
                .title(templateName)
                .content(content)
                .status("sent")
                .sentAt(OffsetDateTime.now())
                .retryCount(0)
                .build();

        notificationMapper.insert(notification);
        log.info("通过模板创建通知成功: id={}, templateName={}, recipientId={}", notification.getId(), templateName, recipientId);

        return convertToDTO(notification);
    }

    /**
     * 分页查询通知列表
     *
     * @param tenantId     租户ID
     * @param recipientId  接收人ID
     * @param queryRequest 查询请求
     * @return 分页响应
     */
    public PageResponse<NotificationDTO> queryNotifications(String recipientId,
                                                             NotificationQueryRequest queryRequest) {
        Page<Notification> page = new Page<>(queryRequest.getPage(), queryRequest.getSize());

        IPage<Notification> resultPage = notificationMapper.selectByRecipientId(
                recipientId, queryRequest.getStatus(), queryRequest.getChannel(), page);

        List<NotificationDTO> dtos = resultPage.getRecords().stream()
                .map(this::convertToDTO)
                .collect(Collectors.toList());

        return PageResponse.of(resultPage.getTotal(), resultPage.getCurrent(), resultPage.getSize(), dtos);
    }

    /**
     * 获取未读通知数
     *
     * @param tenantId    租户ID
     * @param recipientId 接收人ID
     * @return 未读数响应
     */
    public UnreadCountResponse getUnreadCount(String recipientId) {
        Long count = notificationMapper.countUnread(recipientId);
        return new UnreadCountResponse(count);
    }

    /**
     * 标记通知为已读
     *
     * @param tenantId       租户ID
     * @param recipientId    接收人ID
     * @param notificationId 通知ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void markAsRead(Long tenantId, String recipientId, String notificationId) {
        Notification notification = notificationMapper.selectById(notificationId);
        if (notification == null) {
            throw BusinessException.notFound("通知");
        }

        // 多租户安全校验
        if (!tenantId.equals(notification.getTenantId())) {
            throw BusinessException.permissionDenied();
        }

        // 接收人权限校验：确保当前用户只能操作自己的通知
        if (!recipientId.equals(notification.getRecipientId())) {
            throw BusinessException.permissionDenied();
        }

        notification.setStatus("read");
        notification.setReadAt(OffsetDateTime.now());
        notificationMapper.updateById(notification);

        log.info("标记通知已读: id={}, recipientId={}", notificationId, recipientId);
    }

    /**
     * 标记所有通知为已读
     *
     * @param tenantId    租户ID
     * @param recipientId 接收人ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void markAllAsRead(Long tenantId, String recipientId) {
        LambdaUpdateWrapper<Notification> updateWrapper = new LambdaUpdateWrapper<>();
        updateWrapper.eq(Notification::getTenantId, tenantId)
                .eq(Notification::getRecipientId, recipientId)
                .ne(Notification::getStatus, "read")
                .set(Notification::getStatus, "read")
                .set(Notification::getReadAt, OffsetDateTime.now());

        notificationMapper.update(null, updateWrapper);
        log.info("批量标记通知已读: tenantId={}, recipientId={}", tenantId, recipientId);
    }

    /**
     * 删除通知
     *
     * @param tenantId       租户ID
     * @param recipientId    接收人ID
     * @param notificationId 通知ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void deleteNotification(Long tenantId, String recipientId, String notificationId) {
        Notification notification = notificationMapper.selectById(notificationId);
        if (notification == null) {
            throw BusinessException.notFound("通知");
        }

        // 多租户安全校验
        if (!tenantId.equals(notification.getTenantId())) {
            throw BusinessException.permissionDenied();
        }

        // 接收人权限校验：确保当前用户只能操作自己的通知
        if (!recipientId.equals(notification.getRecipientId())) {
            throw BusinessException.permissionDenied();
        }

        notificationMapper.deleteById(notificationId);
        log.info("删除通知成功: id={}, recipientId={}", notificationId, recipientId);
    }

    /**
     * 根据事件触发通知
     * 业务代码（订单变更、工单分配等）调用此方法即可自动创建通知
     *
     * @param tenantId    租户ID
     * @param eventType   事件类型
     * @param contextData 上下文数据，应包含 recipientId 和 recipientType
     */
    @Transactional(rollbackFor = Exception.class)
    public void triggerByEvent(Long tenantId, String eventType, Map<String, String> contextData) {
        // 查询匹配的通知规则
        LambdaQueryWrapper<NotificationRule> ruleWrapper = new LambdaQueryWrapper<>();
        ruleWrapper.eq(NotificationRule::getTenantId, tenantId)
                .eq(NotificationRule::getEventType, eventType)
                .eq(NotificationRule::getEnabled, true);

        List<NotificationRule> rules = notificationRuleMapper.selectList(ruleWrapper);
        if (rules.isEmpty()) {
            log.debug("未找到匹配的通知规则: tenantId={}, eventType={}", tenantId, eventType);
            return;
        }

        String recipientId = contextData.get("recipientId");
        String recipientType = contextData.get("recipientType");

        for (NotificationRule rule : rules) {
            // 解析 channels JSONB 数组，判断是否包含 "internal"
            String channels = rule.getChannels();
            if (channels == null || !channels.contains("internal")) {
                continue;
            }

            // 查找关联模板
            if (rule.getTemplateId() == null) {
                log.warn("通知规则未关联模板: ruleId={}", rule.getId());
                continue;
            }

            NotificationTemplate template = notificationTemplateMapper.selectById(rule.getTemplateId());
            if (template == null) {
                log.warn("通知规则关联的模板不存在: ruleId={}, templateId={}", rule.getId(), rule.getTemplateId());
                continue;
            }

            // 替换模板变量
            String content = template.getTemplateContent();
            if (contextData != null) {
                for (Map.Entry<String, String> entry : contextData.entrySet()) {
                    content = content.replace("{{" + entry.getKey() + "}}", entry.getValue());
                }
            }

            // 使用规则中的 recipientType（如果 contextData 中未提供）
            String finalRecipientType = recipientType != null ? recipientType : rule.getRecipientType();

            // 创建站内通知
            Notification notification = Notification.builder()
                    .tenantId(tenantId)
                    .ruleId(rule.getId())
                    .templateId(template.getId())
                    .recipientId(recipientId)
                    .recipientType(finalRecipientType)
                    .channel("internal")
                    .title(template.getName())
                    .content(content)
                    .status("sent")
                    .sentAt(OffsetDateTime.now())
                    .retryCount(0)
                    .build();

            notificationMapper.insert(notification);
            log.info("事件触发通知成功: ruleId={}, templateId={}, recipientId={}, eventType={}",
                    rule.getId(), template.getId(), recipientId, eventType);
        }
    }

    /**
     * Entity 转 DTO
     */
    private NotificationDTO convertToDTO(Notification notification) {
        NotificationDTO dto = new NotificationDTO();
        BeanUtils.copyProperties(notification, dto);
        return dto;
    }
}
