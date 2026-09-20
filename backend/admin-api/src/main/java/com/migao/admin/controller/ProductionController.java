package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.OrderService;
import com.migao.admin.service.ProcessingOrderService;
import com.migao.admin.service.ProductionOperationCommandService;
import com.migao.admin.service.ProductionOperationPositionCommandService;
import com.migao.admin.service.ProductionOperationQueryService;
import com.migao.admin.service.ProductionInstanceRepricingService;
import com.migao.admin.service.ProcessingFeeCombinationCommandService;
import com.migao.admin.service.ProcessingFeeQueryService;
import com.migao.admin.service.ProductionRoutingCommandService;
import com.migao.admin.service.ProductionRoutingReadService;
import com.migao.admin.service.ProductionScanService;
import com.migao.admin.service.ProductionService;
import com.migao.admin.service.ProductionStuckPointService;
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
    private final OrderService orderService;

    /**
     * 加工费组合定价（V68，issue #4386）：读面（列表 / 缺口）+ 写面（新建 / 改价 / 停用）。
     *
     * <p>用字段注入而不是构造参数：本类构造签名被 {@code ProductionControllerTest} 的
     * standaloneSetup 显式装配（6 个参数），加参数会把该测试的每一处装配都改一遍 ——
     * 而本单的改动面**不应**扩到既有测试（同 #4308 的「不复制第二份装配」口径）。
     * Spring 生产装配下这两条一定非 null（同包 {@code @Service}）。</p>
     */
    @org.springframework.beans.factory.annotation.Autowired
    private ProcessingFeeQueryService processingFeeQueryService;
    @org.springframework.beans.factory.annotation.Autowired
    private ProcessingFeeCombinationCommandService processingFeeCombinationCommandService;

    /**
     * 新模型只读面（issue #4500：部位价目矩阵 + 规则区）。
     *
     * <p>同上面两个字段的理由用字段注入：本类构造签名被 {@code ProductionControllerTest} /
     * {@code ProductionRoutingReadControllerTest} 显式装配，加构造参数会把既有测试的装配全改一遍
     * —— 而本单的改动面**不应**扩到既有测试（同 #4308 的「不复制第二份装配」口径）。
     * Spring 生产装配下该依赖一定非 null（同包 {@code @Service}）。</p>
     */
    @org.springframework.beans.factory.annotation.Autowired
    private ProductionRoutingReadService productionRoutingReadService;

    /**
     * 部位价目矩阵**写面**（issue #4587 ② = 母单 #4586 包A）：格内改价 / 改做不做。
     *
     * <p>与上面两条同款用字段注入：本类构造签名被 {@code ProductionControllerTest} 的 standaloneSetup
     * 显式装配（6 个参数），加参数会把既有测试的每一处装配都改一遍 —— 而本单的改动面不应扩到那里。</p>
     */
    @org.springframework.beans.factory.annotation.Autowired
    private ProductionOperationPositionCommandService productionOperationPositionCommandService;

    /**
     * 扫码解析 + 工序推断（切片 ①，issue #4698）。
     *
     * <p>与上面几条同款用字段注入：本类构造签名被 {@code ProductionControllerTest} 的 standaloneSetup
     * 显式装配（6 个参数），加参数会把既有测试的装配全改一遍 —— 而本单的改动面不应扩到那里。
     * Spring 生产装配下该依赖一定非 null（同包 {@code @Service}）。</p>
     */
    @org.springframework.beans.factory.annotation.Autowired
    private ProductionScanService productionScanService;

    /**
     * 「卡在哪」的判据与报表（切片 ③，issue #4776；设计 §6）。
     *
     * <p>与上面几条同款用字段注入：本类构造签名被 {@code ProductionControllerTest} 的 standaloneSetup
     * 显式装配（6 个参数），加参数会把既有测试的装配全改一遍 —— 而本单的改动面不应扩到那里。
     * Spring 生产装配下该依赖一定非 null（同包 {@code @Service}）。</p>
     */
    @org.springframework.beans.factory.annotation.Autowired
    private ProductionStuckPointService productionStuckPointService;

    /**
     * 未定价实例的**显式补价路径**（issue #4709 C）：只补 {@code NULL}、已有价一律不动、进度不清零。
     *
     * <p>同上面几个字段的理由用字段注入：本类构造签名被 {@code ProductionControllerTest} 的
     * standaloneSetup 显式装配（6 个参数），加构造参数会把既有测试的装配全改一遍 ——
     * 而本单的改动面**不应**扩到那里（同 #4308 的「不复制第二份装配」口径）。</p>
     */
    @org.springframework.beans.factory.annotation.Autowired
    private ProductionInstanceRepricingService productionInstanceRepricingService;

    /**
     * 实例化工序 + 生成加工单二维码 token
     * POST /api/admin/production/orders/{orderId}/instantiate
     * body: {"positions":[{"position_name":"布帘","operations":[{seq,operation,group,unit,qty,
     *        unit_price,factor,is_must_finish,is_start_marker}]}]}
     *
     * <p>⚠️ {@code unit_price} 为 {@code null}（或缺键）= <b>未定价</b>（V90，issue #4696）⇒
     * 实例快照落 {@code NULL}（**不折 0 元**）；{@code 0} 是<b>显式定价为 0 元</b>，仍是有价。
     * 服务端派生路径（{@code derivePositionPayload}）同样**不回落**工序库行价。</p>
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
     * **发货**（issue #4347 §二.2，用户裁定「发货下放到工人扫码端」）。
     * POST /api/admin/production/orders/{orderId}/ship
     * body: {@code {trackingNo, logisticsCompany?}}
     *
     * <p><b>为什么是一个原子端点而不是复用两个管理端点</b>：
     * {@code PUT /orders/{id}/logistics} 只记物流**不流转状态**，{@code PUT /orders/{id}/status}
     * 只流转**不记单号** ⇒ 工人发一次货要调两次，中间失败就是「有单号但没发货」或
     * 「发货了没单号」的静默不一致。发货是**一个动作**，就该是一个入口。</p>
     *
     * <p><b>权限 = 类级 {@code order:list}</b>（与扫码/报工同一权限）：工人身份不需要
     * {@code processing:update} 或新增「仓管」角色即可发货 —— 能扫码报工的人本来就有
     * {@code order:list}（实测：{@code ProductionController} 类级 + 既有
     * {@code PUT /orders/{id}/status} / {@code /logistics} 也都是 {@code order:list}）。</p>
     *
     * <p><b>守卫不复制</b>：含加工项订单必须有 completed 加工单这条判定在
     * {@link OrderService#shipWithLogistics} 内部（与 {@code updateOrderStatus} 路径**同一份**），
     * 本端点只做转发。</p>
     */
    @PostMapping("/orders/{orderId}/ship")
    public ApiResponse<Map<String, Object>> ship(@PathVariable String orderId,
                                                 @RequestBody Map<String, String> body) {
        orderService.shipWithLogistics(orderId,
                body == null ? null : body.get("trackingNo"),
                body == null ? null : body.get("logisticsCompany"));
        return ApiResponse.success(Map.of("order_id", orderId, "status", "shipped"));
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
     * 扫码解析 + 工序推断（**只读**，切片 ① / issue #4698；设计 §2.3 / §2.6 / §3）
     * GET /api/admin/production/scan?token=…&amp;operation_id=…
     *
     * <p>把「找部位 + 找工序」两步从工人手里拿走（今天 ≥4 步 ⇒ 一次扫码 = 1 步）：</p>
     * <ul>
     *   <li><b>新码</b>（{@code processing_set_part_tokens}，带套带部位）⇒ 返回
     *       {@code granularity="set_position"} + {@code (set_no, position)} + **系统推断的下一道待做工序**
     *       （部位级优先 → 套级回落 {@code rerouted=true}），{@code needs_selection} 为空
     *       —— 部位由码给出，**工人不选**；</li>
     *   <li><b>旧码</b>（既有四形态 qr_token / processing_order_no / order_no / order_id）⇒ 降级形态
     *       {@code granularity="order"} + {@code needs_selection:["set","position"]} + 可选清单
     *       —— 🔴 <b>绝不默认取第 1 套</b>（{@code set_no}/{@code position}/{@code operation} 一律 null）；</li>
     *   <li>{@code operation_id} 可选 = 工人「一键改」（必须属于本次扫码的部位/套，否则 422）。</li>
     * </ul>
     *
     * <p><b>本端点不写库</b>（报工主闭环 = 切片 ②）：它只返回一屏所需数据。
     * 硬约束「工序必须确定」在本层体现为<b>拒绝产出非唯一确定的工序</b>
     * （{@code seq} 重复 ⇒ 422 {@code OPERATION_AMBIGUOUS}，不静默取第一道）。</p>
     */
    @GetMapping("/scan")
    public ApiResponse<Map<String, Object>> scan(
            @RequestParam(name = "token") String token,
            @RequestParam(name = "operation_id", required = false) String operationId) {
        return ApiResponse.success(productionScanService.resolve(
                token, operationId, TenantContext.getTenantId()));
    }

    /**
     * 「卡在哪」卡点报表（**只读**，切片 ③ / issue #4776；设计 §6.1 行① / §6.3）
     * GET /api/admin/production/stuck-points?processing_order_id=…
     *
     * <p><b>A 模式只查「没开工」那一种</b>（裁定②-3，设计 §6 开头逐字：「『卡在哪』<b>在 A 模式下的
     * 口径 = 只有『没开工』那一种</b>」）—— 判据 = 没开工 + 立即前道已完成 + 等待超阈值；
     * 「上道几点完成、等了多久」都可答（D8）。B/C 模式的卡点（「开了没完」）**不在本片**
     * （§6.1 行②仅 C；§8 A3「C 只作预留」）。</p>
     *
     * <p>🔴 「卡了多久」取**前道 {@code done_at}**，<b>绝不用 {@code updated_at}</b>（§6.1 逐字点名
     * 它会被任何更新污染 ⇒ 会静默给出错数）。阈值 = S3 全局默认常量（可配
     * {@code migao.production.stuck-point.wait-threshold-hours}），响应带 {@code threshold_source}
     * ⇒「阈值从哪来」可解释（§6.4；S1 历史中位数属 §8 A2 待裁定，本片不发明）。</p>
     *
     * <p>权限沿用类级 {@code order:list}（读口径；与 {@code /operations}、{@code /piecework} 同款）。</p>
     *
     * @param processingOrderId 可选：只看某一个加工单（缺省 = 本租户全部活跃加工单）
     */
    @GetMapping("/stuck-points")
    public ApiResponse<Map<String, Object>> stuckPoints(
            @RequestParam(name = "processing_order_id", required = false) String processingOrderId) {
        return ApiResponse.success(productionStuckPointService.report(
                processingOrderId, TenantContext.getTenantId()));
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
        // 商家侧报工（issue #4733）：**显式**沿用既有 body 口径 —— 来源被标注为 client_body 并落
        // worker_report_audits。取舍：本单不改变商家侧既有行为（逐条断言见 ProductionServiceTest），
        // 但「谁都能填」这件事从此在数据上**可见**，不再静默。工人身份请走 /api/worker/**（服务端解）。
        return ApiResponse.success(productionService.report(
                orderId, operationId, body, TenantContext.getTenantId(), clientRequestId,
                WorkerIdentity.fromClientBody(
                        asText(body, "worker_id"), asText(body, "worker_name"))));
    }

    /** body 取文本（商家侧报工身份口径，与 ProductionService.str 同语义：空白 ⇒ null）。 */
    private static String asText(Map<String, Object> body, String key) {
        if (body == null || body.get(key) == null) {
            return null;
        }
        String value = String.valueOf(body.get(key));
        return value.isBlank() ? null : value;
    }

    /**
     * 加工单计件汇总（内部计件工资，per 工序；与对外加工费两套账分离）
     * GET /api/admin/production/orders/{orderId}/piecework
     *
     * <p><b>未定价显式可见</b>（V90，issue #4696）：响应追加 {@code unpriced}
     * （{@code {qty, operations:[{operation,logical_name,qty}], hint}}）——
     * <b>未定价 ≠ ¥0.00</b>：未定价工序的报工**不进** {@code total}（更不得按 0 计件），
     * 但数量与工序名必须列出来，并给可行动 hint（定价入口）。
     * 既有键名/含义/顺序一字不动（只加键）。</p>
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
     * per_operation:[{operation,amount,qty}], unpriced:{qty,operations,hint}}}；聚合算法与
     * per-order 计件**同一份**（{@code ProductionService.aggregate}）⇒ 两处的 {@code unpriced}
     * 块恒等（不会两套口径漂移）。{@code period} 在服务层校验（缺失/非法 ⇒ 422
     * 可行动错误，而不是 400 参数缺失）。</p>
     *
     * <p><b>未定价显式可见</b>（V90，issue #4696）：见 {@link #piecework(String)} ——
     * 未定价的报工不进 {@code total}，但必须在报表上列出来 + 给定价入口。</p>
     */
    @GetMapping("/piecework/summary")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> pieceworkSummary(
            @RequestParam(required = false) String period,
            @RequestParam(name = "worker_name", required = false) String workerName) {
        return ApiResponse.success(productionService.pieceworkSummary(
                period, workerName, TenantContext.getTenantId()));
    }

    /**
     * <b>按当前价重算未定价工序实例</b>（显式补价路径，issue #4709 C，P1）
     * POST /api/admin/production/orders/{orderId}/repricing
     *
     * <p><b>为什么需要它</b>：商家在部位价目矩阵里补了价，而**已实例化**的旧单快照仍是
     * {@code NULL}（未定价）⇒ 工人那批活的钱算不出来；重新实例化**不是**可用路径
     * （{@code null} 与 {@code 0} 同签名 ⇒ 不触发；{@code null → 非 0} 触发但会软删重插 +
     * 报工进度清零）。</p>
     *
     * <p><b>口径（三条红线，逐条由 SQL 谓词/SET 子句机械保证）</b>：
     * ① <b>只补 {@code NULL}</b> —— {@code unit_price > 0} 或 {@code = 0}（显式定价 0 元）的行
     * **一律不动**（谓词 {@code AND unit_price IS NULL}）；② <b>不碰报工进度与系数</b> ——
     * {@code done_qty} / {@code status} / {@code factor} 不在 SET 子句里；③ <b>不碰历史报工</b> ——
     * {@code production_work_logs} 的 {@code unit_price} / {@code factor} 一字不动。
     * 只影响**之后的**报工（金额在报工那一刻固化，不追溯）。</p>
     *
     * <p>响应：{@code {order_id, processing_order_id, batch_id, filled, already_priced,
     * still_unpriced, filled_operations:[{operation,logical_name,position,unit_price}],
     * still_unpriced_operations:[...], hint}}。{@code batch_id} = 本次动作的留痕批次
     * （{@code filled=0} 时为 {@code null}），可交给回滚端点撤销。**幂等**：重复调用第二次
     * {@code filled=0}，不产生新账行。</p>
     */
    @PostMapping("/orders/{orderId}/repricing")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> repriceUnpricedInstances(@PathVariable String orderId) {
        return ApiResponse.success(productionInstanceRepricingService
                .repriceUnpricedInstances(orderId, TenantContext.getTenantId()));
    }

    /**
     * 回滚一次补价动作（issue #4709 C）
     * POST /api/admin/production/repricing/{batchId}/rollback
     *
     * <p>把该批次补上的实例行还原成「未定价」（{@code unit_price = NULL}）。判据**只来自账本**
     * （这正是留痕的必要性）：逐行 CAS「当前值 == 账本记录的那次补价」⇒ 商家自己定的价、
     * 之后被改过或已重新实例化的行**永远**不被回滚。**幂等**：重复回滚 ⇒ {@code reverted=0}。
     * 响应 {@code {batch_id, reverted, skipped, hint}}。</p>
     */
    @PostMapping("/repricing/{batchId}/rollback")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> rollbackRepricing(@PathVariable String batchId) {
        return ApiResponse.success(productionInstanceRepricingService
                .rollback(batchId, TenantContext.getTenantId()));
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
     * 工艺路线模板（**具名主线 + 适用帘种 + 默认标记**，P2b / issue #4459 起为新结构）
     * GET /api/admin/production/routings
     *
     * <p>响应形态：{@code {total, routings:[{id, name, is_default, positions, mainline, status}]}}。
     * 旧形态（{@code {curtain_type, craft, operations}} 的 9 条展开快照）已随 P2b 退场
     * —— 前端由 P3（#4433）适配。</p>
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
     * **软删工序**（issue #4587 ③ = 母单 #4586 包A）
     * DELETE /api/admin/production/operations/{id}
     *
     * <p>软删 {@code deleted=1}（不物理删：历史报工/工序实例仍引用它）。三条护栏**一次报全**
     * （422 + {@code error.details}）：① 被活跃路线主线引用（按逻辑名或变体名命中，给路线名）；
     * ② 被活跃 {@code production_route_rules} 的 {@code operation}/{@code after_operation} 命中
     * （给触发名）；③ 被矩阵行引用（该变体对应的**全部** {@code (逻辑名, 部位)} 格中任一
     * {@code applicable=true}，给部位）。已软删 ⇒ <b>200 幂等 no-op</b>。</p>
     *
     * <p>⚠️ 本端点**行为一字不变**（不含「一键摘格」）—— 一键语义在
     * {@link #detachAndDeleteOperation(String)}（独立端点，issue #4665）。</p>
     */
    @DeleteMapping("/operations/{id}")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> deleteOperation(@PathVariable String id) {
        return ApiResponse.success(
                productionOperationCommandService.delete(id, TenantContext.getTenantId()));
    }

    /**
     * **一键「设为不做并删除」**（issue #4665 A；用户实测「无法删除，而且没有地方设置做于不做」）
     * DELETE /api/admin/production/operations/{id}/detach-and-delete
     *
     * <p>删除的前置（把受影响的矩阵格设为不做）**系统自己做**：同一事务里先摘格
     * （{@code applicable=false} + 价清空）再软删工序 + **级联软删矩阵行**（#4665 C：删干净），
     * 响应多两个键 {@code detached_positions} / {@code deleted_positions}（各摘/删了几个格，如实报数）。</p>
     *
     * <p><b>护栏不放宽</b>：护栏①主线 / ②规则<b>照样拦</b>（主线涉及车间顺序，必须人工确认），
     * 且<b>先判护栏、后摘格</b> ⇒ 被拦时一格都不摘、一行都不删；只有护栏③变成可一键满足。</p>
     *
     * <p><b>为什么是独立端点而不是给 {@code DELETE /{id}} 加查询参数</b>：`DELETE /{id}` 那条路径下
     * 另有一个既有软删写面（{@code tests/unit_ci_workflows/test_logic_delete_write_shape.py} 的锚点
     * 按**第一个名为 {@code delete} 的方法**取体，issue #4608 的显式写列守卫）—— 把一键语义塞进
     * 同一方法会让护栏判据与守卫锚点纠缠。独立端点 = 两条路径各自可 grep、各自可单测。</p>
     */
    @DeleteMapping("/operations/{id}/detach-and-delete")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> detachAndDeleteOperation(@PathVariable String id) {
        return ApiResponse.success(
                productionOperationCommandService.deleteDetaching(id, TenantContext.getTenantId()));
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
     * 新建工艺路线（{@code mainline} 可缺省 = 初版空主线）
     * POST /api/admin/production/routings
     * body: {name, mainline?, positions?, is_default?, status?}
     *
     * <p><b>P2b / issue #4459 形态变更</b>：写面从旧 {@code production_routings}
     * （{@code {curtain_type, craft, operations}} 展开快照）切到
     * {@code production_route_templates}（{@code {name, mainline, positions, is_default}}）。
     * 工艺不再参与选路（它只触发 {@code production_route_rules}）。</p>
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
     * 改工艺路线（issue #4308 交付物 2；路线是计件工资与完工判定的唯一输入）
     * PUT /api/admin/production/routings/{id}
     * body: {name?, is_default?, mainline?, positions?, status?}（**部分更新**：只写出现的字段）
     *
     * <p><b>P2b / issue #4459 的 body 扩展与护栏（全部有红证）</b>：
     * <b>改名只改 {@code name}</b>（不给 mainline 就不动序列）/ <b>{@code is_default} 恰一条</b>
     * （置 true 时同事务把既有默认降级）/ <b>{@code is_default:false} ⇒ 422</b>
     * （取消默认 ⇒ 该租户零默认 ⇒ 建单全 fail-closed）/ <b>停用默认路线 ⇒ 422</b> /
     * 主线护栏（空主线拒 / 引用工序库中不存在的工序拒 / 重复工序拒 / 至少一道必完工序）/
     * 序列真的变了才落版本账（{@code production_routing_versions}）。
     * 失败统一 **HTTP 422 + {@code error.details:[{field,message}]} 逐条理由**（一次报全）。</p>
     */
    @PutMapping("/routings/{id}")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> updateRouting(@PathVariable String id,
                                                          @RequestBody Map<String, Object> body) {
        return ApiResponse.success(productionRoutingCommandService.updateRouting(
                id, body, TenantContext.getTenantId()));
    }

    /**
     * 删工艺路线（**软删** {@code deleted=1}；P2b / issue #4459 新增）
     * DELETE /api/admin/production/routings/{id}
     *
     * <p><b>护栏</b>：删默认 ⇒ 422（删了就是零默认 ⇒ 建单全 fail-closed）/ 删最后一条 ⇒ 422。
     * 软删而非物理删：派生读 {@code deleted=0 AND status=active}，软删后立刻不参与选路，
     * 而「谁在何时删掉哪条路线」是排查工序错配的唯一证据。</p>
     */
    @DeleteMapping("/routings/{id}")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> deleteRouting(@PathVariable String id) {
        return ApiResponse.success(
                productionRoutingCommandService.deleteRouting(id, TenantContext.getTenantId()));
    }

    /**
     * 改**特殊选项**的对客单价（元/套，issue #4567：用户走查「特殊选项有单价，但数据不全，
     * 新增工序也无法增加特殊选项配置单价」）
     * PUT /api/admin/production/route-rules/{id}/customer-unit-price
     * body: {customer_unit_price}（元/套；{@code null} / 空串 = 显式改回**未定价**）
     *
     * <p><b>为什么单开一个端点而不是并进 {@code PUT /routings/{id}}</b>：这一列挂的是
     * {@code trigger_kind='option'} 的**规则行**（不是路线），而「按套收费」是对客售价账 ——
     * 与路线的车间路由语义、与工序库的**计件**单价是三件事（设计 §4.1 两套账不互读）。
     * 并进路线写面会让「谁改了价」在审计上不可分辨。</p>
     *
     * <p><b>护栏</b>：行不存在 / 非本租户 ⇒ 404；{@code trigger_kind != 'option'} ⇒ 422
     * （只有特殊选项按套计价）；价非数值 / 负数 / 超过两位小数 ⇒ 422。失败统一
     * {@code error.details:[{field,message}]} 逐条理由。**只写这一列**，不碰计件系数 {@code factor}。</p>
     */
    @PutMapping("/route-rules/{id}/customer-unit-price")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> updateRuleCustomerUnitPrice(@PathVariable String id,
                                                                       @RequestBody Map<String, Object> body) {
        return ApiResponse.success(productionRoutingCommandService.updateRuleCustomerUnitPrice(
                id, body, TenantContext.getTenantId()));
    }

    // ══════════════════ 信号映射：读面暂留 / 写面**已退役**（issue #4452）══════════════════
    /**
     * 信号映射列表（**存量单兜底表**的数据源 —— issue #4452 起它不再是新单的判据）。
     * GET /api/admin/production/route-signals
     *
     * <p><b>为什么读面暂留而写面退役</b>：`production_route_signals` 降级为「存量单兜底」
     * （表不删 —— 存量单仍需派生），读面留着便于排查历史单的派生来源；
     * 而 `POST/PUT/DELETE` 三个写面**已删除**（404）—— 让商家继续往兜底表里加行，
     * 只会让「已经不该被读的判据」继续增长（issue #4452：部位改走 {@code componentRole} 受控枚举、
     * 工艺改走加工项的显式声明 {@code processing_items.craft_hint}）。</p>
     */
    @GetMapping("/route-signals")
    public ApiResponse<Map<String, Object>> routeSignals() {
        return ApiResponse.success(productionOperationQueryService.routeSignalList(TenantContext.getTenantId()));
    }

    // ══════════════════ 异常订单清单（issue #4452 交付物 ④）══════════════════

    /**
     * **异常订单清单**：{@code route_source ∈ {default, partial}} 的加工单逐条可见
     * （加工单号 + 实际使用键 + 请求键 + 可行动文案）。
     *
     * <p>信号映射退场后，「部位/工艺是猜的或没填」必须有**可观测面** —— 否则退场只是把静默错配
     * 从「猜错」换成「悄悄落默认」。{@code missing_route}（库里缺路线）不在本清单，
     * 由 {@code GET /routing-gaps} 承担。</p>
     *
     * GET /api/admin/production/orders/routing-anomalies
     */
    @GetMapping("/orders/routing-anomalies")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> routingAnomalies() {
        return ApiResponse.success(
                processingOrderService.routingAnomalies(TenantContext.getTenantId()));
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

    // ══════════════════════ 加工费组合定价（V68，issue #4386）══════════════════════

    /**
     * 加工费组合定价列表（选配特征集合 → 加工费单价 元/米）
     * GET /api/admin/production/processing-fee-combinations
     *
     * <p>用户裁定（2026-09-19）：「不是每个加工项收取一个费用，而且通常是组合」——
     * 本表是商家**配置时**自行组合并定价的写面，也是下单侧按选配结果取价的匹配表。</p>
     */
    @GetMapping("/processing-fee-combinations")
    public ApiResponse<Map<String, Object>> processingFeeCombinations() {
        return ApiResponse.success(processingFeeQueryService.combinations(TenantContext.getTenantId()));
    }

    /**
     * 新建加工费组合定价
     * POST /api/admin/production/processing-fee-combinations
     * body: {items: ["韩褶","打孔","定型"], unit_price, sort_order?, source?, status?}
     *
     * <p><b>护栏（全部有红证）</b>：组合非空 / 特征名合法且不重复 / unit_price ≥ 0 /
     * source 在词表内 / composition_key **归一化后落库**（与书写顺序无关）；撞已有组合 ⇒ **409**。
     * 失败统一 **HTTP 422 + {@code error.details:[{field,message}]} 逐条理由**（一次报全）。</p>
     */
    @PostMapping("/processing-fee-combinations")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> createProcessingFeeCombination(
            @RequestBody Map<String, Object> body) {
        return ApiResponse.success(processingFeeCombinationCommandService.createCombination(
                body, TenantContext.getTenantId()));
    }

    /**
     * 改加工费单价 / 状态（部分更新）
     * PUT /api/admin/production/processing-fee-combinations/{id}
     * body: {unit_price?, status?, source?, sort_order?}
     *
     * <p>单价**真的变了**才追加 {@code processing_fee_combination_versions} 一行
     * （同值重复提交 = 幂等空操作）。</p>
     */
    @PutMapping("/processing-fee-combinations/{id}")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> updateProcessingFeeCombination(
            @PathVariable String id, @RequestBody Map<String, Object> body) {
        return ApiResponse.success(processingFeeCombinationCommandService.updateCombination(
                id, body, TenantContext.getTenantId()));
    }

    /**
     * 停用加工费组合（**软删语义**：status=disabled，行保留可回溯）
     * DELETE /api/admin/production/processing-fee-combinations/{id}
     */
    @DeleteMapping("/processing-fee-combinations/{id}")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> disableProcessingFeeCombination(@PathVariable String id) {
        return ApiResponse.success(processingFeeCombinationCommandService.disableCombination(
                id, TenantContext.getTenantId()));
    }

    /**
     * **加工费缺口**：订单里实际出现过、但「加工费组合」里查不到价的选配组合。
     *
     * <p>与 {@code GET /production/routing-gaps} 同构：把「只会在顾客下单后才发现漏配价」
     * 变成商家在配置阶段就能看见的待办。**不发明任何默认价** —— 缺口就是缺口。</p>
     */
    @GetMapping("/processing-fee-gaps")
    public ApiResponse<Map<String, Object>> processingFeeGaps() {
        return ApiResponse.success(processingFeeQueryService.feeGaps(TenantContext.getTenantId()));
    }

    // ══════════════════════════ 新模型读面（issue #4500 = 母单 #4423 的 P2c，P3 前置）══════════════════════════
    //
    // 两个**只读**端点：P3（#4433）的「部位价目矩阵」与「统一规则区」的数据面。写面（改价/增删规则）
    // 留 v1b（与「商家配置面 v1b」同批）。语义与排序判据在 ProductionRoutingReadService。

    /**
     * 部位价目矩阵（28 逻辑工序 × 3 部位 = **84 格**）
     * GET /api/admin/production/operation-positions
     *
     * <p>响应 {@code data} = {@code [{operation, position, unit_price, applicable}]}，按
     * {@code (operation, position)} 稳定排序。{@code applicable=false} = 该部位**明确不做**
     * （{@code unit_price=null}）—— 与「没定价」可区分（前端两态渲染）。</p>
     */
    @GetMapping("/operation-positions")
    @RequirePermission("processing:manage")
    public ApiResponse<List<Map<String, Object>>> operationPositions() {
        return ApiResponse.success(
                productionRoutingReadService.operationPositions(TenantContext.getTenantId()));
    }

    /**
     * 工艺项**两层分区**（issue #4676 = 设计 {@code docs/design/public-operations-and-craft-ui.md} §4.2）
     * GET /api/admin/production/operation-layers
     *
     * <p>分区判据 = **既有** {@code scope}（**不新造概念**）：{@code scope='set'} ⇒ {@code delivery}
     * （打包发货：打包 / 打卷 / 装袋 / 发货，**一列价**）；其余 ⇒ {@code operations}（工序，按部位）。
     * 响应 {@code data} = {@code {operations:[10 键矩阵行], delivery:[9 键一列价行]}}。</p>
     *
     * <p>⚠️ <b>「一列价」是显式规则（设计 §4.5 方案 A），不是「删格」</b>：{@code delivery} 行的价
     * 由该工序**所有 {@code applicable=TRUE} 格**的价聚合 —— 全同 ⇒ {@code priced}；有 {@code NULL}
     * ⇒ {@code unpriced}（**≠ ¥0.00**）；不同 ⇒ {@code multiple_prices} + {@code different_price_count}
     * （**不静默取第一个**）。删格会让交付工序在缺格的部位单里静默消失（少一道活、少一笔计件钱）。</p>
     *
     * <p>{@code operations} 段的每行与 {@code GET /operation-positions} **同形**（同一个
     * {@code positionView}）⇒ 前端同一份渲染代码；本端点只是**多给一层分区 + 一列价聚合**，
     * 不替代原端点（抽屉的 {@code PUT /operation-positions/{id}} 仍按格的 {@code id} 寻址）。</p>
     */
    @GetMapping("/operation-layers")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> operationLayers() {
        return ApiResponse.success(
                productionRoutingReadService.operationLayers(TenantContext.getTenantId()));
    }

    /**
     * 矩阵格**就地改价 / 改做不做**（issue #4587 ② = 母单 #4586 包A）
     * PUT /api/admin/production/operation-positions/{id}
     * body: {unit_price?: number|null, applicable?: boolean}
     *
     * <p><b>部分更新</b>：只写 body 里出现的键。三态（与 V71 列口径同款，不得发明第四态）：
     * {@code applicable=false} ⇒ 价**强制落 NULL**（明确不做 ⇒ 不报价）；
     * {@code applicable=true} + 价 null = 「**适用但未定价**」（合法，商家待办）；
     * 显式 {@code unit_price=null} = 改回「**未定价**」（**≠ 0 元**）。</p>
     *
     * <p><b>这一屏的价是给工人的「计件单价」</b>（报工工资 = 数量 × 计件单价），**不是对客加工费**
     * —— 对客那两本账在别处：基础加工费 = 加工项组合费用（元/米），特殊选项 =
     * {@code PUT /route-rules/{id}/customer-unit-price}（元/套）。三本账不得互读、不得混。</p>
     *
     * <p>校验失败 ⇒ 422 + {@code error.details} 逐条（负价 / 超两位小数 / 非布尔）；
     * 行不存在 / 跨租户 / 已软删 ⇒ 404。价**真的变了**才同事务向 V86 账表追加一行（改价必须留痕）。
     * 响应与 {@code GET /operation-positions} 的**单行同构**（前端同一个类型渲染）。</p>
     */
    @PutMapping("/operation-positions/{id}")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> updateOperationPosition(@PathVariable String id,
                                                                    @RequestBody Map<String, Object> body) {
        return ApiResponse.success(productionOperationPositionCommandService.update(
                id, body, TenantContext.getTenantId()));
    }

    /**
     * 规则区（工艺变体 ∪ 特殊选项 = **26 条**）
     * GET /api/admin/production/route-rules
     *
     * <p>响应 {@code data} = 11 键（见 {@code ProductionRoutingReadService}），按 {@code (priority, id)}
     * 稳定排序。只返回路线编排档（{@code insert}/{@code remove}）：计件系数档（{@code action='factor'}）
     * 不在此端点（P3 统一规则区不呈现系数）。{@code customer_unit_price}（元/套）只对
     * {@code trigger_kind='option'} 有意义，{@code null} = 未定价（**≠ 0 元**）。
     * {@code operation} / {@code logical_name} 成对给出**逻辑工序名**（issue #4642 读时归一，
     * 存量变体名行不再上屏）。</p>
     */
    @GetMapping("/route-rules")
    @RequirePermission("processing:manage")
    public ApiResponse<List<Map<String, Object>>> routeRules() {
        return ApiResponse.success(
                productionRoutingReadService.routeRules(TenantContext.getTenantId()));
    }

    /**
     * 条件工序规则创建弹窗的**触发值取值域**（issue #4616）
     * GET /api/admin/production/route-rule-options
     *
     * <p>用户裁定：「现在的问题是**没有入口往条件工序规则中添加新的工艺和加工项**」。入口一开，
     * 弹窗的「触发值」必须**按类型从对应词表取**（不手输）—— 手输一个词表里没有的名字 =
     * 建一条永远不命中的规则（商家以为配了、加工单上却没有）。</p>
     *
     * <p>响应：{@code {crafts:[…], processing_items:[…]}} —— 活跃工艺词表（{@code production_crafts}，
     * 此前**没有任何读端点**）+ 活跃加工项目录。特殊选项名**不在此列**（可新建，没有第二份词表）。</p>
     */
    @GetMapping("/route-rule-options")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> routeRuleOptions() {
        return ApiResponse.success(
                productionRoutingReadService.triggerOptions(TenantContext.getTenantId()));
    }

    /**
     * 新建**条件工序规则**（issue #4616 起**通用化**；issue #4570 建立本端点）
     * POST /api/admin/production/route-rules
     *
     * <p>请求体：{@code {trigger_kind?, trigger_value, action?, operation, after_operation?, position?,
     * priority?, customer_unit_price?}}。</p>
     *
     * <ul>
     *   <li>{@code trigger_kind} ∈ <b>闭词表</b> {@code craft}（工艺）/ {@code option}（特殊选项）/
     *       {@code processing_item}（加工项）；<b>缺省 = {@code option}</b>（老调用方/老 bundle
     *       行为一字不变 —— 反向护栏）；{@code shaped} 是表结构预留、无种子行 ⇒ 收到即 422；</li>
     *   <li>{@code trigger_value} <b>必须存在于对应词表</b>（craft ⇒ 活跃工艺词表；processing_item ⇒
     *       加工项目录；option ⇒ 可新建）⇒ 不存在/已停用 ⇒ <b>422</b> 逐条理由；</li>
     *   <li>{@code customer_unit_price}（元/套）<b>只允许 {@code trigger_kind='option'}</b>
     *       —— craft / 加工项按工序单价**计件**（给工人），两套账不互读，带价 ⇒ 422；</li>
     *   <li>{@code action} ∈ {@code insert}/{@code remove}（缺省 {@code insert}）；{@code operation} /
     *       {@code after_operation} = <b>逻辑工序名</b>（必须在该租户工序库里存在）；</li>
     *   <li>同一条「kind + 触发值 + 动作 + 目标工序」已存在 ⇒ <b>409</b>。</li>
     * </ul>
     *
     * <p>「工序」那半（新建一道工序 + 计件单价）走 {@code POST /production/operations}，
     * <b>两本账不混</b>。</p>
     */
    @PostMapping("/route-rules")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> createRouteRule(@RequestBody Map<String, Object> request) {
        return ApiResponse.success(
                productionRoutingCommandService.createRouteRule(request, TenantContext.getTenantId()));
    }

    /**
     * **软删条件工序规则**（issue #4587 ④ = 母单 #4586 包A）
     * DELETE /api/admin/production/route-rules/{id}
     *
     * <p>软删 {@code deleted=1}（不物理删：规则是排查工序顺序错的唯一线索）。**无硬护栏** ——
     * 规则只影响「插/删一道工序」，删错了重加即可。不存在 / 跨租户 / 已软删 ⇒ 404；
     * 响应 {@code {id, deleted:true}}。</p>
     */
    @DeleteMapping("/route-rules/{id}")
    @RequirePermission("processing:manage")
    public ApiResponse<Map<String, Object>> deleteRouteRule(@PathVariable String id) {
        return ApiResponse.success(
                productionRoutingCommandService.deleteRouteRule(id, TenantContext.getTenantId()));
    }
}
