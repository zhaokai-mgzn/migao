package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.*;
import com.migao.admin.service.ProcessingItemService;
import com.migao.admin.security.RequirePermission;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

/**
 * 加工项管理控制器
 * 提供加工项 CRUD 接口（issue #4882：`POST /calculate` 端点随加工项目录的计价方式与单价一并退场）
 */
@Slf4j
@RequirePermission("processing:manage")
@RestController
@RequestMapping("/api/admin/processing-items")
@RequiredArgsConstructor
public class ProcessingItemController {

    private final ProcessingItemService processingItemService;

    /**
     * 分页查询加工项列表
     *
     * GET /api/admin/processing-items?page=1&size=20&keyword=xxx&categoryId=xxx&status=active
     */
    @GetMapping
    public ApiResponse<PageResponse<ProcessingItemResponse>> getProcessingItems(ProcessingItemQueryRequest query) {
        Long tenantId = TenantContext.getTenantId();
        log.info("查询加工项列表: page={}, size={}, keyword={}, tenantId={}", query.getPage(), query.getSize(), query.getKeyword(), tenantId);
        PageResponse<ProcessingItemResponse> result = processingItemService.getProcessingItems(query, tenantId);
        return ApiResponse.success(result);
    }

    /**
     * 查询加工项详情
     *
     * GET /api/admin/processing-items/{id}
     */
    @GetMapping("/{id}")
    public ApiResponse<ProcessingItemResponse> getProcessingItemById(@PathVariable String id) {
        Long tenantId = TenantContext.getTenantId();
        log.info("查询加工项详情: id={}, tenantId={}", id, tenantId);
        ProcessingItemResponse item = processingItemService.getProcessingItemById(id, tenantId);
        return ApiResponse.success(item);
    }

    /**
     * 新增加工项
     *
     * POST /api/admin/processing-items
     */
    @PostMapping
    public ApiResponse<ProcessingItemResponse> createProcessingItem(@Valid @RequestBody ProcessingItemCreateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("创建加工项: name={}, tenantId={}", request.getName(), tenantId);
        ProcessingItemResponse item = processingItemService.createProcessingItem(request, tenantId);
        return ApiResponse.success(item);
    }

    /**
     * 编辑加工项
     *
     * PUT /api/admin/processing-items/{id}
     */
    @PutMapping("/{id}")
    public ApiResponse<ProcessingItemResponse> updateProcessingItem(
            @PathVariable String id,
            @Valid @RequestBody ProcessingItemUpdateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("更新加工项: id={}, tenantId={}", id, tenantId);
        ProcessingItemResponse item = processingItemService.updateProcessingItem(id, request, tenantId);
        return ApiResponse.success(item);
    }

    /**
     * 删除加工项
     *
     * DELETE /api/admin/processing-items/{id}
     */
    @DeleteMapping("/{id}")
    public ApiResponse<Void> deleteProcessingItem(@PathVariable String id) {
        Long tenantId = TenantContext.getTenantId();
        log.info("删除加工项: id={}, tenantId={}", id, tenantId);
        processingItemService.deleteProcessingItem(id, tenantId);
        return ApiResponse.success();
    }
}
