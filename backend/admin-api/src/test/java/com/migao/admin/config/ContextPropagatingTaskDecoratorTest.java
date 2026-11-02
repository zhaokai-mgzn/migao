// case_ids: PR-007, PR-010
package com.migao.admin.config;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 后台批次线程的上下文传播判据（issue #8283）。
 *
 * <p>红证：把 {@link ContextPropagatingTaskDecorator#decorate} 的 tenant / security 捕获删掉，
 * 第一条测试的 tenant/user 读数为 null；把 finally 的「恢复」改成「清空」，第二条测试的
 * 提交线程上下文被抹掉 ⇒ 两者都会红。</p>
 */
@DisplayName("ContextPropagatingTaskDecorator —— tenant / user 上下文跨线程")
class ContextPropagatingTaskDecoratorTest {

    @AfterEach
    void tearDown() {
        TenantContext.clear();
        SecurityContextHolder.clearContext();
    }

    @Test
    @DisplayName("tenant + user 上下文跨线程传播")
    void propagatesTenantAndSecurityContext() throws Exception {
        TenantContext.setTenantId(1001L);
        SecurityContext security = SecurityContextHolder.createEmptyContext();
        security.setAuthentication(new UsernamePasswordAuthenticationToken(
                "user-0001", "n/a", List.of(new SimpleGrantedAuthority("ROLE_ADMIN"))));
        SecurityContextHolder.setContext(security);

        AtomicReference<Long> tenant = new AtomicReference<>();
        AtomicReference<String> user = new AtomicReference<>();
        CountDownLatch done = new CountDownLatch(1);
        Runnable decorated = new ContextPropagatingTaskDecorator().decorate(() -> {
            tenant.set(TenantContext.getTenantId());
            var auth = SecurityContextHolder.getContext().getAuthentication();
            user.set(auth == null ? null : auth.getName());
            done.countDown();
        });

        Thread worker = new Thread(decorated, "batch-decorator-test");
        worker.start();

        assertThat(done.await(5, TimeUnit.SECONDS)).as("工作线程必须跑到").isTrue();
        assertThat(tenant.get()).as("租户上下文必须带过去（否则拦截器直接 500）").isEqualTo(1001L);
        assertThat(user.get()).as("操作人必须带过去（否则 edited_by / 审计变成 system）")
                .isEqualTo("user-0001");
    }

    @Test
    @DisplayName("CallerRuns 内联执行：结束后恢复提交线程原有上下文，不是清空")
    void restoresPreviousContextWhenRunInline() {
        TenantContext.setTenantId(2002L);
        SecurityContext previous = SecurityContextHolder.createEmptyContext();
        previous.setAuthentication(new UsernamePasswordAuthenticationToken(
                "inline-user", "n/a", List.of(new SimpleGrantedAuthority("ROLE_ADMIN"))));
        SecurityContextHolder.setContext(previous);

        // 在同一个线程上 decorate + run：模拟线程池饱和时 CallerRunsPolicy 的内联执行
        new ContextPropagatingTaskDecorator().decorate(() -> {
            assertThat(TenantContext.getTenantId()).isEqualTo(2002L);
            assertThat(SecurityContextHolder.getContext().getAuthentication().getName())
                    .isEqualTo("inline-user");
        }).run();

        assertThat(TenantContext.getTenantId()).as("内联执行不得把请求自己的 tenant 清掉")
                .isEqualTo(2002L);
        assertThat(SecurityContextHolder.getContext().getAuthentication().getName())
                .as("内联执行不得把请求自己的认证清掉").isEqualTo("inline-user");
    }
}
