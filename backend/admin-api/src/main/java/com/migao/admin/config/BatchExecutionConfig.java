package com.migao.admin.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.util.concurrent.ThreadPoolExecutor;

/**
 * 批量写执行器（issue #8283）的线程池。
 *
 * <p>只在「批次执行 / 撤销」这一条链路上用（bean 名 {@code batchExecutor}，显式注入），
 * <b>不是</b> {@code @Async} 的默认执行器 —— 不改变审计 / 知识提炼等既有异步链路的行为。</p>
 *
 * <p>选型口径：单批 ≤50、单条 apply 是普通 DB 写，任务本身秒级且相互独立 ⇒ 小池 + 有界队列即可，
 * 不引入消息队列。队列满时 {@code CallerRunsPolicy} 在提交线程内联执行（请求会退化成同步，
 * 但绝不丢任务）；{@code waitForTasksToCompleteOnShutdown} + 60s 等停覆盖滚动发布。</p>
 */
@Configuration
public class BatchExecutionConfig {

    /** 批次执行线程池（core 2 / max 4 / queue 50）。 */
    @Bean("batchExecutor")
    public ThreadPoolTaskExecutor batchExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(2);
        executor.setMaxPoolSize(4);
        executor.setQueueCapacity(50);
        executor.setThreadNamePrefix("agent-batch-");
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.CallerRunsPolicy());
        executor.setTaskDecorator(new ContextPropagatingTaskDecorator());
        executor.setWaitForTasksToCompleteOnShutdown(true);
        executor.setAwaitTerminationSeconds(60);
        executor.initialize();
        return executor;
    }
}
