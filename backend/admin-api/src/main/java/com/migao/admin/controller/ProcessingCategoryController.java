package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.ProcessingCategoryCreateRequest;
import com.migao.admin.dto.ProcessingCategoryResponse;
import com.migao.admin.dto.ProcessingCategoryUpdateRequest;
import com.migao.admin.service.ProcessingCategoryService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 加工分类管理控制器
 * 提供加工分类的增删改查接口
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/processing-categories")
@RequiredArgsConstructor
public class ProcessingCategoryController {

    private final ProcessingCategoryService processingCategoryService;

    /**
     * 获取加工分类列表
     *
     * GET /api/admin/processing-categories
     */
    @GetMapping
    public ApiResponse<List<ProcessingCategoryResponse>> getProcessingCategories() {
        Long tenantId = TenantContext.getTenantId();
        log.info("获取加工分类列表, tenantId={}", tenantId);
        List<ProcessingCategoryResponse> list = processingCategoryService.getProcessingCategories(tenantId);
        return ApiResponse.success(list);
    }

    /**
     * 查询加工分类详情
     *
     * GET /api/admin/processing-categories/{id}
     */
    @GetMapping("/{id}")
    public ApiResponse<ProcessingCategoryResponse> getProcessingCategoryById(@PathVariable String id) {
        Long tenantId = TenantContext.getTenantId();
        log.info("查询加工分类详情: id={}, tenantId={}", id, tenantId);
        ProcessingCategoryResponse category = processingCategoryService.getProcessingCategoryById(id, tenantId);
        return ApiResponse.success(category);
    }

    /**
     * 创建加工分类
     *
     * POST /api/admin/processing-categories
     */
    @PostMapping
    public ApiResponse<ProcessingCategoryResponse> createProcessingCategory(@Valid @RequestBody ProcessingCategoryCreateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("创建加工分类: name={}, tenantId={}", request.getName(), tenantId);
        ProcessingCategoryResponse category = processingCategoryService.createProcessingCategory(request, tenantId);
        return ApiResponse.success(category);
    }

    /**
     * 更新加工分类
     *
     * PUT /api/admin/processing-categories/{id}
     */
    @PutMapping("/{id}")
    public ApiResponse<ProcessingCategoryResponse> updateProcessingCategory(
            @PathVariable String id,
            @Valid @RequestBody ProcessingCategoryUpdateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("更新加工分类: id={}, tenantId={}", id, tenantId);
        ProcessingCategoryResponse category = processingCategoryService.updateProcessingCategory(id, request, tenantId);
        return ApiResponse.success(category);
    }

    /**
     * 删除加工分类
     *
     * DELETE /api/admin/processing-categories/{id}
     */
    @DeleteMapping("/{id}")
    public ApiResponse<Void> deleteProcessingCategory(@PathVariable String id) {
        Long tenantId = TenantContext.getTenantId();
        log.info("删除加工分类: id={}, tenantId={}", id, tenantId);
        processingCategoryService.deleteProcessingCategory(id, tenantId);
        return ApiResponse.success();
    }
}
