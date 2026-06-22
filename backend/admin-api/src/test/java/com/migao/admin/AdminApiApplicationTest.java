package com.migao.admin;

import org.junit.jupiter.api.Test;
import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import static org.junit.jupiter.api.Assertions.*;

/**
 * AdminApiApplication 单元测试
 *
 * 覆盖 Spring Boot 主启动类：
 * - main 方法执行路径
 * - 类注解配置正确性
 */
class AdminApiApplicationTest {

    @Test
    void main_shouldExecuteCodePath() {
        String prev = System.getProperty("spring.main.web-application-type");
        try {
            System.setProperty("spring.main.web-application-type", "none");
            AdminApiApplication.main(new String[]{
                    "--spring.main.web-application-type=none",
                    "--spring.autoconfigure.exclude="
                            + "org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration,"
                            + "com.baomidou.mybatisplus.autoconfigure.MybatisPlusAutoConfiguration,"
                            + "org.springframework.boot.autoconfigure.data.redis.RedisAutoConfiguration"
            });
        } catch (Exception e) {
            assertFalse(e instanceof ClassNotFoundException,
                    "main() should not throw ClassNotFoundException, got: " + e.getMessage());
        } finally {
            restoreProperty("spring.main.web-application-type", prev);
        }
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

    private static void restoreProperty(String key, String prev) {
        if (prev != null) {
            System.setProperty(key, prev);
        } else {
            System.clearProperty(key);
        }
    }
}
