package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.PriceQuoteView;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.PriceResolution;
import com.migao.admin.service.PriceBookService;
import com.migao.admin.service.PriceService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;

/**
 * 报价（issue #7375，P1-3 段 1）：**服务端**说出这个客户买这个 SKU 该按哪个价、凭哪一条。
 *
 * <p>只读面：权限码沿用既有的 `order:view`（报价是下单读面的一部分，不新造码 ——
 * 新码会让现网种子岗位全体失效，而这一步只是把「本来就能看到的价格」变成服务端判定）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/pricing")
@RequiredArgsConstructor
@RequirePermission("order:view")
public class PricingController {

    private final PriceService priceService;

    /** 价格本录入与读面（issue #7375 段 3）：没有它，价格本只能靠写库维护。 */
    private final PriceBookService priceBookService;

    /**
     * 报价解析：`GET /api/admin/pricing/quote?customerId=&skuId=&quantity=`
     *
     * <p>🔴 未定价 ⇒ `price` / `amount` 为 null、`source = "unpriced"`（**不是 0**）。</p>
     */
    @GetMapping("/quote")
    public ApiResponse<PriceQuoteView> quote(@RequestParam(required = false) String customerId,
                                             @RequestParam Long skuId,
                                             @RequestParam(required = false) BigDecimal quantity) {
        log.info("报价解析: customerId={}, skuId={}, quantity={}", customerId, skuId, quantity);
        PriceResolution.Result result = priceService.resolvePrice(customerId, skuId, quantity);
        BigDecimal amount = result.price() != null && quantity != null
                ? result.price().multiply(quantity).setScale(2, java.math.RoundingMode.HALF_UP)
                : null;
        return ApiResponse.success(PriceQuoteView.builder()
                .customerId(customerId)
                .skuId(skuId)
                .quantity(quantity)
                .source(result.source().name().toLowerCase())
                .price(result.price())
                .amount(amount)
                .tierMinQty(result.tierMinQty())
                .build());
    }

    // ==================== 价格本（issue #7375 段 3） ====================

    /**
     * 价格本读面：`GET /api/admin/pricing/books?skuId=&customerId=`。
     *
     * <p>一个 SKU 的三层价格一次给全（协议 / 等级 / 阶梯），缺层就是没有该层价 —— 页面不必为
     * 「有没有这一层」写分支。</p>
     */
    @GetMapping("/books")
    public ApiResponse<com.migao.admin.dto.PriceBookView> books(
            @RequestParam Long skuId,
            @RequestParam(required = false) String customerId) {
        return ApiResponse.success(priceBookService.list(
                com.migao.admin.config.TenantContext.getTenantId(), skuId, customerId));
    }

    /**
     * 协议价 upsert：`PUT /api/admin/pricing/books/protocol`。
     *
     * <p>🔴 写面用 `product:create`（与商品维护同码，零授权 delta）。价格必须 &gt; 0 ——
     * 0 元 = 白送，未定价就不该录。</p>
     */
    @PutMapping("/books/protocol")
    @RequirePermission("product:create")
    public ApiResponse<Void> upsertProtocol(@RequestBody java.util.Map<String, Object> body) {
        Long tenantId = com.migao.admin.config.TenantContext.getTenantId();
        priceBookService.upsertProtocol(tenantId,
                body == null ? null : (String) body.get("customerId"),
                toLong(body == null ? null : body.get("skuId")),
                toDecimal(body == null ? null : body.get("price")),
                body == null ? null : (String) body.get("note"));
        return ApiResponse.success(null);
    }

    /** 等级价 upsert：`PUT /api/admin/pricing/books/vip-level`。 */
    @PutMapping("/books/vip-level")
    @RequirePermission("product:create")
    public ApiResponse<Void> upsertVipLevel(@RequestBody java.util.Map<String, Object> body) {
        Long tenantId = com.migao.admin.config.TenantContext.getTenantId();
        priceBookService.upsertVipLevel(tenantId,
                body == null ? null : (String) body.get("vipLevel"),
                toLong(body == null ? null : body.get("skuId")),
                toDecimal(body == null ? null : body.get("price")));
        return ApiResponse.success(null);
    }

    /** 阶梯价 upsert：`PUT /api/admin/pricing/books/tier`。 */
    @PutMapping("/books/tier")
    @RequirePermission("product:create")
    public ApiResponse<Void> upsertTier(@RequestBody java.util.Map<String, Object> body) {
        Long tenantId = com.migao.admin.config.TenantContext.getTenantId();
        priceBookService.upsertTier(tenantId,
                toLong(body == null ? null : body.get("skuId")),
                toDecimal(body == null ? null : body.get("minQty")),
                toDecimal(body == null ? null : body.get("maxQty")),
                toDecimal(body == null ? null : body.get("price")));
        return ApiResponse.success(null);
    }

    /** 软删一条价格本记录：`DELETE /api/admin/pricing/books/{kind}/{id}`（kind = protocol / vip-level / tier）。 */
    @DeleteMapping("/books/{kind}/{id}")
    @RequirePermission("product:create")
    public ApiResponse<Void> removeBook(@PathVariable String kind, @PathVariable String id) {
        priceBookService.remove(com.migao.admin.config.TenantContext.getTenantId(), kind, id);
        return ApiResponse.success(null);
    }

    private static Long toLong(Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof Number number) {
            return number.longValue();
        }
        try {
            return Long.valueOf(String.valueOf(value).trim());
        } catch (NumberFormatException notANumber) {
            return null;
        }
    }

    private static java.math.BigDecimal toDecimal(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return new java.math.BigDecimal(String.valueOf(value).trim());
        } catch (NumberFormatException notANumber) {
            return null;
        }
    }
}
