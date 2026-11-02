// case_ids: PR-007, PR-010
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.concurrent.Executor;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 批次 job 提交口的**类级元守卫**（issue #8283）。
 *
 * <p>为什么必须有：Spring Boot 的 {@code TaskExecutionAutoConfiguration} 以
 * {@code @ConditionalOnMissingBean(Executor.class)} 提供 {@code applicationTaskExecutor}；
 * 一旦本接口继承/实现 {@code Executor} 或被注册成 {@code TaskExecutor} bean，既有的
 * {@code @Async}（审计日志 / 知识提炼）会静默改用批次的池。本判据把这条设计钉死。</p>
 */
@DisplayName("BatchJobLauncher —— 非 Executor 的专用提交口")
class BatchJobLauncherTest {

    @Test
    @DisplayName("不得是 Executor：否则会抑制 applicationTaskExecutor，改写既有 @Async")
    void isNotAnExecutor() {
        assertThat(Executor.class.isAssignableFrom(BatchJobLauncher.class))
                .as("BatchJobLauncher 必须是专用接口，不能占用 Spring 的 Executor/TaskExecutor bean 面")
                .isFalse();
    }

    @Test
    @DisplayName("launch 契约：提交的 Runnable 会被执行")
    void launchRunsJob() {
        BatchJobLauncher launcher = job -> job.run();
        AtomicBoolean ran = new AtomicBoolean(false);

        launcher.launch(() -> ran.set(true));

        assertThat(ran).isTrue();
    }
}
