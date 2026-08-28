package com.migao.admin.controller.agent;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.dto.ProductResponse;
import com.migao.admin.dto.ProductProcessingItemResponse;
import com.migao.admin.dto.ProductSkuResponse;
import com.migao.admin.dto.agent.AgentProductCreateRequest;
import com.migao.admin.dto.agent.AgentProductUpdateRequest;
import com.migao.admin.dto.agent.AgentProcessingItemActionRequest;
import com.migao.admin.service.ProductService;
import com.migao.admin.security.RequirePermission;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/**
 * Agent 专用商品管理控制器。
 * 与表单 API (/api/admin/products) 的关键差异：
 * - PATCH 部分更新：null 字段 = 不修改
 * - 分类/加工项 ID 支持名称/UUID/序号
 * - 加工项支持增量 add/remove
 * - 错误返回含 suggestion
 */
@Slf4j
@RequirePermission("product:list")
@RestController
@RequestMapping("/api/admin/agent/products")
@RequiredArgsConstructor
public class AgentProductController {

    private final ProductService productService;

    /**
     * Agent 专用创建商品。
     * POST /api/admin/agent/products
     */
    @PostMapping
    public ApiResponse<ProductResponse> createProduct(@RequestBody AgentProductCreateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("[Agent] 创建商品: name={}, tenantId={}", request.getName(), tenantId);
        try {
            ProductResponse result = productService.createProductForAgent(request, tenantId);
            return ApiResponse.success(result);
        } catch (Exception e) {
            log.warn("[Agent] 创建商品失败: {}", e.getMessage());
            throw e; // GlobalExceptionHandler 统一处理
        }
    }

    /**
     * Agent 专用部分更新商品。
     * PATCH /api/admin/agent/products/{id}
     * null 字段不修改，无 @NotBlank 限制。
     */
    @PatchMapping("/{id}")
    public ApiResponse<ProductResponse> updateProduct(@PathVariable String id,
                                                       @RequestBody AgentProductUpdateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("[Agent] 更新商品: id={}, tenantId={}", id, tenantId);
        String resolvedId = productService.resolveProductId(id, tenantId);
        if (resolvedId == null) {
            throw BusinessException.notFound("商品",
                    "未找到商品「" + id + "」，请先用 product_search 查出正确 ID 后重试");
        }
        try {
            ProductResponse result = productService.updateProductForAgent(resolvedId, request, tenantId);
            return ApiResponse.success(result);
        } catch (Exception e) {
            log.warn("[Agent] 更新商品失败: id={}, error={}", id, e.getMessage());
            throw e;
        }
    }

    /**
     * Agent 专用库存调整（生产回归修复：杜绝"假成功"）。
     * PATCH /api/admin/agent/products/{id}/stock
     * body: {"adjustment": +30, "reason": "盘点"}（adjustment 正=增加 负=减少）
     * 返回更新后的商品详情，data.stock 为 SKU 汇总值，供 agent 读回校验。
     */
    @PatchMapping("/{id}/stock")
    public ApiResponse<ProductResponse> adjustStock(
            @PathVariable String id,
            @RequestBody Map<String, Object> body) {
        Long tenantId = TenantContext.getTenantId();
        Object adjObj = body.get("adjustment");
        if (adjObj == null) {
            throw BusinessException.validationError("缺少 adjustment 字段（正=增加，负=减少）");
        }
        Integer adjustment;
        try {
            adjustment = Integer.valueOf(adjObj.toString());
        } catch (NumberFormatException e) {
            throw BusinessException.validationError("adjustment 必须为整数");
        }
        String reason = (String) body.getOrDefault("reason", "");
        String resolvedId = productService.resolveProductId(id, tenantId);
        if (resolvedId == null) {
            throw BusinessException.notFound("商品",
                    "未找到商品「" + id + "」，请先用 product_search 查出正确 ID 后重试");
        }
        log.info("[Agent] 库存调整: product={}, adjustment={}, reason={}, tenantId={}",
                id, adjustment, reason, tenantId);
        try {
            ProductResponse result = productService.adjustStockForAgent(resolvedId, adjustment, reason, tenantId);
            return ApiResponse.success(result);
        } catch (Exception e) {
            log.warn("[Agent] 库存调整失败: product={}, adjustment={}, error={}", id, adjustment, e.getMessage());
            throw e;
        }
    }

