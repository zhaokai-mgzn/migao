package com.aikf.admin.controller;

import com.aikf.admin.config.TenantContext;
import com.aikf.admin.dto.*;
import com.aikf.admin.service.ProductService;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.io.IOException;
import java.util.List;
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

    /**
     * 批量上架
     *
     * POST /api/admin/products/batch/on-shelf
     * Body: { "productIds": ["id1", "id2", ...] }
     */
    @PostMapping("/batch/on-shelf")
    public ApiResponse<BatchOperationResult> batchOnShelf(@RequestBody Map<String, List<String>> body) {
        Long tenantId = TenantContext.getTenantId();
        List<String> productIds = body.get("productIds");
        log.info("批量上架商品: count={}, tenantId={}", productIds != null ? productIds.size() : 0, tenantId);
        BatchOperationResult result = productService.batchOnShelf(productIds, tenantId);
        return ApiResponse.success(result);
    }

    /**
     * 批量下架
     *
     * POST /api/admin/products/batch/off-shelf
     * Body: { "productIds": ["id1", "id2", ...] }
     */
    @PostMapping("/batch/off-shelf")
    public ApiResponse<BatchOperationResult> batchOffShelf(@RequestBody Map<String, List<String>> body) {
        Long tenantId = TenantContext.getTenantId();
        List<String> productIds = body.get("productIds");
        log.info("批量下架商品: count={}, tenantId={}", productIds != null ? productIds.size() : 0, tenantId);
        BatchOperationResult result = productService.batchOffShelf(productIds, tenantId);
        return ApiResponse.success(result);
    }

    /**
     * 批量删除
     *
     * POST /api/admin/products/batch/delete
     * Body: { "productIds": ["id1", "id2", ...] }
     */
    @PostMapping("/batch/delete")
    public ApiResponse<BatchOperationResult> batchDelete(@RequestBody Map<String, List<String>> body) {
        Long tenantId = TenantContext.getTenantId();
        List<String> productIds = body.get("productIds");
        log.info("批量删除商品: count={}, tenantId={}", productIds != null ? productIds.size() : 0, tenantId);
        BatchOperationResult result = productService.batchDelete(productIds, tenantId);
        return ApiResponse.success(result);
    }

    /**
     * 查询商品关联的加工项列表
     *
     * GET /api/admin/products/{id}/processing-items
     */
    @GetMapping("/{id}/processing-items")
    public ApiResponse<List<ProductProcessingItemResponse>> getProductProcessingItems(@PathVariable String id) {
        Long tenantId = TenantContext.getTenantId();
        log.info("查询商品关联加工项: productId={}, tenantId={}", id, tenantId);
        List<ProductProcessingItemResponse> items = productService.getProductProcessingItems(id, tenantId);
        return ApiResponse.success(items);
    }

    /**
     * 导出商品
     *
     * GET /api/admin/products/export?keyword=xxx&categoryId=xxx&status=on_sale
     */
    @GetMapping("/export")
    public void exportProducts(ProductQueryRequest query, HttpServletResponse response) throws IOException {
        Long tenantId = TenantContext.getTenantId();
        log.info("导出商品: keyword={}, categoryId={}, status={}, tenantId={}",
                query.getKeyword(), query.getCategoryId(), query.getStatus(), tenantId);
        productService.exportProducts(query, tenantId, response);
    }
}
