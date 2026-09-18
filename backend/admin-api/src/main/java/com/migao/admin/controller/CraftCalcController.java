package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.CraftCalcClient;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 算料试算控制器（issue #4421，商家手工下单页）
 *
 * <p>接口：{@code POST /api/admin/orders/craft-calc} —— 按宽/高/开数/档位**试算**用料（**不落库**）。</p>
 *
 * <p><b>单一真值</b>：算料公式的唯一实现在 ai-agent 的 {@code app/tools/curtain_calc.py}；
 * 本控制器只把请求转给 {@link CraftCalcClient} 并搬运结果 ——
 * <b>Java 侧不复制第二份算料逻辑</b>，<b>公式串 {@code formulaText} 亦由后端产出</b>（前端不得自拼）。</p>
 *
 * <p>独立于 {@code OrderController}：试算是下单页的辅助读接口，与订单 CRUD 的生命周期无关
 * （也便于按试算流量单独限流）。</p>
 *
 * <p>权限：{@code order:list}（与订单读域同权限 —— 下单页商家本就持有）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/orders/craft-calc")
@RequiredArgsConstructor
public class CraftCalcController {

    private final CraftCalcClient craftCalcClient;

    /**
     * 算料试算。返回 ai-agent 的算料结果（数值 + 可读公式串）。
     *
     * <p>入参 {@code {width, height?, open_count?, mounting?, craft_tier?, style?}} 原样透传：
     * 缺省值由 ai-agent 端点给，本层**不补默认值、不重算**（补默认值 = 第二份口径）。
     * 缺 {@code width} 或非正 ⇒ 400 且不发起远端调用（fail-closed，不猜窗宽）。</p>
     */
    @RequirePermission("order:list")
    @PostMapping
    public ApiResponse<Map<String, Object>> craftCalc(@RequestBody Map<String, Object> request) {
        Object width = request == null ? null : request.get("width");
        if (width == null) {
            throw new BusinessException("CRAFT_CALC_INVALID_INPUT",
                    "缺少必填入参 width（窗宽，米）", 400,
                    "请传 width（窗宽，米，> 0），例如 {\"width\": 6.6, \"open_count\": 2, \"craft_tier\": \"standard\"}；"
                            + "系统不猜窗宽，也不给 0 米。");
        }
        if (toDouble(width) <= 0) {
            throw new BusinessException("CRAFT_CALC_INVALID_INPUT",
                    "width（窗宽，米）必须大于 0，收到 " + width, 400,
                    "请传正的窗宽（米），例如 6.6。");
        }

        CraftCalcClient.CraftCalcResult result = craftCalcClient.calc(request);

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("fabricMeters", result.fabricMeters());
        data.put("pleatCount", result.pleatCount());
        data.put("perPanelPleats", result.perPanelPleats());
        data.put("fullness", result.fullness());
        data.put("fullnessActual", result.fullnessActual());
        data.put("formulaUsed", result.formulaUsed());
        // 公式串由 ai-agent 后端产出（与数值同源）—— 本层只搬运，**绝不**自拼
        data.put("formulaText", result.formulaText());
        data.put("source", result.source());
        data.put("craftTier", result.craftTier());
        data.put("warning", result.warning());
        log.info("算料试算: width={} openCount={} tier={} => {}米/{}折",
                width, request.get("open_count"), request.get("craft_tier"),
                result.fabricMeters(), result.pleatCount());
        return ApiResponse.success(data);
    }

    private static double toDouble(Object value) {
        if (value instanceof Number number) {
            return number.doubleValue();
        }
        try {
            return Double.parseDouble(String.valueOf(value));
        } catch (NumberFormatException e) {
            throw new BusinessException("CRAFT_CALC_INVALID_INPUT",
                    "width（窗宽，米）必须是数字，收到 " + value, 400,
                    "请传数字窗宽（米），例如 6.6。");
        }
    }
}
