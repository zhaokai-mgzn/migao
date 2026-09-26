package com.migao.admin.security;

import com.migao.admin.exception.BusinessException;
import com.migao.admin.exception.PermissionDeniedException;
import com.migao.admin.service.RoleService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.util.Collection;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * 权限拦截器
 * 使用 AOP 拦截带 @RequirePermission 注解的方法
 * 检查当前用户是否拥有所需权限
 */
@Slf4j
@Aspect
@Component
@RequiredArgsConstructor
public class PermissionInterceptor {

    private final RoleService roleService;

    /**
     * 越权授予的可行动建议（与 {@link PermissionDeniedResponse} 同口径：说清「不是参数问题」+
     * 「不要重试」+ 给出出口）。
     */
    private static final String ESCALATION_SUGGESTION =
            "这是授权面限制，不是参数或数据问题：不要重复提交同一请求。"
                    + "员工管理只能勾选操作者本人已持有的权限码；若确实需要该权限码，"
                    + "请先由更高权限的管理员在「岗位权限」中给操作者本人授予，再由其授予他人。";

    /**
     * 拦截所有带有 @RequirePermission 注解的方法（支持方法级与类级注解）
     *
     * <p>注意：不能使用 {@code @annotation(x) || @within(x)} 绑定参数（AspectJ 的 OR 分支
     * 只从命中的第一个分支绑定，类级命中时参数为 null），改为在切面内手动解析注解：
     * 优先取方法级注解，其次取类级注解。</p>
     *
     * @param joinPoint 连接点
     * @return 方法执行结果
     * @throws Throwable 异常
     */
    @Around("@annotation(com.migao.admin.security.RequirePermission)"
            + " || @within(com.migao.admin.security.RequirePermission)")
    public Object intercept(ProceedingJoinPoint joinPoint) throws Throwable {
        RequirePermission requirePermission = resolveRequirePermission(joinPoint);
        if (requirePermission == null) {
            log.warn("权限检查失败：无法解析 @RequirePermission 注解");
            throw new AccessDeniedException("权限配置异常，请联系管理员");
        }
        return doIntercept(joinPoint, requirePermission);
    }

    /**
     * 解析方法上的 @RequirePermission：优先方法级注解，其次类级注解。
     */
    private RequirePermission resolveRequirePermission(ProceedingJoinPoint joinPoint) {
        if (joinPoint.getSignature() instanceof org.aspectj.lang.reflect.MethodSignature methodSignature) {
            RequirePermission methodAnn = methodSignature.getMethod().getAnnotation(RequirePermission.class);
            if (methodAnn != null) {
                return methodAnn;
            }
        }
        Object target = joinPoint.getTarget();
        if (target != null) {
            RequirePermission classAnn = target.getClass().getAnnotation(RequirePermission.class);
            if (classAnn != null) {
                return classAnn;
            }
        }
        return null;
    }

    Object doIntercept(ProceedingJoinPoint joinPoint, RequirePermission requirePermission) throws Throwable {
        requirePermission(requirePermission.value());

        // 执行目标方法
        return joinPoint.proceed();
    }

    /**
     * 命令式权限断言（issue #4148）：判定语义与 AOP 拦截**逐条相同**（未认证 ⇒ 拒绝 /
     * 平台管理员与内部服务旁路 / `*` 通配 / `RoleService.getUserPermissions` 细粒度查询），
     * 拒绝时抛 {@link PermissionDeniedException}（带结构化权限码，由 GlobalExceptionHandler
     * 生成 403 + 缺失码 + 可执行 suggestion）。
     *
     * <p>为什么需要它：{@code @RequirePermission} 只能声明**端点级**的静态权限码，而
     * {@code PATCH /api/admin/agent/orders/{id}} 一个入口按请求体的 {@code action} 覆盖
     * status/logistics/payment/cancel/**refund** —— 退款是财务动作（表单路径
     * {@code OrderController} 用的是 {@code order:refund}），只有到了 action 维度才判得出来。
     * 控制器调用本方法复用**同一份**判定，而不是在自己的类里再写一段查权限：那是第二份授权实现，
     * 必然与 AOP 口径漂移（旁路角色/通配/取码来源任一处不一致就会放出越权或误拒）。</p>
     *
     * @param requiredPermission 需要的权限码（如 {@code order:refund}）
     */
    public void requirePermission(String requiredPermission) {
        // 获取当前用户认证信息
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !authentication.isAuthenticated()) {
            log.warn("权限检查失败：用户未认证");
            throw new AccessDeniedException("用户未认证");
        }

