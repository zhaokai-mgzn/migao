package com.aikf.admin.controller;

import com.aikf.admin.config.TenantContext;
import com.aikf.admin.dto.*;
import com.aikf.admin.service.ProductService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * 商品管理控制器
 * 提供商品 CRUD、上下架等管理接口
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/products")
@RequiredArgsConstructor
public class ProductController {

    private final ProductService productService;

    /**
     * 分页查询商品列表
     *
     * GET /api/admin/products?page=1&size=20&keyword=xxx&categoryId=xxx&status=on_sale
     */
    @GetMapping
    public ApiResponse<PageResponse<ProductResponse>> getProducts(ProductQueryRequest query) {
        Long tenantId = TenantContext.getTenantId();
        log.info("查询商品列表: page={}, size={}, keyword={}, tenantId={}", query.getPage(), query.getSize(), query.getKeyword(), tenantId);
        PageResponse<ProductResponse> result = productService.getProducts(query, tenantId);
        return ApiResponse.success(result);
    }

    /**
     * 查询商品详情
     *
     * GET /api/admin/products/{id}
     */
    @GetMapping("/{id}")
    public ApiResponse<ProductResponse> getProductById(@PathVariable String id) {
        Long tenantId = TenantContext.getTenantId();
        log.info("查询商品详情: id={}, tenantId={}", id, tenantId);
        ProductResponse product = productService.getProductById(id, tenantId);
        return ApiResponse.success(product);
    }

    /**
     * 新增商品
     *
     * POST /api/admin/products
     */
    @PostMapping
    public ApiResponse<ProductResponse> createProduct(@Valid @RequestBody ProductCreateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("创建商品: name={}, tenantId={}", request.getName(), tenantId);
        ProductResponse product = productService.createProduct(request, tenantId);
        return ApiResponse.success(product);
    }

    /**
     * 编辑商品
     *
     * PUT /api/admin/products/{id}
     */
    @PutMapping("/{id}")
    public ApiResponse<ProductResponse> updateProduct(
            @PathVariable String id,
            @Valid @RequestBody ProductUpdateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("更新商品: id={}, tenantId={}", id, tenantId);
        ProductResponse product = productService.updateProduct(id, request, tenantId);
        return ApiResponse.success(product);
    }

    /**
     * 删除商品
     *
     * DELETE /api/admin/products/{id}
     */
    @DeleteMapping("/{id}")
    public ApiResponse<Void> deleteProduct(@PathVariable String id) {
        Long tenantId = TenantContext.getTenantId();
        log.info("删除商品: id={}, tenantId={}", id, tenantId);
        productService.deleteProduct(id, tenantId);
        return ApiResponse.success();
    }

    /**
     * 上下架商品
     *
     * PUT /api/admin/products/{id}/status
     * Body: { "status": "on_sale" / "off_sale" }
     */
    @PutMapping("/{id}/status")
    public ApiResponse<Void> updateProductStatus(
            @PathVariable String id,
            @RequestBody Map<String, String> body) {
        Long tenantId = TenantContext.getTenantId();
        String status = body.get("status");
        log.info("更新商品状态: id={}, status={}, tenantId={}", id, status, tenantId);
        productService.updateProductStatus(id, status, tenantId);
        return ApiResponse.success();
    }
}
