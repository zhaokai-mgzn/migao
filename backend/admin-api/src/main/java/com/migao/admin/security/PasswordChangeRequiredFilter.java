package com.migao.admin.security;

import com.migao.admin.config.TenantContext;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.Set;

/**
 * 首登强制改密拦截器（issue #5485 不变式 I4）。
 *
 * <p><b>为什么是独立过滤器而不是业务层校验</b>：强制改密是**会话级**约束 —— 要求「除白名单外
 * 一律 403」而不是「某个接口自己记得判」。放在业务层等于每个新端点都要重复判一次，
 * 漏一个就是绕过面；放在过滤链上则是**默认拒绝**（fail-closed）。</p>
 *
 * <p><b>claim 从哪来</b>：{@link JwtAuthenticationFilter} 在验签后把
 * {@code pwd_change_required} claim 落到请求属性 {@link #PWD_CHANGE_REQUIRED_ATTRIBUTE}
 * （不重复验签、不改 {@code SecurityUser} 的形状）。签发侧（登录 / **刷新**）按数据库当前
 * {@code users.must_change_password} 计算该 claim —— 只在登录时算会被「刷新一次 token」绕过。</p>
 *
 * <p><b>白名单最小化</b>：改密（否则永远出不去）、登出（换账号的自救出口）、
 * 读自己信息（前端靠 {@code GET /api/auth/me} 判断该跳改密页）。</p>
 */
@Slf4j
@Component
public class PasswordChangeRequiredFilter extends OncePerRequestFilter {

    /**
     * 请求属性名：由 {@link JwtAuthenticationFilter} 写入、本过滤器读取。
     *
     * <p>字面量只有这一处（生产者引用本常量，不各写一份）。</p>
     */
    public static final String PWD_CHANGE_REQUIRED_ATTRIBUTE = "migao.auth.pwdChangeRequired";

    /** 403 错误码：客户端据此跳「首登强制改密」页（与既有 UNAUTHORIZED / PERMISSION_DENIED 同族）。 */
    public static final String ERROR_CODE = "PASSWORD_CHANGE_REQUIRED";

    /** 用户可见文案（明确「下一步做什么」）。 */
    public static final String MESSAGE = "首次登录需先修改密码，请调用 POST /api/auth/password/change";

    /**
     * 白名单（最小化，见类 javadoc）。
     *
     * <p>为什么 {@code /api/auth/refresh} 也在里面（**有意为之，不是漏判**）：
     * 刷新签发的**新 access token 的 {@code pwd_change_required} 是按数据库当前值重算的**
     * （见 {@code AuthService.refreshToken}）⇒ 刷新**不会**把标记刷掉，它不是绕过面；
     * 而把它拦在外面有真实代价 —— 员工在改密页停留到 access token 过期时，前端自动刷新拿到 403，
     * 大概率按「未认证」把他登出，用户得重新登录一次（重新登录后仍带标记、仍只能改密）。
     * 红证：{@code ForcePasswordChangeServiceTest} —— 刷新后拿新 token 访问业务 API **仍然 403**。</p>
     */
    private static final Set<String> WHITELIST = Set.of(
            "/api/auth/password/change",
            "/api/auth/logout",
            "/api/auth/me",
            "/api/auth/refresh");

    /** 403 响应体（与 {@code SecurityConfig} 的 entryPoint / accessDeniedHandler 同一信封形状）。 */
    static final String FORBIDDEN_BODY =
            "{\"success\":false,\"error\":{\"code\":\"" + ERROR_CODE + "\",\"message\":\"" + MESSAGE + "\"}}";

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        boolean mustChange = Boolean.TRUE.equals(request.getAttribute(PWD_CHANGE_REQUIRED_ATTRIBUTE));
        if (mustChange && !WHITELIST.contains(request.getRequestURI())) {
            log.warn("强制改密未完成，拒绝访问: uri={}（白名单外一律 403，issue #5485）",
                    request.getRequestURI());
            response.setStatus(HttpServletResponse.SC_FORBIDDEN);
            response.setContentType("application/json;charset=UTF-8");
            response.getWriter().write(FORBIDDEN_BODY);
            return;
        }
        filterChain.doFilter(request, response);
    }
}