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

        // 替换模板变量（issue #7524：标题与正文同一份渲染）
        String content = render(template.getTemplateContent(), variables);
        String title = render(template.getTitleTemplate() != null ? template.getTitleTemplate() : templateName,
                variables);

        // 创建通知
        Notification notification = Notification.builder()
                .tenantId(tenantId)
                .templateId(template.getId())
                .recipientId(recipientId)
                .recipientType(recipientType)
                .channel(template.getChannel())
                .title(title)
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
                recipientId, queryRequest.getStatus(), queryRequest.getChannel(),
                queryRequest.getBizType(), page);

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

        // issue #6956 · 现象 C：判影响行数（同一条被并发读走两次时，只许一次真删到）
        if (notificationMapper.deleteById(notificationId) == 0) {
            throw BusinessException.notFound("通知");
        }
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
        triggerByEvent(tenantId, eventType, contextData, null);
    }

    /**
     * 根据事件触发通知（带**结构化业务信息**，issue #7524）。
     *
     * <p>与三参版的唯一差别：多一个 {@link NotificationEvent}，把「哪一单、点去哪、多急、什么时候发生」
     * 一并落库（改前只有渲染好的 title/content 两段文本 ⇒ 铃铛点不进单据、也无法按类型筛）。</p>
     *
     * <p>幂等：同一 {@code eventType + bizId + recipientId} 只落一条（业务事件重放/事务重试不得刷屏），
     * 由唯一索引 {@code uk_notifications_dedupe} 兜底。</p>
     *
     * @param event 结构化业务信息；{@code null} = 老调用方（行为与改前逐字一致：不写 biz 列、不去重）
     */
    @Transactional(rollbackFor = Exception.class)
    public void triggerByEvent(Long tenantId, String eventType, Map<String, String> contextData,
                               NotificationEvent event) {
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

            // 替换模板变量（标题也渲染 —— 改前标题恒等于模板名，铃铛里没有单号）
            String content = render(template.getTemplateContent(), contextData);
            String title = render(template.getTitleTemplate() != null ? template.getTitleTemplate() : template.getName(),
                    contextData);

            // 使用规则中的 recipientType（如果 contextData 中未提供）
            String finalRecipientType = recipientType != null ? recipientType : rule.getRecipientType();

            // 幂等（issue #7524）：同一事件 × 同一业务对象 × 同一收件人只落一条。
            // 先查一次而不是直接撞索引 —— PG 事务里撞唯一索引会让整条事务 aborted（多管理员循环会连带失败）。
            String dedupeKey = null;
            if (event != null && event.getBizId() != null && recipientId != null) {
                dedupeKey = eventType + ":" + event.getBizId() + ":" + recipientId;
                Long existing = notificationMapper.countByDedupeKey(tenantId, dedupeKey);
                if (existing != null && existing > 0) {
                    log.debug("事件已通知过，跳过重复落库: eventType={}, bizId={}, recipientId={}",
                            eventType, event.getBizId(), recipientId);
                    continue;
                }
            }

            // 创建站内通知
            Notification notification = Notification.builder()
                    .tenantId(tenantId)
                    .ruleId(rule.getId())
                    .templateId(template.getId())
                    .recipientId(recipientId)
                    .recipientType(finalRecipientType)
                    .channel("internal")
                    .title(title)
                    .content(content)
                    .bizType(event != null ? event.getBizType() : null)
                    .bizId(event != null ? event.getBizId() : null)
                    .bizNo(event != null ? event.getBizNo() : null)
                    .targetPath(event != null ? event.getTargetPath() : null)
                    .severity(event != null && event.getSeverity() != null ? event.getSeverity() : "info")
                    .occurredAt(event != null && event.getOccurredAt() != null
                            ? event.getOccurredAt() : OffsetDateTime.now())
                    .dedupeKey(dedupeKey)
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
        triggerForTenantAdmins(tenantId, eventType, vars, null);
    }

    /**
     * 面向租户管理员的待办事件广播（带结构化业务信息，issue #7524）。
     * 收件人路由与三参版**逐字相同**（租户 admin 角色），只是把 event 一并透传给 {@link #triggerByEvent}。
     */
    @Transactional(rollbackFor = Exception.class)
    public void triggerForTenantAdmins(Long tenantId, String eventType, Map<String, String> vars,
                                       NotificationEvent event) {
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
                triggerByEvent(tenantId, eventType, ctx, event);
            } catch (Exception e) {
                log.warn("管理员待办通知发送失败，忽略: adminId={}, eventType={}, error={}",
                        admin.getId(), eventType, e.getMessage());
            }
        }
    }

    /**
     * 渲染模板：把 {@code {{var}}} 替换为上下文值（issue #7524 —— 标题与正文走同一份渲染）。
     *
     * <p>未提供的变量**保留占位原样**（与改前逐字一致：老模板缺变量时不静默清空，
     * 反而让人一眼看出漏传）；显式传 {@code null} 值才渲染为空串。</p>
     */
    private static String render(String template, Map<String, String> variables) {
        if (template == null) {
            return null;
        }
        String rendered = template;
        if (variables != null) {
            for (Map.Entry<String, String> entry : variables.entrySet()) {
                rendered = rendered.replace("{{" + entry.getKey() + "}}",
                        entry.getValue() == null ? "" : entry.getValue());
            }
        }
        return rendered;
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
