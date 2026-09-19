package com.migao.admin;

// case_ids: MC-009
//
// 载体：AdminApiApplication（Spring Boot 主启动类）。
// MC-009「应用入口 - create_app/健康检查/生命周期」是「应用入口能起来」的既有行为用例；
// 本文件是它在 admin-api 侧的启动守卫（Spring 上下文能装配起来）。
// 本文件**不新增/修改** .github/cases/** 条目（issue #4557 明确不碰用例库）。

import com.migao.bootfixture.broken.BrokenStartupFixture;
import com.migao.bootfixture.healthy.HealthyStartupFixture;
import org.junit.jupiter.api.Test;
import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import static org.junit.jupiter.api.Assertions.*;

/**
 * AdminApiApplication 单元测试
 *
 * 覆盖 Spring Boot 主启动类：
 * - main 方法执行路径（**启动期失败必须可归因**，见下）
 * - 类注解配置正确性
 *
 * <h2>为什么 main 的异常不能「catch 一切 + 只排除一种」（issue #4557）</h2>
 * 本用例守的是「**应用能起来**」。旧实现是 {@code catch (Exception e)} 后只断言
 * 「不是 ClassNotFoundException」⇒ **Bean 装配失败（UnsatisfiedDependencyException /
 * NoSuchBeanDefinitionException / BeanCreationException …）全部静默通过**
 * （实测：去掉一个 @Autowired 该用例仍然绿）⇒ 「部署能起来」没有被任何判据钉住
 * （#4514「V72 整份未应用 ⇒ 云上加工单全挂」那类「部署 success 但实际不可用」的形态）。
 *
 * 现在改为**显式白名单**：只有「本测试环境必然发生且无害」的那一类失败放行，其余一律判红，
 * 且失败信息携带**异常类型 + 原始栈**（不再只打 {@code e.getMessage()}）。
 */
class AdminApiApplicationTest {

    /**
     * 本测试环境**唯一**放行的启动失败：MyBatis 的 mapper bean 拿不到 sqlSessionFactory。
     *
     * <p>理由（显式列白名单，不是「catch 一切」顺带放过）：本用例为了不依赖云上 DB/Redis，
     * 用 {@code --spring.autoconfigure.exclude=} 排除了 DataSource / MyBatis-Plus / Redis 三个自动配置
     * ⇒ 自动配置链里没有 SqlSessionFactory，而主类上的 {@code @MapperScan("com.migao.admin.mapper")}
     * 仍会为每个 mapper 建 bean ⇒ 必然抛
     * {@code UnsatisfiedDependencyException → BeanCreationException → IllegalArgumentException:
     * Property 'sqlSessionFactory' or 'sqlSessionTemplate' are required}。
     *
     * <p>判据取的是**根因**（MyBatis 那句不可配置的断言原文）而不是 bean 名：任何**其它**根因
     * （缺 bean / 循环依赖 / 构造器参数解析不了 / 类加载不了 …）都会落到 {@code else} 判红 ——
     * 包括「新增了一个 Bean，其依赖没人提供」这种 #4557 要治的形态。
     */
    private static boolean isExpectedStartupFailureInThisTestEnv(Throwable t) {
        Throwable root = t;
        while (root.getCause() != null && root.getCause() != root) {
            root = root.getCause();
        }
        String msg = root.getMessage();
        return root instanceof IllegalArgumentException
                && msg != null
                && msg.contains("sqlSessionFactory");
    }

    @Test
    void main_shouldExecuteCodePath() {
        String prev = System.getProperty("spring.main.web-application-type");
        try {
            System.setProperty("spring.main.web-application-type", "none");
            Throwable failure = startupFailureOf(AdminApiApplication.class, new String[]{
                    "--spring.main.web-application-type=none",
                    "--spring.autoconfigure.exclude="
                            + "org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration,"
                            + "com.baomidou.mybatisplus.autoconfigure.MybatisPlusAutoConfiguration,"
                            + "org.springframework.boot.autoconfigure.data.redis.RedisAutoConfiguration"
            });
            if (failure != null && !isExpectedStartupFailureInThisTestEnv(failure)) {
                fail("main() 启动期抛出了**预期之外**的异常（Bean 装配/定义类失败必须判红，见 issue #4557）：\n"
                        + stackTraceOf(failure));
            }
        } finally {
            restoreProperty("spring.main.web-application-type", prev);
        }
    }

