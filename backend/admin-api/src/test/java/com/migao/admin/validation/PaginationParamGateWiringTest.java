// case_ids: PG-070
package com.migao.admin.validation;

import com.migao.admin.config.WebConfig;
import com.migao.admin.security.PaginationParamInterceptor;
import com.migao.admin.security.PermissionInterceptor;
import com.migao.admin.security.TenantOwnershipInterceptor;
import com.migao.admin.service.RoleService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.handler.MappedInterceptor;

import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * issue #6222 **接线判据**：分页入参闸必须真注册进 MVC 链，且**排在授权/归属判定之后**。
 *
 * <p>为什么需要它（{@code migao-dev-flow} §28.2：判据本体绿 ≠ 接线在）：闸的函数级判据
 * （{@link PaginationParamGateTest}）与 standalone MockMvc 判据（{@link PaginationParamGateEndpointTest}）
 * 都**自己**调 {@code addInterceptors(...)} —— 生产装配里把注册删掉，它们**照样全绿**，
 * 而线上一天都不会拒。本类读的是**真 {@code WebConfig}** 给出的注册清单（不复制那份列表）。</p>
 *
 * <p>顺序同样是判据：{@code InterceptorRegistry} 按添加序执行 ⇒ 闸必须在
 * {@link PermissionInterceptor} / {@link TenantOwnershipInterceptor} **之后**，
 * 否则无权限 + {@code size=-5} 会从 403 变 400（破坏 F3 #6063 的 403-before-400 契约）。</p>
 */
@DisplayName("#6222 接线：WebConfig 必须注册分页入参闸（且排在授权/归属之后）")
class PaginationParamGateWiringTest {

    @Test
    @DisplayName("🔴 分页入参闸在 WebConfig 的注册清单里（删掉注册 ⇒ 本判据当场红）")
    void webConfig_registersPaginationGate() {
        PaginationParamInterceptor gate = new PaginationParamInterceptor();
        WebConfig webConfig = new WebConfig(
                new PermissionInterceptor(Mockito.mock(RoleService.class)),
                new TenantOwnershipInterceptor(),
                gate);
        SpyRegistry registry = new SpyRegistry();
        webConfig.webMvcConfigurer().addInterceptors(registry);

        assertThat(registry.registeredInterceptors())
                .as("#6222：分页入参闸必须进 /api/** 的 MVC 链")
                .contains(gate);
    }

    @Test
    @DisplayName("🔴 顺序：闸在授权/归属判定之后（无权限 + size=-5 仍是 403，不破坏 F3）")
    void gateIsRegisteredAfterAuthorization() {
        PaginationParamInterceptor gate = new PaginationParamInterceptor();
        PermissionInterceptor permission = new PermissionInterceptor(Mockito.mock(RoleService.class));
        TenantOwnershipInterceptor ownership = new TenantOwnershipInterceptor();
        WebConfig webConfig = new WebConfig(permission, ownership, gate);
        SpyRegistry registry = new SpyRegistry();
        webConfig.webMvcConfigurer().addInterceptors(registry);

        List<Object> ordered = registry.registeredInterceptors();
        assertThat(ordered.indexOf(gate))
                .as("闸必须排在授权拦截器之后（注册序 = 执行序）")
                .isGreaterThan(ordered.indexOf(permission));
        assertThat(ordered.indexOf(gate))
                .as("闸必须排在归属认定拦截器之后")
                .isGreaterThan(ordered.indexOf(ownership));
    }

    /** {@code getInterceptors()} 是 protected —— 测试子类只读暴露（不改注册行为，同 #6063 的写法）。 */
    static class SpyRegistry extends InterceptorRegistry {
        List<Object> registeredInterceptors() {
            List<Object> interceptors = new ArrayList<>();
            for (Object item : getInterceptors()) {
                if (item instanceof MappedInterceptor mapped) {
                    interceptors.add(mapped.getInterceptor());
                } else {
                    interceptors.add(item);
                }
            }
            return interceptors;
        }
    }
}
