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
 * 门幅规则**只读**端点（issue #5043 包 2b，商家手工下单页）
 *
 * <p>接口：{@code POST /api/admin/orders/door-width-plan} —— 回答「<b>哪个门幅 / 单幅还是接高 /
 * 客服所选是否最优</b>」，<b>不算钱、不落库</b>。前端 {@code door-width-plan.ts} 的口径搬到服务端后的读面。</p>
 *
 * <p><b>为什么独立于 {@code /orders/craft-calc}</b>：规则要在<b>发试算请求之前</b>用
 * （靠它决定选哪个 SKU/门幅），而试算请求本身要带门幅 ⇒ <b>鸡生蛋</b>；且
 * <b>四爪钩 / 穿杆 / 平幔</b> 不发试算请求（用户 2026-09-21 裁定：这三类工艺<b>不影响用料和门幅</b>）
 * ⇒ 规则面不能挂在试算上。</p>
 *
 * <p><b>单一真值</b>：规则解 / 幅数只在 ai-agent 的
 * {@code backend/ai-agent-service/app/tools/curtain_calc.py::build_quote(..., fabric_widths=...)}
 * → {@code resolve_fabric_plan}；裁决只在 {@code judge_door_width_choice} ——
 * 本控制器与 {@link CraftCalcClient#doorWidthPlan} 只<b>搬运</b>，Java 侧不复制规则。</p>
 *
 * <p>入参：{@code {width, height, door_widths, cutting_mode, selected_door_width, allowance,
 * open_count, mounting, fullness, craft, craft_tier, pleat_count, formula, has_pattern,
 * pattern_repeat, config}}（{@code config} 由客户端按租户注入）。权限 {@code order:list}
 * （与试算/判定同域 —— 下单页商家本就持有）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/orders/door-width-plan")
@RequiredArgsConstructor
public class DoorWidthPlanController {

    private final CraftCalcClient craftCalcClient;

    @RequirePermission("order:list")
    @PostMapping
    public ApiResponse<Map<String, Object>> doorWidthPlan(
            @RequestBody(required = false) Map<String, Object> request) {
        return ApiResponse.success(craftCalcClient.doorWidthPlan(request == null ? Map.of() : request));
    }
}
