package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.PriceQuoteView;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.PriceResolution;
import com.migao.admin.service.PriceService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
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
}
