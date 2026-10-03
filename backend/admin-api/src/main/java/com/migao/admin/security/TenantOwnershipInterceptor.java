package com.migao.admin.security;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.annotation.AnnotationUtils;
import org.springframework.stereotype.Component;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.servlet.HandlerInterceptor;
import org.springframework.web.servlet.HandlerMapping;

import java.util.Map;

/**
 * 租户域**写端点**的归属认定拦截器（issue #6158）—— 把认定提前到**参数解析之前**。
 *
 * <h3>它治的是什么（次序，不是权限）</h3>
 * <p>{@code @Valid} 请求体校验与请求体反序列化都发生在 MVC 的**参数解析阶段**，早于控制器方法体。
 * 于是跨租户 + 非法载荷写会先拿到 <b>422 / 400</b>（「参数错误」），而跨租户 + 合法载荷才拿到
 * <b>404</b> ⇒ 安全审计把越权尝试记成参数错误，掩盖真实攻击面（{@code acceptance/2026-10-03/
 * tenant-isolation-sweep/REPORT.md} §F-1）。</p>
 *
 * <p>本拦截器在 {@code preHandle}（MVC 分发阶段，**早于**参数解析）按
 * {@link TenantOwnedResource} 的键做归属认定：认定不过 ⇒ 404，参数解析不再发生。
 * 这与 {@link PermissionInterceptor} 的 F3（issue #6063：403 必须先于 400/422）是**同一条次序纪律**
 * 的第二个实例 —— 那条治「授权」，本条治「归属」。</p>
 *
 * <h3>它不做什么</h3>
 * <ul>
 *   <li><b>不</b>替代 {@code @Valid}：跨过认定之后校验照旧执行（同租户 + 非法载荷仍 422 + 逐字段）。</li>
 *   <li><b>不</b>新造越权判定：认定 = 该资源写路径本来就会执行的那条带租户过滤的查询
 *       （见 {@link TenantResourceOwnership}）。</li>
 * </ul>
 */
@Slf4j
@Component
public class TenantOwnershipInterceptor implements HandlerInterceptor {

    /**
     * 归属认定表（**字段注入**，不是构造参数）。
     *
     * <p>理由同 {@code OrderService.poolChangeNotifier} 的先例：{@code WebConfig} 的构造签名
     * 被既有判据显式装配（{@code PermissionPreHandleGateTest}），加一个构造参数会波及那些
     * 与「归属认定」无关的既有测试 —— 而本注解**不会**改变它们的语义。</p>
     */
    @Autowired
    private TenantResourceOwnership ownership;

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        if (!(handler instanceof HandlerMethod handlerMethod)) {
            return true;
        }
        TenantOwnedResource annotation =
                AnnotationUtils.findAnnotation(handlerMethod.getMethod(), TenantOwnedResource.class);
        if (annotation == null) {
            return true;
        }

        String resource = annotation.value();
        String id = pathVariableId(request);
        if (id == null) {
            // 标注了本注解却拿不到 {id} ⇒ 标注与路由不匹配（写错了）。fail-closed 报错，
            // 不静默放行 —— 静默放行会让这条端点在无人察觉的情况下退回旧缺陷。
            throw new IllegalStateException(
                    "端点标注了 @TenantOwnedResource(\"" + resource + "\") 但路由里没有 {id} 路径变量: "
                            + handlerMethod.getShortLogMessage());
        }

        log.debug("归属认定（先于载荷校验）: resource={}, id={}, tenantId={}",
                resource, id, com.migao.admin.config.TenantContext.getTenantId());
        ownership.check(resource, id);
        return true;
    }

    /** 取 {@code {id}} 路径变量（本仓控制器用 {@code @PathVariable String id}）。 */
    private static String pathVariableId(HttpServletRequest request) {
        Object vars = request.getAttribute(HandlerMapping.URI_TEMPLATE_VARIABLES_ATTRIBUTE);
        if (vars instanceof Map<?, ?> map) {
            Object id = map.get("id");
            return id == null ? null : id.toString();
        }
        return null;
    }
}
