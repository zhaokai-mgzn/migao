package com.migao.admin.security;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletRequestWrapper;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.net.URI;
import java.net.URISyntaxException;
import java.util.Collections;
import java.util.Enumeration;
import java.util.List;
import java.util.Locale;

/**
 * 摘掉**同源请求**自带的 {@code Origin}（issue #5721）。
 *
 * <h3>为什么必须有它（2026-09-27 线上实测）</h3>
 * 浏览器对**非 GET** 请求一律带 {@code Origin} —— 即便是同源请求。而本服务跑在 nginx 之后，
 * 容器内看到的是 {@code http://<host>:8080}，Spring 的
 * {@code org.springframework.web.cors.CorsUtils#isCorsRequest} 用的正是**容器本地视角**，
 * 于是「app.migaozn.com 的页面 → app.migaozn.com 的 /api」被判成**跨域**，再拿
 * {@code CORS_ALLOWED_ORIGINS}（实例上的值不含 app.migaozn.com）一比就 403：
 *
 * <pre>
 *   POST /api/auth/sms/login  + Origin: https://app.migaozn.com  → 403 Invalid CORS request
 *   同一请求、同一 body，不带 Origin                              → 200
 *   （工人端 /w/ 的报工 POST 同款：带 ⇒ 403，不带 ⇒ 422 校验错）
 * </pre>
 *
 * 前端只看到 {@code Load failed}（Safari）/ {@code Failed to fetch}（Chrome）这种**网络层**文案，
 * 而服务端日志里一条记录都没有（请求根本没进控制器）⇒ 极易被误判成「后端挂了」。
 *
 * <h3>为什么不能在 CorsConfiguration 里修</h3>
 * 误判发生在**判定是不是 CORS** 这一步，早于任何白名单；把 app.migaozn.com 加进
 * {@code CORS_ALLOWED_ORIGINS} 只能算兜底（那是实例级环境变量，仓库里改不到；且每加一个新落地面
 * 都要记着改一处运维配置）。这里按**浏览器同源口径**（scheme + host + port 逐项比）判定同源，
 * 同源 ⇒ {@code Origin} 对后端没有信息量，摘掉即可；真正的跨域调用（admin-web）原样保留。
 *
 * <h3>边界（照实登记）</h3>
 * <ul>
 *   <li>外部视角取自 nginx 注入的 {@code X-Forwarded-Proto/Host/Port}；**没有这些头就是直连**，
 *       此时退回容器本地视角 ⇒ 本地开发（页面 :3001 → 接口 :8080）仍是真跨域，CORS 照旧生效
 *       （摘掉它会让本地 admin-web 拿不到 ACAO 而全挂 —— 判据里专门钉了这一条）。</li>
 *   <li>本类只管「同源不该被当成跨域」；跨域白名单的语义**一字未动**。</li>
 *   <li>更彻底的做法是让应用知道自己被反向代理（{@code server.forward-headers-strategy}），
 *       那会改动全应用的 scheme/host/port 取值面，**不在本单范围**（登记为未固化项）。</li>
 * </ul>
 *
 * <h3>为什么是 Servlet 级（而不是挂进 Security 过滤链）</h3>
 * 要拦的是 Spring Security 链**内部**的 {@code CorsFilter}，所以必须排在整条链之前：
 * {@code @Order(HIGHEST_PRECEDENCE)} 让 Boot 把本 bean 注册成最外层 Servlet Filter
 * （Security 链的 order 是 -100）⇒ 不需要进 {@code SecurityConfig} 的构造参数、也不改任何
 * 既有过滤链顺序（同族先例：{@code WorkerSessionFilter} 那批是**链内**过滤器，故走
 * {@code FilterRegistrationBean.setEnabled(false)} 禁掉自动注册；本类相反，**要**自动注册）。
 */
