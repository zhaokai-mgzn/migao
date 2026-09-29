package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.CuttingHeightConfigService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 裁高（定高）**租户级配置**读写端点（V140，母单 #5161；商家面「工艺配置 → 裁高配置」tab）。
 *
 * <ul>
 *   <li>{@code GET /api/admin/production/cutting-height-config} —— 本租户生效配置；
 *       无配置行 ⇒ <b>默认种子</b>（壁达现场弹窗那 7 项）+ {@code source='default'}</li>
 *   <li>{@code PUT} —— upsert（<b>全量替换</b>）；非法值 ⇒ {@code 422 + error.details:[{field,message}]} 逐条理由</li>
 *   <li>{@code POST …/preview} —— 预演一次裁剪高度（配置页预演 + 一体机裁高计算器共用；
 *       <b>只读</b>：不改配置、不落库、<b>不写机器</b>）</li>
 * </ul>
 *
 * <p><b>权限</b>：与算料配置同口径 —— <b>读面</b>（{@code GET} / {@code preview}）挂生产域<b>读</b>码
 * {@code production:view}（与「工艺配置」侧边栏节点同码）；<b>写面</b>（{@code PUT}）是类级
 * {@code processing:manage}（与工序库 / 工艺路线 / 算料配置写面同口径）。</p>
 *
 * <p><b>单一真值</b>：本控制器不持有任何默认值/公式常量 —— 默认种子在
 * {@link CuttingHeightConfigService} 一处，命中与取整在 {@code CuttingHeightCalculator} 一处。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/production/cutting-height-config")
@RequiredArgsConstructor
@RequirePermission("processing:manage")
public class CuttingHeightConfigController {

    private final CuttingHeightConfigService cuttingHeightConfigService;

    /** 读本租户生效的裁高配置（{@code data = {source, config}}）。 */
    @RequirePermission("production:view")
    @GetMapping
    public ApiResponse<Map<String, Object>> get() {
        return ApiResponse.success(cuttingHeightConfigService.get(TenantContext.getTenantId()));
    }

    /** 写本租户裁高配置（upsert，**全量替换**）。 */
    @PutMapping
    public ApiResponse<Map<String, Object>> put(@RequestBody Map<String, Object> body) {
        return ApiResponse.success(cuttingHeightConfigService.put(TenantContext.getTenantId(), body));
    }

    /** 预演一次裁剪高度（只读）。 */
    @RequirePermission("production:view")
    @PostMapping("/preview")
    public ApiResponse<Map<String, Object>> preview(@RequestBody Map<String, Object> body) {
        return ApiResponse.success(cuttingHeightConfigService.preview(TenantContext.getTenantId(), body));
    }
}
