package com.migao.admin.waybill;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 取号编排（issue #8698）。
 *
 * <p>🔴 <b>本类与订单状态完全无关</b>（口径文档 §3-2「取号 ≠ 发货」）：</p>
 * <ul>
 *   <li>不注入 {@code OrderService} / {@code OrderMapper} / {@code OrderLifecycleService}
 *       —— <b>结构上写不到订单状态</b>（判据 {@code WaybillServiceTest}
 *       另有静态守卫 + 注入式红证）；</li>
 *   <li>不写 {@code order_logistics} / {@code order_shipments}：取号只把运单号**回给页面**，
 *       由商家点「确认发货」走既有 {@code ProductionController#ship}（本单**一行不改**它）；</li>
 *   <li>取号成功的订单仍「待发货」—— 这是产品口径，不是实现细节。</li>
 * </ul>
 *
 * <p><b>manual 兜底</b>：租户没配 / 配了未接入 / code 未登记 ⇒ {@link Carrier#MANUAL}
 * ⇒ {@link #create} 在**调用任何 provider 之前**抛 422（可行动文案：手填单号），
 * 因此**不产生任何外呼**（{@link ManualWaybillProvider} 连 HTTP 客户端都没有）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class WaybillService {

    private final CarrierRegistry registry;
    private final TenantLogisticsConfigService configService;

    /** 本租户的承运商能力面（设置页 + 发货页共用的**唯一读面**）。 */
    public WaybillCapabilities capabilities(Long tenantId) {
        String configured = configService.configuredCarrierCode(tenantId);
        Carrier effective = registry.carrierOf(configured);
        return new WaybillCapabilities(registry.carriers(), configured, effective);
    }

    /**
     * 取号。**成功后订单状态不变**（本方法不碰订单）。
     *
     * @throws WaybillUnsupportedException 承运商未接入（manual 兜底，未发生任何外呼）
     * @throws com.migao.admin.exception.BusinessException 请求数据不完整（fail-closed，未发生任何外呼）
     */
    public WaybillCreateResult create(Long tenantId, String orderId, WaybillCreateRequest request) {
        Carrier carrier = registry.carrierOf(configService.configuredCarrierCode(tenantId));
        if (carrier.isManual() && CarrierCatalogue.MANUAL_CODE.equals(carrier.code())) {
            // 没配 / 配了个未登记的 code ⇒ 全 manual：直接给「手填」这条行动出口，不发外呼
            throw WaybillUnsupportedException.manualFallback(carrier.displayName());
        }
        if (!carrier.canCreate()) {
            // 配了某家但没接入（P0 的全部承运商都在这里）⇒ 同一出口，但显示商家选的那家名字
            throw WaybillUnsupportedException.manualFallback(carrier.displayName());
        }
        // fail-closed 在**调 provider 之前**：脏地址不许下单（面单打歪比报错贵，口径 §6-1）
        request.assertCreatable();
        WaybillProvider provider = registry.providerOf(carrier);
        WaybillCreateResult result = provider.create(request);
        log.info("取号成功（订单状态不变，等待人工确认发货）: tenantId={}, orderId={}, carrier={}, trackingNo={}",
                tenantId, orderId, carrier.code(), result.trackingNo());
        return result;
    }

    /** 轨迹查询（P0 无 Java 侧实现 ⇒ 恒 422「未接入」，不返回空轨迹冒充「查过了」）。 */
    public WaybillTrackResult track(Long tenantId, String trackingNo) {
        if (trackingNo == null || trackingNo.isBlank()) {
            throw com.migao.admin.exception.BusinessException.validationError("运单号为空，无法查询轨迹");
        }
        Carrier carrier = registry.carrierOf(configService.configuredCarrierCode(tenantId));
        if (!carrier.canTrack()) {
            throw WaybillUnsupportedException.of(carrier.code(), "轨迹查询");
        }
        return registry.providerOf(carrier).track(trackingNo.trim());
    }

    /**
     * 能力面（对外形状）。{@code configuredCarrier} = 库里存的原值（可能为 {@code null}）；
     * {@code effectiveCarrier} = 解析后的生效承运商（未登记 ⇒ manual）。
     */
    public record WaybillCapabilities(
            List<Carrier> carriers,
            String configuredCarrier,
            Carrier effectiveCarrier) {

        /** 是否处于 manual 兜底（= 今天不能自动取号）。前端按钮可用性**只看这个**。 */
        public boolean manualFallback() {
            return !effectiveCarrier.canCreate();
        }
    }
}
