package com.migao.admin.controller.agent;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.TenantPaymentQrcode;
import com.migao.admin.mapper.TenantPaymentQrcodeMapper;
import com.migao.admin.security.RequirePermission;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.Map;

/**
 * Agent 收款二维码（C 端支付页展示；issue #3990，M3-F-3）
 *
 * 平台不经手资金（二清规避）：只透出收款码图片与收款主体，顾客扫码直接付给商家。
 * 精简字段：imageUrl / payeeName（不含内部字段）。
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/agent/payment-qrcodes")
@RequiredArgsConstructor
public class AgentPaymentController {

    private final TenantPaymentQrcodeMapper paymentQrcodeMapper;

    /**
     * 当前租户收款二维码（按类型分组，C 端支付页展示用）
     * GET /api/admin/agent/payment-qrcodes
     */
    @RequirePermission("order:list")
    @GetMapping
    public ApiResponse<Map<String, Object>> getPaymentQrcodes() {
        Long tenantId = TenantContext.getTenantId();
        var wrapper = new LambdaQueryWrapper<TenantPaymentQrcode>()
                .eq(TenantPaymentQrcode::getTenantId, tenantId)
                .eq(TenantPaymentQrcode::getDeleted, 0)
                .eq(TenantPaymentQrcode::getStatus, "active");
        Map<String, Object> result = new HashMap<>();
        for (TenantPaymentQrcode q : paymentQrcodeMapper.selectList(wrapper)) {
            Map<String, Object> lite = new HashMap<>();
            lite.put("paymentType", q.getPaymentType());
            lite.put("imageUrl", q.getImageUrl());
            lite.put("payeeName", q.getPayeeName());
            result.put(q.getPaymentType(), lite);
        }
        return ApiResponse.success(result);
    }
}
