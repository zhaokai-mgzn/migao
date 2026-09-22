package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.*;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.ProductService;
import com.migao.admin.security.RequirePermission;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

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
    @RequirePermission("product:list")
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
    @RequirePermission("product:list")
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
    @RequirePermission("product:create")
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
    @RequirePermission("product:create")
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
    @RequirePermission("product:create")
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
    @RequirePermission("product:create")
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
     * 设置/取消商品推荐标记（C 端「新品推荐」位控制）
     *
     * PUT /api/admin/products/{id}/recommend
     * Body: { "recommended": true / false }
     */
    @RequirePermission("product:create")
    @PutMapping("/{id}/recommend")
    public ApiResponse<Void> updateProductRecommended(
            @PathVariable String id,
            @RequestBody Map<String, Boolean> body) {
        Long tenantId = TenantContext.getTenantId();
        Boolean recommended = body.get("recommended");
        if (recommended == null) {
            throw new BusinessException("VALIDATION_ERROR", "recommended 不能为空");
        }
        log.info("设置商品推荐标记: id={}, recommended={}, tenantId={}", id, recommended, tenantId);
        productService.updateProductRecommended(id, recommended, tenantId);
        return ApiResponse.success();
    }

    /**
     * 按颜色+规格维度查询低库存 SKU（库存告警用）
     *
     * GET /api/admin/products/low-stock-by-color?threshold=100&limit=50
     */
    @RequirePermission("product:list")
    @GetMapping("/low-stock-by-color")
    public ApiResponse<List<LowStockByColorResponse>> getLowStockByColor(
            @RequestParam(defaultValue = "100") int threshold,
            @RequestParam(defaultValue = "50") int limit) {
        log.info("低库存查询(颜色维度): threshold={}, limit={}", threshold, limit);
        List<LowStockByColorResponse> result = productService.getLowStockByColor(threshold, limit);
        return ApiResponse.success(result);
    }

    /**
     * 批量上架
     *
     * POST /api/admin/products/batch/on-shelf
     * Body: { "productIds": ["id1", "id2", ...] }
     */
    @RequirePermission("product:create")
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
    @RequirePermission("product:create")
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
    @RequirePermission("product:create")
    @PostMapping("/batch/delete")
    public ApiResponse<BatchOperationResult> batchDelete(@RequestBody Map<String, List<String>> body) {
        Long tenantId = TenantContext.getTenantId();
        List<String> productIds = body.get("productIds");
        log.info("批量删除商品: count={}, tenantId={}", productIds != null ? productIds.size() : 0, tenantId);
        BatchOperationResult result = productService.batchDelete(productIds, tenantId);
        return ApiResponse.success(result);
    }

    /**
     * 导出商品
     *
     * GET /api/admin/products/export?keyword=xxx&categoryId=xxx&status=on_sale
     */
    @RequirePermission("product:list")
    @GetMapping("/export")
    public void exportProducts(ProductQueryRequest query, HttpServletResponse response) throws IOException {
        Long tenantId = TenantContext.getTenantId();
        log.info("导出商品: keyword={}, categoryId={}, status={}, tenantId={}",
                query.getKeyword(), query.getCategoryId(), query.getStatus(), tenantId);
        productService.exportProducts(query, tenantId, response);
    }

    /**
     * 批量导入商品 + SKU（issue #5154）—— 「导出」的对偶入口。
     *
     * <p>响应**恒为 200 + 逐行报告**（行级原子，不是整包回滚）：合法的行照常落库，
     * 非法的行在 {@code data.errors[]} 里带「行号 + 货号 + 可行动原因」。
     * 只有「整包级别的输入问题」（文件为空 / 表头缺必填列）才走 400。</p>
     *
     * <p>租户取自 {@link TenantContext}，**不接受**客户端传入 —— 导入建的是本租户的商品。</p>
     *
     * POST /api/admin/products/import （multipart/form-data，字段名 file）
     */
    @RequirePermission("product:create")
    @PostMapping("/import")
    public ApiResponse<ProductImportResult> importProducts(@RequestParam("file") MultipartFile file) {
        Long tenantId = TenantContext.getTenantId();
        log.info("导入商品: filename={}, size={}, tenantId={}",
                file != null ? file.getOriginalFilename() : null,
                file != null ? file.getSize() : -1, tenantId);
        ProductImportResult result = productService.importProducts(file, tenantId);
        log.info("导入商品完成: total={}, success={}, fail={}, blank={}, created={}, updated={}",
                result.getTotal(), result.getSuccessCount(), result.getFailCount(),
                result.getBlankRows(), result.getCreatedProducts(), result.getUpdatedProducts());
        return ApiResponse.success(result);
    }

    /**
     * 下载商品导入模板（「导入」的对偶入口：模板表头与导入解析共用同一常量）。
     *
     * GET /api/admin/products/import-template
     */
    @RequirePermission("product:list")
    @GetMapping("/import-template")
    public void downloadImportTemplate(HttpServletResponse response) throws IOException {
        log.info("下载商品导入模板: tenantId={}", TenantContext.getTenantId());
        productService.generateImportTemplate(response);
    }
}
