package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.NotificationTemplateDTO;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.SaveNotificationTemplateRequest;
import com.migao.admin.service.NotificationTemplateService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

/**
 * 通知模板管理控制器（issue #2965 补齐）
 *
 * 接口契约：
 * - GET    /api/admin/notification-templates?page=&size= → 分页查询（本租户 + 系统内置）
 * - POST   /api/admin/notification-templates            → 创建租户模板
 * - PUT    /api/admin/notification-templates/{id}        → 更新租户模板
 * - DELETE /api/admin/notification-templates/{id}        → 删除租户模板（系统模板/被引用模板禁止）
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/notification-templates")
@RequiredArgsConstructor
public class NotificationTemplateController {

    private final NotificationTemplateService templateService;

    /**
     * GET /api/admin/notification-templates?page=1&size=20
     */
    @GetMapping
    public ApiResponse<PageResponse<NotificationTemplateDTO>> listTemplates(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size) {
        Long tenantId = TenantContext.getTenantId();
        PageResponse<NotificationTemplateDTO> result = templateService.queryTemplates(page, size, tenantId);
        return ApiResponse.success(result);
    }

    /**
     * POST /api/admin/notification-templates
     */
    @PostMapping
    public ApiResponse<NotificationTemplateDTO> createTemplate(
            @Valid @RequestBody SaveNotificationTemplateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("创建通知模板: name={}, tenantId={}", request.getName(), tenantId);
        NotificationTemplateDTO result = templateService.createTemplate(tenantId, request);
        return ApiResponse.success(result);
    }

    /**
     * PUT /api/admin/notification-templates/{id}
     */
    @PutMapping("/{id}")
    public ApiResponse<NotificationTemplateDTO> updateTemplate(
            @PathVariable String id,
            @Valid @RequestBody SaveNotificationTemplateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("更新通知模板: id={}, tenantId={}", id, tenantId);
        NotificationTemplateDTO result = templateService.updateTemplate(tenantId, id, request);
        return ApiResponse.success(result);
    }

    /**
     * DELETE /api/admin/notification-templates/{id}
     */
    @DeleteMapping("/{id}")
    public ApiResponse<Void> deleteTemplate(@PathVariable String id) {
        Long tenantId = TenantContext.getTenantId();
        log.info("删除通知模板: id={}, tenantId={}", id, tenantId);
        templateService.deleteTemplate(tenantId, id);
        return ApiResponse.success();
    }
}