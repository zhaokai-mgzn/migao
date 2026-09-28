package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.ImageRecognitionClient;
import com.migao.admin.service.OrderShipmentService;
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
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 工人发货控制器（issue #5648）：{@code /api/worker/shipment/**}。
 *
 * <h3>为什么是新路径（能力保留、载体分离，照 #4727 / #4733 先例）</h3>
 * <p>发货此前只有 {@code POST /api/admin/production/orders/{orderId}/ship} —— 而
 * {@code /api/admin/**} 的门禁把 {@code worker} 放进**拒绝集合**
 * （{@code SecurityConfig.ADMIN_API_REJECTED_ROLES}）⇒ 纯工号 + PIN 的设备点发货**必 403**
 * （issue #5648 实测：工人被硬拒在管理后台外）。</p>
 * <p>本控制器挂在 {@code /api/worker/**} 下：不匹配 {@code /api/admin/**} ⇒ 工人到得了；
 * 准入判据 = 有效工人 session（{@link WorkerSessionService#resolveIdentity}），
 * <b>不查任何商家权限码</b>（工人 {@code permissions=[]}，加 {@code @RequirePermission}
 * 只会恒 403 —— 与 {@code WorkerProductionController} 同一口径）。</p>
 *
 * <h3>身份纪律</h3>
 * <p>{@code worker_id}/{@code worker_name} **只**来自 {@code X-Worker-Session-Id}（服务端解），
 * body 里的同名字段一个字节都不读 —— 发货留痕（谁发的货）是**责任凭证**，不能由前端自称。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/worker/shipment")
@RequiredArgsConstructor
public class WorkerShipmentController {

    private final OrderShipmentService orderShipmentService;
    private final WorkerSessionService workerSessionService;

    /**
     * 拍照识别：图 → 订单行 / 商品标签上的**文字**候选（**不落库、不提交**）。
     *
     * <p>POST /api/worker/shipment/recognize body {@code {images: ["https://…"]}}</p>
     *
     * <p>只回候选 + 是否需要人工确认：识别不确定 ⇒ 不预填（前端据此提示工人手输）。
     * 提交永远是人的动作 —— 工人核对后再调发货端点。</p>
     */
    @PostMapping("/recognize")
    public ApiResponse<ImageRecognitionClient.ImageRecognitionResult> recognize(
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId) {
        requireWorker(sessionId);
        Object raw = body == null ? null : body.get("images");
        List<String> images = (raw instanceof List<?> list)
                ? list.stream().map(String::valueOf).toList()
                : List.of();
        return ApiResponse.success(orderShipmentService.recognize(images));
    }

    /**
     * 打包：{@code confirmed|producing → packed}（用户裁定：打包与发货都是工人的动作）。
     *
     * <p>POST /api/worker/shipment/orders/{orderId}/pack</p>
     */
    @PostMapping("/orders/{orderId}/pack")
    public ApiResponse<Map<String, Object>> pack(
            @PathVariable String orderId,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId,
            @RequestHeader(value = ClientRequestIdService.HEADER, required = false) String clientRequestId) {
        WorkerIdentity identity = requireWorker(sessionId);
        return ApiResponse.success(orderShipmentService.pack(
                orderId, TenantContext.getTenantId(), clientRequestId, identity));
    }

    /**
     * 发货：记**实发**明细 + 物流 + 原子流转 {@code shipped}（一次事务，一个入口）。
     *
     * <p>POST /api/worker/shipment/orders/{orderId}/ship
     * body {@code {trackingNo, logisticsCompany?, photoRefs?, recognition?, items[]}}</p>
     */
    @PostMapping("/orders/{orderId}/ship")
    public ApiResponse<Map<String, Object>> ship(
            @PathVariable String orderId,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId,
            @RequestHeader(value = ClientRequestIdService.HEADER, required = false) String clientRequestId) {
        WorkerIdentity identity = requireWorker(sessionId);
        return ApiResponse.success(orderShipmentService.ship(
                orderId, body, TenantContext.getTenantId(), clientRequestId, identity));
    }

    /**
     * 撤销打包：{@code packed → producing}（**必带理由** + 留痕；商家侧无此入口）。
     *
     * <p>POST /api/worker/shipment/orders/{orderId}/unpack body {@code {reason}}</p>
     */
    @PostMapping("/orders/{orderId}/unpack")
    public ApiResponse<Map<String, Object>> unpack(
            @PathVariable String orderId,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId,
            @RequestHeader(value = ClientRequestIdService.HEADER, required = false) String clientRequestId) {
        WorkerIdentity identity = requireWorker(sessionId);
        return ApiResponse.success(orderShipmentService.unpack(
                orderId, body == null ? null : (body.get("reason") == null ? null : String.valueOf(body.get("reason"))),
                TenantContext.getTenantId(), clientRequestId, identity));
    }

    /**
     * 发货读面：状态 + 发货单（照片引用 / 识别留痕 / 撤销留痕）+ **实发套/件/卷**。
     *
     * <p>GET /api/worker/shipment/orders/{orderId}</p>
     *
     * <p>与 {@link OrderShipmentService#readShipment} **同一份实现** ⇒ 工人端与
     * 将来的商家/纸面消费方看到的实发数量逐字同源（不新造第二套响应形状）。</p>
     */
    @GetMapping("/orders/{orderId}")
    public ApiResponse<Map<String, Object>> read(
            @PathVariable String orderId,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId) {
        requireWorker(sessionId);
        return ApiResponse.success(orderShipmentService.readShipment(orderId, TenantContext.getTenantId()));
    }

    /**
     * 工人身份 fail-closed：无有效工人 session ⇒ 401（**不降级**）。
     *
     * <p>必须**显式判空**：只调 {@code resolveIdentity} 而不用返回值会让「无 session 也能发货」
     * 变成软约束（{@code WorkerProductionController} 的实测口径）。</p>
     */
    private WorkerIdentity requireWorker(String sessionId) {
        WorkerIdentity identity = workerSessionService.resolveIdentity(sessionId);
        if (identity == null) {
            throw BusinessException.authFailed("尚未登录工人身份，请先用工号 + PIN 登录");
        }
        return identity;
    }
}
