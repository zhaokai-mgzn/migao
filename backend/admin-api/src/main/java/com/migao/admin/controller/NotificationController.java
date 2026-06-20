package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.*;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.NotificationService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

/**
 * 通知管理控制器
 * 提供通知查询、已读标记、创建、删除等管理接口
 *
 * 前端对齐：notificationApi
 * - GET    /api/admin/notifications              → 查询通知列表
 * - GET    /api/admin/notifications/unread-count  → 获取未读数
 * - PUT    /api/admin/notifications/{id}/read     → 标记已读
 * - PUT    /api/admin/notifications/read-all      → 全部已读
 * - DELETE /api/admin/notifications/{id}          → 删除通知
 * - POST   /api/admin/notifications               → 创建通知
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/notifications")
@RequiredArgsConstructor
public class NotificationController {

    private final NotificationService notificationService;

    /**
     * 分页查询通知列表
     *
     * GET /api/admin/notifications?page=1&size=20&status=sent&channel=internal
     */
    @GetMapping
    public ApiResponse<PageResponse<NotificationDTO>> getNotifications(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String channel) {
        String userId = getCurrentUserId();
        log.info("查询通知列表: userId={}, page={}, size={}, status={}, channel={}", userId, page, size, status, channel);

        NotificationQueryRequest queryRequest = new NotificationQueryRequest();
        queryRequest.setPage(page);
        queryRequest.setSize(size);
        queryRequest.setStatus(status);
        queryRequest.setChannel(channel);

        PageResponse<NotificationDTO> result = notificationService.queryNotifications(userId, queryRequest);
        return ApiResponse.success(result);
    }

    /**
     * 获取未读通知数量
     *
     * GET /api/admin/notifications/unread-count
     */
    @GetMapping("/unread-count")
    public ApiResponse<UnreadCountResponse> getUnreadCount() {
        String userId = getCurrentUserId();
        log.info("获取未读通知数: userId={}", userId);

        UnreadCountResponse result = notificationService.getUnreadCount(userId);
        return ApiResponse.success(result);
    }

    /**
     * 标记单条通知为已读
     *
     * PUT /api/admin/notifications/{id}/read
     */
    @PutMapping("/{id}/read")
    public ApiResponse<Void> markAsRead(@PathVariable String id) {
        Long tenantId = TenantContext.getTenantId();
        String userId = getCurrentUserId();
        log.info("标记通知已读: id={}, userId={}", id, userId);

        notificationService.markAsRead(tenantId, userId, id);
        return ApiResponse.success();
    }

    /**
     * 标记当前用户所有未读通知为已读
     *
     * PUT /api/admin/notifications/read-all
     */
    @PutMapping("/read-all")
    public ApiResponse<Void> markAllAsRead() {
        Long tenantId = TenantContext.getTenantId();
        String userId = getCurrentUserId();
        log.info("批量标记通知已读: userId={}", userId);

        notificationService.markAllAsRead(tenantId, userId);
        return ApiResponse.success();
    }

    /**
     * 删除单条通知
     *
     * DELETE /api/admin/notifications/{id}
     */
    @DeleteMapping("/{id}")
    public ApiResponse<Void> deleteNotification(@PathVariable String id) {
        Long tenantId = TenantContext.getTenantId();
        String userId = getCurrentUserId();
        log.info("删除通知: id={}, userId={}", id, userId);

        notificationService.deleteNotification(tenantId, userId, id);
        return ApiResponse.success();
    }

    /**
     * 创建通知（管理员手动发送）
     *
     * POST /api/admin/notifications
     */
    @PostMapping
    public ApiResponse<NotificationDTO> createNotification(@Valid @RequestBody CreateNotificationRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("创建通知: recipientId={}, title={}", request.getRecipientId(), request.getTitle());

        NotificationDTO result = notificationService.createNotification(tenantId, request);
        return ApiResponse.success(result);
    }

    /**
     * 从认证信息中提取当前用户ID
     *
     * @return 当前用户ID
     */
    private String getCurrentUserId() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !(authentication.getPrincipal() instanceof SecurityUser securityUser)) {
            throw BusinessException.authFailed("用户未认证");
        }
        return securityUser.getUserId();
    }
}
