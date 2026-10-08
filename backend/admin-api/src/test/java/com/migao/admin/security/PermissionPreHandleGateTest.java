// case_ids: DF-025, PG-070
package com.migao.admin.security;

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.WebConfig;
import com.migao.admin.service.RoleService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.containsString;
import static org.mockito.ArgumentMatchers.anyString;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * F3（issue #6063）：无权限请求的 403 必须先于参数校验的 400/422。
 *
 * <p>病（R2 阶段3 RBAC 矩阵实测 20 格）：{@code PermissionInterceptor} 是 AOP {@code @Around}，
 * 运行在**方法体调用**阶段；{@code @RequestParam} 必填校验（{@code MissingServletRequestParameterException}
 * → 400/422）发生在**参数解析**阶段，早于 AOP ⇒ 无权限 GET 缺必填参数拿到 422
 * （从错误形态可确认端点存在 + 参数结构 = 信息泄露），而带齐参数时是 403 ——
 * 同一授权判定时序不确定。</p>
 *
 * <p>修法：{@code PermissionInterceptor} 实现 {@code HandlerInterceptor.preHandle}
 * （MVC 分发阶段，先于参数解析），复用同一份 public {@code requirePermission(code)}
 * （不产生第二套授权语义）；{@code WebConfig} 注册 {@code /api/**}；AOP 保留为双保险。</p>
 *
 * <p>实例判据（本文件）：真 {@code @RestControllerAdvice} + standalone MockMvc 真实 MVC
 * 分发链；类级元守卫（{@code WebConfig} 拦截器注册，删注册即红）在末条测试。</p>
 */
@DisplayName("F3 #6063：无权限 403 先于参数 422（preHandle 权限门禁）")
class PermissionPreHandleGateTest {

    @RestController
    static class ProbeController {
        @GetMapping("/api/admin/orders/probe")
        @RequirePermission("order:view")
        public String probe(@RequestParam long page) {
            return "ok";
        }
    }

    /** 类级注解形态：方法上无注解，权限码声明在 controller 类上。 */
    @RestController
    @RequirePermission("report:view")
    static class ClassGuardedController {
        @GetMapping("/api/admin/reports/probe")
        public String probe(@RequestParam long page) {
            return "ok";
        }
    }

    @AfterEach
    void clearSecurityContext() {
        SecurityContextHolder.clearContext();
    }

    /** 建一个「登录身份 = userId、权限 = permissions」的 standalone MockMvc（真实 MVC 分发链）。 */
    private MockMvc login(String userId, String... permissions) {
        RoleService roleService = Mockito.mock(RoleService.class);
        Mockito.when(roleService.getUserPermissions(userId)).thenReturn(List.of(permissions));
        SecurityUser principal = new SecurityUser(userId, 20L, userId,
                List.of("employee"), List.of(new SimpleGrantedAuthority("ROLE_employee")));
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(principal, null, principal.getAuthorities()));
        return MockMvcBuilders.standaloneSetup(new ProbeController(), new ClassGuardedController())
                .setControllerAdvice(new GlobalExceptionHandler())
                .addInterceptors(new PermissionInterceptor(roleService))
                .build();
    }

    @Test
    @DisplayName("无权限 + 缺必填参数 → 403（修前 422：参数校验先于权限判定泄露端点结构）")
    void denied_missingParam_returns403_not422() throws Exception {
        mockMvcForDeny().perform(get("/api/admin/orders/probe"))
                .andExpect(status().isForbidden())
                .andExpect(content().string(containsString("PERMISSION_DENIED")))
                .andExpect(content().string(containsString("order:view")));
    }

    @Test
    @DisplayName("无权限 + 参数齐 → 403（与缺参时同形，授权判定时序稳定）")
    void denied_fullParam_returns403() throws Exception {
        mockMvcForDeny().perform(get("/api/admin/orders/probe").param("page", "1"))
                .andExpect(status().isForbidden())
                .andExpect(content().string(containsString("PERMISSION_DENIED")));
    }

    @Test
    @DisplayName("有权限 + 参数齐 → 200（放行语义不回归）")
    void granted_returns200() throws Exception {
        login("emp-granted", "order:view").perform(get("/api/admin/orders/probe").param("page", "1"))
                .andExpect(status().isOk())
                .andExpect(content().string(containsString("ok")));
    }

    @Test
    @DisplayName("有权限 + 缺必填参数 → 400（参数校验语义保留，不被 403 吞掉）")
    void granted_missingParam_returns400() throws Exception {
        login("emp-granted", "order:view").perform(get("/api/admin/orders/probe"))
                .andExpect(status().isBadRequest());
    }

    @Test
    @DisplayName("类级 @RequirePermission 同样在 preHandle 生效（方法无注解、类有）")
    void classLevelAnnotation_gatedInPreHandle() throws Exception {
        login("emp-no-perm").perform(get("/api/admin/reports/probe").param("page", "1"))
                .andExpect(status().isForbidden())
                .andExpect(content().string(containsString("report:view")));
    }

    @Test
    @DisplayName("类级元守卫：WebConfig 必须把 PermissionInterceptor / 归属认定 / 分页入参闸都注册进 MVC 链")
    void webConfig_registersPreHandleInterceptor() {
        PermissionInterceptor permissionInterceptor =
                new PermissionInterceptor(Mockito.mock(RoleService.class));
        TenantOwnershipInterceptor tenantOwnershipInterceptor = new TenantOwnershipInterceptor();
        // issue #6222：第三条闸也是**构造注入**（漏装配 = 编译期红，不是静默少一条）
        PaginationParamInterceptor paginationParamInterceptor = new PaginationParamInterceptor();
        WebConfig webConfig = new WebConfig(permissionInterceptor, tenantOwnershipInterceptor,
                paginationParamInterceptor);
        SpyRegistry registry = new SpyRegistry();
        webConfig.webMvcConfigurer().addInterceptors(registry);
        assertThat(registry.interceptorCount()).as("F3 #6063：/api/** 拦截器注册不可消失").isGreaterThan(0);
        // issue #6158：两条「判定先于参数解析」的拦截器都必须真在注册表里（少一条即红）
        // issue #6222：分页入参闸同款（本单的接线判据；顺序判据见 PaginationParamGateWiringTest）
        assertThat(registry.registeredInterceptors())
                .as("#6063 授权 + #6158 归属 + #6222 分页入参闸 都必须进 MVC 链")
                .contains(permissionInterceptor, tenantOwnershipInterceptor, paginationParamInterceptor);
    }

    /** getInterceptors() 是 protected —— 测试子类暴露只读计数与只读清单（不改变注册行为）。 */
    static class SpyRegistry extends InterceptorRegistry {
        int interceptorCount() {
            return getInterceptors().size();
        }

        /**
         * {@code getInterceptors()} 登记的是 {@code MappedInterceptor}（薄包装：带 include/exclude 模式）
         * ⇒ 读它的 {@code getInterceptor()} 拿回拦截器本体（只读，不改变注册）。
         */
        java.util.List<Object> registeredInterceptors() {
            java.util.List<Object> interceptors = new java.util.ArrayList<>();
            for (Object item : getInterceptors()) {
                if (item instanceof org.springframework.web.servlet.handler.MappedInterceptor mapped) {
                    interceptors.add(mapped.getInterceptor());
                } else {
                    interceptors.add(item);
                }
            }
            return interceptors;
        }
    }

    /** 无权限身份的便捷入口（权限表返回空）。 */
    private MockMvc mockMvcForDeny() {
        return login("emp-no-perm");
    }
}
