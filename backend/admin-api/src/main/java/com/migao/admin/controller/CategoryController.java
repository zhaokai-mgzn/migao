package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.CategoryCreateRequest;
import com.migao.admin.dto.CategoryMoveRequest;
import com.migao.admin.dto.CategoryResponse;
import com.migao.admin.dto.CategoryUpdateRequest;
import com.migao.admin.service.CategoryService;
import com.migao.admin.security.RequirePermission;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 商品分类管理控制器
 * 提供分类的扁平列表管理接口（issue #2905 — 无父子概念，支持上下移动排序）
 */
@Slf4j
@RequirePermission("product:category")
@RestController
@RequestMapping("/api/admin/categories")
@RequiredArgsConstructor
public class CategoryController {

    private final CategoryService categoryService;

    /**
     * 获取分类列表（扁平结构，按 sort 升序）
     *
     * GET /api/admin/categories
     * GET /api/admin/categories/tree
     */
    @GetMapping({"" , "/tree"})
    public ApiResponse<List<CategoryResponse>> getCategoryTree() {
        Long tenantId = TenantContext.getTenantId();
        log.info("获取分类列表, tenantId={}", tenantId);
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
     * 上下移动分类
     *
     * POST /api/admin/categories/{id}/move
     * body: {"direction": "up" | "down"}
     */
    @PostMapping("/{id}/move")
    public ApiResponse<Void> moveCategory(
            @PathVariable String id,
            @Valid @RequestBody CategoryMoveRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("移动分类: id={}, direction={}, tenantId={}", id, request.getDirection(), tenantId);
        categoryService.moveCategory(id, request.getDirection(), tenantId);
        return ApiResponse.success();
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