    /**
     * Agent 专用 SKU 价格更新。按颜色/售卖方式/门幅精确匹配。
     * PATCH /api/admin/agent/products/{productId}/skus/price
     */
    @PatchMapping("/{productId}/skus/price")
    public ApiResponse<ProductResponse> updateSkuPrice(
            @PathVariable String productId,
            @RequestBody Map<String, Object> body) {
        Long tenantId = TenantContext.getTenantId();
        String color = (String) body.getOrDefault("color", "");
        String sellingMethod = (String) body.getOrDefault("selling_method", "");
        String doorWidth = (String) body.getOrDefault("door_width", "");
        Object priceObj = body.get("price");
        if (priceObj == null) {
            throw BusinessException.validationError("缺少 price 字段");
        }
        java.math.BigDecimal price = new java.math.BigDecimal(priceObj.toString());
        log.info("[Agent] SKU调价: product={}, color={}, method={}, width={}, price={}",
                productId, color, sellingMethod, doorWidth, price);
        try {
            String resolvedId = productService.resolveProductId(productId, tenantId);
            if (resolvedId == null) {
                throw BusinessException.notFound("商品（" + productId + "）",
                        "请先用 product_search 查出正确 ID");
            }
            productService.updateSkuPrice(resolvedId, color, sellingMethod, doorWidth, price, tenantId);
            ProductResponse result = productService.getProductById(resolvedId, tenantId);
            return ApiResponse.success(result);
        } catch (Exception e) {
            log.warn("[Agent] SKU调价失败: product={}, error={}", productId, e.getMessage());
            throw e;
        }
    }

    /**
     * Agent/前端行内编辑专用：按 SKU id 精确改价。
     * PATCH /api/admin/agent/products/{productId}/skus/{skuId}
     * body: {"price": 99.00}（price ≥ 0），返回更新后的 SKU。
     * 与 /skus/price（按颜色/售卖方式/门幅匹配）互为补充：
     * 本端点校验 skuId 属于该商品，供前端拿到 sku.id 后直接调用。
     */
    @PatchMapping("/{productId}/skus/{skuId}")
    public ApiResponse<ProductSkuResponse> updateSkuPriceById(
            @PathVariable String productId,
            @PathVariable Long skuId,
            @RequestBody Map<String, Object> body) {
        Long tenantId = TenantContext.getTenantId();
        Object priceObj = body.get("price");
        if (priceObj == null) {
            throw BusinessException.validationError("缺少 price 字段");
        }
        BigDecimal price;
        try {
            price = new BigDecimal(priceObj.toString());
        } catch (NumberFormatException e) {
            throw BusinessException.validationError("price 必须为数字");
        }
        String resolvedId = productService.resolveProductId(productId, tenantId);
        if (resolvedId == null) {
            throw BusinessException.notFound("商品（" + productId + "）",
                    "请先用 product_search 查出正确 ID");
        }
        log.info("[Agent] 单SKU调价: product={}, skuId={}, price={}, tenantId={}",
                productId, skuId, price, tenantId);
        try {
            ProductSkuResponse result = productService.updateSkuPriceById(resolvedId, skuId, price, tenantId);
            return ApiResponse.success(result);
        } catch (Exception e) {
            log.warn("[Agent] 单SKU调价失败: product={}, skuId={}, error={}", productId, skuId, e.getMessage());
            throw e;
        }
    }

    /**
     * Agent 专用加工项增删。
     * PATCH /api/admin/agent/products/{id}/processing-items
     * add: 仅插入不存在的；remove: 仅删除存在的（幂等）。
     */
    @PatchMapping("/{id}/processing-items")
    public ApiResponse<List<ProductProcessingItemResponse>> mergeProcessingItems(
            @PathVariable String id,
            @RequestBody AgentProcessingItemActionRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("[Agent] 加工项 {}: productId={}, count={}, tenantId={}",
                request.getAction(), id,
                request.getItemIds() != null ? request.getItemIds().size() : 0, tenantId);
        String resolvedId = productService.resolveProductId(id, tenantId);
        if (resolvedId == null) {
            throw BusinessException.notFound("商品",
                    "未找到商品「" + id + "」，请先用 product_search 查出正确 ID 后重试");
        }
        try {
            List<ProductProcessingItemResponse> result =
                    productService.updateProductProcessingItems(resolvedId, request, tenantId);
            return ApiResponse.success(result);
        } catch (Exception e) {
            log.warn("[Agent] 加工项操作失败: productId={}, error={}", id, e.getMessage());
            throw e;
        }
    }
}
