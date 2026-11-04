package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.security.PermissionInterceptor;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ConfigReadinessService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 「配置就绪度」聚合读端点（issue #6579；上游 = #6573 的配置主线）。
 *
 * <ul>
 *   <li>{@code GET /api/admin/config-readiness} —— 一次请求给出配置主线**七步**的事实
 *       （工序与单价 / 工艺路线 / 默认路线 / 加工项 / 加工费组合 / 余料尺寸 / 算料配置）。</li>
 * </ul>
 *
 * <p><b>权限（#6579 已定口径 1）：方法级 {@code production:view}</b> —— 它就是
 * 「企业基础设置」页第一屏的读码、菜单节点码与路由守卫码（#6573 已定：**不新造码**）。
 * 声明在**方法级**而不是类级：本控制器只有一个端点，方法级让「这一个端点的码」在源码上
 * 就是它自己那一行（类级声明在只有一个端点时读起来像「整个控制器都这个码」，判据也拿不到
 * 「这个端点声明了哪个码」的直接证据）。</p>
 *
 * <p><b>跨码步骤（#6579 已定口径 3）</b>：{@code remnant-sizes} 的读面码是
 * {@link ConfigReadinessService#REMNANT_SIZES_READ_CODE}（余料尺寸表读端点所属的类级码）。
 * 调用方不持该码 ⇒ 那一步**整个不出现在 {@code steps} 里**（不返回 0、不返回 forbidden 占位）。
 * 判定走 {@link PermissionInterceptor#holdsPermission(String)} —— 与
 * {@code @RequirePermission} **同一个授权实现**（同一份身份解析 / 旁路角色 / 取码来源），
 * 不在这里另写一份「查一下这个用户有没有那个码」。</p>
 *
 * <p><b>本控制器只做转发</b>：事实怎么算是 {@link ConfigReadinessService} 的事，
 * 它**不碰 Mapper、不写 SQL、不新造口径**（聚合既有 service）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin")
@RequiredArgsConstructor
public class ConfigReadinessController {

    private final ConfigReadinessService configReadinessService;
    private final PermissionInterceptor permissionInterceptor;

    /**
     * 配置主线七步的事实（**只给事实，不给三态**）。
     *
     * <p>响应 {@code data = {steps: {<stepKey>: {facts: {...}, href: "..."}}}}；三态
     * （{@code done} / {@code todo} / {@code unknown}）的判定**唯一真值源**是
     * {@code frontend/admin-web/src/lib/config-readiness.ts} 的 {@code judge*} 系列
     * —— 本端点不返回任何三态字符串。</p>
     */
    @GetMapping("/config-readiness")
    @RequirePermission("production:view")
    public ApiResponse<Map<String, Object>> readiness() {
        Long tenantId = TenantContext.getTenantId();
        boolean includeRemnantSizes =
                permissionInterceptor.holdsPermission(ConfigReadinessService.REMNANT_SIZES_READ_CODE);
        log.info("配置就绪度: tenantId={}, remnantSizesIncluded={}", tenantId, includeRemnantSizes);
        return ApiResponse.success(configReadinessService.readiness(tenantId, includeRemnantSizes));
    }
}
