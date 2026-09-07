package com.migao.admin.service;

import com.migao.admin.dto.*;
import com.migao.admin.entity.Notification;
import com.migao.admin.entity.NotificationRule;
import com.migao.admin.entity.NotificationTemplate;
import com.migao.admin.entity.Tenant;
import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.NotificationMapper;
import com.migao.admin.mapper.NotificationRuleMapper;
import com.migao.admin.mapper.NotificationTemplateMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserMapper;
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
import java.util.HashMap;
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
    private final UserMapper userMapper;
    private final TenantMapper tenantMapper;

    /**
     * 租户系统通知总开关（#3003）：企业基础设置「启用系统通知」。
     * tenants.notification_enabled=false 时租户不再产生自动站内信（历史通知保留）。
     * 租户不存在或字段为 null（存量数据）视为开启 —— 不改变既有行为。
     */
    private boolean tenantNotificationsEnabled(Long tenantId) {
        Tenant tenant = tenantMapper.selectById(tenantId);
        return tenant == null || Boolean.TRUE.equals(tenant.getNotificationEnabled());
    }

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
        // 查找模板：优先租户自定义模板，其次系统内置模板（tenantId=0），取租户级优先
        LambdaQueryWrapper<NotificationTemplate> wrapper = new LambdaQueryWrapper<>();
        wrapper.and(w -> w.eq(NotificationTemplate::getTenantId, tenantId)
                        .or().eq(NotificationTemplate::getTenantId, 0L))
                .eq(NotificationTemplate::getName, templateName)
                .eq(NotificationTemplate::getStatus, "active")
                .orderByDesc(NotificationTemplate::getTenantId)
                .last("LIMIT 1");
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
        // #3003：租户关闭「启用系统通知」→ 自动站内信直接跳过（历史通知保留）
        if (!tenantNotificationsEnabled(tenantId)) {
            log.debug("租户已关闭系统通知，跳过事件通知: tenantId={}, eventType={}", tenantId, eventType);
            return;
        }
        // 查询匹配的通知规则：优先租户自定义规则，其次系统内置规则（tenantId=0）
        LambdaQueryWrapper<NotificationRule> ruleWrapper = new LambdaQueryWrapper<>();
        ruleWrapper.and(w -> w.eq(NotificationRule::getTenantId, tenantId)
                        .or().eq(NotificationRule::getTenantId, 0L))
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
     * 面向租户管理员的待办事件广播（站内信接收人路由，issue #2965 v2）
     *
     * 主流通知中心设计：B 端待办事件（新订单、新售后工单）应通知负责处理的人——
     * 本实现按「租户 admin 角色」路由（users.role = 'admin'，与登录鉴权口径一致），
     * 每位管理员独立收到一条站内信（B 端铃铛即可见），管理员据此分派处理。
     * 某一管理员发送失败不影响其余管理员（逐个容错）。
     *
     * @param tenantId  租户ID
     * @param eventType 事件类型（order_created / after_sales_created 等）
     * @param vars      模板变量（不含 recipientId/recipientType，由本方法填充）
     */
    @Transactional(rollbackFor = Exception.class)
    public void triggerForTenantAdmins(Long tenantId, String eventType, Map<String, String> vars) {
        // #3003：租户关闭「启用系统通知」→ 待办广播直接跳过（避免无谓查管理员/逐管理员触发）
        if (!tenantNotificationsEnabled(tenantId)) {
            log.debug("租户已关闭系统通知，跳过管理员待办广播: tenantId={}, eventType={}", tenantId, eventType);
            return;
        }
        LambdaQueryWrapper<User> adminWrapper = new LambdaQueryWrapper<>();
        adminWrapper.eq(User::getTenantId, tenantId)
                .eq(User::getRole, "admin")
                .eq(User::getDeleted, 0);
        List<User> admins = userMapper.selectList(adminWrapper);
        if (admins.isEmpty()) {
            log.debug("租户无管理员账号，跳过待办通知: tenantId={}, eventType={}", tenantId, eventType);
            return;
        }
        for (User admin : admins) {
            try {
                Map<String, String> ctx = vars != null ? new HashMap<>(vars) : new HashMap<>();
                ctx.put("recipientId", admin.getId());
                ctx.put("recipientType", "employee");
                triggerByEvent(tenantId, eventType, ctx);
            } catch (Exception e) {
                log.warn("管理员待办通知发送失败，忽略: adminId={}, eventType={}, error={}",
                        admin.getId(), eventType, e.getMessage());
            }
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
