package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.ProductionScanCompleteService;
import com.migao.admin.service.ProductionReworkService;
import com.migao.admin.service.ProductionScanService;
import com.migao.admin.service.ProductionService;
import com.migao.admin.service.WorkerAdminService;
import com.migao.admin.service.WorkerCuttingHeightService;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerSessionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.util.StringUtils;
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
    /** 一体机裁高读面（母单 #5161）：同一个算面 + 同一个码解析，**只读**、不写机器。 */
    private final WorkerCuttingHeightService workerCuttingHeightService;
    /**
     * 报返工（issue #7860）：任一工序工人都能报 —— 改记该笔报工 + 回退进度 + 生成返工单。
     *
     * <p>🔴 <b>字段注入而非常构造参数</b>（与本类既有 {@code productionScanCompleteService} 的
     * 装配纪律一致，见 {@code ProductionScanCompleteService} 对 {@code FinishedGoodsService} 的注记）：
     * {@code @RequiredArgsConstructor} 的构造签名被三个既有测试直接装配 —— 加参数会让它们一起红，
     * 而那不是本单要改的行为。包级可见 ⇒ 同包测试可直接注入替身。</p>
     */
    @org.springframework.beans.factory.annotation.Autowired(required = false)
    ProductionReworkService productionReworkService;
    /**
     * 工人档案（issue #7749）：只读一处 —— 这位工人**绑定的工序**。
     *
     * <p>绑定读的是 {@code users.worker_operation}（工人档案），不是请求体：工人端不能自称
     * 「我这次做的是别的工序」（计件归属是工资凭证，与身份同一条纪律）。</p>
     */
    private final WorkerAdminService workerAdminService;

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
     * <p>GET /api/worker/production/scan?token=…&amp;operation_id=…&amp;set_id=…&amp;order_item_id=…</p>
     *
     * <p><b>旧码收口（issue #4794）</b>：{@code set_id} + {@code order_item_id} 是**可选**入参，
     * 只在旧码（{@code granularity="order"}）降级形态下由工人「选完套 + 选部位」后回传 ⇒
     * 服务端按同一份推断口径重新解析出部位级视图。不给 ⇒ 与改前逐字一致的降级形态。</p>
     *
     * <p><b>为什么工人端也要一个</b>：切片 ① 的 {@code /api/admin/production/scan} 工人在门禁处
     * 到不了（{@code ADMIN_API_REJECTED_ROLES} 含 {@code worker}）⇒ A 模式「扫码 ⇒ 一屏」在工人端
     * 需要同一条读面。实现**逐字复用** {@link ProductionScanService#resolve}（不新造第二套响应形状
     * —— 商家端与工人端看到的推断结果逐字同源）。</p>
     *
     * <p>🔴 <b>响应含 {@code rework_records}</b>（issue #7973）：本件（套号 × 部位）的返工单记录，
     * 工人屏「返工记录（布料）」块与件级闭环（有未完结单 ⇒ 不再给报返工入口）的唯一数据源；
     * 未定位到件 / 服务未接线 ⇒ 不加这个键（不谎报「没有返工」）。</p>
     *
     * <p>🔴 <b>响应含 {@code set_overview}</b>（issue #4967 交付物 2）：本套 → 部位 → 工序明细
     * （逻辑名 / 应做数量+单位 / 单价 / 状态 / 已报数量）⇒ 工人扫一次就看到「这一套还有哪几道没做」。
     * 聚合**只有这一份**（在解析面，与推断/进度/卡点同源）—— 页面不另拉一份再按套重排。</p>
     *
     * <p>无有效工人 session ⇒ 401（fail-closed，与 {@code operations} 同款）。</p>
     */
    @GetMapping("/scan")
    public ApiResponse<Map<String, Object>> scan(
            @RequestParam(name = "token") String token,
            @RequestParam(name = "operation_id", required = false) String operationId,
            @RequestParam(name = "set_id", required = false) String setId,
            @RequestParam(name = "order_item_id", required = false) String orderItemId,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId) {
        WorkerIdentity identity = requireWorker(sessionId);
        Long tenantId = TenantContext.getTenantId();
        // 工人档案上绑定的工序（issue #7749）：非空 ⇒ 扫描面按它**自动选工序**（工人屏不出选择器）。
        String workerOperation = boundOperationOf(identity);
        // 旧码收口（issue #4794）：选了（套 + 部位）才走扩展重载；否则走同一份实现的空选择形态
        // （既有调用方/既有响应一字不动 —— 无选择时行为完全相同，只是多了一个「绑定工序」入参）。
        Map<String, Object> view = StringUtils.hasText(setId) || StringUtils.hasText(orderItemId)
                ? productionScanService.resolve(token, operationId, setId, orderItemId, tenantId,
                        workerOperation, identity.workerId())
                : productionScanService.resolve(token, operationId, null, null, tenantId,
                        workerOperation, identity.workerId());
        attachPieceReworkRecords(view, tenantId);
        return ApiResponse.success(view);
    }

    /**
     * 扫码视图追加**本件**的返工记录（issue #7973）—— 工人屏「返工记录（布料）」块的唯一数据源。
     *
     * <p>只加一个键 {@code rework_records}（与既有键同形，页面不重算）。三条判断：</p>
     * <ol>
     *   <li>未定位到件（旧码降级形态 / 无 {@code position.order_item_id}）⇒ <b>不加</b>：没有件就没有件级记录；</li>
     *   <li>服务未接线 ⇒ <b>不加</b>：不谎报「这一件没有返工」（与 {@code requireReworkWired} 同一口径）；</li>
     *   <li>真读了（哪怕是空列表）⇒ 加；页面据此区分「没有返工」与「这次读不到」。</li>
     * </ol>
     */
    private void attachPieceReworkRecords(Map<String, Object> view, Long tenantId) {
        if (view == null || productionReworkService == null) {
            return;
        }
        if (!(view.get("position") instanceof Map<?, ?> position)) {
            return;
        }
        Object rawItemId = position.get("order_item_id");
        String orderItemId = rawItemId == null ? null : String.valueOf(rawItemId).trim();
        if (!StringUtils.hasText(orderItemId)) {
            return;
        }
        Object rawSetNo = view.get("set_no");
        String setNo = rawSetNo == null ? null : String.valueOf(rawSetNo).trim();
        view.put("rework_records", productionReworkService.pieceRecords(tenantId, setNo, orderItemId));
    }

    /**
     * 工人扫码<b>开工 / 领活</b>（A 模式闭环的唯一写入口，切片 ② / 设计 §4 / §5）。
     *
     * <p>POST /api/worker/production/scan/complete</p>
     *
     * <p>🔴 <b>2026-09-21 语义改判（issue #4967，用户逐字裁定①）</b>：本端点的语义是
     * <b>开工 / 领活</b>（真实车间是「先扫码领活 → 再生产；完工不扫」），<b>不是</b>「做完扫一次」。
     * <b>路径名 {@code /scan/complete} 刻意不改</b>：它是**冻结契约**（工人端 H5 / bmini 两处
     * 客户端 + 幂等端点标识 {@code ProductionScanCompleteService.ENDPOINT_SCAN_COMPLETE} 都按它
     * 落证）—— 改名会让 {@code client_request_keys.endpoint} 出现两个历史值、并把已发版的小程序
     * 打回 404。记账时点与实现一字未变（仍是这一次推进 {@code done_qty} + 记计件）。</p>
     *
     * <p>body：{@code token}（必填）+ 可选 {@code operation_id}（一键改）/ {@code qty} /
     * {@code qualified_qty} / {@code work_type}。数量缺省 = 剩余应做。</p>
     *
     * <p>🔴 身份**只**来自 {@code X-Worker-Session-Id}：body 里的 {@code worker_id} /
     * {@code worker_name} **一个字节都不读**（计件归属 = 工资凭证，见 issue #4733）。
     * 无 session ⇒ 401，**不**降级到 body 口径。身份同时被写进工序实例的
     * {@code worker_id} / {@code worker_name} / {@code started_at}（领活人 + 领活时刻，issue #4967）。</p>
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

    /**
     * **报返工**（issue #7860，用户 2026-10-26 裁定）：任一工序工人扫水洗唛即可报。
     *
     * <p>用户逐字：「质检不能绑定死打包工序，需要允许任一工序工人报返工」
     * 「报返工的那个工序不能计件的，只报返工，生成返工单」。</p>
     *
     * <p>🔴 准入 = 有效工人 session（本路径统一口径）：**不看**打包工序、**不看**工人档案的页面键 ——
     * 报返工是「这件没做好」的事实上报，任何一个工位都可能在第一时间发现，卡页面键只会让事实丢掉。
     * 身份同样只由 {@code X-Worker-Session-Id} 解（body 里的 worker_id / worker_name 一个字节都不读）。</p>
     *
     * <p>body：{@code token}（必填）+ {@code reason}（必填，≤500 字）+ 可选 {@code operation_id} / {@code qty}。
     * 服务端把这件这道工序**最近一笔「正常」报工改记为返工**（回退进度与计件）并生成返工单。</p>
     */
    @PostMapping("/rework")
    public ApiResponse<Map<String, Object>> reportRework(
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId,
            @RequestHeader(value = ClientRequestIdService.HEADER, required = false) String clientRequestId) {
        WorkerIdentity identity = requireWorker(sessionId);
        requireReworkWired();
        return ApiResponse.success(productionReworkService.report(
                body, TenantContext.getTenantId(), clientRequestId, identity));
    }

    /**
     * **报返工的加工单列表**（issue #7860）—— 工人端「返工记录」页（`/w/rework.html`）。
     *
     * <p>🔴 准入 = 工人档案页面集含 {@link com.migao.admin.worker.WorkerPages#REWORK}（用户 2026-10-26
     * 逐字「在工人档案中设置过可见权限的工人」）：未开 ⇒ **403**，不降级成空列表
     * （空列表 = 「没有返工」，会让人以为真的没有）。</p>
     */
    @GetMapping("/rework-orders")
    public ApiResponse<Map<String, Object>> reworkOrders(
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId) {
        WorkerIdentity identity = requireWorker(sessionId);
        requireWorkerPage(identity, com.migao.admin.worker.WorkerPages.REWORK);
        requireReworkWired();
        return ApiResponse.success(productionReworkService.reworkOrders(TenantContext.getTenantId()));
    }

    /**
     * 一体机（机台旁那块屏 + 有线扫码枪）的**只读**裁高读面（母单 #5161；设计
     * {@code docs/design/cutting-height-config-and-terminal.md} §2.5 / §2.6）。
     *
     * <p>GET /api/worker/production/cutting-height?token=…（短码 / 裸 token / 整条印刷 URL）</p>
     *
     * <p>一次请求给一屏：扫码定位到的（套 × 部位）+ 该单**逐部位**的订单详情字段与裁剪高度
     * （{@code base} / {@code cutting_height} / {@code rounding} / {@code hits[]} / {@code misses[]}
     * / {@code missing[]}）—— 计算**逐字复用** {@link com.migao.admin.service.CuttingHeightConfigService#preview}
     * （本层不重算工艺/选项/加工项，也不写第二份命中实现）。</p>
     *
     * <p>🔴 <b>不写机器</b>（用户 2026-09-29 裁定①）：本包的终点是「请在机器屏输入 X.XXX 米」。</p>
     *
     * <p>🔴 权限：本路径在 {@code /api/worker/**} 内 ⇒ **零商家权限码**（工人 {@code permissions=[]}，
     * 加 {@code @RequirePermission} 只会恒 403）；准入 = 有效工人 session（无 ⇒ 401，fail-closed）。</p>
     */
    @GetMapping("/cutting-height")
    public ApiResponse<Map<String, Object>> cuttingHeight(
            @RequestParam(name = "token") String token,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId) {
        requireWorker(sessionId);
        return ApiResponse.success(workerCuttingHeightService.read(token, TenantContext.getTenantId()));
    }

    /**
     * 这位工人档案上绑定的逻辑工序（issue #7749）；未绑定 / 档案读不到 ⇒ {@code null}
     * （= 保持改前的「系统推断 + 工序选择器」行为）。
     */
    private String boundOperationOf(WorkerIdentity identity) {
        if (identity == null) {
            return null;
        }
        var worker = workerAdminService.findOwnedWorker(identity.workerId());
        return worker == null ? null : worker.getWorkerOperation();
    }

    /** 报返工服务未接线 ⇒ fail-closed（**不**静默返回「没有返工」—— 那会被读成「没人报过」）。 */
    private void requireReworkWired() {
        if (productionReworkService == null) {
            throw new com.migao.admin.exception.BusinessException("REWORK_UNAVAILABLE",
                    "报返工暂不可用：服务未接线", 503,
                    "请让管理员确认后端版本后再试；本次没有写入任何数据");
        }
    }

    /**
     * 工人档案页面集必须含某个**能力页键**，否则 403（issue #7162 的同一套形态，issue #7860 复用到 `rework`）。
     *
     * <p>🔴 这是**服务端准入**，不是「界面不显示入口」：档案查不到 / 页面集里没有该键 ⇒ 同一个 403
     * （不区分「没有这个工人」与「没开这个页」，避免把档案存在性当探针）。</p>
     */
    private void requireWorkerPage(WorkerIdentity identity, String pageKey) {
        var worker = workerAdminService.findOwnedWorker(identity.workerId());
        java.util.Set<String> granted =
                com.migao.admin.worker.WorkerPages.restrictedOrNull(worker == null ? null : worker.getWorkerPages());
        if (granted == null || !granted.contains(pageKey)) {
            throw com.migao.admin.exception.BusinessException.permissionDenied();
        }
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
