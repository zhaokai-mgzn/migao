package com.migao.admin.controller.agent;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.ProductResponse;
import com.migao.admin.dto.ProductProcessingItemResponse;
import com.migao.admin.dto.agent.AgentProductCreateRequest;
import com.migao.admin.dto.agent.AgentProductUpdateRequest;
import com.migao.admin.dto.agent.AgentProcessingItemActionRequest;
import com.migao.admin.service.ProductService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * Agent 专用商品管理控制器。
 * 与表单 API (/api/admin/products) 的关键差异：
 * - PATCH 部分更新：null 字段 = 不修改
 * - 分类/加工项 ID 支持名称/UUID/序号
 * - 加工项支持增量 add/remove
 * - 错误返回含 suggestion
 */
@Slf4j
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
        try {
            ProductResponse result = productService.updateProductForAgent(id, request, tenantId);
            return ApiResponse.success(result);
        } catch (Exception e) {
            log.warn("[Agent] 更新商品失败: id={}, error={}", id, e.getMessage());
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
        try {
            List<ProductProcessingItemResponse> result =
                    productService.updateProductProcessingItems(id, request, tenantId);
            return ApiResponse.success(result);
        } catch (Exception e) {
            log.warn("[Agent] 加工项操作失败: productId={}, error={}", id, e.getMessage());
            throw e;
        }
    }
}
