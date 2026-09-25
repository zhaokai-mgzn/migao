package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.CraftCalcConfigService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 算料公式**租户级配置**读写端点（issue #4528 = 包 E，商家面「工艺配置 → 算料配置」tab）。
 *
 * <ul>
 *   <li>{@code GET /api/admin/production/craft-calc-config} —— 本租户生效配置；
 *       无配置行 ⇒ <b>算料引擎默认值</b> + {@code source='default'}</li>
 *   <li>{@code PUT /api/admin/production/craft-calc-config} —— upsert（**全量替换**）；
 *       非法值 ⇒ {@code 422 + error.details:[{field,message}]} 逐条理由</li>
 * </ul>
 *
 * <p><b>权限</b>：<b>读面</b>（{@code GET}）按 issue #5291 改挂方法级生产域**读**码
 * {@code production:view}（与「工艺配置」侧边栏节点、Agent 侧 {@code craft_calc_config_query} 同码）；
 * <b>写面</b>（{@code PUT}）仍是类级 {@code processing:manage}（与工序库 / 工艺路线写面同口径）。
 * 类级声明只覆盖未被方法级覆盖的端点（{@code PermissionInterceptor} 的方法级优先规则）。</p>
 * <p>原口径（改前留档）：读写在同一个 {@code processing:manage} 上 ⇒ 只读工具不得不持管理码。</p>
 *
 * <p><b>单一真值</b>：本控制器不持有任何默认值/公式常量 —— 默认值来自算料引擎
 * （{@code CraftCalcClient#defaultConfig}），护栏理由来自
 * {@link CraftCalcConfigService}；算料公式的唯一实现仍在
 * {@code backend/ai-agent-service/app/tools/curtain_calc.py}。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/production/craft-calc-config")
@RequiredArgsConstructor
@RequirePermission("processing:manage")
public class CraftCalcConfigController {

    private final CraftCalcConfigService craftCalcConfigService;

    /**
     * 读本租户生效的算料配置。
     *
     * <p>响应 {@code data = {source, config}}：{@code source='stored'} 商家配置 /
     * {@code source='default'} 引擎默认值（**本租户没有配置行**）。前端据此显示
     * 「当前使用系统默认值」而不是把默认值伪装成商家配置（口径漂移风险见设计文档 §7.5）。</p>
     *
     * <p>{@code ?with_defaults=true} ⇒ **额外**附 {@code defaults} + {@code defaults_source}
     * （§22 P3 逐键「我改过没有」，issue #5131 增量 2）。🔴 **默认不带**：既有调用方响应逐字节不变，
     * 也**不新增**「读配置要依赖引擎可达性」这条依赖 —— 只有「参数总览」显式要。</p>
     */
    // issue #5291：读面（GET）改挂生产域读码 `production:view`；写面 `PUT` 仍是类级 `processing:manage`。
    @RequirePermission("production:view")
    @GetMapping
    public ApiResponse<Map<String, Object>> get(
            @RequestParam(name = "with_defaults", required = false, defaultValue = "false")
            boolean withDefaults) {
        return ApiResponse.success(
                craftCalcConfigService.get(TenantContext.getTenantId(), withDefaults));
    }

    /**
     * 写本租户算料配置（upsert，**全量替换**）。
     *
     * <p>body = 配置键的**扁平**映射（与 {@code GET} 的 {@code data.config} 同形，
     * 与算料端点 {@code config} 入参同形 —— 三处一个形状，前端零映射）。</p>
     */
    @PutMapping
    public ApiResponse<Map<String, Object>> put(@RequestBody Map<String, Object> body) {
        return ApiResponse.success(craftCalcConfigService.put(TenantContext.getTenantId(), body));
    }
}
