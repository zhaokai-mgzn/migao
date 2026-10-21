package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.OrderCreateRequest;
import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.mapper.CustomerProfileMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

/**
 * 下单时的服务端定价（issue #7375，P1-3 段 2）：价格本命中 ⇒ **以服务端为准**，并留下定价依据。
 *
 * <h3>取数（不新造第二套）</h3>
 * <ul>
 *   <li>价格层级：{@link PriceService#resolvePrice}（段 1 的唯一实现点）；</li>
 *   <li>SKU：从 `processingInfo` 的**既有键族**读（`skuId` / `skuCode`）—— 🔴 **不加顶层字段**：
 *       `OrderDtoContractTest` 的 D1 判据明确「顶层 skuCode 是死字段、SKU 只在 processingInfo」，
 *       加回去等于把已经消除的分叉再开一次；都没有 ⇒ **本行不参与定价**；</li>
 *   <li>客户：按手机号取（{@code findFirstByPhone}，与授信/账龄同一条取法）⇒ 才有协议价/等级价。</li>
 * </ul>
 *
 * <h3>为什么「定位不到 SKU」不是错误</h3>
 * <p>手工行、存量调用都没有 SKU。这时**不动价格**（保持客户端价），标签写 {@code client} ——
 * 「没有定价依据」是事实，不该变成 500，也不该被静默算成标准价。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OrderPricingService {

    private final PriceService priceService;
    private final ProductSkuMapper productSkuMapper;
    private final CustomerProfileMapper customerProfileMapper;

    /**
     * 空实现（**不改任何价格**、不返回依据）—— 供「不扫描 Spring 组件的切片上下文」与直接 new 构造的
     * 既有单测使用，与 {@code OrderService.businessClock} 的默认实例同款口径：
     * 没有定价组件时行为**逐字等于改前**（不定价、不改价），不是静默降级成某个默认价。
     */
    public static final OrderPricingService NOOP = new OrderPricingService(null, null, null) {
        @Override
        public List<LinePricing> applyServerPrices(List<com.migao.admin.dto.OrderCreateRequest.OrderItemRequest> items,
                                                   String customerPhone, Long tenantId) {
            return new ArrayList<>();
        }
    };

    /** 单行定价结果（只读快照，供 {@code OrderService} 落列）。 */
    public record LinePricing(Long skuId, String skuCode, String priceSource, BigDecimal clientPrice) {
    }

    /**
     * 逐行定价：**改写** {@code items} 里的 `unitPrice`（价格本命中时），返回与服务端对齐的留痕。
     *
     * @param items        下单明细（会被就地改写）
     * @param customerPhone 下单手机号（用于取客户 ⇒ 协议价/等级价）
     * @param tenantId      租户
     */
    public List<LinePricing> applyServerPrices(List<OrderCreateRequest.OrderItemRequest> items,
                                               String customerPhone,
                                               Long tenantId) {
        List<LinePricing> out = new ArrayList<>();
        if (items == null || items.isEmpty()) {
            return out;
        }
        String customerId = resolveCustomerId(tenantId, customerPhone);
        for (OrderCreateRequest.OrderItemRequest item : items) {
            if (item == null) {
                out.add(null);
                continue;
            }
            String skuCodeFromRequest = skuCodeOf(item);
            Long skuId = resolveSkuId(tenantId, item, skuCodeFromRequest);
            if (skuId == null) {
                // 没有可定位的 SKU ⇒ 不参与服务端定价（保持客户端价，标签 client）
                out.add(new LinePricing(null, skuCodeFromRequest, OrderPriceOverride.CLIENT_SOURCE, null));
                continue;
            }
            PriceResolution.Result resolved = priceService.resolvePrice(
                    customerId, skuId, item.getQuantity());
            boolean overridden = OrderPriceOverride.shouldOverride(resolved.source());
            BigDecimal clientPrice = item.getUnitPrice();
            if (overridden) {
                // 金额精度准入（issue #6228）：改写值也要过同一道闸（超两位小数直接拒，不静默四舍五入）
                item.setUnitPrice(MoneyScale.requireTwoDecimalsOrNull(
                        resolved.price(), "服务端定价单价"));
            }
            out.add(new LinePricing(skuId, skuCodeFromRequest,
                    OrderPriceOverride.sourceLabel(resolved.source()),
                    OrderPriceOverride.clientPriceWhenOverridden(clientPrice, resolved.price(), overridden)));
        }
        return out;
    }

    private String resolveCustomerId(Long tenantId, String phone) {
        if (phone == null || phone.isBlank()) {
            return null;
        }
        CustomerProfile customer = customerProfileMapper.findFirstByPhone(tenantId, phone.trim());
        return customer == null ? null : customer.getId();
    }

    /** 从 `processingInfo` 取 SKU 键族（既有唯一来源）；不是 Map / 没键 ⇒ null。 */
    private static Object skuKeyOf(OrderCreateRequest.OrderItemRequest item, String key) {
        Object info = item == null ? null : item.getProcessingInfo();
        if (!(info instanceof java.util.Map<?, ?> map)) {
            return null;
        }
        return map.get(key);
    }

    private static String skuCodeOf(OrderCreateRequest.OrderItemRequest item) {
        Object value = skuKeyOf(item, "skuCode");
        return value == null ? null : String.valueOf(value);
    }

    /** `processingInfo.skuId` 优先（校验存在）；否则按 `skuCode`（+ 商品）定位；都没有 ⇒ null。 */
    private Long resolveSkuId(Long tenantId, OrderCreateRequest.OrderItemRequest item, String skuCode) {
        Object rawSkuId = skuKeyOf(item, "skuId");
        if (rawSkuId != null) {
            try {
                Long candidate = Long.valueOf(String.valueOf(rawSkuId).trim());
                ProductSku byId = productSkuMapper.selectById(candidate);
                if (byId != null) {
                    return byId.getId();
                }
            } catch (NumberFormatException ignored) {
                // 非数字 skuId（脏值）⇒ 退化到货号族匹配，不在这里抛（定价不该让下单 500）
            }
        }
        if (skuCode == null || skuCode.isBlank()) {
            return null;
        }
        LambdaQueryWrapper<ProductSku> wrapper = new LambdaQueryWrapper<ProductSku>()
                .eq(ProductSku::getTenantId, tenantId)
                .eq(ProductSku::getSkuCode, skuCode.trim());
        if (item.getProductId() != null) {
            wrapper.eq(ProductSku::getProductId, item.getProductId());
        }
        List<ProductSku> rows = productSkuMapper.selectList(wrapper);
        return rows.isEmpty() ? null : rows.get(0).getId();
    }
}
