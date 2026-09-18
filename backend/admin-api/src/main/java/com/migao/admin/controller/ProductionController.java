package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.ProcessingOrderService;
import com.migao.admin.service.ProductionOperationCommandService;
import com.migao.admin.service.ProductionOperationQueryService;
import com.migao.admin.service.ProductionRoutingCommandService;
import com.migao.admin.service.ProductionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.DeleteMapping;
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
    private final ProductionRoutingCommandService productionRoutingCommandService;
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
     * body: {unit_price?, is_must_finish?, is_start_marker?, status?, unit?, group_name?, sort_order?,
     *        scope?}
     *
     * <p>{@code scope}（V67，issue #4384 A1）= 工序作用域：{@code position} 部位级 / {@code set} 套级
     * （**每樘窗一次**）。用户裁定「套级先按每樘窗一次实现，打卷是否每帘一次**留成可配**」
     * ⇒ 这一档由本端点开放给商家改；取值校验在服务层（闭词表，非法值 422 + 可读理由）。</p>
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

    /**
     * 新增工序（issue #4308 交付物 4：商家建自己的路线前必须能先建工序）
     * POST /api/admin/production/operations
     * body: {name, group_name?, unit?, unit_price, position?, is_must_finish?, is_start_marker?, sort_order?,
     *        scope?}
     *
     * <p>{@code scope} 缺省 = {@code position}（部位级，与 V67 列默认值同口径）——
     * **不默认 set**：默认套级会把商家新建的每道工序都静默去重（issue #4384 A1）。</p>
     *
     * <p>单价版本账**同事务写首行**（使「当前价 = 最新版本行」对新工序同样成立）。</p>
     */
    @PostMapping("/operations")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> createOperation(@RequestBody Map<String, Object> body) {
        return ApiResponse.success(productionOperationCommandService.create(body, TenantContext.getTenantId()));
    }

    // ══════════════════════════ 工艺路线写面（issue #4308 P1）══════════════════════════

    /**
     * 新建工艺路线（{@code operations} 可缺省 = 初版空序列）
     * POST /api/admin/production/routings
     * body: {curtain_type, craft, operations?, status?}
     *
     * <p>响应形态与 {@code GET /routings} 的单项**同构**（前端同一个 TS 类型渲染两者）。</p>
     */
    @PostMapping("/routings")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> createRouting(@RequestBody Map<String, Object> body) {
        return ApiResponse.success(
                productionRoutingCommandService.createRouting(body, TenantContext.getTenantId()));
    }

    /**
     * 改工艺路线序列（issue #4308 交付物 2；路线是计件工资与完工判定的唯一输入）
     * PUT /api/admin/production/routings/{id}
     * body: {operations: ["精裁-布", …], status?}
     *
     * <p><b>护栏（全部有红证）</b>：空序列拒 / 引用工序库中不存在的工序拒 / 重复工序拒 /
     * 至少一道必完工序 / seq 归一化为 1..N / 每次变更落版本账（{@code production_routing_versions}）。
     * 失败统一 **HTTP 422 + {@code error.details:[{field,message}]} 逐条理由**（一次报全）。</p>
     */
    @PutMapping("/routings/{id}")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> updateRouting(@PathVariable String id,
                                                          @RequestBody Map<String, Object> body) {
        return ApiResponse.success(productionRoutingCommandService.updateRouting(
                id, body, TenantContext.getTenantId()));
    }

    // ══════════════════════════ 信号映射写面（issue #4308 交付物 3）══════════════════════

    /**
     * 信号映射列表（派生路线键的数据源；迁移前是 Java 常量表）
     * GET /api/admin/production/route-signals
     */
    @GetMapping("/route-signals")
    public ApiResponse<Map<String, Object>> routeSignals() {
        return ApiResponse.success(productionOperationQueryService.routeSignalList(TenantContext.getTenantId()));
    }

    /**
     * 新增信号映射
     * POST /api/admin/production/route-signals
     * body: {signal, curtain_type?, craft?, priority?, status?}（两维至少给一个）
     */
    @PostMapping("/route-signals")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> createRouteSignal(@RequestBody Map<String, Object> body) {
        return ApiResponse.success(
                productionRoutingCommandService.createSignal(body, TenantContext.getTenantId()));
    }

    /**
     * 改信号映射（部分更新：只写 body 里出现的字段）
     * PUT /api/admin/production/route-signals/{id}
     */
    @PutMapping("/route-signals/{id}")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> updateRouteSignal(@PathVariable String id,
                                                              @RequestBody Map<String, Object> body) {
        return ApiResponse.success(productionRoutingCommandService.updateSignal(
                id, body, TenantContext.getTenantId()));
    }

    /**
     * 删信号映射（**软删**：deleted=1 —— 谁在何时删掉哪条映射是排查路线错配的唯一证据）
     * DELETE /api/admin/production/route-signals/{id}
     */
    @DeleteMapping("/route-signals/{id}")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> deleteRouteSignal(@PathVariable String id) {
        return ApiResponse.success(
                productionRoutingCommandService.deleteSignal(id, TenantContext.getTenantId()));
    }

    // ══════════════════════════ 缺口可查（issue #4308 交付物 5 / P4）══════════════════════════

    /**
     * 路线缺口：① 有活跃工序但未进任何活跃路线（真值源下 4 道，且**有意挂起等客户输入**，
     * 见 issue #4261 ⇒ 每条带 {@code pending_confirmation}）② 库里没有路线的信号组合。
     * GET /api/admin/production/routing-gaps
     */
    @GetMapping("/routing-gaps")
    public ApiResponse<Map<String, Object>> routingGaps() {
        return ApiResponse.success(
                productionOperationQueryService.routingGaps(TenantContext.getTenantId()));
    }
}
