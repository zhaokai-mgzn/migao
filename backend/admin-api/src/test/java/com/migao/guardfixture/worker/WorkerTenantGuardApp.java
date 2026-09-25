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
import com.migao.admin.security.PasswordChangeRequiredFilter;
import com.migao.admin.security.SecurityConfig;
import com.migao.admin.security.LoginFailureGuard;
import com.migao.admin.security.ServiceTokenFilter;
import com.migao.admin.security.WorkerSessionFilter;
import com.migao.admin.worker.WorkerSessionService;
import org.apache.ibatis.session.SqlSessionFactory;
import org.mybatis.spring.mapper.MapperFactoryBean;
import org.springframework.boot.SpringBootConfiguration;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.context.annotation.Bean;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.context.annotation.Import;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import org.springframework.jdbc.datasource.SimpleDriverDataSource;

import javax.sql.DataSource;
import java.util.Map;
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
        JwtAuthenticationFilter.class, ServiceTokenFilter.class, PasswordChangeRequiredFilter.class,
        LoginFailureGuard.class,
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

    /**
     * 登录失败计数（issue #5531）依赖的 Redis：本夹具**不断言**这一面（工人会话⇒租户链不经过它），
     * 只为满足 {@link WorkerSessionService} 的构造依赖 ⇒ 用 test double，并显式登记这个边界。
     * 失败计数的**行为**由 {@code WorkerLoginLockoutTest} / {@code EmployeeLoginLockoutTest} 钉住。
     */
    @Bean
    @SuppressWarnings("unchecked")
    StringRedisTemplate stringRedisTemplate() {
        // ⚠️ 必须是**有行为的**替身：裸 mock 的 opsForValue() 返回 null ⇒ LoginFailureGuard 的
        //    fail-closed 会把每次登录判成 503（实测：8 条里 5 条挂在 "Status expected:<200> but was:<503>"）。
        //    这也顺带证明 fail-closed 真的生效（守卫不可执行 ⇒ 不放行）。
        Map<String, String> store = new java.util.concurrent.ConcurrentHashMap<>();
        StringRedisTemplate t = mock(StringRedisTemplate.class);
        ValueOperations<String, String> ops = mock(ValueOperations.class);
        when(t.opsForValue()).thenReturn(ops);
        when(ops.get(anyString())).thenAnswer(i -> store.get(i.getArgument(0, String.class)));
        when(ops.increment(anyString())).thenAnswer(i -> {
            String k = i.getArgument(0, String.class);
            long v = Long.parseLong(store.getOrDefault(k, "0")) + 1;
            store.put(k, String.valueOf(v));
            return v;
        });
        when(t.expire(anyString(), anyLong(), any(java.util.concurrent.TimeUnit.class))).thenReturn(true);
        when(t.delete(anyString())).thenAnswer(i -> store.remove(i.getArgument(0, String.class)) != null);
        return t;
    }

    /** {@link LoginFailureGuard} 只用到 MeterRegistry 的 counter(...) 读数面 ⇒ 真实现即可。 */
    @Bean
    MeterRegistry meterRegistry() {
        return new SimpleMeterRegistry();
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
