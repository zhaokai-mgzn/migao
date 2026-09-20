// case_ids: PG-056
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import org.apache.ibatis.mapping.MappedStatement;
import org.apache.ibatis.mapping.ResultMap;
import org.apache.ibatis.mapping.ResultMapping;

import java.lang.reflect.Field;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🔴 **#4865 防再犯判据的唯一出处**：真 MyBatis 映射上，「带 {@code JacksonTypeHandler} 字段的实体」
 * 必须真的把处理器挂上（否则 JSONB 列以 **JSON 字符串**落到字段上 ⇒ 所有
 * {@code instanceof List}/{@code instanceof Map} 判据**静默为假**：不抛异常、不报错，只是空）。
 *
 * <h2>为什么判据长这样</h2>
 * 判据直接读 {@code MybatisConfiguration} 里真实的 {@code MappedStatement → ResultMap →
 * ResultMapping.getTypeHandler()}（与运行期同一份元数据），**不读注解文本、不 mock、不连库** ⇒ CI 恒定可跑。
 * MyBatis-Plus 的 {@code @TableName(autoResultMap = true)} 只对 BaseMapper 的内置方法生效 ——
 * 手写 {@code @Select} 不显式 {@code @ResultMap("mybatis-plus_<Entity>")}（或 {@code @Results} 声明处理器）
 * 就是一条**无任何类型处理器**的内联 ResultMap。
 *
 * <h2>为什么值得一条类级判据</h2>
 * 同一根因在本仓**复发过两次**：issue #3340（{@code order_items.processing_info} 以字符串返回 ⇒
 * buildSnapshot 恒空；当时只改调用方 + 加 {@code instanceof String} 兜底，映射没修）与
 * issue #4865（{@code processing_orders.items_snapshot} 同样以字符串返回 ⇒ 套号分配跳过 ⇒
 * 部位码/短码永不产出）。
 *
 * <p>本类是判据的**单一出处**：类级守卫 {@link JacksonTypeHandlerMappingGuardTest} 与逐 mapper 的
 * {@code *MapperTest} 都调它（不各写一份口径）。</p>
 */
final class MapperTypeHandlerAssertions {

    /** 一次扫描的结果：扫到多少个「返回 JSONB 实体」的 statement + 违规清单（已去重排序）。 */
    record Report(int inspectedStatements, Set<String> violations) {
    }

    private MapperTypeHandlerAssertions() {
    }

    /** 只注册指定 mapper 的配置（用于逐 mapper 判据）。 */
    static MybatisConfiguration configurationOf(Class<?>... mappers) {
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        for (Class<?> mapper : mappers) {
            configuration.addMapper(mapper);
        }
        return configuration;
    }

    /** 注册 {@code com.migao.admin.mapper} 包下**全部**接口（类级判据用；按 class 文件枚举，避免手写清单漂移）。 */
    static MybatisConfiguration configurationWithAllMappers() {
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        List<Class<?>> mappers = mapperInterfaces();
        assertThat(mappers).as("必须扫到 mapper 接口（扫不到 ⇒ 判据空跑）").isNotEmpty();
        for (Class<?> mapper : mappers) {
            configuration.addMapper(mapper);
        }
        return configuration;
    }

    /** `com.migao.admin.mapper` 包下的全部接口。 */
    static List<Class<?>> mapperInterfaces() {
        Path packageDir;
        try {
            packageDir = Paths.get(ProcessingOrderMapper.class
                    .getResource("ProcessingOrderMapper.class").toURI()).getParent();
        } catch (Exception e) {
            throw new IllegalStateException("无法定位主代码的 mapper 包（判据无法运行，不静默跳过）", e);
        }
        List<Class<?>> mappers = new ArrayList<>();
        try (Stream<Path> files = Files.list(packageDir)) {
            for (Path path : files.toList()) {
                String name = path.getFileName().toString();
                if (!name.endsWith(".class") || name.contains("$")) {
                    continue;
                }
                try {
                    Class<?> type = Class.forName(
                            "com.migao.admin.mapper." + name.substring(0, name.length() - ".class".length()));
                    if (type.isInterface()) {
                        mappers.add(type);
                    }
                } catch (Throwable missing) {
                    // 非 mapper 的类/不可加载的类 ⇒ 跳过（不影响「带 JSONB 实体的 statement」判据）
                }
            }
        } catch (Exception e) {
            throw new IllegalStateException("枚举 mapper 包失败（判据无法运行，不静默跳过）", e);
        }
        mappers.sort(Comparator.comparing(Class::getName));
        return mappers;
    }

    /** 扫描：`statement → 属性` 的违规清单（= 该 statement 的 ResultMap 没给 JSONB 字段挂处理器）。 */
    static Report scan(MybatisConfiguration configuration) {
        Set<String> violations = new TreeSet<>();
        int inspected = 0;
        for (String id : configuration.getMappedStatementNames()) {
            if (!id.contains(".")) {
                continue; // 短名别名（MyBatis 的 StrictMap 会额外登记一份）
            }
            MappedStatement statement;
            try {
                statement = configuration.getMappedStatement(id);
            } catch (RuntimeException ambiguousShortName) {
                continue;
            }
            for (ResultMap resultMap : statement.getResultMaps()) {
                Set<String> jsonbProperties = jsonbPropertiesOf(resultMap.getType());
                if (jsonbProperties.isEmpty()) {
                    continue;
                }
                inspected++;
                Set<String> bound = boundJsonbProperties(resultMap);
                for (String property : jsonbProperties) {
                    if (!bound.contains(property)) {
                        violations.add(statement.getId() + " → " + property);
                    }
                }
            }
        }
        return new Report(inspected, violations);
    }

    /** 判据本体：这些 mapper 的 JSONB 字段必须在真实 ResultMap 上挂到处理器。 */
    static void assertJsonbColumnsBound(Class<?>... mappers) {
        Report report = scan(configurationOf(mappers));
        assertThat(report.violations())
                .as("手写 select 返回带 JacksonTypeHandler 字段的实体时必须绑 resultMap（否则 JSONB 列落成"
                        + "字符串 ⇒ instanceof 判据静默为假，issue #3340 / #4865 同根因）。违规清单：\n  "
                        + String.join("\n  ", report.violations()))
                .isEmpty();
    }

    private static final Map<Class<?>, Set<String>> JSONB_PROPERTIES = new HashMap<>();

    /** 该实体上带 `JacksonTypeHandler` 的字段名（= ResultMapping 的 property 口径）。 */
    static Set<String> jsonbPropertiesOf(Class<?> type) {
        return JSONB_PROPERTIES.computeIfAbsent(type, clazz -> {
            Set<String> properties = new LinkedHashSet<>();
            for (Class<?> current = clazz; current != null && current != Object.class;
                 current = current.getSuperclass()) {
                for (Field field : current.getDeclaredFields()) {
                    TableField tableField = field.getAnnotation(TableField.class);
                    if (tableField != null && JacksonTypeHandler.class.isAssignableFrom(tableField.typeHandler())) {
                        properties.add(field.getName());
                    }
                }
            }
            return properties;
        });
    }

    /** 该 ResultMap 上**真的挂了 JacksonTypeHandler** 的属性集合。 */
    static Set<String> boundJsonbProperties(ResultMap resultMap) {
        Set<String> bound = new HashSet<>();
        for (ResultMapping mapping : resultMap.getResultMappings()) {
            if (mapping.getProperty() != null && mapping.getTypeHandler() instanceof JacksonTypeHandler) {
                bound.add(mapping.getProperty());
            }
        }
        return bound;
    }
}
