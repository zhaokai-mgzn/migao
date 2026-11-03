package com.migao.admin.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * 把「一个请求一个追踪 id」钉在 Servlet 链的**最前面**（issue #6957）。
 *
 * <p>顺序 = {@link Ordered#HIGHEST_PRECEDENCE} ⇒ 排在 Spring Security 过滤器链（默认 order = -100）
 * **之前**。这一点是必需的：{@code SecurityConfig} 的 {@code authenticationEntryPoint} 与
 * {@code PasswordChangeRequiredFilter} 等**在 MVC 之外**就写响应体的出口，也要能拿到同一个 id。</p>
 *
 * <p>三件事，缺一不可（判据 = {@code RequestIdTraceabilityTest}）：</p>
 * <ol>
 *   <li>取 id（{@link RequestId#acceptOrGenerate}：合法的 {@code X-Request-Id} 复用，否则新生成）；</li>
 *   <li>绑到请求属性 + MDC（日志模式 {@code %X{requestId:-}} 立刻生效，**同请求的每一行日志**都可 grep）；</li>
 *   <li>回写响应头 {@code X-Request-Id}（前端/客服据此与服务端日志对账）。</li>
 * </ol>
 *
 * <p>错误分派（ERROR dispatch）不再经过本过滤器（{@code OncePerRequestFilter} 默认跳过），
 * 但请求属性还在 ⇒ {@link RequestId#current()} 仍返回同一个 id。</p>
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class RequestIdFilter extends OncePerRequestFilter {

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        String requestId = RequestId.acceptOrGenerate(request.getHeader(RequestId.HEADER));
        RequestId.bind(requestId, request);
        response.setHeader(RequestId.HEADER, requestId);
        try {
            filterChain.doFilter(request, response);
        } finally {
            RequestId.unbind();
        }
    }
}
