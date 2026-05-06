package com.aikf.admin.controller;

import com.aikf.admin.config.TenantContext;
import com.aikf.admin.dto.*;
import com.aikf.admin.service.ProcessingItemService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

/**
 * 加工项管理控制器
 * 提供加工项 CRUD 和价格计算接口
 */
@Slf4j
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

    /**
     * 价格计算
     *
     * POST /api/admin/processing-items/calculate
     */
    @PostMapping("/calculate")
    public ApiResponse<PriceCalculateResponse> calculatePrice(@Valid @RequestBody PriceCalculateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("计算加工项价格: processingItemId={}, quantity={}, tenantId={}", request.getProcessingItemId(), request.getQuantity(), tenantId);
        PriceCalculateResponse result = processingItemService.calculatePrice(request, tenantId);
        return ApiResponse.success(result);
    }
}
