package com.aikf.admin.controller;

import com.aikf.admin.config.TenantContext;
import com.aikf.admin.dto.ApiResponse;
import com.aikf.admin.dto.CategoryCreateRequest;
import com.aikf.admin.dto.CategoryResponse;
import com.aikf.admin.dto.CategoryUpdateRequest;
import com.aikf.admin.service.CategoryService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 商品分类管理控制器
 * 提供分类的树形结构管理接口
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/categories")
@RequiredArgsConstructor
public class CategoryController {

    private final CategoryService categoryService;

    /**
     * 获取分类树
     *
     * GET /api/admin/categories
     * GET /api/admin/categories/tree
     */
    @GetMapping({"" , "/tree"})
    public ApiResponse<List<CategoryResponse>> getCategoryTree() {
        Long tenantId = TenantContext.getTenantId();
        log.info("获取分类树, tenantId={}", tenantId);
        List<CategoryResponse> tree = categoryService.getCategoryTree(tenantId);
        return ApiResponse.success(tree);
    }

    /**
     * 创建分类
     *
     * POST /api/admin/categories
     */
    @PostMapping
    public ApiResponse<CategoryResponse> createCategory(@Valid @RequestBody CategoryCreateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("创建分类: name={}, tenantId={}", request.getName(), tenantId);
        CategoryResponse category = categoryService.createCategory(request, tenantId);
        return ApiResponse.success(category);
    }

    /**
     * 更新分类
     *
     * PUT /api/admin/categories/{id}
     */
    @PutMapping("/{id}")
    public ApiResponse<CategoryResponse> updateCategory(
            @PathVariable String id,
            @Valid @RequestBody CategoryUpdateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("更新分类: id={}, tenantId={}", id, tenantId);
        CategoryResponse category = categoryService.updateCategory(id, request, tenantId);
        return ApiResponse.success(category);
    }

    /**
     * 删除分类
     *
     * DELETE /api/admin/categories/{id}
     */
    @DeleteMapping("/{id}")
    public ApiResponse<Void> deleteCategory(@PathVariable String id) {
        Long tenantId = TenantContext.getTenantId();
        log.info("删除分类: id={}, tenantId={}", id, tenantId);
        categoryService.deleteCategory(id, tenantId);
        return ApiResponse.success();
    }
}
