package com.migao.bootfixture.broken;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringBootConfiguration;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.context.annotation.ComponentScan;
import org.springframework.context.annotation.FilterType;
import org.springframework.stereotype.Component;

/**
 * **注入式红证夹具**：一个必然装配失败的 Spring 启动上下文（issue #4557）。
 *
 * <p>{@link NeedsMissingDependency} 的构造器依赖 {@link NoSuchBeanInThisFixture}，而该类型
 * **故意不是 bean** ⇒ 启动必抛 {@code UnsatisfiedDependencyException}（根因
 * {@code NoSuchBeanDefinitionException}）。用于证明
 * {@code AdminApiApplicationTest} 的启动判据**会报出**这类失败（旧实现会静默吞掉）。
 *
 * <p>与 {@code bootfixture.healthy.HealthyStartupFixture} **分包**：组件扫描根 = 本类所在包
 * ⇒ 两个夹具互不扫到对方（同包会把坏 bean 扫进「好上下文」）。
 */
@SpringBootConfiguration
@EnableAutoConfiguration
@ComponentScan(excludeFilters = @ComponentScan.Filter(
        type = FilterType.ASSIGNABLE_TYPE, classes = com.migao.admin.config.MigrationRunner.class))
@MapperScan("com.migao.admin.mapper.nonexistent")
public class BrokenStartupFixture {

    /** 依赖一个不存在的 bean ⇒ 装配必失败。 */
    @Component
    static class NeedsMissingDependency {
        NeedsMissingDependency(NoSuchBeanInThisFixture missing) {
        }
    }

    /** 本夹具里**故意不存在**的依赖类型。 */
    static class NoSuchBeanInThisFixture {
    }
}
