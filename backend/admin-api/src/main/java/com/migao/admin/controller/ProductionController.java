package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.ProcessingOrderService;
import com.migao.admin.service.ProductionOperationCommandService;
import com.migao.admin.service.ProductionOperationQueryService;
import com.migao.admin.service.ProductionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 生产报工 Controller（issue #3995，M4-G-2）
 *
 * 加工单工序实例化（含二维码 token）/ 工序查询 / 扫码报工 / 计件汇总
 * + 工序库与工艺路线只读查询（issue #4116 P0-2）
 * + 存量单补工序 / 二维码撤销 / 打印计数 / 工序库写面 / 计件工资报表（issue #4202/#4204/#4205）。
 * 真值源：docs/curtain-production-rules.md §1 打印物 / §2 工序库 / §3 工艺路线 / §4 计件 / §5 扫码报工闭环。
 *
 * <p><b>权限口径（本批新增端点逐条声明，见 issue #4104 的控制器级错配台账）</b>：
 * 类级 {@code order:list} 是读口径；写/报表端点用方法级 {@code processing:manage} 覆盖
 * （方法级优先，见 {@code PermissionInterceptor.resolveRequirePermission}）。
 * **唯一例外是打印计数**：它沿用类级 {@code order:list} —— 打印按钮今天对客服/销售/财务可见
 * （{@code order:list} 授了 4 个岗位，{@code processing:manage} 只授 operator），
 * 收窄会让「能打开生产明细却打不了卡」变成功能回退；计数只是打印动作的元数据，不涉安全边界。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/production")
@RequiredArgsConstructor
@RequirePermission("order:list")
public class ProductionController {

    private final ProductionService productionService;
    private final ProductionOperationQueryService productionOperationQueryService;
    private final ProductionOperationCommandService productionOperationCommandService;
    private final ProcessingOrderService processingOrderService;

    /**
     * 实例化工序 + 生成加工单二维码 token
     * POST /api/admin/production/orders/{orderId}/instantiate
     * body: {"positions":[{"position_name":"布帘","operations":[{seq,operation,group,unit,qty,
     *        unit_price,factor,is_must_finish,is_start_marker}]}]}
     *
     * <p><b>positions 可选</b>（issue #4202）：缺省/空数组 ⇒ 服务端**按订单派生**
     * （复用生成加工单的工序库路线解析，见 {@link ProcessingOrderService#derivePositionPayload}）。
     * 存量单（生成于「生成即实例化」之前，工序实例与 qr_token 双空）由此获得恢复路径；
     * 对已有实例的单仍是**幂等空操作**（不重插行、不清零 done_qty、token 复用）。</p>
     */
    @PostMapping("/orders/{orderId}/instantiate")
    public ApiResponse<Map<String, Object>> instantiate(@PathVariable String orderId,
                                                        @RequestBody(required = false) Map<String, Object> body) {
        return ApiResponse.success(productionService.instantiate(
                orderId, withDerivedPositions(orderId, body), TenantContext.getTenantId()));
    }

    /**
     * positions 缺省/空 ⇒ 按订单派生（issue #4202）。显式传入（非空数组）时原样透传，
     * 服务层仍保留「positions 不能为空」的兜底校验（直接调服务层的调用方不会落空实例）。
     */
    private Map<String, Object> withDerivedPositions(String orderId, Map<String, Object> body) {
        Object raw = body == null ? null : body.get("positions");
        if (raw instanceof List<?> positions && !positions.isEmpty()) {
            return body;
        }
        return Map.of("positions",
                processingOrderService.derivePositionPayload(orderId, TenantContext.getTenantId()));
    }

    /**
     * 撤销加工单二维码 token（issue #4202，真值源 §1「token 化、可撤销」）
     * POST /api/admin/production/orders/{orderId}/qr-token/revoke
     *
     * <p>撤销后 qr_token 置空 ⇒ 已打印的码立即失效；再次 instantiate 时重新生成。</p>
     */
    @PostMapping("/orders/{orderId}/qr-token/revoke")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> revokeQrToken(@PathVariable String orderId) {
        return ApiResponse.success(
                productionService.revokeQrToken(orderId, TenantContext.getTenantId()));
    }

    /**
     * 记录一次任务卡打印（issue #4202 边角修复：print_count 此前零写方）
     * POST /api/admin/production/orders/{orderId}/print
     *
     * <p>权限**故意**沿用类级 {@code order:list}（见类注释）。</p>
     */
    @PostMapping("/orders/{orderId}/print")
    public ApiResponse<Map<String, Object>> printOrder(@PathVariable String orderId) {
        return ApiResponse.success(
                processingOrderService.recordPrint(orderId, TenantContext.getTenantId()));
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

    /**
     * 计件工资报表（按人/按期，issue #4205；真值源 §4「工资报表 = 报工事件聚合」）
     * GET /api/admin/production/piecework/summary?period=YYYY-MM[&worker_name=]
     *
     * <p>返回 {@code {period,total,per_worker:[{worker_name,amount,qty}],
     * per_operation:[{operation,amount,qty}]}}；聚合算法与 per-order 计件**同一份**
     * （{@code ProductionService.aggregate}）。{@code period} 在服务层校验（缺失/非法 ⇒ 422
     * 可行动错误，而不是 400 参数缺失）。</p>
     */
    @GetMapping("/piecework/summary")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> pieceworkSummary(
            @RequestParam(required = false) String period,
            @RequestParam(name = "worker_name", required = false) String workerName) {
        return ApiResponse.success(productionService.pieceworkSummary(
                period, workerName, TenantContext.getTenantId()));
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

    // ══════════════════════════ 工序库写面（issue #4204 P1）══════════════════════════

    /**
     * 更新工序（商家改单价/停用/排序的唯一入口）
     * PUT /api/admin/production/operations/{id}
     * body: {unit_price?, is_must_finish?, is_start_marker?, status?, unit?, group_name?, sort_order?}
     *
     * <p>改价同一事务写两处：{@code production_operations.unit_price}（新单实例化取值源）
     * + {@code production_operation_price_versions} 追加一行（当前价 = 最新版本行）。
     * 实例快照 {@code processing_position_operations.unit_price} **不动**：调价只影响新报工，
     * 历史报工按当时价（真值源 §4）。</p>
     */
    @PutMapping("/operations/{id}")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> updateOperation(@PathVariable String id,
                                                            @RequestBody Map<String, Object> body) {
        return ApiResponse.success(productionOperationCommandService.update(
                id, body, TenantContext.getTenantId()));
    }
}