        // 平台管理员（super_admin）与内部服务（service）拥有全部权限，直接放行。
        // super_admin 用户不在 users 表（platform_admins），getUserPermissions 会返回空集；
        // service 为内部服务身份（internal-service），同样不适用租户权限查询。
        if (hasBypassRole(authentication)) {
            log.debug("权限检查跳过：用户为平台管理员或内部服务，权限 {}", requiredPermission);
            return;
        }

        // 获取当前用户ID
        String userId = extractUserId(authentication);
        if (userId == null) {
            log.warn("权限检查失败：无法获取用户ID");
            throw new AccessDeniedException("无法获取用户信息");
        }

        // 获取用户所有权限
        List<String> userPermissions = roleService.getUserPermissions(userId);

        // 检查是否拥有所需权限
        // admin 角色拥有所有权限（用 "*" 表示）
        boolean hasPermission = userPermissions.contains("*") || userPermissions.contains(requiredPermission);

        if (!hasPermission) {
            log.warn("权限检查失败：用户 {} 缺少权限 {}", userId, requiredPermission);
            // 权限码作为结构化字段随异常传递（issue #4105 F1），下游不再解析 message
            throw new PermissionDeniedException(
                    "权限不足，需要权限: " + requiredPermission, requiredPermission);
        }

        log.debug("权限检查通过：用户 {} 拥有权限 {}", userId, requiredPermission);
    }

    /**
     * 命令式「授权面 ⊆ 操作者」断言（issue #4104，用户 2026-09-26 裁定：
     * **授予的权限码必须 ⊆ 操作者自身权限**）。
     *
     * <p>为什么需要它：{@code @RequirePermission} 只能声明「调用本端点需要哪个码」，
     * 表达不了「写进去的码必须 ⊆ 操作者自己的码」。「谁能调用」与「谁能授予」是**同一份身份口径**
     * 的两侧，故复用本类既有的解析（未认证 / 旁路角色 / 取码来源 {@link RoleService}），
     * 不另写第二份授权实现 —— 两份判定必然漂移（issue #4148 的既有口径）。</p>
     *
     * <p><b>三态处置</b>（与 {@link #requirePermission(String)} 的身份口径逐条一致）：</p>
     * <ol>
     *   <li><b>旁路身份</b>（平台管理员 {@code super_admin} / 内部服务 {@code service}）⇒ 放行：
     *       它们本身就是全权限，不存在「超出自身」这一说；</li>
     *   <li><b>无操作者</b>（无认证 / 匿名主体）：唯一合法调用方是公开注册引导
     *       （{@code RegistrationService} 建新租户的首个管理员，不经 {@code /api/admin/**} 门禁）
     *       —— 该路径下不存在「操作者」这一方，⊆ 判定无从谈起。既有的「保留角色 / 通配码」
     *       拦截不依赖本方法，照旧生效；</li>
     *   <li><b>商户员工</b> ⇒ 强制 {@code 授予集 ⊆ 自身生效权限}；自身权限解析不出来（空集）
     *       ⇒ <b>拒绝</b>（fail-closed：判不出来就不放行；查询异常一律上抛，不吞成「放行」）。</li>
     * </ol>
     *
     * <p><b>授予集</b> = 显式写入的权限码快照 ∪ <b>所授角色隐含的生效码</b>
     * （{@code role=admin} ⇒ {@code *}）—— 只看快照数组会被「授予一个比自己权限更大的角色」绕过。
     * 角色码 → 码按**目标租户**解析（不跨租户查 ⇒ 不泄露他租户的角色/权限是否存在）。</p>
     *
     * <p><b>拒绝形态</b>：403 + 独立错误码 {@code PERMISSION_ESCALATION_DENIED}，
     * 消息**点名**违规码 —— 只回显请求里出现过的码，不回答「该码在目录里存不存在」
     * （目录是全租户共享的，回答它等于给出跨租户信息）。</p>
     *
     * @param roleCode     即将写入的角色码（null / 空 = 不改角色）
     * @param grantedCodes 即将写入的权限码快照（可为 null / 空）
     * @param tenantId     目标租户 ID（角色码按该租户解析；null ⇒ 只按快照判，角色回退走内置映射）
     */
    public void assertGrantable(String roleCode, Collection<String> grantedCodes, Long tenantId) {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !authentication.isAuthenticated() || hasBypassRole(authentication)) {
            return;  // ① 旁路身份 / ② 无认证
        }
        String actorId = extractUserId(authentication);
        if (actorId == null) {
            return;  // ② 匿名主体（AnonymousAuthenticationToken.isAuthenticated() == true，principal 不是员工）
        }

        // ③ 商户员工：先取自身生效权限（查询异常不吞 ⇒ 上抛 = fail-closed）
        List<String> ownPermissions = roleService.getUserPermissions(actorId);
        Set<String> own = ownPermissions == null ? Set.of() : new HashSet<>(ownPermissions);
        if (own.contains("*")) {
            return;  // 全权限岗位（admin）/ 显式授予 * ：无需再比
        }

        Set<String> fromRole = new LinkedHashSet<>();
        Set<String> granting = new LinkedHashSet<>();
        if (grantedCodes != null) {
            for (String code : grantedCodes) {
                if (StringUtils.hasText(code)) {
                    granting.add(code);
                }
            }
        }
        if (StringUtils.hasText(roleCode)) {
            fromRole.addAll(roleService.getEffectivePermissionCodesForRoleCode(roleCode, tenantId));
            granting.addAll(fromRole);
        }
        if (granting.isEmpty()) {
            return;  // 没有授予任何码（如仅改昵称 / 手机号 / 岗位）
        }

        List<String> over = granting.stream().filter(code -> !own.contains(code)).sorted().toList();
        if (!over.isEmpty()) {
            List<String> overFromRole = fromRole.stream().filter(code -> !own.contains(code)).sorted().toList();
            log.warn("越权授予被拒：操作者 {} 不具备权限码 {}（角色码={}）", actorId, over, roleCode);
            throw BusinessException.permissionEscalationDenied(
                    escalationMessage(over, overFromRole, roleCode), ESCALATION_SUGGESTION);
        }
        log.debug("可授予性检查通过：操作者 {} 授予 {} 均在其自身权限内", actorId, granting);
    }

    /** 越权授予的拒绝措辞：点名违规码（不回答「目录里有没有这个码」，避免泄露跨租户信息）。 */
    private static String escalationMessage(List<String> over, List<String> overFromRole, String roleCode) {
        StringBuilder message = new StringBuilder("不能授予自己不具备的权限码: ").append(String.join("、", over));
        if (!overFromRole.isEmpty()) {
            message.append("（其中 ").append(String.join("、", overFromRole))
                    .append(" 来自角色 ").append(roleCode).append(" 的隐含权限）");
        }
        return message.toString();
    }

    /**
     * 判断当前认证是否为平台管理员（super_admin）或内部服务（service），
     * 二者拥有全部权限，跳过细粒度权限查询。
     */
    private boolean hasBypassRole(Authentication authentication) {
        if (authentication.getAuthorities() == null) {
            return false;
        }
        for (GrantedAuthority authority : authentication.getAuthorities()) {
            String name = authority.getAuthority();
            if (name == null) {
                continue;
            }
            String role = name.startsWith("ROLE_") ? name.substring(5) : name;
            role = role.toLowerCase(Locale.ROOT);
            if ("super_admin".equals(role) || "service".equals(role)) {
                return true;
            }
        }
        return false;
    }

    /**
     * 从认证信息中提取用户ID
     *
     * @param authentication 认证信息
     * @return 用户ID
     */
    private String extractUserId(Authentication authentication) {
        Object principal = authentication.getPrincipal();
        if (principal instanceof SecurityUser securityUser) {
            return securityUser.getUserId();
        }
        if (principal instanceof org.springframework.security.core.userdetails.User userDetails) {
            return userDetails.getUsername();
        }
        return null;
    }
}
