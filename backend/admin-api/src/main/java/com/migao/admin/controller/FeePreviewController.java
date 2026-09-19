package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ProcessingFeeCalculator;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 加工费计价**预览**控制器（issue #4450 · 前置 #4406）。
 *
 * <p>接口：{@code POST /api/admin/orders/fee-preview} —— 按将提交的明细行**试算**加工费（**不落库**）。</p>
 *
 * <p><b>为什么必须有它（不是可选优化）</b>：下单页此前**本地自算**（Σ 加工项单价 × 数量），
 * 而 {@code OrderService.createOrder} 自 #4406 起按**选配组合取价**。两者口径不同 ⇒
 * 页面总额 ≠ 服务端总额 ⇒ 命中创建路径的「实收金额与应收不一致」校验（容差 0.01）
 * ⇒ <b>带加工项的订单提交被拒</b>（逐段实证见 issue #4450）。
 * 本端点把**同一份**取价结果提前交给页面，使「页面显示 === 落库」。</p>
 *
 * <p><b>单一真值</b>：本类<b>不实现任何取价逻辑</b>，只调
 * {@link ProcessingFeeCalculator#feesFor} —— 与创建订单是**同一个**实现
 * （在 Java 侧再写一份取价 = 页面与落库第二次分叉，正是本单要消灭的形态）。</p>
 *
 * <p><b>不落库</b>：纯试算，零写操作；不校验库存、不生成订单号。</p>
 *
 * <p>权限：{@code order:list}（与订单读域同权限 —— 下单页商家本就持有，同 {@code CraftCalcController}）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/orders/fee-preview")
@RequiredArgsConstructor
public class FeePreviewController {

    private final ProcessingFeeCalculator processingFeeCalculator;

    /**
     * 逐行试算加工费。
     *
     * <p>请求体与创建订单**同形**（{@code {"items":[{"processingInfo":{…}}]}}）——
     * 页面可以把「即将提交的那一份」原样送来，避免预览与提交两套入参。
     * 缺 {@code items} / 空数组 ⇒ 返回空列表（不报错：下单页在没选商品时本就会问）。</p>
     *
     * <p>响应 {@code data}：{@code items[i] = {processingFee, processingFeeDetail}}
     * （与订单详情行的键名**逐字一致**，页面与详情页可用同一套渲染）+ {@code processingFeeTotal}。</p>
     */
    @RequirePermission("order:list")
    @PostMapping
    public ApiResponse<Map<String, Object>> preview(
            @RequestBody(required = false) Map<String, Object> request) {
        Long tenantId = TenantContext.getTenantId();

        // 顺序与请求 items 一一对应（缺 processingInfo 的行给 null ⇒ 取价结果同样是 unpriced，
        // 不跳过 —— 跳过会让页面下标与服务端错位，正是「按下标对齐」要防的形态）。
        List<Object> processingInfos = new ArrayList<>();
        Object rawItems = request == null ? null : request.get("items");
        if (rawItems instanceof List<?> list) {
            for (Object item : list) {
                processingInfos.add(item instanceof Map<?, ?> map ? map.get("processingInfo") : null);
            }
        }

        List<ProcessingFeeCalculator.Fee> fees = processingFeeCalculator.feesFor(processingInfos, tenantId);

        List<Map<String, Object>> rows = new ArrayList<>();
        BigDecimal total = BigDecimal.ZERO;
        for (ProcessingFeeCalculator.Fee fee : fees) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("processingFee", fee.amount());
            row.put("processingFeeDetail", fee.detail());
            rows.add(row);
            if (fee.amount() != null) {
                total = total.add(fee.amount());
            }
        }

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("items", rows);
        data.put("processingFeeTotal", total);
        log.info("加工费试算: tenantId={}, lines={}, total={}", tenantId, rows.size(), total);
        return ApiResponse.success(data);
    }
}
