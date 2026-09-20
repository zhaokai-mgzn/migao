package com.migao.admin.security;

import com.migao.admin.config.TenantContext;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerSessionService;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.authentication.WebAuthenticationDetailsSource;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.List;

/**
 * 工人登录态过滤器（issue #4733）。
 *
 * <p>把 {@code X-Worker-Session-Id} 解析成 SecurityContext 里的
 * {@code ROLE_WORKER} 认证（{@code principal} = 工人 id，{@code credentials} = session id）。</p>
 *
 * <p><b>为什么需要它</b>：工人 session 不是 JWT ⇒ {@code /api/worker/**} 若配
 * {@code .authenticated()} 会被 {@link JwtAuthenticationFilter} 之后的授权规则判 401，
 * 而配 {@code permitAll} 又会让「无 session 也能进」变成一条只靠控制器自觉的软约束。
 * 过滤器把「有没有效工人身份」变成**过滤链层**的判据，授权规则才能写 {@code authenticated()}
 * （fail-closed：无效/已结束/已闲置超时 ⇒ 不设认证 ⇒ 401）。</p>
 *
 * <p>🔴 <b>绝不给工人商家权限</b>：这里只挂 {@code ROLE_WORKER} 一个 authority，
 * 工人可达面 = {@code /api/worker/**}；{@code /api/admin/**} 的
 * {@code adminApiAuthorizationManager} 把 {@code worker} 放进**拒绝集合**。</p>
 *
 * <p>与 JWT 的优先级：**只在 SecurityContext 尚无认证时**设置 —— 商家（持 JWT）的请求
 * 逐字走既有链路（本过滤器对它是 no-op，不改变任何既有行为）。</p>
 *
 * <p>🔴 <b>issue #4864（工人端除 {@code /login} 外全链路 401）</b>：本过滤器原先**自己**读
 * {@code worker_sessions} 行（{@code workerSessionMapper.selectActiveById}），而该表受租户拦截器管、
 * 租户又要从那一行里取 ⇒ 循环 ⇒ 拦截器抛 {@code Tenant context not initialized} ⇒ catch 吞成
 * 「未认证」⇒ 401。现在：① 会话解析**只有一处**实现（委托
 * {@link WorkerSessionService#resolveIdentityOrNull}，租户在读到行之后才定下来）；
 * ② 认证期异常记 **ERROR + 栈**（不静默）；③ 过滤器链的后续执行移出 catch（旧实现会在下游异常时
 * 把整条链**执行两次**）；④ 租户上下文由本过滤器自己清（不依赖别的过滤器的 finally）。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class WorkerSessionFilter extends OncePerRequestFilter {

    private final WorkerSessionService workerSessionService;

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        String sessionId = request.getHeader(WorkerSessionService.SESSION_HEADER);
        try {
            if (StringUtils.hasText(sessionId)
                    && SecurityContextHolder.getContext().getAuthentication() == null) {
                authenticate(request, sessionId.trim());
            }
        } catch (Exception e) {
            // 🔴 认证期异常**不得静默**（issue #4864）：旧实现是 `log.warn(e.getMessage())`，
            // 把「租户上下文缺失 ⇒ 工人端全链路 401」这种**系统性故障**降级成一条看不出异常类型、
            // 也没有栈的 WARN ⇒ 没人能发现。改为 ERROR + 栈 + 稳定标记（可 grep / 可告警）。
            // 会话 id 是凭据 ⇒ 只记前 8 位，不进日志全文。
            // 处置仍是 fail-closed：清掉可能被部分写入的认证状态 ⇒ 下游按 401 拒绝（不降级为匿名放行）。
            log.error("[工人登录态][filter-error] 会话认证异常，本次请求按未认证拒绝：sessionIdPrefix={}",
                    sessionIdPrefix(sessionId), e);
            SecurityContextHolder.clearContext();
            TenantContext.clear();
        }
        // ⚠️ 过滤器链的后续执行**必须在 catch 之外**：旧实现把 `filterChain.doFilter` 同时写在
        // try 与 catch 里 ⇒ 下游抛异常时整条链被**执行两次**（一次真实处理 + 一次重放）。
        try {
            filterChain.doFilter(request, response);
        } finally {
            // 本过滤器自己设的租户上下文自己清（不再依赖 JwtAuthenticationFilter 的 finally ——
            // 那条隐式耦合正是本缺陷长期无人察觉的同族形态）
            TenantContext.clear();
        }
    }

    /**
     * 会话 ⇒ 认证。
     *
     * <p>🔴 <b>只有一处权威实现</b>（issue #4864）：本方法原先自己抄了一份「读会话行 + 闲置判 +
     * endSession + touch + setTenantContext」，与 {@link WorkerSessionService#resolveIdentityOrNull}
     * 里的同名逻辑**两份并存**（且过滤器那份**没有**把租户先定下来 ⇒ 循环）。现在直接委托服务层 ——
     * 单一出处，两边不可能再漂移。</p>
     */
    private void authenticate(HttpServletRequest request, String sessionId) {
        WorkerIdentity identity = workerSessionService.resolveIdentityOrNull(sessionId);
        if (identity == null) {
            // 无效 / 已结束 / 已闲置超时 / 会话租户与请求租户不一致 ⇒ 不设认证 ⇒ 下游 401
            // （原因已在 WorkerSessionService 留痕，不在此重复打日志）
            return;
        }
        UsernamePasswordAuthenticationToken authentication = new UsernamePasswordAuthenticationToken(
                identity.workerId(), identity.sessionId(),
                List.of(new SimpleGrantedAuthority("ROLE_WORKER"), new SimpleGrantedAuthority("worker")));
        authentication.setDetails(new WebAuthenticationDetailsSource().buildDetails(request));
        SecurityContextHolder.getContext().setAuthentication(authentication);
    }

    /** 会话 id 的日志前缀（凭据不进日志全文）。 */
    private static String sessionIdPrefix(String sessionId) {
        if (!StringUtils.hasText(sessionId)) {
            return "(none)";
        }
        String trimmed = sessionId.trim();
        return trimmed.length() <= 8 ? trimmed : trimmed.substring(0, 8);
    }

    /**
     * 与 JwtAuthenticationFilter 同款：请求完成后清租户上下文，防线程复用串租户。
     */
    @Override
    protected void doFilterNestedErrorDispatch(HttpServletRequest request, HttpServletResponse response,
                                               FilterChain filterChain) throws ServletException, IOException {
        try {
            filterChain.doFilter(request, response);
        } finally {
            TenantContext.clear();
        }
    }
}
