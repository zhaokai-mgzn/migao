package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.ProcessingOrderGenerateRequest;
import com.migao.admin.dto.ProcessingOrderResponse;
import com.migao.admin.dto.ProcessingOrderUpdateRequest;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ProcessingOrderService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 加工单 Controller（issue #3340）
 * 供 admin-web 与米宝 Agent 共同调用。
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/processing-orders")
@RequiredArgsConstructor
public class ProcessingOrderController {

    private final ProcessingOrderService processingOrderService;

    /**
     * 批量生成加工单（写操作，权限 processing:update）
     * POST /api/admin/processing-orders/generate
     *
     * <p>V116 / issue #5145 阶段 1：请求体可带 {@code batches}（逐面料行指定批次）；
     * 缺省 = 不指派 ⇒ 行为与今天逐字相同（本阶段的定义特征是「只记录、不改指派行为」）。</p>
     *
     * <p>issue #5167：请求体可带 {@code assignmentRule}（{@code fifo} 缺省 / {@code best_fit}）——
     * 只对**没有**指定 {@code batchNo} 的行按该规则补位；不传它时行为与上面逐字相同。</p>
     */
    @PostMapping("/generate")
    @RequirePermission("processing:update")
    public ApiResponse<List<ProcessingOrderService.GenerateResult>> generate(
            @RequestBody ProcessingOrderGenerateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(processingOrderService.generate(request.getOrderIds(),
                request.getBatches(), tenantId, null, request.getAssignmentRule()));
    }

    /**
     * 加工单列表（权限 production:view —— issue #5291 新增的生产域**读**码）
     * GET /api/admin/processing-orders?keyword=&status=
     *
     * 沿革：issue #5246 曾把本读面从 processing:view 改到 processing:manage（当时「生产看板」节点的码
     * 是 processing:manage，而 processing:view 没有任何菜单节点）；issue #5291 为生产域读出**读**码
     * production:view 后，节点与本读端点同批改挂读码 —— 只读持有者不再被迫持管理码。
     */
    // issue #5291：读面（列表 / 详情）改挂生产域读码 `production:view`；
    // 写面（POST /generate、PATCH /{id}）仍是 `processing:update`。
    @GetMapping
    @RequirePermission("production:view")
    public ApiResponse<List<ProcessingOrderResponse>> list(
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String status) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(processingOrderService.list(keyword, status, tenantId));
    }

    /**
     * 加工单详情（权限 production:view，issue #5291）
     * GET /api/admin/processing-orders/{id}   id 可为 UUID/加工单号/订单号
     *
     * 与列表同码（production:view）—— 详情与列表是同一入口的两个读面，
     * 同页不同码会造出「列表打不开、详情打得开」的错位。
     */
    @GetMapping("/{id}")
    @RequirePermission("production:view")
    public ApiResponse<ProcessingOrderResponse> detail(@PathVariable String id) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(processingOrderService.getDetail(id, tenantId));
    }

    /**
     * 加工单状态更新（权限 processing:update）
     * PATCH /api/admin/processing-orders/{id}  action: issue/start/complete/cancel
     */
    @PatchMapping("/{id}")
    @RequirePermission("processing:update")
    public ApiResponse<ProcessingOrderResponse> update(@PathVariable String id,
                                                       @RequestBody ProcessingOrderUpdateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(processingOrderService.updateStatus(id, request, tenantId, null));
    }
}
