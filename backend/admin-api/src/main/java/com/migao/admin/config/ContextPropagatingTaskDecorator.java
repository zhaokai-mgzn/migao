package com.migao.admin.config;

import org.springframework.core.task.TaskDecorator;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.core.context.SecurityContextHolder;

/**
 * 把提交线程的 {@link TenantContext} 与 {@link SecurityContextHolder} 带到线程池工作线程。
 *
 * <p><b>为什么必须有</b>：{@code TenantLineInnerInterceptor} 的 {@code getTenantId()} 在
 * 上下文为 null 时会抛 {@code Tenant context not initialized}；后台批次逐条写走的是既有
 * {@code ProductService.updateProductForAgent}，它还要用 {@code SecurityContext} 取
 * {@code edited_by} / 审计操作人。不传播 ⇒ 后台线程要么 500，要么把操作人写成 {@code system}。</p>
 *
 * <p><b>为什么 finally 是「恢复」而不是「清空」</b>：线程池饱和时 {@code CallerRunsPolicy}
 * 会在**提交线程**里内联执行任务 —— 那时提交线程本身就是请求线程，直接清空会把请求自己的
 * tenant / security 上下文抹掉。恢复「执行前的值」对工作线程等价于清空，对提交线程则是无操作。</p>
 */
public class ContextPropagatingTaskDecorator implements TaskDecorator {

    @Override
    public Runnable decorate(Runnable runnable) {
        Long tenantId = TenantContext.getTenantId();
        SecurityContext securityContext = SecurityContextHolder.getContext();
        return () -> {
            Long previousTenant = TenantContext.getTenantId();
            SecurityContext previousSecurity = SecurityContextHolder.getContext();
            try {
                if (tenantId != null) {
                    TenantContext.setTenantId(tenantId);
                } else {
                    TenantContext.clear();
                }
                SecurityContextHolder.setContext(securityContext);
                runnable.run();
            } finally {
                if (previousTenant != null) {
                    TenantContext.setTenantId(previousTenant);
                } else {
                    TenantContext.clear();
                }
                SecurityContextHolder.setContext(previousSecurity);
            }
        };
    }
}
