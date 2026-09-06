package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.NotificationRuleDTO;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.SaveNotificationRuleRequest;
import com.migao.admin.service.NotificationRuleService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

/**
 * 通知规则管理控制器（issue #2965 补齐）
 *
 * 接口契约：
 * - GET    /api/admin/notification-rules?page=&size=&eventType= → 分页查询（可按事件类型过滤）
 * - POST   /api/admin/notification-rules            → 创建租户规则
 * - PUT    /api/admin/notification-rules/{id}        → 更新租户规则
 * - DELETE /api/admin/notification-rules/{id}        → 删除租户规则（系统规则禁止）
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/notification-rules")
@RequiredArgsConstructor
public class NotificationRuleController {

    private final NotificationRuleService ruleService;

    /**
     * GET /api/admin/notification-rules?page=1&size=20&eventType=order_created
     */
    @GetMapping
    public ApiResponse<PageResponse<NotificationRuleDTO>> listRules(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size,
            @RequestParam(required = false) String eventType) {
        Long tenantId = TenantContext.getTenantId();
        PageResponse<NotificationRuleDTO> result = ruleService.queryRules(page, size, tenantId, eventType);
        return ApiResponse.success(result);
    }

    /**
     * POST /api/admin/notification-rules
     */
    @PostMapping
    public ApiResponse<NotificationRuleDTO> createRule(
            @Valid @RequestBody SaveNotificationRuleRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("创建通知规则: eventType={}, tenantId={}", request.getEventType(), tenantId);
        NotificationRuleDTO result = ruleService.createRule(tenantId, request);
        return ApiResponse.success(result);
    }

    /**
     * PUT /api/admin/notification-rules/{id}
     */
    @PutMapping("/{id}")
    public ApiResponse<NotificationRuleDTO> updateRule(
            @PathVariable String id,
            @Valid @RequestBody SaveNotificationRuleRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("更新通知规则: id={}, tenantId={}", id, tenantId);
        NotificationRuleDTO result = ruleService.updateRule(tenantId, id, request);
        return ApiResponse.success(result);
    }

    /**
     * DELETE /api/admin/notification-rules/{id}
     */
    @DeleteMapping("/{id}")
    public ApiResponse<Void> deleteRule(@PathVariable String id) {
        Long tenantId = TenantContext.getTenantId();
        log.info("删除通知规则: id={}, tenantId={}", id, tenantId);
        ruleService.deleteRule(tenantId, id);
        return ApiResponse.success();
    }
}