    /**
     * **注入式红证（负例）**：本测试环境下的「装配失败」必须被判据报出来。
     *
     * <p>夹具 {@link BrokenStartupFixture} 是 @MapperScan 为空的 Spring Boot 应用 + 一个依赖
     * **不存在** bean 的 {@code @Component}（构造器参数没人提供）⇒ 启动必然抛
     * {@code UnsatisfiedDependencyException}（根因 {@code NoSuchBeanDefinitionException}）。
     * 该失败**不属于**白名单（白名单只放行「mapper 拿不到 sqlSessionFactory」）⇒ 判据必报出。
     *
     * <p>注意：这里断言的是「**判据会报出这类失败**」这个能力，**不是**「仓库当下有这个缺陷」
     * （那种真值主张修好即红、且报错指向错误方向，本仓明令禁止）。
     */
    @Test
    void startupGuard_shouldReportInjectedBeanWiringFailure() {
        Throwable failure = startupFailureOf(BrokenStartupFixture.class, new String[]{
                "--spring.main.web-application-type=none",
                "--spring.autoconfigure.exclude="
                        + "org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration,"
                        + "com.baomidou.mybatisplus.autoconfigure.MybatisPlusAutoConfiguration,"
                        + "org.springframework.boot.autoconfigure.data.redis.RedisAutoConfiguration"
        });
        assertNotNull(failure,
                "注入的 Bean 装配失败（构造器依赖无人提供）必须被启动判据报出来；"
                        + "返回 null = 判据又把它静默吞掉了（issue #4557 复发）");
        assertFalse(isExpectedStartupFailureInThisTestEnv(failure),
                "注入的装配失败不得落进「预期失败」白名单（否则白名单过宽 = 判据失效）：\n"
                        + stackTraceOf(failure));
    }

    /**
     * **正例（防误报）**：正常上下文 ⇒ 判据不报。
     *
     * <p>{@link HealthyStartupFixture} 依赖全部由自己提供（无 Mapper、无 DB/Redis）⇒ 上下文能装配起来
     * ⇒ {@link #startupFailureOf} 返回 null。若这里非 null，说明判据把「正常启动」也判成了失败。
     */
    @Test
    void startupGuard_shouldNotReportHealthyContext() {
        Throwable failure = startupFailureOf(HealthyStartupFixture.class, new String[]{
                "--spring.main.web-application-type=none"
        });
        assertNull(failure, "正常上下文不得被判据报出（误报）：\n" + (failure == null ? "" : stackTraceOf(failure)));
    }

    @Test
    void class_shouldHaveSpringBootApplicationAnnotation() {
        SpringBootApplication annotation = AdminApiApplication.class
                .getAnnotation(SpringBootApplication.class);
        assertNotNull(annotation);
    }

    @Test
    void class_shouldHaveMapperScanAnnotation() {
        MapperScan annotation = AdminApiApplication.class
                .getAnnotation(MapperScan.class);
        assertNotNull(annotation);
        assertArrayEquals(new String[]{"com.migao.admin.mapper"}, annotation.value());
    }

    @Test
    void class_shouldBePublic() {
        assertTrue(java.lang.reflect.Modifier.isPublic(
                AdminApiApplication.class.getModifiers()));
    }

    /**
     * 启动 {@code source}，返回启动期失败（正常启动返回 null）。
     *
     * <p>失败**不在这里断言**：分类与判红留给调用方（{@link #isExpectedStartupFailureInThisTestEnv}），
     * 这样「预期失败」与「意外失败」两态都由同一段代码判定，正/负例都能走真实启动路径。
     *
     * <p>捕获 {@link Throwable} 而非 {@link Exception}：类加载类失败（NoClassDefFoundError /
     * ExceptionInInitializerError）同样是「起不来」；{@link VirtualMachineError} 不可恢复，原样上抛。
     */
    private static Throwable startupFailureOf(Class<?> source, String[] args) {
        try {
            org.springframework.boot.SpringApplication.run(source, args);
            return null;
        } catch (VirtualMachineError unrecoverable) {
            throw unrecoverable;
        } catch (Throwable t) {
            return t;
        }
    }

    /** 完整现场：异常类型 + 全链（含根因）+ 原始栈。只打 e.getMessage() 会丢掉类型与栈（#4557 判据 3）。 */
    private static String stackTraceOf(Throwable t) {
        java.io.StringWriter sw = new java.io.StringWriter();
        t.printStackTrace(new java.io.PrintWriter(sw));
        return t.getClass().getName() + ": " + t.getMessage() + "\n" + sw;
    }

    private static void restoreProperty(String key, String prev) {
        if (prev != null) {
            System.setProperty(key, prev);
        } else {
            System.clearProperty(key);
        }
    }
}
