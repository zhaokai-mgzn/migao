// case_ids: PG-056
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.TableField;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 「实体字段 ⊆ 建库列」的**唯一**判据实现（issue #7796）。
 *
 * <h2>为什么收敛成一份</h2>
 * 改前 16 个 {@code *MapperTest} 各自复制了同一段「解析 {@code schema.sql} 的建库列 + 与实体字段比对」。
 * 复制体之间会漂移：PR #7793 给实体加只读投影字段（{@code @TableField(exist = false)}，如 join 来的
 * {@code inbound_no}）时，只有当时被改到的那个文件过滤了 {@code exist = false}，其余 15 份立刻**假红**。
 * 口径只留一份 ⇒ 修一处全仓跟着对，且类级守卫
 * {@link MapperColumnAssertionsGuardTest} 禁止任何 {@code *MapperTest} 再自写第二份。
 *
 * <h2>口径（与全仓一致）</h2>
 * <ul>
 *   <li>列面：{@code CREATE TABLE IF NOT EXISTS <table> ( … );\n} 段里**顶格 4 空格 + 小写列名 + 大写类型**的行
 *       （约束 / 索引 / 注释行天然不匹配）；</li>
 *   <li>字段面：{@code getDeclaredFields()}，跳过 {@code static} 与 synthetic，**再跳过
 *       {@code @TableField(exist = false)}** —— 只读投影不是 DB 列，MyBatis 也不带它写 SQL
 *       （与 {@code tests/unit_ci_workflows/_sql_schema.py} 的 {@code entity_columns()} 同一口径，
 *       见 issue #7792）；</li>
 *   <li>camelCase → snake_case 按 {@code ([a-z0-9])([A-Z]) → $1_$2} 再小写。</li>
 * </ul>
 */
final class MapperColumnAssertions {

    /** 建库脚本（模块相对路径；surefire 的 workdir = admin-api 模块根，与同包其它判据同口径）。 */
    private static final Path SCHEMA = Path.of("src/main/resources/db/init/schema.sql");

    /**
     * 建表段：{@code CREATE TABLE [IF NOT EXISTS] <table> ( … \n);} —— 组 1 = 列定义区。
     *
     * <p>🔴 {@code IF NOT EXISTS} 必须**可选**：存量表 {@code orders}（建库脚本里最早那张）没有它 ——
     * 写死会让「按表名解析」对那张表直接判红（`OrderShipmentQueryMapperTest` 就在读它）。</p>
     */
    private static final String CREATE_TABLE = "CREATE TABLE (?:IF NOT EXISTS )?";

    /** 列定义行：4 空格缩进的小写列名 + 大写类型（约束 / 索引行不会被命中）。 */
    private static final Pattern COLUMN_LINE = Pattern.compile("^\\s{4}([a-z_]+)\\s+[A-Z]");

    /** 字段名 → 列名（本仓不用自定义 {@code @TableField(value=…)}）。 */
    private static final Pattern CAMEL_HUMP = Pattern.compile("([a-z0-9])([A-Z])");

    private MapperColumnAssertions() {
    }

    /**
     * 建库脚本里该表的**列名集合**（键 = 列名，非空）。
     *
     * <p>解析自证：找不到表段 / 段里解析出 0 列 ⇒ 直接红（否则建库段格式一变，所有「缺列」判据会静默变空）。</p>
     */
    static Set<String> columnsOf(String table) {
        Matcher tableSection = Pattern
                .compile(CREATE_TABLE + table + " \\(([\\s\\S]*?)\\n\\);")
                .matcher(schemaSql());
        assertThat(tableSection.find()).as("建库脚本里必须有 %s 表", table).isTrue();
        Set<String> columns = new LinkedHashSet<>();
        for (String line : tableSection.group(1).split("\n")) {
            Matcher column = COLUMN_LINE.matcher(line);
            if (column.find()) {
                columns.add(column.group(1));
            }
        }
        assertThat(columns).as("解析自证：%s 的列面不能为空（建库段格式变了 ⇒ 判据会静默变空）", table).isNotEmpty();
        return columns;
    }

    /**
     * 判据本体：实体声明的每个字段（{@code @TableField(exist = false)} 的只读投影**除外**）都必须有对应列。
     *
     * <p>失败消息形态固定为 {@code "<Entity> 实体字段缺列：[…]"}。</p>
     */
    static void assertEveryEntityFieldHasColumn(Class<?> entity, String table) {
        Set<String> missing = entityColumnNames(entity);
        missing.removeAll(columnsOf(table));
        assertThat(missing).as("%s 实体字段缺列：%s", entity.getSimpleName(), missing).isEmpty();
    }

    /** 实体的**建库列**口径：跳过 static / synthetic / {@code @TableField(exist = false)}。 */
    private static Set<String> entityColumnNames(Class<?> entity) {
        Set<String> columns = new LinkedHashSet<>();
        for (Field field : entity.getDeclaredFields()) {
            if (Modifier.isStatic(field.getModifiers()) || field.isSynthetic()) {
                continue;
            }
            TableField tableField = field.getAnnotation(TableField.class);
            if (tableField != null && !tableField.exist()) {
                continue; // 只读投影（join 来的列，如 inbound_no）不是本表列
            }
            columns.add(CAMEL_HUMP.matcher(field.getName()).replaceAll("$1_$2").toLowerCase());
        }
        return columns;
    }

    private static String schemaSql() {
        try {
            return Files.readString(SCHEMA);
        } catch (Exception e) {
            throw new IllegalStateException(
                    "读不到建库脚本 " + SCHEMA.toAbsolutePath() + "（判据无法运行，不静默跳过）", e);
        }
    }
}
