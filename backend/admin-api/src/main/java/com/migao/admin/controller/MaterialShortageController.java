package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.MaterialShortageViews.MaterialShortageView;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.MaterialShortageService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 商品级用料缺口与耗尽风险（具名跨域视图 {@code material_shortage}，issue #6280）—— **只读**端点。
 *
 * <p>页面与 agent **共用同一份数字**（口径单点在 {@link MaterialShortageService} 的纯函数装配层）——
 * 本控制器不持任何算法，只做入参解析与租户上下文透传。</p>
 *
 * <p>权限复用商品域 {@code product:list}（与库存台账 / 批次看板 / 低库存端点同码 ——
 * 库存属于商品管理的读权限，不新造权限点）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/materials")
@RequiredArgsConstructor
public class MaterialShortageController {

    private final MaterialShortageService materialShortageService;

    /**
     * 用料缺口视图。
     *
     * <pre>GET /api/admin/materials/shortage?statuses=confirmed,producing&amp;limit=50&amp;as_of=2026-10-04</pre>
     *
     * @param statuses 订单状态过滤（逗号分隔；缺省 {@code confirmed,producing}；未知状态 ⇒ 400）
     * @param limit    行数上限（缺省 50；&lt;1 或非整数 ⇒ 400）
     * @param asOf     基准日（{@code YYYY-MM-DD}；缺省取业务「今天」{@code Asia/Shanghai}）
     */
    @RequirePermission("product:list")
    @GetMapping("/shortage")
    public ApiResponse<MaterialShortageView> shortage(
            @RequestParam(required = false) String statuses,
            @RequestParam(required = false) String limit,
            @RequestParam(name = "as_of", required = false) String asOf) {
        Long tenantId = TenantContext.getTenantId();
        log.info("查询用料缺口视图: tenantId={}, statuses={}, limit={}, asOf={}",
                tenantId, statuses, limit, asOf);
        return ApiResponse.success(materialShortageService.shortage(statuses, limit, asOf));
    }
}
