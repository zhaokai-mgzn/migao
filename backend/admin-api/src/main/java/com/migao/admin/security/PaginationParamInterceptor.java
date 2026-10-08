package com.migao.admin.security;

import com.migao.admin.validation.PaginationParamGate;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.servlet.HandlerInterceptor;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

/**
 * 分页入参闸（issue #6222）：把 {@code page} / {@code size} 的**准入**放在**一个**地方。
 *
 * <p>注册点 = {@link com.migao.admin.config.WebConfig}（{@code /api/**}），**排在**
 * {@link PermissionInterceptor} / {@link TenantOwnershipInterceptor} **之后** ⇒ 沿用 F3（#6063）
 * 与 #6158 的同一条次序纪律：**授权 / 归属判定先于参数判定**（无权限的非法分页请求先拿 403/404，
 * 不因新增这道闸而变 400）。注册顺序即执行顺序（{@code InterceptorRegistry} 按添加序）。</p>
 *
 * <p>为何放在 {@code preHandle}：它在**参数解析之前**，所以连「控制器根本不认识这个参数」的
 * 请求也判得了（例如 {@code POST /api/admin/orders?size=-5}）—— 而任何控制器级/DTO 级写法
 * 都只能覆盖「自己认领的那个参数」。这是本单能做到**单点准入**的关键（详见
 * {@link PaginationParamGate} 的「为什么是一个地方」）。</p>
 *
 * <p>判据实现是纯函数，本类只做取参 + 委派 + 日志，不复制任何阈值。</p>
 */
@Slf4j
@Component
public class PaginationParamInterceptor implements HandlerInterceptor {

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        // 只裁真控制器方法（静态资源 / 错误页 / 非 MVC handler 一律放行）
        if (!(handler instanceof HandlerMethod)) {
            return true;
        }
        try {
            PaginationParamGate.requireValid(request.getParameterMap());
        } catch (RuntimeException rejected) {
            log.warn("分页入参非法 ⇒ 拒绝（issue #6222）: {} {}?{}",
                    request.getMethod(), request.getRequestURI(), request.getQueryString());
            throw rejected;
        }
        return true;
    }
}