@Slf4j
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class SameOriginOriginHeaderFilter extends OncePerRequestFilter {

    static final String X_FORWARDED_PROTO = "X-Forwarded-Proto";
    static final String X_FORWARDED_HOST = "X-Forwarded-Host";
    static final String X_FORWARDED_PORT = "X-Forwarded-Port";

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        String origin = request.getHeader(HttpHeaders.ORIGIN);
        if (origin == null || origin.isBlank() || !isSameOrigin(origin, request)) {
            filterChain.doFilter(request, response);
            return;
        }
        log.debug("同源请求的 Origin 已摘除（防被 CORS 误判）: {} {}", request.getMethod(), origin);
        filterChain.doFilter(new OriginStrippedRequest(request), response);
    }

    /**
     * 浏览器口径的同源判定：{@code scheme + host + port} 逐项比，port 按 scheme 默认值归一
     * （{@code https://a.com} 与 {@code https://a.com:443} 视为同一个源）。
     */
    static boolean isSameOrigin(String origin, HttpServletRequest request) {
        URI uri;
        try {
            uri = new URI(origin);
        } catch (URISyntaxException e) {
            return false;
        }
        String scheme = uri.getScheme();
        String host = uri.getHost();
        if (scheme == null || host == null) {
            // `Origin: null`（沙箱 iframe / file://）等形态：不是同源，交回原有 CORS 判定
            return false;
        }
        int port = uri.getPort() == -1 ? defaultPort(scheme) : uri.getPort();

        String externalScheme = headerOr(request, X_FORWARDED_PROTO, request.getScheme());
        String externalHost = headerOr(request, X_FORWARDED_HOST, request.getServerName());
        int externalPort = externalPort(request, externalScheme);

        return externalScheme.equalsIgnoreCase(scheme)
                && externalHost.equalsIgnoreCase(host)
                && externalPort == port;
    }

    /**
     * 请求在本服务**外部**的端口。
     *
     * <p>代理在场（有 {@code X-Forwarded-Proto}）而没给 {@code X-Forwarded-Port} 时，按该 scheme
     * 的默认端口算 —— 终止 TLS 的那一层（nginx）只监听 80/443，这是唯一自洽的取值；
     * 直连时（无任何 forwarded 头）用容器本地端口，本地开发的跨端口形态才能保持跨域语义。</p>
     */
    private static int externalPort(HttpServletRequest request, String externalScheme) {
        String forwardedPort = request.getHeader(X_FORWARDED_PORT);
        if (forwardedPort != null && !forwardedPort.isBlank()) {
            // 多级代理会给出逗号列表，取第一个
            String first = forwardedPort.split(",")[0].trim();
            try {
                return Integer.parseInt(first);
            } catch (NumberFormatException e) {
                log.warn("X-Forwarded-Port 不是数字（{}），退回按 scheme 默认端口判定", first);
            }
        }
        String forwardedProto = request.getHeader(X_FORWARDED_PROTO);
        if (forwardedProto != null && !forwardedProto.isBlank()) {
            return defaultPort(externalScheme);
        }
        return request.getServerPort();
    }

    private static int defaultPort(String scheme) {
        return "https".equalsIgnoreCase(scheme) ? 443 : 80;
    }

    private static String headerOr(HttpServletRequest request, String name, String fallback) {
        String value = request.getHeader(name);
        if (value == null || value.isBlank()) {
            return fallback;
        }
        return value.split(",")[0].trim().toLowerCase(Locale.ROOT);
    }

    /** 把 {@code Origin} 从请求里摘掉（含 {@code getHeaderNames()}，免得下游按名字遍历时又看见它）。 */
    private static final class OriginStrippedRequest extends HttpServletRequestWrapper {

        OriginStrippedRequest(HttpServletRequest request) {
            super(request);
        }

        @Override
        public String getHeader(String name) {
            return isOrigin(name) ? null : super.getHeader(name);
        }

        @Override
        public Enumeration<String> getHeaders(String name) {
            return isOrigin(name) ? Collections.emptyEnumeration() : super.getHeaders(name);
        }

        @Override
        public Enumeration<String> getHeaderNames() {
            List<String> names = Collections.list(super.getHeaderNames());
            names.removeIf(SameOriginOriginHeaderFilter.OriginStrippedRequest::isOrigin);
            return Collections.enumeration(names);
        }

        private static boolean isOrigin(String name) {
            return name != null && HttpHeaders.ORIGIN.equalsIgnoreCase(name);
        }
    }
}
