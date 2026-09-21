package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.CraftCalcClient;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 自动特征判定端点（issue #4976 包 2，商家手工下单页）
 *
 * <p>接口：{@code POST /api/admin/orders/auto-features} —— 判「超高 / 超宽 / 倒幅」
 * （用户 2026-09-21 裁定 B「<b>判定移到服务端</b>」的读面），<b>不算用料、不取价、不落库</b>。</p>
 *
 * <p><b>为什么独立于 {@code /orders/craft-calc}</b>：算料试算对 <b>四爪钩 / 穿杆 / 平幔</b>
 * 没有口径（下单页不发试算请求），而自动特征是<b>每一行</b>都要判的 —— 挂在试算上会让那些行
 * <b>丢特征</b> ⇒ 加工费组合键少一项 ⇒ 匹配不到组合价。判定只吃「几何 + SKU 门幅 + 加工类型 +
 * 租户配置」，与用料公式无关。</p>
 *
 * <p><b>单一真值</b>：判据的唯一实现在 ai-agent 的
 * {@code backend/ai-agent-service/app/tools/curtain_calc.py::detect_auto_features}；
 * 本控制器与 {@link CraftCalcClient#autoFeatures} 只<b>搬运</b>，Java 侧不复制判据。</p>
 *
 * <p>入参（全部可缺，缺 ⇒ <b>不判</b> + {@code notice} 说明原因，<b>不回落任何默认门幅</b>，issue #4877）：
 * {@code {width, height, fabric_width, cutting_mode, fullness, config}}。权限 {@code order:list}
 * （与试算同域 —— 下单页商家本就持有）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/orders/auto-features")
@RequiredArgsConstructor
public class AutoFeaturesController {

    private final CraftCalcClient craftCalcClient;

    @RequirePermission("order:list")
    @PostMapping
    public ApiResponse<Map<String, Object>> autoFeatures(
            @RequestBody(required = false) Map<String, Object> request) {
        return ApiResponse.success(craftCalcClient.autoFeatures(request == null ? Map.of() : request));
    }
}
