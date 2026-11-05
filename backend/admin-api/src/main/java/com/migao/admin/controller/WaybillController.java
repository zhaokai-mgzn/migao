package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.waybill.Carrier;
import com.migao.admin.waybill.TenantLogisticsConfigService;
import com.migao.admin.waybill.WaybillCreateRequest;
import com.migao.admin.waybill.WaybillCreateResult;
import com.migao.admin.waybill.WaybillService;
import com.migao.admin.waybill.WaybillTrackResult;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 物流取号端点（issue #8698 P0；口径源 {@code docs/logistics-waybill-api-research.md}）。
 *
 * <ul>
 *   <li>{@code GET  /api/admin/logistics/carriers} —— 承运商注册表 + 能力位 + 本租户生效承运商。
 *       <b>设置页与发货页共用这一个读面</b>（能力位只有一个来源，前端不复制词表）。</li>
 *   <li>{@code PUT  /api/admin/logistics/carrier-config} —— 租户级配置写面（{@code /settings?domain=logistics}）。</li>
 *   <li>{@code POST /api/admin/logistics/orders/{orderId}/waybill} —— <b>取号</b>（不是发货）。</li>
 *   <li>{@code GET  /api/admin/logistics/track/{trackingNo}} —— 轨迹查询（P0 无实现 ⇒ 422）。</li>
 * </ul>
 *
 * <p>🔴 <b>取号端点不改变订单状态</b>（口径 §3-2）：它只返回运单号，落库与状态流转仍走既有
 * {@code POST /api/admin/production/orders/{orderId}/ship}（本单**一行不改**）。
 * 判据 {@code WaybillServiceTest}（注入式红证：往取号路径塞一次状态写 ⇒ 红）。</p>
 *
 * <p><b>权限</b>：读面 = {@code production:view}（与「工艺配置」侧边栏节点同码，
 * 发货页与设置页第一屏都持它）；租户配置写面 = {@code system:manage}（经营域写码，
 * 与「企业信息 / AI 客服 / 通知设置」同口径）；取号 = {@code order:update}
 * （**写码**：口径是「改订单状态/物流/备注」——取号落的是运单号，动的是订单的物流面）。
 * ⚠️ 为什么**不**复用 {@code production:execute}：那个码被 I4 台账冻结为**恰好四个**端点
 * （{@code tests/unit_ci_workflows/test_rbac_endpoint_write_codes.py} 的零外溢判据），
 * 新端点挂上去即红；扩台账属于授权变更，不在本单射程。</p>
 *
 * <p><b>密钥面</b>：本控制器从不下发任何承运商凭据（P0 没有凭据；P1 接入时凭据只进服务端），
 * 判据 {@code tests/unit_ci_workflows/test_waybill_p0_guards.py}。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/logistics")
@RequiredArgsConstructor
public class WaybillController {

    private final WaybillService waybillService;
    private final TenantLogisticsConfigService configService;

    /** 承运商注册表 + 本租户生效承运商（能力位的**唯一读面**）。 */
    @RequirePermission("production:view")
    @GetMapping("/carriers")
    public ApiResponse<Map<String, Object>> carriers() {
        return ApiResponse.success(capabilityPayload(TenantContext.getTenantId()));
    }

    /** 写本租户承运商（{@code carrierCode} 空 / 缺键 ⇒ 清空 = 全 manual）。 */
    @RequirePermission("system:manage")
    @PutMapping("/carrier-config")
    public ApiResponse<Map<String, Object>> updateCarrierConfig(@RequestBody(required = false) Map<String, Object> body) {
        Long tenantId = TenantContext.getTenantId();
        Object raw = body == null ? null : body.get("carrierCode");
        configService.put(tenantId, raw == null ? null : String.valueOf(raw));
        return ApiResponse.success(capabilityPayload(tenantId));
    }

    /**
     * **取号**（不是发货）：成功后订单仍「待发货」，运单号只回给页面手填/回填。
     *
     * <p>承运商未接入（P0 全部）⇒ 422 + 可行动文案（手填单号），**不发生任何外呼**。</p>
     */
    @RequirePermission("order:update")
    @PostMapping("/orders/{orderId}/waybill")
    public ApiResponse<WaybillCreateResult> create(
            @PathVariable String orderId,
            @RequestBody(required = false) Map<String, Object> body) {
        Long tenantId = TenantContext.getTenantId();
        log.info("取号请求: tenantId={}, orderId={}", tenantId, orderId);
        return ApiResponse.success(waybillService.create(tenantId, orderId, WaybillCreateRequest.from(orderId, body)));
    }

    /** 轨迹查询（P0 无实现 ⇒ 422「未接入」；不返回空轨迹冒充「查过了」）。 */
    @RequirePermission("production:view")
    @GetMapping("/track/{trackingNo}")
    public ApiResponse<WaybillTrackResult> track(@PathVariable String trackingNo) {
        return ApiResponse.success(waybillService.track(TenantContext.getTenantId(), trackingNo));
    }

    /** 能力面 → 响应体（记录 → 普通 Map，避免前端吃 Java 记录名）。 */
    private Map<String, Object> capabilityPayload(Long tenantId) {
        WaybillService.WaybillCapabilities caps = waybillService.capabilities(tenantId);
        List<Map<String, Object>> carriers = caps.carriers().stream().map(WaybillController::carrierPayload).toList();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("carriers", carriers);
        out.put("configuredCarrier", caps.configuredCarrier());
        out.put("effectiveCarrier", carrierPayload(caps.effectiveCarrier()));
        out.put("manualFallback", caps.manualFallback());
        return out;
    }

    private static Map<String, Object> carrierPayload(Carrier carrier) {
        Map<String, Object> one = new LinkedHashMap<>();
        one.put("code", carrier.code());
        one.put("displayName", carrier.displayName());
        one.put("logisticsType", carrier.logisticsType());
        one.put("trackQueryCode", carrier.trackQueryCode());
        one.put("canCreate", carrier.canCreate());
        one.put("canCancel", carrier.canCancel());
        one.put("canTrack", carrier.canTrack());
        one.put("mode", carrier.mode());
        return one;
    }
}
