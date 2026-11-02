// case_ids: PR-007, PR-010
package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 批次 job 线程池的装配判据（issue #8283）。
 *
 * <p>红证：把构造函数里的 {@code setTaskDecorator} 删掉 ⇒ 第一条的 tenant/user 读数为 null；
 * 把 {@code AbortPolicy} + catch 改成静默丢弃 ⇒ 第二条的 {@code ran} 为 false。</p>
 */
@DisplayName("ThreadPoolBatchJobLauncher —— 上下文传播 + 停机退化")
class ThreadPoolBatchJobLauncherTest {

    @AfterEach
    void tearDown() {
        TenantContext.clear();
        SecurityContextHolder.clearContext();
    }

    @Test
    @DisplayName("launch 在 worker 上跑，并带上 tenant/user 上下文")
    void launchPropagatesContext() throws Exception {
        TenantContext.setTenantId(1001L);
        SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken(
                "user-0001", "n/a", List.of(new SimpleGrantedAuthority("ROLE_ADMIN"))));
        ThreadPoolBatchJobLauncher launcher = new ThreadPoolBatchJobLauncher();
        AtomicReference<Long> tenant = new AtomicReference<>();
        AtomicReference<String> user = new AtomicReference<>();
        CountDownLatch done = new CountDownLatch(1);
        try {
            launcher.launch(() -> {
                tenant.set(TenantContext.getTenantId());
                var auth = SecurityContextHolder.getContext().getAuthentication();
                user.set(auth == null ? null : auth.getName());
                done.countDown();
            });
            assertThat(done.await(5, TimeUnit.SECONDS)).as("worker 必须跑到").isTrue();
        } finally {
            launcher.shutdown();
        }

        assertThat(tenant.get()).as("租户上下文必须带过去（否则拦截器 500）").isEqualTo(1001L);
        assertThat(user.get()).as("操作人必须带过去（否则 edited_by / 审计变成 system）")
                .isEqualTo("user-0001");
    }

    @Test
    @DisplayName("停机后 launch 退化为同步执行，不丢任务")
    void launchAfterShutdownRunsInline() {
        ThreadPoolBatchJobLauncher launcher = new ThreadPoolBatchJobLauncher();
        launcher.shutdown();

        AtomicBoolean ran = new AtomicBoolean(false);
        launcher.launch(() -> ran.set(true));

        assertThat(ran).as("停机窗口的 job 必须退化执行，不得静默丢弃").isTrue();
    }
}
