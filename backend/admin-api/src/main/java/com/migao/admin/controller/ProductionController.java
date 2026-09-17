package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.ProductionOperationQueryService;
import com.migao.admin.service.ProductionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 生产报工 Controller（issue #3995，M4-G-2）
 *
 * 加工单工序实例化（含二维码 token）/ 工序查询 / 扫码报工 / 计件汇总
 * + 工序库与工艺路线只读查询（issue #4116 P0-2）。
 * 真值源：docs/curtain-production-rules.md §2 工序库 / §3 工艺路线 / §4 计件 / §5 扫码报工闭环。
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/production")
@RequiredArgsConstructor
@RequirePermission("order:list")
public class ProductionController {

    private final ProductionService productionService;
    private final ProductionOperationQueryService productionOperationQueryService;

    /**
     * 实例化工序 + 生成加工单二维码 token
     * POST /api/admin/production/orders/{orderId}/instantiate
     * body: {"positions":[{"position_name":"布帘","operations":[{seq,operation,group,unit,qty,
     *        unit_price,factor,is_must_finish,is_start_marker}]}]}
     */
    @PostMapping("/orders/{orderId}/instantiate")
    public ApiResponse<Map<String, Object>> instantiate(@PathVariable String orderId,
                                                        @RequestBody Map<String, Object> body) {
        return ApiResponse.success(productionService.instantiate(orderId, body, TenantContext.getTenantId()));
    }

    /**
     * 加工单工序树 + 进度
     * GET /api/admin/production/orders/{orderId}/operations
     */
    @GetMapping("/orders/{orderId}/operations")
    public ApiResponse<Map<String, Object>> operations(@PathVariable String orderId) {
        return ApiResponse.success(productionService.getOperations(orderId, TenantContext.getTenantId()));
    }

    /**
     * 扫码报工（推进工序进度 + 记录个人计件）
     * POST /api/admin/production/orders/{orderId}/operations/{operationId}/report
     * body: {worker_id, worker_name, qty, qualified_qty, work_type(normal/rework/scrap)}
     *
     * <p>幂等键（issue #4116 §5-1）：请求头 {@code X-Client-Request-Id} 非空时按
     * {@code (tenantId, 键)} 去重 —— 同一键只真正报工一次，重复到达回放首次结果
     * （响应多一个 {@code replayed:true}）。无键 ⇒ 原路径逐字不变（向后兼容未升级的调用方）。
     * 与下单/建工单复用**同一套** {@link ClientRequestIdService}（同一张表、同一种占位语义）。</p>
     */
    @PostMapping("/orders/{orderId}/operations/{operationId}/report")
    public ApiResponse<Map<String, Object>> report(
            @PathVariable String orderId,
            @PathVariable String operationId,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = ClientRequestIdService.HEADER, required = false) String clientRequestId) {
        return ApiResponse.success(productionService.report(
                orderId, operationId, body, TenantContext.getTenantId(), clientRequestId));
    }

    /**
     * 加工单计件汇总（内部计件工资，per 工序；与对外加工费两套账分离）
     * GET /api/admin/production/orders/{orderId}/piecework
     */
    @GetMapping("/orders/{orderId}/piecework")
    public ApiResponse<Map<String, Object>> piecework(@PathVariable String orderId) {
        return ApiResponse.success(productionService.piecework(orderId, TenantContext.getTenantId()));
    }

    // ══════════════════════════ 工序库 / 工艺路线（只读消费者，issue #4116 P0-2）══════════════════════════

    /**
     * 工序库（按分组/排序的工序目录，含计件单价与必完/开始标记）
     * GET /api/admin/production/operations-catalog
     */
    @GetMapping("/operations-catalog")
    public ApiResponse<Map<String, Object>> operationsCatalog() {
        return ApiResponse.success(
                productionOperationQueryService.catalog(TenantContext.getTenantId()));
    }

    /**
     * 工艺路线模板（部位 × 工艺 → 工序序列；布帘·韩褶 = 11 道）
     * GET /api/admin/production/routings
     */
    @GetMapping("/routings")
    public ApiResponse<Map<String, Object>> routings() {
        return ApiResponse.success(
                productionOperationQueryService.routings(TenantContext.getTenantId()));
    }
}
