// case_ids: KF-013
package com.migao.admin.config;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;

import static org.assertj.core.api.Assertions.assertThat;

class KfSchedulerConfigTest {

    @Test
    @DisplayName("kfScheduler 独立池：2 线程 + 专属前缀")
    void schedulerPool() {
        KfSchedulerConfig config = new KfSchedulerConfig();
        ThreadPoolTaskScheduler scheduler = config.kfScheduler();
        scheduler.initialize();
        assertThat(scheduler.getScheduledThreadPoolExecutor().getCorePoolSize()).isEqualTo(2);
        assertThat(scheduler.getThreadNamePrefix()).isEqualTo("kf-scheduler-");
        scheduler.shutdown();
    }
}
