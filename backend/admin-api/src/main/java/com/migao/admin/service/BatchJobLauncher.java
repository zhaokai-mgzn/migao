package com.migao.admin.service;

/**
 * 批次后台 job 的提交口（issue #8283）。
 *
 * <p><b>为什么不是 Spring 的 {@code TaskExecutor} bean</b>：Spring Boot 的
 * {@code TaskExecutionAutoConfiguration} 以 {@code @ConditionalOnMissingBean(Executor.class)}
 * 提供 {@code applicationTaskExecutor}；再把一个 {@code TaskExecutor} 注册成 bean 会让它退避，
 * 并让既有的 {@code @Async}（审计日志 / 知识提炼）**改用批次的池** —— 那是本单之外的隐性行为变更。
 * 用一个专用接口把「批次 job」与通用线程池执行器隔开：既拿到独立生命周期，也不污染 {@code @Async}。</p>
 */
public interface BatchJobLauncher {

    /** 提交一个后台 job；线程池拒绝（停机窗口）时由实现退化为同步执行。 */
    void launch(Runnable job);
}
