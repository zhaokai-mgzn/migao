package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.ProductionScanCompleteService;
import com.migao.admin.service.ProductionScanService;
import com.migao.admin.service.ProductionService;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerSessionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 工人报工控制器（issue #4733）：`/api/worker/production/**`。
 *
 * <p><b>为什么必须是新路径</b>（设计 #4716 §2.4 / C11）：报工端点今天挂在
 * {@code /api/admin/production/**} 下，而 {@code /api/admin/**} 的门禁把「非
 * customer/agent 的角色」视为商户员工**放行进入**（细粒度由 {@code @RequirePermission} 拦）。
 * 工人若持 {@code role=worker} 且 {@code permissions=[]}，能进后台但会在带注解的端点 403
 * —— 而实测**有 10 个 controller 完全没有 {@code @RequirePermission}**（含
 * {@code /api/admin/user}、{@code /api/admin/menus}）⇒ 「不给工人商家权限」在那批上**不成立**。
 * ⇒ 工人走 {@code /api/worker/**}（不匹配 {@code /api/admin/**}），并在
 * {@code adminApiAuthorizationManager} 的拒绝集合追加 {@code worker}（双保险）。</p>
 *
 * <p><b>身份纪律（本单核心）</b>：本控制器**只**从 {@code X-Worker-Session-Id} 解身份
 * （{@link WorkerSessionService#resolveIdentity}），body 里的 {@code worker_id}/{@code worker_name}
 * **一个字节都不读**（连读取代码都没有 —— 想冒领的人改前端也没用）。</p>
 *
 * <p>权限：本路径下**不**使用 {@code @RequirePermission}（工人 {@code permissions=[]}，
 * 加注解只会恒 403）；准入由「有效工人 session」这一条判据把关，见
 * {@link com.migao.admin.security.SecurityConfig} 的 {@code /api/worker/**} 规则。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/worker/production")
@RequiredArgsConstructor
public class WorkerProductionController {

    private final ProductionService productionService;
    private final WorkerSessionService workerSessionService;
    /** 扫码解析 + 工序推断（切片 ① 的**同一份**只读实现，工人路径与商家路径共用一个类）。 */
    private final ProductionScanService productionScanService;
    /** 扫码报工主闭环（切片 ②）：一次事务记账 + 未确定工序拒绝记账 + A 模式 {@code done_at}。 */
    private final ProductionScanCompleteService productionScanCompleteService;

    /**
     * 工人扫工页读面：加工单工序树 + 进度。
     *
     * <p>复用 {@link ProductionService#getOperations}（**同一份读面**，不新造第二套响应形状）
     * ⇒ 工人端与商家端看到的工序/进度/报工流水逐字同源。</p>
     */
    @GetMapping("/orders/{orderId}/operations")
    public ApiResponse<Map<String, Object>> operations(
            @PathVariable String orderId,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId) {
        // 无有效工人 session ⇒ 401（fail-closed）。必须**显式判空**：只调 resolveIdentity 而不用返回值
        // 会让「无 session 也能读」变成软约束（实测：不判空时该端点 200）
        if (workerSessionService.resolveIdentity(sessionId) == null) {
            throw com.migao.admin.exception.BusinessException.authFailed(
                    "尚未登录工人身份，请先用工号 + PIN 登录");
        }
        return ApiResponse.success(productionService.getOperations(orderId, TenantContext.getTenantId()));
    }

    /**
     * 工人扫码报工：推进工序进度 + 记个人计件。
     *
     * <p>POST /api/worker/production/orders/{orderId}/operations/{operationId}/report</p>
     *
     * <p>body 与既有冻结契约同形（{@code qty}/{@code qualified_qty}/{@code work_type}），
     * <b>但不含</b> {@code worker_id}/{@code worker_name} —— 身份来自
     * {@code X-Worker-Session-Id}（服务端解）。请求体里即使塞了这两个键也**不被读取**。</p>
     */
    @PostMapping("/orders/{orderId}/operations/{operationId}/report")
    public ApiResponse<Map<String, Object>> report(
            @PathVariable String orderId,
            @PathVariable String operationId,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId,
            @RequestHeader(value = ClientRequestIdService.HEADER, required = false) String clientRequestId) {
        WorkerIdentity identity = workerSessionService.resolveIdentity(sessionId);
        if (identity == null) {
            // 无 session ⇒ 显式拒绝（**不**降级到 body 口径）：工人路径上「谁报的」没有第二条来源。
            // 商家侧报工仍走 /api/admin/**（那条路径显式标注 client_body 来源）。
            throw com.migao.admin.exception.BusinessException.authFailed(
                    "尚未登录工人身份，请先用工号 + PIN 登录后再报工");
        }
        return ApiResponse.success(productionService.report(
                orderId, operationId, body, TenantContext.getTenantId(), clientRequestId, identity));
    }

    /**
     * 工人扫码解析 + 工序推断（**只读**，切片 ① / 设计 §2.3 / §2.6 / §3；切片 ② 接线）。
     *
     * <p>GET /api/worker/production/scan?token=…&amp;operation_id=…</p>
     *
     * <p><b>为什么工人端也要一个</b>：切片 ① 的 {@code /api/admin/production/scan} 工人在门禁处
     * 到不了（{@code ADMIN_API_REJECTED_ROLES} 含 {@code worker}）⇒ A 模式「扫码 ⇒ 一屏」在工人端
     * 需要同一条读面。实现**逐字复用** {@link ProductionScanService#resolve}（不新造第二套响应形状
     * —— 商家端与工人端看到的推断结果逐字同源）。</p>
     *
     * <p>无有效工人 session ⇒ 401（fail-closed，与 {@code operations} 同款）。</p>
     */
    @GetMapping("/scan")
    public ApiResponse<Map<String, Object>> scan(
            @RequestParam(name = "token") String token,
            @RequestParam(name = "operation_id", required = false) String operationId,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId) {
        requireWorker(sessionId);
        return ApiResponse.success(productionScanService.resolve(
                token, operationId, TenantContext.getTenantId()));
    }

    /**
     * 工人扫码**完成**（A 模式闭环的唯一写入口，切片 ② / 设计 §4 / §5）。
     *
     * <p>POST /api/worker/production/scan/complete</p>
     *
     * <p>body：{@code token}（必填）+ 可选 {@code operation_id}（一键改）/ {@code qty} /
     * {@code qualified_qty} / {@code work_type}。数量缺省 = 剩余应做。</p>
     *
     * <p>🔴 身份**只**来自 {@code X-Worker-Session-Id}：body 里的 {@code worker_id} /
     * {@code worker_name} **一个字节都不读**（计件归属 = 工资凭证，见 issue #4733）。
     * 无 session ⇒ 401，**不**降级到 body 口径。</p>
     *
     * <p>幂等：请求头 {@code X-Client-Request-Id}（与既有报工同一套实现/同一张表）；
     * 同键重复 ⇒ 不重复计件、回放首次结果（{@code replayed:true}）。</p>
     */
    @PostMapping("/scan/complete")
    public ApiResponse<Map<String, Object>> completeByScan(
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId,
            @RequestHeader(value = ClientRequestIdService.HEADER, required = false) String clientRequestId) {
        WorkerIdentity identity = requireWorker(sessionId);
        return ApiResponse.success(productionScanCompleteService.complete(
                body, TenantContext.getTenantId(), clientRequestId, identity));
    }

    /** 有效工人 session 或 401（fail-closed 的**唯一**一处判据：工人路径上「谁」没有第二条来源）。 */
    private WorkerIdentity requireWorker(String sessionId) {
        WorkerIdentity identity = workerSessionService.resolveIdentity(sessionId);
        if (identity == null) {
            throw com.migao.admin.exception.BusinessException.authFailed(
                    "尚未登录工人身份，请先用工号 + PIN 登录");
        }
        return identity;
    }

    /**
     * 工人扫工页的「当前工人」确认面（设计 W2：提交前显示「当前工人：张三」）。
     *
     * <p>与 {@code POST /api/worker/session/current} 同源（都读 {@code worker_sessions}），
     * 放在本控制器是为了让扫工页**一次请求**就能拿到「这单的工序 + 我是谁」的对齐信息。</p>
     */
    @GetMapping("/current-worker")
    public ApiResponse<Map<String, Object>> currentWorker(
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId) {
        WorkerIdentity identity = workerSessionService.resolveIdentity(sessionId);
        if (identity == null) {
            throw com.migao.admin.exception.BusinessException.authFailed(
                    "尚未登录工人身份，请先用工号 + PIN 登录");
        }
        return ApiResponse.success(workerSessionService.currentWorker(identity.sessionId()));
    }
}
