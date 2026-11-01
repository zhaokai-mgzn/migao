package com.migao.admin.service;

import com.migao.admin.config.ContextPropagatingTaskDecorator;
import jakarta.annotation.PreDestroy;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.task.TaskRejectedException;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.stereotype.Component;

import java.util.concurrent.ThreadPoolExecutor;

/**
 * 批次 job 的进程内线程池实现（issue #8283）。
 *
 * <p>池子**不是** Spring bean（见 {@link BatchJobLauncher} 的说明）；由本组件自己持有并随
 * {@code @PreDestroy} 关闭。core 2 / max 4 / queue 50：单批 ≤50、单条是普通 DB 写，任务秒级且
 * 相互独立。队列满 / 已停机时用 {@code AbortPolicy} 显式拒绝，再由 {@link #launch} catch 后
 * **在提交线程同步执行**（绝不丢任务；也避免 {@code CallerRunsPolicy} 在停机上静默丢弃）。
 * {@code waitForTasksToCompleteOnShutdown} + 60s 等停覆盖滚动发布。</p>
 */
@Slf4j
@Component
public class ThreadPoolBatchJobLauncher implements BatchJobLauncher {

    private final ThreadPoolTaskExecutor executor;

    public ThreadPoolBatchJobLauncher() {
        ThreadPoolTaskExecutor pool = new ThreadPoolTaskExecutor();
        pool.setCorePoolSize(2);
        pool.setMaxPoolSize(4);
        pool.setQueueCapacity(50);
        pool.setThreadNamePrefix("agent-batch-");
        pool.setRejectedExecutionHandler(new ThreadPoolExecutor.AbortPolicy());
        pool.setTaskDecorator(new ContextPropagatingTaskDecorator());
        pool.setWaitForTasksToCompleteOnShutdown(true);
        pool.setAwaitTerminationSeconds(60);
        pool.initialize();
        this.executor = pool;
    }

    @Override
    public void launch(Runnable job) {
        try {
            executor.execute(job);
        } catch (TaskRejectedException e) {
            log.warn("[Agent] 批次线程池拒绝任务，改为同步执行", e);
            job.run();
        }
    }

    @PreDestroy
    void shutdown() {
        executor.shutdown();
    }
}
