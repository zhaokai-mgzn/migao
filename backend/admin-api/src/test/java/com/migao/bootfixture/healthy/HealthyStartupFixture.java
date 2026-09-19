package com.migao.bootfixture.healthy;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringBootConfiguration;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.context.annotation.ComponentScan;
import org.springframework.context.annotation.FilterType;

/**
 * **正例夹具**：一个能正常装配起来的 Spring 启动上下文（issue #4557 防误报用）。
 *
 * <p>无 Mapper、无 DB/Redis、无外部依赖 ⇒ 上下文能起来 ⇒ 启动判据**不得**报出任何失败。
 * 排除 {@code MigrationRunner}：它是 @Component 且无 DB 时 fail-closed 拒启动（重试 5 次 ~30s），
 * 与本夹具要证的「Spring 能不能把 bean 装配起来」无关。
 *
 * <p>与 {@code bootfixture.broken.BrokenStartupFixture} **分包**：组件扫描根 = 本类所在包 ⇒ 不互扫。
 */
@SpringBootConfiguration
@EnableAutoConfiguration
@ComponentScan(excludeFilters = @ComponentScan.Filter(
        type = FilterType.ASSIGNABLE_TYPE, classes = com.migao.admin.config.MigrationRunner.class))
@MapperScan("com.migao.admin.mapper.nonexistent")
public class HealthyStartupFixture {
}
