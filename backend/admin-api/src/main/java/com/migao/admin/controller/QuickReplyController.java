package com.migao.admin.controller;

import com.migao.admin.dto.*;
import com.migao.admin.config.TenantContext;
import com.migao.admin.service.QuickReplyTemplateService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 快捷回复模板管理控制器
 * 提供快捷回复模板 CRUD 及分类查询接口
 *
 * 前端对齐：quickReplyApi (frontend/admin-web/src/lib/api.ts)
 * - GET    /api/admin/quick-replies              → getTemplates
 * - GET    /api/admin/quick-replies/categories   → getCategories
 * - POST   /api/admin/quick-replies              → createTemplate
 * - PUT    /api/admin/quick-replies/{id}         → updateTemplate
 * - DELETE /api/admin/quick-replies/{id}         → deleteTemplate
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/quick-replies")
@RequiredArgsConstructor
public class QuickReplyController {

    private final QuickReplyTemplateService quickReplyTemplateService;

    /**
     * 分页查询快捷回复模板
     *
     * GET /api/admin/quick-replies?page=1&size=20&category=xxx&keyword=xxx
     */
    @GetMapping
    public ApiResponse<PageResponse<QuickReplyResponse>> getTemplates(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size,
            @RequestParam(required = false) String category,
            @RequestParam(required = false) String keyword) {
        log.info("查询快捷回复模板列表: page={}, size={}, category={}, keyword={}", page, size, category, keyword);
        Long tenantId = TenantContext.getTenantId();
        PageResponse<QuickReplyResponse> result = quickReplyTemplateService.getTemplatePage(page, size, category, keyword, tenantId);
        return ApiResponse.success(result);
    }

    /**
     * 获取所有分类列表
     * 注意：此路由必须放在 /{id} 之前，避免 Spring 将 "categories" 当作 id 匹配
     *
     * GET /api/admin/quick-replies/categories
     */
    @GetMapping("/categories")
    public ApiResponse<List<String>> getCategories() {
        Long tenantId = TenantContext.getTenantId();
        log.info("查询快捷回复分类列表: tenantId={}", tenantId);
        List<String> categories = quickReplyTemplateService.getCategories(tenantId);
        return ApiResponse.success(categories);
    }

    /**
     * 创建快捷回复模板
     *
     * POST /api/admin/quick-replies
     */
    @PostMapping
    public ApiResponse<QuickReplyResponse> createTemplate(
            @Valid @RequestBody QuickReplyCreateRequest request) {
        log.info("创建快捷回复模板: title={}, category={}", request.getTitle(), request.getCategory());
        Long tenantId = TenantContext.getTenantId();
        QuickReplyResponse result = quickReplyTemplateService.createTemplate(request, tenantId);
        return ApiResponse.success(result);
    }

    /**
     * 更新快捷回复模板
     *
     * PUT /api/admin/quick-replies/{id}
     */
    @PutMapping("/{id}")
    public ApiResponse<QuickReplyResponse> updateTemplate(
            @PathVariable String id,
            @Valid @RequestBody QuickReplyUpdateRequest request) {
        log.info("更新快捷回复模板: id={}", id);
        QuickReplyResponse result = quickReplyTemplateService.updateTemplate(id, request);
        return ApiResponse.success(result);
    }

    /**
     * 删除快捷回复模板
     *
     * DELETE /api/admin/quick-replies/{id}
     */
    @DeleteMapping("/{id}")
    public ApiResponse<Void> deleteTemplate(@PathVariable String id) {
        log.info("删除快捷回复模板: id={}", id);
        quickReplyTemplateService.deleteTemplate(id);
        return ApiResponse.success();
    }
}
