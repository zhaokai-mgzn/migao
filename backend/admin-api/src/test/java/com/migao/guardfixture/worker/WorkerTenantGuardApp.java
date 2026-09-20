package com.migao.guardfixture.worker;

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.MybatisPlusConfig;
import com.migao.admin.config.PasswordEncoderConfig;
import com.migao.admin.config.TenantDomainResolver;
import com.migao.admin.controller.WorkerAuthController;
import com.migao.admin.controller.WorkerProductionController;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.mapper.WorkerSessionMapper;
import com.migao.admin.security.JwtAuthenticationFilter;
import com.migao.admin.security.SecurityConfig;
import com.migao.admin.security.ServiceTokenFilter;
import com.migao.admin.security.WorkerSessionFilter;
import com.migao.admin.worker.WorkerSessionService;
import org.apache.ibatis.session.SqlSessionFactory;
import org.mybatis.spring.mapper.MapperFactoryBean;
import org.springframework.boot.SpringBootConfiguration;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.datasource.SimpleDriverDataSource;

import javax.sql.DataSource;
import java.sql.Driver;

/**
 * 「工人端 会话⇒租户」集成守卫的**测试专用应用**（issue #4864，守卫本体见
 * {@code com.migao.admin.security.WorkerTenantCycleGuardTest}）。
 *
 * <p>只装配工人端这条链需要的东西，但**每一件都是真身**：真 {@link SecurityConfig}
 * （{@code /api/worker/**} 的授权规则逐字来自生产配置）、真 {@link WorkerSessionFilter}、
 * 真 {@link WorkerSessionService}、真 {@link MybatisPlusConfig}（即**真租户拦截器**）、
 * 真 MyBatis Mapper（{@code WorkerSessionMapper} / {@code UserMapper} 都是真代理，**不是 mock**）。
 * 生产侧与本链无关的外部依赖（Redis / OSS / SMS / 报工业务服务）不在装配面内。</p>
 *
 * <p>⚠️ <b>为什么是「独立包里的顶层类」而不是守卫测试里的嵌套 {@code @SpringBootConfiguration}</b>：
 * {@code @SpringBootTest} 不显式给 {@code classes} 时，Spring Boot 会从**测试类所在包向上**找
 * {@code @SpringBootConfiguration}。嵌套类与 {@code SecurityConfigTest} **同包**
 * （{@code com.migao.admin.security}）⇒ 后者被解析到本夹具（实测：{@code SecurityConfigTest}
 * 42 条全部 error，报 {@code classes = [WorkerTenantCycleGuardTest$TestApp]}）⇒ 把别的测试打红。
 * 放进一个**任何测试都不在其祖先链上**的包即可（同 {@code com.migao.bootfixture.*} 的既有做法）。</p>
 *
 * <p>库：默认 H2 的 PostgreSQL 兼容模式（CI 的 {@code admin-api-test} 没有 postgres service，
 * 且本机 token 无 {@code workflow} scope ⇒ 不能改 workflow 加服务）。需要对着真 PostgreSQL 复核时
 * 用 {@code -Dworker.guard.jdbc.url=jdbc:postgresql://…} 指向本地 PG 跑同一份断言。</p>
 */
@SpringBootConfiguration
@EnableAutoConfiguration
@Import({SecurityConfig.class, PasswordEncoderConfig.class, MybatisPlusConfig.class,
        GlobalExceptionHandler.class, TenantDomainResolver.class,
        WorkerSessionFilter.class, WorkerSessionService.class,
        JwtAuthenticationFilter.class, ServiceTokenFilter.class,
        WorkerAuthController.class, WorkerProductionController.class})
public class WorkerTenantGuardApp {

    /** H2（PostgreSQL 兼容模式）。`NON_KEYWORDS=POSITION` 因为 `users.position` 与 H2 函数同名。 */
    public static final String H2_URL =
            "jdbc:h2:mem:workerguard4864;MODE=PostgreSQL;DATABASE_TO_LOWER=TRUE;"
                    + "NON_KEYWORDS=POSITION;DB_CLOSE_DELAY=-1";

    public static String jdbcUrl() {
        return System.getProperty("worker.guard.jdbc.url", H2_URL);
    }

    public static String jdbcUser() {
        return System.getProperty("worker.guard.jdbc.user", "sa");
    }

    public static String jdbcPassword() {
        return System.getProperty("worker.guard.jdbc.password", "");
    }

    @Bean
    DataSource dataSource() {
        return new SimpleDriverDataSource(driver(), jdbcUrl(), jdbcUser(), jdbcPassword());
    }

    private static Driver driver() {
        String className = jdbcUrl().startsWith("jdbc:postgresql") ? "org.postgresql.Driver" : "org.h2.Driver";
        try {
            return (Driver) Class.forName(className).getDeclaredConstructor().newInstance();
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("无法加载 JDBC 驱动 " + className, e);
        }
    }

    /** 真 Mapper（**不是** mock）：本守卫的全部意义就是行使租户拦截器那条真实路径。 */
    @Bean
    MapperFactoryBean<WorkerSessionMapper> workerSessionMapper(SqlSessionFactory sqlSessionFactory) {
        MapperFactoryBean<WorkerSessionMapper> factory = new MapperFactoryBean<>(WorkerSessionMapper.class);
        factory.setSqlSessionFactory(sqlSessionFactory);
        return factory;
    }

    @Bean
    MapperFactoryBean<UserMapper> userMapper(SqlSessionFactory sqlSessionFactory) {
        MapperFactoryBean<UserMapper> factory = new MapperFactoryBean<>(UserMapper.class);
        factory.setSqlSessionFactory(sqlSessionFactory);
        return factory;
    }
}
